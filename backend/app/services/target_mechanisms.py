"""Pure, deterministic compiler for the numeric part of forecast-case/v1.

Templates (input order is significant; parameter sets are exact):
* growth: [base, rate], {} -> base * (1 + rate).
* sum/product: one or more inputs, {} -> their sum/product. Product uses scaled
  multiplication so intermediate overflow/underflow cannot erase a finite result.
* linear: inputs, {coefficients: [scalar, ...], intercept: scalar}
  -> intercept + sum(coefficients[i] * inputs[i]). The list must contain exactly
  one coefficient per input, in inputNodeIds order; at least one input is required.
* supply_demand: [supply, demand], {} -> demand - supply (positive is shortage).
* adoption: [current, capacity], {rate: scalar} -> current + rate *
  (capacity - current); 0 <= current <= capacity and 0 <= rate <= 1.
  Exact rate endpoints are preserved; rounding is confined to [current, capacity].
* regulatory_milestone: [], {milestonePeriod: scalar, before: scalar,
  after: scalar} -> before when period < milestonePeriod, otherwise after.
  Periods are nonnegative integers; a fractional threshold switches at its ceil.

A scalar is a finite int/float (excluding bool), or a continuous uniform prior
with required low/high and optional basis/gap/sourceIds. A prior's value key is
explicitly rejected: central estimates never silently influence or get ignored
by sampling. Bounds are finite and ordered; assumed bases require a nonempty
gap. Prior provenance overrides the mechanism's provenance, inheriting
basis/sourceIds/gap when omitted. Equal bounds and
literals are fixed and consume no randomness. Draw coefficients are flattened
to ``coefficient:<inputNodeId>``; all other draw keys match parameter names.

Call initial_values and draw_parameters ONCE per path using the caller's RNG
(a random.Random-compatible object with random()). Propagate never samples,
mutates its arguments, compounds by elapsed time, or clips outputs to initial
node ranges. Each call evaluates the DAG once using updated upstream outputs;
the caller owns state evolution between periods. No app/core/provider imports
are needed. Whole-case evidence and authority validation belongs to the core.
"""

from dataclasses import dataclass
from fractions import Fraction
from heapq import heapify, heappop, heappush
from math import frexp, fsum, isfinite, ldexp
from re import findall


class MechanismValidationError(ValueError):
    """Malformed numeric model or invalid runtime inputs/results."""


def _fail(where, message):
    raise MechanismValidationError(f"{where}: {message}")


def _number(value, where):
    if type(value) not in (int, float):
        _fail(where, "expected a finite number (not bool)")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _fail(where, "number is outside finite float range")
    if not isfinite(result):
        _fail(where, "expected a finite number")
    # Keep integer literals exact for bounds checks and fixed initial values.
    # Converting 2**53 + 1 to float would conceal reversed bounds or overrides.
    return value


def _object(value, where):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        _fail(where, "expected an object with string keys")
    return value


def _identifier(value, where):
    if not isinstance(value, str) or not value.strip():
        _fail(where, "expected a nonempty string")
    return value


def _keys(value, required, optional, where):
    _object(value, where)
    missing = set(required) - value.keys()
    extra = value.keys() - set(required) - set(optional)
    if missing or extra:
        _fail(where, f"missing keys {sorted(missing)}; unsupported keys {sorted(extra)}")


def _list(value, where):
    if not isinstance(value, list):
        _fail(where, "expected a list")
    return value


def _sources(value, known_sources, where):
    ids = tuple(_identifier(item, where) for item in _list(value, where))
    if len(set(ids)) != len(ids):
        _fail(where, "duplicate source IDs")
    if set(ids) - known_sources:
        _fail(where, f"unknown source IDs {sorted(set(ids) - known_sources)}")
    return tuple(sorted(ids))


def _provenance(value, known_sources, where, inherited=None):
    basis = value.get("basis")
    if basis not in ("observed", "estimated", "assumed"):
        _fail(where, "basis must be observed, estimated, or assumed")
    inherited_sources, inherited_gap = inherited or ((), "")
    sources = _sources(value.get("sourceIds", list(inherited_sources)),
                       known_sources, where + ".sourceIds")
    gap = value.get("gap", inherited_gap)
    if not isinstance(gap, str) or (basis == "assumed" and not gap.strip()):
        _fail(where, "gap must be text and nonempty when basis is assumed")
    return basis, sources, gap


