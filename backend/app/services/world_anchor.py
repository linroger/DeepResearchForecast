"""Host-owned World Anchor context and consumer projections.

An anchor context is never decoded from a model's candidate world spec.  The
research/lifecycle loader authenticates its source index and external completion
pin before supplying it to a compiler, seed builder or actor projection.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
import hashlib
import json
from pathlib import Path
import re
import unicodedata
from typing import Any

from .official_data import bridge_module

ENGINES = frozenset({"oasis-legacy", "world-v1", "target-first-v1"})
CONFIG_KEY = "world_anchor"
LIFECYCLE_KEY = "world_anchor_lifecycle"
SCOPE_COMPLETION_KEY = "world_anchor_scope_completion"
_HASH = re.compile(r"[0-9a-f]{64}\Z")
ANCHOR_ARTIFACTS = (
    ("world_anchor_manifest", "world_anchor_manifest.json"),
    ("world_anchor_pack", "world_anchor.json"),
    ("world_anchor_sheet", "world_anchor.md"),
    ("world_anchor_gaps", "world_anchor_gaps.json"),
    ("world_anchor_coverage", "world_anchor_coverage.json"),
    ("world_anchor_inputs", "world_anchor_inputs.json"),
    ("world_anchor_contract", "world_anchor_contract.json"),
    ("world_anchor_policy", "world_anchor_policy.json"),
)


class WorldAnchorIntegrationError(ValueError):
    """A fixed-code boundary failure, without private evidence in its message."""

    def __init__(self, code):
        allowed = {"invalid_anchor_context", "invalid_anchor_join", "anchor_not_ready",
                   "anchor_binding_mismatch", "anchor_artifact_invalid", "anchor_actor_missing",
                   "invalid_anchor_request", "anchor_profile_required"}
        self.code = code if code in allowed else "invalid_anchor_context"
        super().__init__(self.code)


def _api():
    return bridge_module("world_anchor")


def _bytes(value):
    # Domain validation also rejects Python-only values, duplicate identities,
    # nonfinite numbers and scalar coercions before a context is constructed.
    _api().anchor_hash(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _name(value):
    if not isinstance(value, str) or not value.strip():
        raise WorldAnchorIntegrationError("invalid_anchor_join")
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _valid_hash(value):
    return isinstance(value, str) and _HASH.fullmatch(value) is not None


def new_run_option(value, *, private_binding=None):
    """Resolve the new-run default once. Reuse readers never call this function."""
    if value is None:
        if private_binding is not None:
            return None
        from ..config import Config
        value = bool(getattr(Config, "SIM_WORLD_ANCHOR", False))
    if value is False:
        return None
    if value is True:
        return {"mode": "v1"}
    if type(value) is not dict or value.get("mode") != "v1":
        raise WorldAnchorIntegrationError("invalid_anchor_request")
    if private_binding is None and set(value) != {"mode"}:
        raise WorldAnchorIntegrationError("invalid_anchor_request")
    return json.loads(json.dumps(value, allow_nan=False))


def pending_lifecycle(pipeline_id, request):
    """Persist enabled intent before any producer call or directory preparation."""
    if type(request) is not dict or "world_anchor" not in request:
        raise WorldAnchorIntegrationError("invalid_anchor_request")
    from .run_spending import api
    return {"schema_version": "world-anchor-lifecycle/v1", "status": "pending",
            "policy_version": "world-anchor-policy/v1", "owner_pipeline_id": pipeline_id,
            "request_sha256": api().hash_payload(request), "input_generation_id": None,
            "input_hash": None, "completion_manifest_sha256": None, "pack_hash": None,
            "error_code": None}


def enabled(options):
    """Absence permanently means off, including after environment changes."""
    if type(options) is not dict:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    if CONFIG_KEY not in options:
        if LIFECYCLE_KEY in options:
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        return False
    value = options[CONFIG_KEY]
    lifecycle = options.get(LIFECYCLE_KEY)
    if (type(value) is not dict or value.get("mode") != "v1"
            or type(lifecycle) is not dict
            or lifecycle.get("schema_version") != "world-anchor-lifecycle/v1"
            or lifecycle.get("status") not in {"pending", "ready", "failed"}):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    return True


def require_completed(state):
    """Admit only a completion pinned by the controller; never discover a loose pack."""
    if not enabled(state.options):
        return None
    lifecycle = state.options[LIFECYCLE_KEY]
    if lifecycle.get("owner_pipeline_id") != state.pipeline_id:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    if lifecycle["status"] != "ready" or not _valid_hash(lifecycle.get("completion_manifest_sha256")):
        raise WorldAnchorIntegrationError("anchor_not_ready")
    context = load_research_anchor(state.handoff_dir,
        expected_manifest_sha256=lifecycle["completion_manifest_sha256"],
        expected_budget_completion=_bound_scope_completion(state))
    if (context.pack["scope"]["run_id"] != state.pipeline_id
            or context.pack_hash != lifecycle.get("pack_hash")
            or context.pack["input_hash"] != lifecycle.get("input_hash")
            or context.pack["scope"]["research_generation_id"] != lifecycle.get("input_generation_id")):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    return context


def accept_completion(state, *, expected_manifest_sha256):
    """Called by the producer controller after its admitted output receipt arrives."""
    if not enabled(state.options):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    current = state.options[LIFECYCLE_KEY]
    if current["owner_pipeline_id"] != state.pipeline_id or current["status"] == "failed":
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    context = load_research_anchor(state.handoff_dir, expected_manifest_sha256=expected_manifest_sha256,
                                  expected_budget_completion=_bound_scope_completion(state))
    if context.pack["scope"]["run_id"] != state.pipeline_id:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    ready = {**current, "status": "ready", "input_generation_id": context.pack["scope"]["research_generation_id"],
             "input_hash": context.pack["input_hash"], "completion_manifest_sha256": expected_manifest_sha256,
             "pack_hash": context.pack_hash, "error_code": None}
    if current["status"] == "ready" and current != ready:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    state.options[LIFECYCLE_KEY] = ready
    return context


def _bound_scope_completion(state):
    """Only a ledger-authenticated parent handoff supplies this expected pin."""
    binding = state.options.get("spending_policy_v1")
    if type(binding) is dict and binding.get("schema") == "target-run-spending-binding/v2":
        completion = state.options.get(SCOPE_COMPLETION_KEY)
        if type(completion) is not dict:
            raise WorldAnchorIntegrationError("anchor_artifact_invalid")
        return completion
    return None


def complete_research_anchor(state):
    """Resolve the authenticated producer result before sealing the research stage."""
    if not enabled(state.options):
        return None
    lifecycle = state.options[LIFECYCLE_KEY]
    if lifecycle["status"] == "ready":
        return require_completed(state)
    return accept_completion(state,
        expected_manifest_sha256=lifecycle.get("completion_manifest_sha256"))


@dataclass(frozen=True, slots=True)
class AnchorContext:
    """Immutable admitted bytes plus the opaque authenticated evidence index.

    JSON properties return detached values.  Private-only pack identities belong
    to host control and must never be copied into actor prompts.
    """

    _pack_bytes: bytes = field(repr=False)
    _requirements_bytes: bytes = field(repr=False)
    _policy_bytes: bytes = field(repr=False)
    index: Any = field(repr=False)
    pack_hash: str
    emission_receipt_hash: str | None = None
    research_manifest_hash: str | None = None
    _join_bytes: bytes | None = field(default=None, repr=False)
    _cast_bytes: bytes | None = field(default=None, repr=False)
    _source_binding_bytes: bytes | None = field(default=None, repr=False)

    @property
    def pack(self):
        return json.loads(self._pack_bytes)

    @property
    def requirements(self):
        return json.loads(self._requirements_bytes)

    @property
    def policy(self):
        return json.loads(self._policy_bytes)

    @property
    def join(self):
        return None if self._join_bytes is None else json.loads(self._join_bytes)

    def with_join(self, join, *, cast_bytes):
        """Bind an exact host-owned cast file; callers cannot grant arbitrary UUIDs."""
        validate_anchor_context(self)
        _validate_join(self, join, cast_bytes)
        return AnchorContext(self._pack_bytes, self._requirements_bytes,
                             self._policy_bytes, self.index, self.pack_hash,
                             self.emission_receipt_hash, self.research_manifest_hash,
                             _bytes(join), bytes(cast_bytes), self._source_binding_bytes)


def make_anchor_context(pack, *, requirements, index, policy, expected_pack_hash,
                        emission_receipt_hash=None, research_manifest_hash=None):
    """Called only after the producer/loader authenticates the external pins."""
    api = _api()
    if not _valid_hash(expected_pack_hash) or api.anchor_hash(pack) != expected_pack_hash:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    for value in (emission_receipt_hash, research_manifest_hash):
        if value is not None and not _valid_hash(value):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    admitted = api.validate_pack(pack, requirements=requirements, index=index, policy=policy)
    if api.anchor_hash(admitted) != expected_pack_hash:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    return AnchorContext(_bytes(admitted), _bytes(requirements), _bytes(policy), index,
                         expected_pack_hash, emission_receipt_hash, research_manifest_hash)


def validate_anchor_context(context, *, engine=None):
    if type(context) is not AnchorContext or (engine is not None and engine not in ENGINES):
        raise WorldAnchorIntegrationError("invalid_anchor_context")
    api = _api()
    pack = context.pack
    if api.anchor_hash(pack) != context.pack_hash:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    api.validate_pack(pack, requirements=context.requirements,
                      index=context.index, policy=context.policy)
    if context._join_bytes is not None:
        _validate_join(context, context.join, context._cast_bytes)
    if engine is not None:
        ready = [row for row in pack["readiness"] if row["engine"] == engine]
        if len(ready) != 1 or ready[0]["status"] != "ready":
            raise WorldAnchorIntegrationError("anchor_not_ready")
    return context


def engine_projection(context, *, engine):
    validate_anchor_context(context, engine=engine)
    return _api().engine_projection(context.pack, requirements=context.requirements,
                                    index=context.index, policy=context.policy, engine=engine)


def actor_ref_for(context, entity_uuid):
    validate_anchor_context(context)
    if not isinstance(entity_uuid, str) or not context.join:
        raise WorldAnchorIntegrationError("anchor_actor_missing")
    rows = [row for row in context.join["rows"] if row["entity_uuid"] == entity_uuid]
    if len(rows) != 1:
        raise WorldAnchorIntegrationError("anchor_actor_missing")
    return rows[0]["actor_ref"]


def actor_projection(context, *, entity_uuid, at):
    actor_ref = actor_ref_for(context, entity_uuid)
    return _api().actor_projection(context.pack, requirements=context.requirements,
                                   index=context.index, policy=context.policy,
                                   actor_ref=actor_ref, at=at)


def prepare_world_parameters(context, requests):
    validate_anchor_context(context, engine="world-v1")
    return _api().prepare_world_parameters(context.pack, requests,
        expected_pack_hash=context.pack_hash, requirements=context.requirements,
        index=context.index, policy=context.policy)


def _validate_join(context, join, cast_bytes):
    keys = {"schema_version", "pack_hash", "research_manifest_hash", "cast_hash", "rows"}
    if (type(join) is not dict or set(join) != keys
            or join["schema_version"] != "world-anchor-actor-join/v1"
            or join["pack_hash"] != context.pack_hash
            or not context.research_manifest_hash
            or join["research_manifest_hash"] != context.research_manifest_hash
            or type(cast_bytes) is not bytes
            or hashlib.sha256(cast_bytes).hexdigest() != join["cast_hash"]
            or type(join["rows"]) is not list):
        raise WorldAnchorIntegrationError("invalid_anchor_join")
    try:
        cast = json.loads(cast_bytes)
        selected = [row for row in cast["decisions"] if row["status"] == "selected"]
        members = {row["entity_uuid"]: row for row in selected}
        if len(members) != len(selected) or any(not isinstance(k, str) or not k for k in members):
            raise ValueError
        contract = context.requirements["contract"]
        actors = {row["actor_ref"]: row for row in contract["actors"]}
        aliases = {}
        alias_refs = {}
        for alias in contract["aliases"]:
            if alias["field"] == "entity" and alias["canonical_id"] in actors:
                name = _name(alias["literal"])
                aliases.setdefault(name, set()).add(alias["canonical_id"])
                alias_refs.setdefault(name, []).append("alias_" + _api().anchor_hash(alias))
        seen_actors, seen_uuids = set(), set()
        for row in join["rows"]:
            if type(row) is not dict or set(row) != {
                    "actor_ref", "entity_uuid", "registry_artifact_id", "registry_pointer", "alias_ref_ids"}:
                raise ValueError
            actor, uuid = row["actor_ref"], row["entity_uuid"]
            if actor in seen_actors or uuid in seen_uuids or actor not in actors or uuid not in members:
                raise ValueError
            name = _name(members[uuid]["actor_name"])
            if (row["registry_artifact_id"] != actors[actor]["registry_artifact_id"]
                    or row["registry_pointer"] != actors[actor]["registry_pointer"]
                    or aliases.get(name) != {actor}
                    or row["alias_ref_ids"] != sorted(alias_refs.get(name, []))):
                raise ValueError
            seen_actors.add(actor)
            seen_uuids.add(uuid)
        if seen_uuids != set(members):
            raise ValueError
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise WorldAnchorIntegrationError("invalid_anchor_join") from exc


def anchor_config_pin(context, *, require_join=True):
    validate_anchor_context(context)
    if ((require_join and not context.join) or not context.research_manifest_hash
            or not context.emission_receipt_hash):
        raise WorldAnchorIntegrationError("anchor_not_ready")
    return {"mode": "v1", "policy_hash": _api().anchor_hash(context.policy),
            "research_generation_id": context.pack["scope"]["research_generation_id"],
            "pack_hash": context.pack_hash,
            "emission_receipt_hash": context.emission_receipt_hash,
            "completion_manifest_sha256": context.research_manifest_hash,
            "actor_join_sha256": (hashlib.sha256(context._join_bytes).hexdigest()
                                  if context._join_bytes is not None else None)}


def _publication():
    return bridge_module("world_anchor_publication")


def load_research_anchor(directory, *, expected_manifest_sha256, expected_scope=None,
                         expected_budget_completion=None):
    """Load a host-pinned completion generation, including independent review proof."""
    if not _valid_hash(expected_manifest_sha256):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    loaded = _publication().load_completion(directory,
        expected_manifest_sha256=expected_manifest_sha256, expected_scope=expected_scope)
    if expected_budget_completion is not None:
        try:
            _publication().validate_budget_completion(loaded, expected_budget_completion)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise WorldAnchorIntegrationError("anchor_artifact_invalid") from exc
    return make_anchor_context(loaded["pack"], requirements=loaded["requirements"],
        index=loaded["index"], policy=loaded["policy"],
        expected_pack_hash=loaded["manifest"]["pack_hash"],
        emission_receipt_hash=_api().anchor_hash(loaded["manifest"]["emission_receipt"]),
        research_manifest_hash=loaded["manifest_sha256"])


def bind_context_sources(context, *, simulation_id):
    """Attach the separately sealed research inputs consumed by a world compiler."""
    from .official_data import read_bound_research_core
    from .simulation_manager import SimulationManager

    validate_anchor_context(context)
    source = read_bound_research_core(simulation_id)
    if source.get("status") != "valid":
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    refreshed = load_research_anchor(source["handoff_dir"],
        expected_manifest_sha256=context.research_manifest_hash)
    if refreshed.pack_hash != context.pack_hash:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    directory = Path(SimulationManager.SIMULATION_DATA_DIR) / simulation_id
    binding_bytes = _publication().read_bytes(directory, "official_research_binding.json", limit=65536)
    fingerprint = {"simulation_id": simulation_id, "handoff_dir": source["handoff_dir"],
                   "binding_sha256": hashlib.sha256(binding_bytes).hexdigest(), "files": source["files"]}
    return replace(context, index=refreshed.index, _source_binding_bytes=_bytes(fingerprint))


def research_source_identity(simulation_id):
    """Content identity consumed at preparation, independent of its locator."""
    from .official_data import read_bound_research_core

    return _research_identity(read_bound_research_core(simulation_id))


def _research_identity(source):
    if source.get("status") != "valid":
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    return {"schema_version": "world-anchor-research-identity/v1",
            "pipeline_id": source["pipeline_id"], "files": dict(source["files"])}


def validate_world_source_inputs(context, *, research_report, actor_bundle, research_engine):
    """Compare supplied compiler inputs with the external immutable source binding."""
    from .official_data import read_bound_research_core
    from .simulation_manager import SimulationManager

    validate_anchor_context(context, engine="world-v1")
    if context._source_binding_bytes is None:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    pin = json.loads(context._source_binding_bytes)
    source = read_bound_research_core(pin["simulation_id"])
    raw = _publication().read_bytes(Path(SimulationManager.SIMULATION_DATA_DIR) / pin["simulation_id"],
                                    "official_research_binding.json", limit=65536)
    if (source.get("status") != "valid" or source.get("handoff_dir") != pin["handoff_dir"]
            or source.get("files") != pin["files"]
            or hashlib.sha256(raw).hexdigest() != pin["binding_sha256"]
            or not isinstance(research_report, str) or research_report != source["research_report"]):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    if research_engine in {"v3", "linear"}:
        expected = source["actors"]
    elif research_engine in {"legacy", "deerflow", "agentic"}:
        expected = {"actors": source["actors"], "sources": source["sources"],
                    "dossier": source["actor_dossier"]}
    else:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    if _api().anchor_hash(actor_bundle) != _api().anchor_hash(expected):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    # Match the existing compiler's source JSON recipe, including finite floats.
    return {"reportSha256": hashlib.sha256(research_report.encode("utf-8")).hexdigest(),
            "actorBundleSha256": _api().anchor_hash(actor_bundle or {"actors": []})}


def validate_config_pin(pin, *, require_join=True):
    fields = {"mode", "policy_hash", "research_generation_id", "pack_hash",
              "emission_receipt_hash", "completion_manifest_sha256", "actor_join_sha256"}
    if (type(pin) is not dict or set(pin) != fields or pin["mode"] != "v1"
            or not isinstance(pin["research_generation_id"], str) or not pin["research_generation_id"]
            or not all(_valid_hash(pin[k]) for k in fields - {"mode", "research_generation_id", "actor_join_sha256"})
            or (require_join and not _valid_hash(pin["actor_join_sha256"]))
            or (pin["actor_join_sha256"] is not None and not _valid_hash(pin["actor_join_sha256"]))):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    return dict(pin)


def bind_actor_cast(context, simulation_dir):
    """Create the one-to-one source-registry/cast join before config sealing."""
    validate_anchor_context(context)
    pub = _publication()
    cast_bytes = pub.read_bytes(simulation_dir, "actor_cast_manifest.json")
    cast = pub.decode_json(cast_bytes)
    contract = context.requirements["contract"]
    rows = []
    for decision in cast["decisions"]:
        if decision["status"] != "selected":
            continue
        name = _name(decision["actor_name"])
        matches = [a for a in contract["aliases"] if a["field"] == "entity" and _name(a["literal"]) == name]
        refs = {a["canonical_id"] for a in matches}
        actors = [a for a in contract["actors"] if a["actor_ref"] in refs]
        if len(actors) != 1 or refs != {actors[0]["actor_ref"]}:
            raise WorldAnchorIntegrationError("invalid_anchor_join")
        actor = actors[0]
        rows.append({"actor_ref": actor["actor_ref"], "entity_uuid": decision["entity_uuid"],
                     "registry_artifact_id": actor["registry_artifact_id"],
                     "registry_pointer": actor["registry_pointer"],
                     "alias_ref_ids": sorted("alias_" + _api().anchor_hash(a) for a in matches)})
    join = {"schema_version": "world-anchor-actor-join/v1", "pack_hash": context.pack_hash,
            "research_manifest_hash": context.research_manifest_hash,
            "cast_hash": hashlib.sha256(cast_bytes).hexdigest(),
            "rows": sorted(rows, key=lambda row: row["entity_uuid"])}
    joined = context.with_join(join, cast_bytes=cast_bytes)
    pub.write_once(simulation_dir, "world_anchor_join.json", joined._join_bytes)
    return joined


def load_runtime_anchor(config, simulation_dir):
    """Revalidate outside config/pack authority before runtime or cache reuse.

    An absent pin exits without importing the bridge, reading files, or consulting
    an environment default.  An enabled pin cannot select its own handoff path.
    """
    if type(config) is not dict:
        raise WorldAnchorIntegrationError("invalid_anchor_context")
    if CONFIG_KEY not in config:
        return None
    pin = validate_config_pin(config[CONFIG_KEY], require_join=False)
    try:
        from .simulation_manager import SimulationManager, validate_simulation_config_seal
        from .official_data import read_bound_research_core

        pub = _publication()
        directory = Path(simulation_dir)
        simulation_id = config.get("simulation_id")
        expected = Path(SimulationManager.SIMULATION_DATA_DIR).resolve() / str(simulation_id)
        if (not isinstance(simulation_id, str) or directory.is_symlink()
                or directory.resolve() != expected or directory.name != simulation_id):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        state = pub.decode_json(pub.read_bytes(directory, "state.json"))
        if state.get("simulation_engine") == "world-v1":
            return _load_native_world_anchor(directory, simulation_id, pin, state)
        validate_config_pin(pin)
        state_keys = ("simulation_id", "simulation_config_manifest_sha256", "simulation_config_sha256")
        if (state.get("simulation_id") != simulation_id
                or not all(_valid_hash(state.get(k)) for k in state_keys[1:])):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        config_bytes = pub.read_bytes(directory, "simulation_config.json")
        if (_api().anchor_hash(pub.decode_json(config_bytes)) != _api().anchor_hash(config)
                or hashlib.sha256(config_bytes).hexdigest() != state["simulation_config_sha256"]):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        preparation = validate_simulation_config_seal(str(directory),
            expected_manifest_sha256=state["simulation_config_manifest_sha256"],
            expected_config_sha256=state["simulation_config_sha256"],
            expected_simulation_id=simulation_id, require=True)
        source = read_bound_research_core(simulation_id)
        if (_research_identity(source)
                != preparation["bindings"]["world_anchor"]["research_identity"]):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        context = load_research_anchor(source["handoff_dir"],
            expected_manifest_sha256=pin["completion_manifest_sha256"])
        join_bytes = pub.read_bytes(directory, "world_anchor_join.json")
        if hashlib.sha256(join_bytes).hexdigest() != pin["actor_join_sha256"]:
            raise WorldAnchorIntegrationError("invalid_anchor_join")
        context = context.with_join(pub.decode_json(join_bytes),
                                    cast_bytes=pub.read_bytes(directory, "actor_cast_manifest.json"))
        if anchor_config_pin(context) != pin:
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        after = pub.decode_json(pub.read_bytes(directory, "state.json"))
        source_after = read_bound_research_core(simulation_id)
        if (any(after.get(k) != state.get(k) for k in state_keys)
                or pub.read_bytes(directory, "simulation_config.json") != config_bytes
                or pub.read_bytes(directory, "world_anchor_join.json") != join_bytes
                or source_after.get("status") != "valid"
                or source_after.get("pipeline_id") != source.get("pipeline_id")
                or source_after.get("files") != source["files"]
                or source_after.get("handoff_dir") != source["handoff_dir"]):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        return context
    except WorldAnchorIntegrationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise WorldAnchorIntegrationError("anchor_artifact_invalid") from exc


def _load_native_world_anchor(directory, simulation_id, pin, state):
    """Authenticate native world inputs before asking their compiler to recheck them."""
    from .official_data import read_bound_research_core
    from .world_simulation.artifacts import load_inputs

    pub = _publication()
    keys = ("simulation_id", "simulation_engine", "world_input_manifest_sha256",
            "world_spec_sha256", "world_generation_id")
    if (state.get("simulation_id") != simulation_id
            or not _valid_hash(state.get("world_input_manifest_sha256"))
            or not _valid_hash(state.get("world_spec_sha256"))):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    raw_manifest = pub.read_bytes(directory, "world_input_manifest.json")
    raw_spec = pub.read_bytes(directory, "world_spec.json", limit=16 * 1024 * 1024)
    manifest, spec = pub.decode_json(raw_manifest), pub.decode_json(raw_spec)
    if (hashlib.sha256(raw_manifest).hexdigest() != state["world_input_manifest_sha256"]
            or hashlib.sha256(raw_spec).hexdigest() != state["world_spec_sha256"]
            or manifest.get("specSha256") != state["world_spec_sha256"]
            or manifest.get("worldAnchor") != pin
            or spec.get("simulationId") != simulation_id
            or spec.get("generationId") != state["world_generation_id"]
            or spec.get("sourceBindings", {}).get("worldAnchor", {}).get("pin") != pin):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    source = read_bound_research_core(simulation_id)
    if source.get("status") != "valid":
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    context = load_research_anchor(source["handoff_dir"],
        expected_manifest_sha256=pin["completion_manifest_sha256"])
    context = bind_context_sources(context, simulation_id=simulation_id)
    if pin["actor_join_sha256"] is not None:
        raw_join = pub.read_bytes(directory, "world_anchor_join.json")
        if hashlib.sha256(raw_join).hexdigest() != pin["actor_join_sha256"]:
            raise WorldAnchorIntegrationError("invalid_anchor_join")
        context = context.with_join(pub.decode_json(raw_join),
                                    cast_bytes=pub.read_bytes(directory, "actor_cast_manifest.json"))
    if anchor_config_pin(context, require_join=False) != pin:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    source_engine = spec.get("sourceBindings", {}).get("researchEngine")
    bundle = source["actors"] if source_engine == "v3" else {
        "actors": source["actors"], "sources": source["sources"], "dossier": source["actor_dossier"]}
    consumed = validate_world_source_inputs(context, research_report=source["research_report"],
        actor_bundle=bundle, research_engine=source_engine)
    if spec["sourceBindings"]["worldAnchor"].get("consumedSources") != consumed:
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    # Supplying the authenticated context avoids recursive loader invocation.
    load_inputs(directory, simulation_id=simulation_id,
        expected_manifest_sha256=state["world_input_manifest_sha256"], anchor_context=context)
    after = pub.decode_json(pub.read_bytes(directory, "state.json"))
    source_after = read_bound_research_core(simulation_id)
    if (any(after.get(k) != state.get(k) for k in keys)
            or pub.read_bytes(directory, "world_input_manifest.json") != raw_manifest
            or pub.read_bytes(directory, "world_spec.json", limit=16 * 1024 * 1024) != raw_spec
            or source_after.get("status") != "valid"
            or source_after.get("pipeline_id") != source.get("pipeline_id")
            or source_after.get("files") != source["files"]
            or source_after.get("handoff_dir") != source["handoff_dir"]):
        raise WorldAnchorIntegrationError("anchor_binding_mismatch")
    return context


def load_target_anchor(simulation_dir, *, expected_case_hash=None):
    """Read the native target preparation through its external pipeline seals."""
    from ..config import Config
    from .pipeline_orchestrator import PipelineManager, PipelineState
    from .target_pipeline import AUTHORITY, validate_stage
    from .official_data import _contained_bytes

    try:
        directory = Path(simulation_dir)
        if (directory.is_symlink() or not re.fullmatch(r"sim_[A-Za-z0-9_-]{1,100}", directory.name)
                or directory.resolve().parent != Path(Config.OASIS_SIMULATION_DATA_DIR).resolve()):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    raise WorldAnchorIntegrationError("anchor_artifact_invalid")
                result[key] = value
            return result

        def invalid_constant(_):
            raise WorldAnchorIntegrationError("anchor_artifact_invalid")

        raw_input = _contained_bytes(directory, "target_input.json", limit=8 * 1024 * 1024)
        inputs = json.loads(raw_input, object_pairs_hook=pairs, parse_constant=invalid_constant)
        if type(inputs) is not dict:
            raise WorldAnchorIntegrationError("anchor_artifact_invalid")
        pipeline_id = inputs.get("pipelineId")
        if (inputs.get("schemaVersion") != "target-input/v1" or not isinstance(pipeline_id, str)
                or not re.fullmatch(r"pipe_[A-Za-z0-9_-]{1,100}", pipeline_id)):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        saved = PipelineManager.load(pipeline_id)

        def require_unmarked_result():
            try:
                result = json.loads(_contained_bytes(directory, "target_simulation.json", limit=64 * 1024 * 1024),
                                    object_pairs_hook=pairs, parse_constant=invalid_constant)
            except FileNotFoundError:
                result = {}
            if not isinstance(result, dict) or "worldAnchor" in result:
                raise WorldAnchorIntegrationError("anchor_binding_mismatch")

        if "worldAnchor" not in inputs and saved is None:
            # Old off-mode target artifacts can outlive their pipeline status.
            # A surviving enabled marker or corrupt retained owner is not off.
            if Path(PipelineManager.state_path(pipeline_id)).exists():
                raise WorldAnchorIntegrationError("anchor_binding_mismatch")
            require_unmarked_result()
            return None
        if not isinstance(saved, dict):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        state = PipelineState.from_dict(saved)
        if state.simulation_id != directory.name or state.options.get("forecast_authority") != AUTHORITY:
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        if not enabled(state.options):
            if "worldAnchor" in inputs:
                raise WorldAnchorIntegrationError("anchor_binding_mismatch")
            require_unmarked_result()
            return None
        pub = _publication()
        pin = validate_config_pin(inputs.get("worldAnchor"), require_join=False)
        if (any(state.stages.get(name) is None or state.stages[name].status != "completed"
                for name in ("research", "prepare"))
                or not validate_stage(state, "research") or not validate_stage(state, "prepare")):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        context = require_completed(state)
        if anchor_config_pin(context, require_join=False) != pin:
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        case_hash = state.options.get("target_case_binding", {}).get("caseHash")
        if (inputs.get("caseHash") != case_hash or not _valid_hash(case_hash)
                or (expected_case_hash is not None and expected_case_hash != case_hash)):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        case = bridge_module("forecast_case").read_case(directory / "target_case.json", expected_hash=case_hash)
        bridge_module("world_anchor_case").validate_anchored_case(case, pack=context.pack,
            requirements=context.requirements, index=context.index, policy=context.policy)
        after = PipelineState.from_dict(PipelineManager.load(pipeline_id))
        if (after.simulation_id != state.simulation_id
                or after.options.get(LIFECYCLE_KEY) != state.options.get(LIFECYCLE_KEY)
                or after.options.get("target_case_binding") != state.options.get("target_case_binding")
                or pub.read_bytes(directory, "target_input.json") != raw_input
                or not validate_stage(after, "research") or not validate_stage(after, "prepare")):
            raise WorldAnchorIntegrationError("anchor_binding_mismatch")
        return context
    except WorldAnchorIntegrationError:
        raise
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise WorldAnchorIntegrationError("anchor_artifact_invalid") from exc