@dataclass(frozen=True)
class _Scalar:
    low: float
    high: float
    basis: str
    sources: tuple
    gap: str

    def midpoint(self):
        """Central parameter value without sampling or overflowing the span."""
        if self.low == self.high:
            return self.low
        if self.low < 0 < self.high:
            return self.low * 0.5 + self.high * 0.5
        return self.low + (self.high - self.low) * 0.5

    def draw(self, rng):
        if self.low == self.high:
            return self.low
        fraction = _number(rng.random(), "rng.random()")
        if not 0 <= fraction < 1:
            _fail("rng.random()", "expected 0 <= result < 1")
        # Avoid high-low overflow for finite bounds of opposite signs.
        if self.low < 0 < self.high:
            result = (1 - fraction) * self.low + fraction * self.high
        else:
            result = self.low + fraction * (self.high - self.low)
        result = _number(result, "sample")
        return min(self.high, max(self.low, result))

    def record(self, **identity):
        return {**identity, "low": self.low, "high": self.high,
                "distribution": "fixed" if self.low == self.high else "uniform",
                "basis": self.basis, "sourceIds": list(self.sources), "gap": self.gap}


def _scalar(value, provenance, known_sources, where):
    if isinstance(value, dict):
        _keys(value, {"low", "high"}, {"basis", "gap", "sourceIds"}, where)
        low = _number(value["low"], where + ".low")
        high = _number(value["high"], where + ".high")
        basis, sources, gap = _provenance({"basis": provenance[0], **value},
                                          known_sources, where, (provenance[1], provenance[2]))
        if low > high:
            _fail(where, "low must be <= high")
    else:
        low = high = _number(value, where)
        basis, sources, gap = provenance
    return _Scalar(low, high, basis, sources, gap)


def _product(values):
    if any(value == 0 for value in values):
        return 0.0
    mantissa, exponent = 1.0, 0
    for value in values:
        part, power = frexp(value)
        mantissa, adjustment = frexp(mantissa * part)
        exponent += power + adjustment
    return ldexp(mantissa, exponent)


@dataclass(frozen=True)
class _Mechanism:
    mechanism_id: str
    kind: str
    output: str
    inputs: tuple
    parameters: tuple
    basis: str
    sources: tuple
    gap: str

    def evaluate(self, values, parameters, period):
        inputs = [values[node_id] for node_id in self.inputs]
        if self.kind == "growth":
            return inputs[0] * (1 + inputs[1])
        if self.kind == "sum":
            return fsum(inputs)
        if self.kind == "product":
            return _product(inputs)
        if self.kind == "linear":
            return fsum([parameters["intercept"], *(
                parameters[f"coefficient:{node_id}"] * value
                for node_id, value in zip(self.inputs, inputs))])
        if self.kind == "supply_demand":
            return inputs[1] - inputs[0]
        if self.kind == "adoption":
            current, capacity = inputs
            if not 0 <= current <= capacity:
                _fail(self.mechanism_id, "adoption requires 0 <= current <= capacity")
            rate = parameters["rate"]
            if rate == 0:
                return current
            if rate == 1:
                return capacity
            return min(capacity, max(current, current + rate * (capacity - current)))
        if self.kind == "regulatory_milestone":
            return parameters["before"] if period < parameters["milestonePeriod"] else parameters["after"]
        _fail(self.mechanism_id, "unsupported mechanism kind")


@dataclass(frozen=True)
class CompiledModel:
    """Immutable compiled snapshot; public metadata properties return fresh JSON.

    order is a list of mechanism IDs in topological order, breaking ready-node
    ties lexicographically by mechanism ID. Nodes draw in node-ID order, then
    parameters draw in mechanism order and lexicographic scalar-key order.
    parameter_bounds is {mechanismId: {scalarKey: {low, high}}}; initial-value
    bounds and their explicit assumptions are included in parameter_bases.
    Runtime values and parameter maps must have exactly the compiled keys.
    Parameters must remain within their declared bounds, including fixed values.
    """

    _nodes: tuple
    _mechanisms: tuple

    @property
    def order(self):
        return [mechanism.mechanism_id for mechanism in self._mechanisms]

    @property
    def parameter_bounds(self):
        return {m.mechanism_id: {key: {"low": scalar.low, "high": scalar.high}
                                 for key, scalar in m.parameters}
                for m in self._mechanisms}

    @property
    def parameter_bases(self):
        records = [scalar.record(nodeId=node_id, parameter="initialValue")
                   for node_id, scalar in self._nodes]
        for mechanism in self._mechanisms:
            records.append({"mechanismId": mechanism.mechanism_id,
                            "kind": mechanism.kind, "basis": mechanism.basis,
                            "sourceIds": list(mechanism.sources), "gap": mechanism.gap})
            records.extend(scalar.record(mechanismId=mechanism.mechanism_id, parameter=key)
                           for key, scalar in mechanism.parameters)
        return records

    def initial_values(self, rng):
        """Draw null-valued nodes; numeric values are fixed even with a range."""
        return {node_id: scalar.draw(rng) for node_id, scalar in self._nodes}

    def draw_parameters(self, rng):
        """Return per-mechanism scalar maps, including {} for parameterless ones."""
        return {m.mechanism_id: {key: scalar.draw(rng) for key, scalar in m.parameters}
                for m in self._mechanisms}

    def visible_projection(self, values, period):
        """Project a partial observation using parameter-prior midpoints.

        Only supplied, known primitive nodes with numeric values enter the
        projection. Unknown keys, nonnumeric observations and ALL supplied
        mechanism outputs are discarded. Nonfinite numeric observations raise.
        An output appears only if its identifier was supplied (visible) AND
        every upstream input is available. Even zero-input milestones cannot
        manufacture unobserved private nodes. Node
        seeds/ranges never fill an observation gap. Neither argument is mutated.
        """
        if type(period) is not int or period < 0:
            _fail("period", "expected a nonnegative integer")
        _object(values, "values")
        outputs = {mechanism.output for mechanism in self._mechanisms}
        state = {node_id: _number(values[node_id], f"values.{node_id}")
                 for node_id, _ in self._nodes
                 if node_id not in outputs and node_id in values
                 and type(values[node_id]) in (int, float)}
        for mechanism in self._mechanisms:
            if mechanism.output not in values or not all(node_id in state for node_id in mechanism.inputs):
                continue
            parameters = {key: scalar.midpoint() for key, scalar in mechanism.parameters}
            try:
                result = mechanism.evaluate(state, parameters, period)
            except (OverflowError, ValueError) as exc:
                if isinstance(exc, MechanismValidationError):
                    raise
                raise MechanismValidationError(
                    f"{mechanism.mechanism_id}: arithmetic produced an invalid result") from exc
            state[mechanism.output] = _number(result, mechanism.mechanism_id + ".output")
        return state

    def propagate(self, values, parameters, period):
        """Evaluate one period without mutation, randomness, or hidden state."""
        if type(period) is not int or period < 0:
            _fail("period", "expected a nonnegative integer")
        _keys(values, {node_id for node_id, _ in self._nodes}, (), "values")
        state = {key: _number(value, f"values.{key}") for key, value in values.items()}
        _keys(parameters, set(self.order), (), "parameters")
        checked = {}
        for mechanism in self._mechanisms:
            where = f"parameters.{mechanism.mechanism_id}"
            supplied = parameters[mechanism.mechanism_id]
            _keys(supplied, {key for key, _ in mechanism.parameters}, (), where)
            checked[mechanism.mechanism_id] = {}
            for key, scalar in mechanism.parameters:
                value = _number(supplied[key], f"{where}.{key}")
                if not scalar.low <= value <= scalar.high:
                    _fail(f"{where}.{key}", "value is outside declared parameter bounds")
                checked[mechanism.mechanism_id][key] = value
        for mechanism in self._mechanisms:
            try:
                result = mechanism.evaluate(state, checked[mechanism.mechanism_id], period)
            except (OverflowError, ValueError) as exc:
                if isinstance(exc, MechanismValidationError):
                    raise
                raise MechanismValidationError(
                    f"{mechanism.mechanism_id}: arithmetic produced an invalid result") from exc
            state[mechanism.output] = _number(result, mechanism.mechanism_id + ".output")
        return state


def compile_model(case):
    """Validate numeric inputs and compile a frozen DAG, raising ValueError.

    This deliberately does not replace whole-case validation. Only sources,
    nodes, mechanisms and an optional resolution.targetNodeId are consumed.
    Initial ranges must be bounded even on mechanism outputs. A fixed node
    value, when accompanied by a range, must lie within that range.
    """
    _object(case, "case")
    source_ids = set()
    for source in _list(case.get("sources", []), "sources"):
        _object(source, "source")
        source_id = _identifier(source.get("sourceId"), "source.sourceId")
        if source_id in source_ids:
            _fail("sources", f"duplicate source ID {source_id}")
        source_ids.add(source_id)

    nodes = {}
    for node in _list(case.get("nodes"), "nodes"):
        _object(node, "node")
        node_id = _identifier(node.get("nodeId"), "node.nodeId")
        if node_id in nodes:
            _fail("nodes", f"duplicate node ID {node_id}")
        where = f"nodes.{node_id}"
        sources = _sources(node.get("sourceIds", []), source_ids, where + ".sourceIds")
        provenance = (_provenance(node, source_ids, where) if "basis" in node else None)
        bounds = node.get("range")
        if bounds is not None:
            _keys(bounds, {"low", "high"}, (), where + ".range")
            low = _number(bounds["low"], where + ".range.low")
            high = _number(bounds["high"], where + ".range.high")
            if low > high:
                _fail(where, "range.low must be <= range.high")
        value = node.get("value")
        if value is None:
            if bounds is None:
                _fail(where, "a null value requires a bounded range")
            scalar = _Scalar(low, high, *(provenance or (
                "assumed", sources, "No fixed node value; uniform bounded initial-value assumption.")))
        else:
            value = _number(value, where + ".value")
            if bounds is not None and not low <= value <= high:
                _fail(where, "value is outside its declared range")
            observed = node.get("status") == "settled" and bool(sources)
            scalar = _Scalar(value, value, *(provenance or (
                "observed" if observed else "assumed", sources,
                "" if observed else "Fixed case value; no observed basis established here.")))
        nodes[node_id] = scalar
    if not nodes:
        _fail("nodes", "at least one node is required")
    if "resolution" in case:
        resolution = _object(case["resolution"], "resolution")
        target = _identifier(resolution.get("targetNodeId"), "resolution.targetNodeId")
        if target not in nodes:
            _fail("resolution.targetNodeId", "unknown node reference")

    mechanisms, writers = {}, {}
    parameter_keys = {
        "growth": set(), "sum": set(), "product": set(), "supply_demand": set(),
        "linear": {"coefficients", "intercept"}, "adoption": {"rate"},
        "regulatory_milestone": {"milestonePeriod", "before", "after"},
    }
    for raw in _list(case.get("mechanisms"), "mechanisms"):
        _object(raw, "mechanism")
        mechanism_id = _identifier(raw.get("mechanismId"), "mechanism.mechanismId")
        where = f"mechanisms.{mechanism_id}"
        if mechanism_id in mechanisms:
            _fail(where, "duplicate mechanism ID")
        kind = _identifier(raw.get("kind"), where + ".kind")
        if kind not in parameter_keys:
            _fail(where, f"unsupported mechanism kind {kind}")
        output = _identifier(raw.get("outputNodeId"), where + ".outputNodeId")
        inputs = tuple(_identifier(item, where + ".inputNodeIds")
                       for item in _list(raw.get("inputNodeIds"), where + ".inputNodeIds"))
        if output not in nodes or set(inputs) - nodes.keys():
            _fail(where, "unknown input or output node reference")
        if output in writers:
            _fail(where, f"duplicate output writer for {output}")
        if len(inputs) != len(set(inputs)):
            _fail(where, "duplicate input node references")
        arity = {"growth": 2, "supply_demand": 2, "adoption": 2,
                 "regulatory_milestone": 0}.get(kind)
        if (arity is not None and len(inputs) != arity) or (arity is None and not inputs):
            _fail(where, f"invalid input count for {kind}")
        params = raw.get("parameters")
        _keys(params, parameter_keys[kind], (), where + ".parameters")
        provenance = _provenance(raw, source_ids, where)
        scalars = {}
        if kind == "linear":
            coefficients = _list(params["coefficients"], where + ".parameters.coefficients")
            if len(coefficients) != len(inputs):
                _fail(where, "linear requires exactly one coefficient per input")
            scalars.update((f"coefficient:{node_id}",
                            _scalar(coefficient, provenance, source_ids,
                                    where + f".parameters.coefficients.{node_id}"))
                           for node_id, coefficient in zip(inputs, coefficients))
        for key, value in params.items():
            if key != "coefficients":
                scalars[key] = _scalar(value, provenance, source_ids, where + f".parameters.{key}")
        if kind == "adoption" and not 0 <= scalars["rate"].low <= scalars["rate"].high <= 1:
            _fail(where, "adoption rate bounds must be within [0, 1]")
        if kind == "regulatory_milestone" and scalars["milestonePeriod"].low < 0:
            _fail(where, "milestonePeriod must be nonnegative")
        mechanisms[mechanism_id] = _Mechanism(
            mechanism_id, kind, output, inputs, tuple(sorted(scalars.items())), *provenance)
        writers[output] = mechanism_id

    # Kahn's algorithm avoids recursion limits and input-list-order dependence.
    dependencies = {key: {writers[node_id] for node_id in m.inputs if node_id in writers}
                    for key, m in mechanisms.items()}
    dependents = {key: set() for key in mechanisms}
    for key, upstream in dependencies.items():
        for parent in upstream:
            dependents[parent].add(key)
    ready = [key for key, upstream in dependencies.items() if not upstream]
    heapify(ready)
    ordered = []
    while ready:
        key = heappop(ready)
        ordered.append(mechanisms[key])
        for child in sorted(dependents[key]):
            dependencies[child].remove(key)
            if not dependencies[child]:
                heappush(ready, child)
    if len(ordered) != len(mechanisms):
        _fail("mechanisms", "dependency graph contains a cycle")
    return CompiledModel(tuple(sorted(nodes.items())), tuple(ordered))


@dataclass(frozen=True)
class _Unit:
    dimensions: tuple
    scale: Fraction = Fraction(1)

    def combine(self, other, *, divide=False):
        dimensions = dict(self.dimensions)
        sign = -1 if divide else 1
        for name, power in other.dimensions:
            dimensions[name] = dimensions.get(name, 0) + sign * power
        return _Unit(tuple(sorted((name, power) for name, power in dimensions.items() if power)),
                     self.scale / other.scale if divide else self.scale * other.scale)


_DIMENSIONLESS = _Unit(())
_UNIT_NAMES = {name: _DIMENSIONLESS for name in ("fraction", "ratio", "1", "dimensionless")}
_UNIT_NAMES.update({name: _Unit((("count", 1),)) for name in ("unit", "units", "count", "counts")})
_UNIT_NAMES.update({name: _Unit(((name, 1),)) for name in ("USD", "EUR", "CNY")})
_UNIT_NAMES.update({name: _Unit((), Fraction(1, 100)) for name in ("percent", "%")})
_UNIT_SCALES = {"million": 10**6, "billion": 10**9}


class _UnsupportedUnit(ValueError):
    pass


def _parse_unit(raw):
    """Parse units with an explicit, iterative expression parser (never eval).

    Grammar: expression := factor (("*" | "/") factor)*; factor is a
    parenthesized expression or a named unit with at most one million/billion
    modifier immediately before or after it. Operators associate left to right.
    Vocabulary is case-sensitive and bounded by the tables above. Whitespace
    is insignificant; implicit products, powers and arbitrary names are rejected.
    Scale arithmetic is rational and exact, including reciprocal currencies.
    """
    if not isinstance(raw, str) or not raw.strip():
        raise _UnsupportedUnit("missing or non-text units")
    tokens = findall(r"[A-Za-z]+|[0-9]+|[^\s]", raw)
    values, operators = [], []
    expect_factor = True
    index = 0

    def reduce_operator():
        right = values.pop()
        left = values.pop()
        values.append(left.combine(right, divide=operators.pop() == "/"))

    while index < len(tokens):
        token = tokens[index]
        if expect_factor:
            if token == "(":
                operators.append(token)
                index += 1
                continue
            scale = 1
            has_prefix = token in _UNIT_SCALES
            if has_prefix:
                scale = _UNIT_SCALES[token]
                index += 1
                if index == len(tokens):
                    raise _UnsupportedUnit("scale modifier requires a named unit")
                token = tokens[index]
            unit = _UNIT_NAMES.get(token)
            if unit is None:
                raise _UnsupportedUnit(f"unsupported unit token {token!r}")
            index += 1
            if index < len(tokens) and tokens[index] in _UNIT_SCALES:
                if has_prefix:
                    raise _UnsupportedUnit("a named unit permits only one scale modifier")
                scale = _UNIT_SCALES[tokens[index]]
                index += 1
            values.append(_Unit(unit.dimensions, unit.scale * scale))
            expect_factor = False
        elif token in ("*", "/"):
            while operators and operators[-1] != "(":
                reduce_operator()
            operators.append(token)
            expect_factor = True
            index += 1
        elif token == ")":
            while operators and operators[-1] != "(":
                reduce_operator()
            if not operators:
                raise _UnsupportedUnit("unmatched closing parenthesis")
            operators.pop()
            index += 1
        else:
            raise _UnsupportedUnit(f"expected a product or division operator, got {token!r}")
    if expect_factor:
        raise _UnsupportedUnit("missing unit factor")
    while operators:
        if operators[-1] == "(":
            raise _UnsupportedUnit("unmatched opening parenthesis")
        reduce_operator()
    return values[0]


def _dimension_check(mechanism, units, unsupported):
    involved = (*mechanism.inputs, mechanism.output)
    invalid = {node_id: unsupported[node_id] for node_id in involved if node_id in unsupported}
    record = {"mechanismId": mechanism.mechanism_id, "kind": mechanism.kind,
              "outputNodeId": mechanism.output}
    if invalid:
        # An unknown unit must not mask an independently decidable contradiction.
        # Growth has two separate constraints; additive templates require every
        # pair of known units to agree. A partially unknown product cannot be
        # checked without inventing the missing factor's dimensions.
        known = {node_id: units[node_id] for node_id in involved if node_id not in invalid}
        contradiction = False
        if mechanism.kind == "growth":
            base, rate = mechanism.inputs
            contradiction = (base in known and mechanism.output in known
                             and known[base] != known[mechanism.output]) or (
                                 rate in known and known[rate] != _DIMENSIONLESS)
        elif mechanism.kind in {"sum", "linear", "supply_demand", "adoption"}:
            contradiction = len(set(known.values())) > 1
        if contradiction:
            return {**record, "status": "failed", "unsupportedUnits": invalid,
                    "message": "Known input/output dimensions or scales contradict the template; other units remain unsupported."}
        return {**record, "status": "unsupported", "unsupportedUnits": invalid,
                "message": "Unsupported units prevent a dimension and scale check."}
    inputs = [units[node_id] for node_id in mechanism.inputs]
    output = units[mechanism.output]
    if mechanism.kind == "growth":
        matches = inputs[0] == output and inputs[1] == _DIMENSIONLESS
        rule = "Base/output dimensions and scales must match; rate must be dimensionless with scale 1."
    elif mechanism.kind == "product":
        expected = _DIMENSIONLESS
        for unit in inputs:
            expected = expected.combine(unit)
        matches = expected == output
        rule = "Output dimensions and scale must equal the product of the input units."
    elif mechanism.kind == "regulatory_milestone":
        matches = True
        rule = "Numeric before/after levels inherit output units; milestonePeriod is a period index."
    else:
        matches = all(unit == output for unit in inputs)
        rule = "All input/output dimensions and scales must match."
        if mechanism.kind == "linear":
            rule += " Coefficients are dimensionless with scale 1; intercept inherits output units."
        elif mechanism.kind == "adoption":
            rule += " The numeric rate parameter is dimensionless with scale 1."
    return {**record, "status": "passed" if matches else "failed", "message": rule}


def _seed_check(mechanism, nodes, tolerance):
    """Check a local seed identity, never sampling or filling missing seeds."""
    record = {"mechanismId": mechanism.mechanism_id, "kind": mechanism.kind,
              "outputNodeId": mechanism.output, "period": 0, "tolerance": tolerance}
    missing = [node_id for node_id in (*mechanism.inputs, mechanism.output)
               if nodes[node_id].get("value") is None]
    uncertain = [key for key, scalar in mechanism.parameters if scalar.low != scalar.high]
    if missing or uncertain:
        return {**record, "status": "unmeasured", "missingSeedNodeIds": missing,
                "uncertainParameters": uncertain,
                "message": "A seed identity requires fixed input/output seeds and fixed parameters."}
    values = {node_id: nodes[node_id]["value"] for node_id in mechanism.inputs}
    parameters = {key: scalar.low for key, scalar in mechanism.parameters}
    actual = nodes[mechanism.output]["value"]
    try:
        expected = _number(mechanism.evaluate(values, parameters, 0), mechanism.mechanism_id + ".seed")
        # Rational subtraction avoids overflow and preserves integer differences
        # above 2**53. Tolerance is absolute, with no implicit relative allowance.
        difference = abs(Fraction(actual) - Fraction(expected))
    except (OverflowError, ValueError) as exc:
        return {**record, "status": "failed", "actual": actual,
                "message": f"Seed formula could not be evaluated: {exc}"}
    return {**record, "status": "passed" if difference <= Fraction(tolerance) else "failed",
            "actual": actual, "expected": expected,
            "message": "Compare the declared output with its formula on declared input seeds at period 0."}


def validate_model(case, *, strict=False, seed_tolerance=1e-8):
    """Return JSON-compatible dimension/scale and local period-zero seed checks.

    Structural errors still raise as in compile_model. Each mechanism gets one
    dimensionChecks and one seedChecks record. Unsupported units on unused
    nodes also get a dimensionChecks record. Check status is passed, failed,
    unsupported (units), or unmeasured (missing seeds/uncertain parameters).
    Overall status is failed if any check failed or is unsupported, otherwise
    passed; unmeasured checks are explicitly accepted, not counted as evidence.

    Seed checks use each equation's declared input/output values, including
    fixed intermediate-node seeds, with absolute seed_tolerance and no relative
    tolerance. Null values (even with a degenerate range) or non-degenerate
    parameter priors make that identity unmeasured. Parameters with equal bounds
    are fixed. No generated values or prior midpoints are used for seed checks.
    Numeric fixed values remain fixed even if accompanied by a wider range.

    Strict mode raises MechanismValidationError on failed/unsupported checks;
    missing seed evidence alone is accepted. compile_model is unchanged and
    does not implicitly invoke this opt-in validation.
    """
    if type(strict) is not bool:
        _fail("strict", "expected a bool")
    tolerance = _number(seed_tolerance, "seed_tolerance")
    if tolerance < 0:
        _fail("seed_tolerance", "expected a nonnegative number")
    model = compile_model(case)
    nodes = {node["nodeId"]: node for node in case["nodes"]}
    units, unsupported = {}, {}
    for node_id, node in sorted(nodes.items()):
        try:
            units[node_id] = _parse_unit(node.get("units"))
        except _UnsupportedUnit as exc:
            unsupported[node_id] = str(exc)
    dimensions = [_dimension_check(mechanism, units, unsupported) for mechanism in model._mechanisms]
    used = {node_id for mechanism in model._mechanisms for node_id in (*mechanism.inputs, mechanism.output)}
    dimensions.extend({"nodeId": node_id, "status": "unsupported", "message": message}
                      for node_id, message in unsupported.items() if node_id not in used)
    seeds = [_seed_check(mechanism, nodes, tolerance) for mechanism in model._mechanisms]
    failed = [check for check in (*dimensions, *seeds) if check["status"] in ("failed", "unsupported")]
    result = {"status": "failed" if failed else "passed", "dimensionChecks": dimensions, "seedChecks": seeds}
    if strict and failed:
        details = "; ".join(f"{check.get('mechanismId', check.get('nodeId'))}: {check['status']}: {check['message']}"
                            for check in failed)
        _fail("model", details)
    return result


def admit_model(case, *, seed_tolerance=1e-8):
    """Reject known contradictions and retain all unmeasured admission checks.

    This pure check is for target-first production admission. It neither changes
    compiler semantics nor interprets unsupported units as a contradiction.
    Strict/diagnostic experiments keep their existing validate_model behavior.
    Consumers must retain this receipt with the admitted case: ``unsupported``
    and ``unmeasured`` are permitted evidence gaps, never a successful check.
    """
    result = validate_model(case, seed_tolerance=seed_tolerance)
    checks = [*result["dimensionChecks"], *result["seedChecks"]]
    contradictions = [check for check in checks if check["status"] == "failed"]
    if contradictions:
        details = "; ".join(
            f"{check.get('mechanismId', check.get('nodeId'))}: {check['message']}"
            for check in contradictions)
        _fail("model admission", details)
    statuses = {check["status"] for check in checks}
    status = ("unsupported" if "unsupported" in statuses else
              "unmeasured" if "unmeasured" in statuses else "passed")
    return {**result, "status": status, "policy": "known-contradictions/v1"}
