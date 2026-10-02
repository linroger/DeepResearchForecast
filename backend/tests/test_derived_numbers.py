"""RESEARCH-8: the hardened Decimal evaluator and clause grammar of
declarative derived findings (deerflow_bridge/derived_numbers.py).

A research agent writes a calculated figure as a formula over named operands
read from one fetched page; the engine recomputes it.  These tests pin the
AST whitelist (and everything it rejects), the literal policy (every number
but 0, 1, 100 and 1000 must be a named, page-checked operand), the exponent
pre-check and finiteness at every step, the bounded running time on
adversarial input, the clause grammar (also the Chinese form and
``years(Y1,Y2)``), display-precision matching and exact formatting.
Offline, stdlib only.
"""

from __future__ import annotations

import os
import sys
import time
from decimal import Decimal

import pytest

_BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BRIDGE = os.path.join(os.path.dirname(_BACKEND), "deerflow_bridge")
if _BRIDGE not in sys.path:
    sys.path.insert(0, _BRIDGE)

import derived_numbers as dn  # noqa: E402

OPERANDS = {"a": Decimal(37), "b": Decimal(13), "n": Decimal(5), "big": Decimal(1000), "ten": Decimal(10),
            "hundred": Decimal(100)}


def calc(expr: str, **operands: Decimal) -> Decimal:
    return dn.evaluate(expr, operands or OPERANDS)


def rejects(expr: str, **operands: Decimal) -> str:
    with pytest.raises(dn.CalcError) as caught:
        calc(expr, **operands)
    return str(caught.value)


# ------------------------------------------------------------------ whitelist

@pytest.mark.parametrize("expr", [
    "c + a",                         # a name outside the operand set
    "a.real",                        # attribute
    "a.__class__",
    "(a, b)[0]",                     # subscript
    "sqrt(a=a)",                     # keyword
    "max(a, b, key=a)",
    "lambda: a",                     # lambda
    "[x for x in (a, b)]",           # comprehensions
    "{x for x in (a, b)}",
    "{x: x for x in (a, b)}",
    "sum(x for x in (a, b))",
    "a % b",                         # modulo
    "a // b",                        # floor division
    "True",                          # bool literals
    "a * False",
    "True + a",
])
def test_the_whitelist_rejects_everything_outside_it(expr):
    rejects(expr)


def test_bool_literals_are_rejected_by_type_even_though_true_equals_one():
    assert True in dn.ALLOWED_LITERALS      # membership alone would let True through
    assert "literal True" in rejects("a * True")


def test_a_number_literal_must_be_a_named_operand_and_the_message_names_it():
    message = rejects("(37-13)/13*100")
    assert "literal 37" in message and "named operand" in message
    assert calc("(a-b)/b*100") == Decimal(24) / Decimal(13) * 100
    assert dn.format_exact(calc("(a-b)/b*100")) == "184.615384615"
    for literal in ("0", "1", "100", "1000", "1000.0"):
        calc(f"a + {literal}")
    for literal in ("2", "10", "0.5", "1e3j", "'1'", "None"):
        rejects(f"a + {literal}")


def test_the_allowed_operators_and_functions_compute_in_decimal():
    assert calc("a + b - n * b / b") == Decimal(45)
    assert calc("-a") == Decimal(-37)
    assert calc("n ** 1") == Decimal(5)
    assert calc("abs(b - a)") == Decimal(24)
    assert calc("min(a, b, n)") == Decimal(5) and calc("max(a, b)") == Decimal(37)
    assert calc("sqrt(hundred)") == Decimal(10)
    assert calc("log10(big)") == Decimal(3)
    assert calc("ln(exp(n))").quantize(Decimal("1.000000")) == Decimal("5.000000")
    # Compound growth with a period operand: (37/13)^(1/5) - 1.
    assert dn.format_exact(calc("((a/b)**(1/n)-1)*100")) == "23.2683759853"


@pytest.mark.parametrize("expr", ["+a", "~a", "not a", "a ^ b", "a & b", "a << n", "a < b", "a and b",
                                  "a if b else n", "a @ b", "(a := b)", "f'{a}'", "*a"])
def test_unlisted_operators_are_rejected(expr):
    rejects(expr)


@pytest.mark.parametrize("expr", ["round(a)", "pow(a, b)", "__import__('os')", "eval('a')", "math.sqrt(a)",
                                  "abs(a, b)", "sqrt()", "max(a)", "min(*a)", "a(b)"])
def test_only_whitelisted_calls_with_their_arity_are_allowed(expr):
    rejects(expr)


# ------------------------------------------------------------------ bounds

@pytest.mark.parametrize("expr,operands", [
    ("10**10**10", {}),
    ("ten**ten**ten", {"ten": Decimal(10)}),
    ("ten**(ten*ten*ten)", {"ten": Decimal(10)}),
    ("((big**hundred)**hundred)**hundred", {"big": Decimal(1000), "hundred": Decimal(100)}),
    ("exp(exp(exp(exp(ten))))", {"ten": Decimal(10)}),
    ("exp(big*big*big)", {"big": Decimal(1000)}),
])
def test_huge_and_nested_powers_fail_fast(expr, operands):
    start = time.perf_counter()
    with pytest.raises(dn.CalcError):
        dn.evaluate(expr, operands)
    assert time.perf_counter() - start < 0.05


def test_the_exponent_is_checked_before_the_power_is_computed():
    assert "larger than 100" in rejects("a ** big")
    assert "larger than 100" in rejects("a ** -big")
    assert calc("ten ** hundred / ten ** hundred") == 1      # 1e100 is a valid intermediate step


@pytest.mark.parametrize("expr", ["(-8)**0.5", "(-a)**(1/n*0+1/(n-3))", "exp(ln(0))", "a/0", "a/(b-b)", "ln(0)",
                                  "log10(b-b)", "sqrt(-a)", "ln(-a)", "0**(0-1)", "(b-b)**0"])
def test_invalid_and_non_finite_steps_fail(expr):
    rejects(expr)


def test_negative_square_root_power_and_finiteness_at_every_node():
    rejects("x ** 0.5", x=Decimal(-8))           # literal 0.5 is not allowed either
    rejects("x ** h", x=Decimal(-8), h=Decimal("0.5"))
    # ln(0) is -Infinity without a trap; exp of it would be a finite 0.
    assert "not finite" in rejects("exp(ln(z))", z=Decimal(0))


def test_size_depth_and_result_bounds():
    assert "longer than 300" in rejects("a+" * 150 + "a")
    assert "syntax nodes" in rejects("+".join(["a"] * 25))
    assert "nests deeper" in rejects("-(" * 19 + "a" + ")" * 19)
    assert calc("-(" * 17 + "a" + ")" * 17) == -37
    assert "1e15" in rejects("big ** n")                       # 1e15 itself
    assert calc("big ** n / ten") == Decimal("1e14")
    with pytest.raises(dn.CalcError):
        dn.evaluate("a", {"a": Decimal("NaN")})
    with pytest.raises(dn.CalcError):
        dn.evaluate("a", {"a": 37})


ADVERSARIAL = [
    "__import__('os').system('true')", "().__class__.__bases__[0].__subclasses__()", "open('/etc/passwd')",
    "globals()", "a.__dict__", "getattr(a, 'real')", "[a] * big", "'x' * big", "b'x'", "...", "None",
    "a if a else b", "yield a", "await a", "lambda a: a", "(lambda: 0)()", "a[0:1]", "{a: b}", "{a, b}", "[a, b]",
    "(a, b)", "a == b", "not a", "a or b", "a; b", "import os", "a = b", "del a", "print(a)",
    "exp(exp(exp(a)))", "a ** a ** a", "sqrt(-b)", "ln(b - b)", "log10(-a)", "exp(ln(b - b))", "a / (b - b)",
    "1e309 * a", "(" * 90 + "a" + ")" * 90, "-" * 299 + "a", "a" * 400, "\x00", "a\nb", "max()",
    "min(a, b, n, big, ten, hundred, a, b, n, big, ten, hundred, a, b, n, big, ten, hundred, a, b, n)",
    "(a - b) / b * 100", "abs(-a) + max(a, b) - min(a, b)", "sqrt(a * b) / n", "-(-(-a))", "ln(a) / ln(b)",
]
# The corpus members that are valid formulas (redundant brackets and a long
# argument list included).
BENIGN = {"(" * 90 + "a" + ")" * 90, "min(a, b, n, big, ten, hundred, a, b, n, big, ten, hundred, a, b, n, big, ten, "
          "hundred, a, b, n)", "(a - b) / b * 100", "abs(-a) + max(a, b) - min(a, b)", "sqrt(a * b) / n",
          "-(-(-a))", "ln(a) / ln(b)"}


def test_an_adversarial_corpus_yields_only_calc_errors_or_finite_decimals():
    assert len(ADVERSARIAL) >= 30 and BENIGN <= set(ADVERSARIAL)
    finite = set()
    for expr in ADVERSARIAL:
        start = time.perf_counter()
        try:
            value = dn.evaluate(expr, OPERANDS)
        except dn.CalcError:
            pass
        else:
            assert isinstance(value, Decimal) and value.is_finite() and abs(value) < dn.RESULT_LIMIT, expr
            finite.add(expr)
        assert time.perf_counter() - start < 0.05, expr
    assert finite == BENIGN


# ------------------------------------------------------------------ matching and formatting

def test_token_matches_uses_the_stated_display_precision():
    assert dn.token_matches("185", Decimal("184.6"))
    assert not dn.token_matches("190", Decimal("184.6"))
    assert dn.token_matches("184.6", Decimal("184.615"))
    assert not dn.token_matches("184.7", Decimal("184.615"))
    assert dn.token_matches("185", Decimal("185.5"))          # the half-unit bound is inclusive
    assert not dn.token_matches("185", Decimal("185.51"))
    assert not dn.token_matches("185", Decimal("1.846"))
    for token in ("", "abc", "-5", "1.2.3", "NaN", "Infinity"):
        assert not dn.token_matches(token, Decimal(5))
    assert not dn.token_matches("5", Decimal("Infinity"))
    assert not dn.token_matches("5", 5)
    assert not dn.token_matches("1" + "0" * 2000, Decimal(5))             # never raises on a huge token


def test_token_matches_keeps_the_result_sign():
    """An unsigned token states only a non-negative result: "grew 65%" is no
    (b-a)/a*100 = -64.9, a decline is written in its own direction."""
    assert not dn.token_matches("12", Decimal("-12.2"))
    assert not dn.token_matches("65", Decimal("-64.8648648649"))
    assert not dn.token_matches("0.00", Decimal("-0.001"))
    assert not dn.token_matches("185", Decimal("-1.846"), percent=True)
    assert dn.token_matches("12", Decimal("12.2"))
    assert dn.token_matches("0", Decimal("0.4"))


def test_token_matches_reads_a_percentage_at_one_scale_only():
    # percent: the result is a ratio, compared x 100 only.
    assert dn.token_matches("185", Decimal("1.846"), percent=True)
    assert not dn.token_matches("1.8", Decimal("1.846"), percent=True)
    assert not dn.token_matches("2.8", Decimal("2.846"), percent=True)
    assert not dn.token_matches("185", Decimal("184.6"), percent=True)
    # Otherwise the result as it is.
    assert dn.token_matches("185", Decimal("184.6"))
    assert dn.token_matches("1.8", Decimal("1.846"))


def test_scales_to_percent_finds_a_multiplication_by_the_literal_100():
    for expr in ("(a-b)/b*100", "100*(a-b)/b", "((a/b)**(1/n)-1)*100", "a/b*100 - 100", "a * 100.0"):
        assert dn.scales_to_percent(expr), expr
    for expr in ("(a-b)/b", "a/b", "a*1000", "a/100", "(a-b)/(b/100)", "a+100", "", "a +* b", None, "a" * 400,
                 "(a-b)/b*hundred"):
        assert not dn.scales_to_percent(expr), expr


def test_is_additive_reads_sums_and_differences_only():
    for expr in ("a-b", "a+b-c", "100-a", "-a", "abs(a-b)", "max(a,b)-c", "min(a, b)", "a"):
        assert dn.is_additive(expr), expr
    for expr in ("a/b", "a*b", "(a-b)/b*100", "a**2", "sqrt(a)-b", "ln(a)", "abs(a/b)", "a-b*1", "", "a +* b",
                 None, "a" * 400, "a.b - c", "f(a)"):
        assert not dn.is_additive(expr), expr


def test_keeps_unit_reads_sums_of_data_operands_scaled_by_literals():
    names = {"a", "b", "c"}
    for expr in ("a-b", "a+b-c", "100-a", "-a", "abs(a-b)", "max(a,b)-c", "min(a, b)", "a", "a*1000", "1000*a",
                 "a/1000", "-a*100", "(a-b)/1000", "abs(a)*1000", "a*1000*1000", "(a-b)*1000/1000"):
        assert dn.keeps_unit(expr, names), expr
    for expr in ("a/b", "a*b", "(a-b)/b", "(a-b)/b*100", "1000/a", "a**2", "a**1", "sqrt(a)", "ln(a)", "a-n",
                 "a/n", "(a-b)/n", "100", "1000*100", "abs(1000)", "a*True", "+a", "max(a, key=b)", "max(*a)",
                 "", "a +* b", None, "a" * 400, "a.b - c", "f(a)"):
        assert not dn.keeps_unit(expr, names), expr
    assert not dn.keeps_unit("a-b", set()) and not dn.keeps_unit("a-b", {"a"})


def test_is_quotient_reads_a_top_division_of_data_operands_only():
    names = {"a", "b", "c"}
    for expr in ("a/b", "(a-b)/b", "(b-a)/a", "a/(b+c)", "100*a/b", "abs(a-b)/b", "-a/b", "a/b/c", " a / b "):
        assert dn.is_quotient(expr, names), expr
    for expr in ("a/b*100", "a/b-1", "((a/b)**(1/n)-1)", "a*b", "a**1", "sqrt(a)", "ln(a)", "abs(a/b)", "-(a/b)",
                 "a-b", "a", "(a-b)/1000", "(a-b)/n", "1000/a", "a/1000", "100/1000", "n/a", "a/n",
                 "", "a +* b", None, "a" * 400):
        assert not dn.is_quotient(expr, names), expr
    assert not dn.is_quotient("a/b", set()) and not dn.is_quotient("a/b", {"a"}) and not dn.is_quotient("a/b", None)


def test_format_exact_has_twelve_significant_digits_and_no_exponent():
    assert dn.format_exact(Decimal(24) / Decimal(13) * 100) == "184.615384615"
    assert dn.format_exact(Decimal("1.2e12")) == "1200000000000"
    assert dn.format_exact(Decimal("123456789012345")) == "123456789012000"
    assert dn.format_exact(Decimal("-0.0001234567890123")) == "-0.000123456789012"
    assert dn.format_exact(Decimal("17.50")) == "17.5"
    assert dn.format_exact(Decimal("0E-5")) == "0"
    with pytest.raises(dn.CalcError):
        dn.format_exact(Decimal("Infinity"))


# ------------------------------------------------------------------ clause grammar

def test_parse_derivation_reads_the_formula_operands_sources_and_period():
    expr, operands = dn.parse_derivation(
        "(DERIVED: ((a/b)**(1/n)-1)*100; a=37 GW [S12], b=13 GW [S12], n=years(2019,2024))")
    assert expr == "((a/b)**(1/n)-1)*100"
    assert operands == [("a", "37 GW", 12, dn.KIND_DATA), ("b", "13 GW", 12, dn.KIND_DATA),
                        ("n", "years(2019,2024)", None, dn.KIND_PERIOD)]
    assert dn.period_value("years(2019,2024)") == Decimal(5)
    assert dn.period_value("years( 2019 , 2024 )") == Decimal(5)
    assert dn.period_years("years( 2019 , 2024 )") == (2019, 2024)
    for raw in ("years(2024,2019)", "years(1850,2024)", "2019-2024", None):
        with pytest.raises(dn.CalcError):
            dn.period_years(raw)


def test_the_clause_opener_is_upper_case_derived_or_the_chinese_form():
    for text in ("(DERIVED: a; a=37 [S1])", "（DERIVED：a; a=37 [S1])", "(DERIVED : a", "（推算：a；a=37）"):
        assert dn.CLAUSE_OPEN_RE.search(text), text
    # Prose is no clause.
    for text in ("Revenue (derived: from licensing) rose", "(Derived: a; a=37 [S1])", "(derivedly: a"):
        assert dn.CLAUSE_OPEN_RE.search(text) is None, text


def test_parse_derivation_accepts_the_chinese_clause():
    expr, operands = dn.parse_derivation("（推算：（a－b）／b×100；a=37 GW [S12]，b=1,234 GW [S12]、c=５% [S12]）")
    assert expr == "(a-b)/b*100"
    assert operands == [("a", "37 GW", 12, dn.KIND_DATA), ("b", "1,234 GW", 12, dn.KIND_DATA),
                        ("c", "5%", 12, dn.KIND_DATA)]


def test_parse_derivation_without_the_wrapper_and_with_typographic_operators():
    expr, operands = dn.parse_derivation("`(a − b) ÷ b × 100 ^ 1`; a=37 [S1], b=13")
    assert expr == "(a - b) / b * 100 ** 1"
    assert operands == [("a", "37", 1, dn.KIND_DATA), ("b", "13", None, dn.KIND_DATA)]


@pytest.mark.parametrize("clause", [
    "(DERIVED: )",                                            # no formula
    "(DERIVED: (a-b)/b*100)",                                 # no operands
    "(DERIVED: (a-b)/b*100; )",
    "(DERIVED: a; where a=37 [S1])",                          # text before the first operand
    "(DERIVED: a; A=37 [S1])",                                # names are lower-case
    "(DERIVED: a; a=[S1])",                                   # an empty value
    "(DERIVED: a; a=37 [S1][S2])",                            # one value, two sources
    "(DERIVED: a+b; a=37 [S1], a=13 [S1])",                   # a name defined twice
    "(DERIVED: a; ln=37 [S1])",                               # a function name
    "(DERIVED: a; if=37 [S1])",                               # a keyword
    "(DERIVED: a/n; a=37 [S1], n=years(2024,2019))",          # a period running backwards
    "(DERIVED: a/n; a=37 [S1], n=years(1850,2024))",
    "(DERIVED: a; " + ", ".join(f"v{i}={i}0 [S1]" for i in range(9)) + ")",   # more than 8 operands
])
def test_parse_derivation_rejects_malformed_clauses(clause):
    with pytest.raises(dn.CalcError):
        dn.parse_derivation(clause)


def test_an_operand_name_is_at_most_sixteen_characters():
    assert dn.parse_derivation("x; capacity_2024_gw=37 [S1]")[1][0][0] == "capacity_2024_gw"
    with pytest.raises(dn.CalcError):
        dn.parse_derivation("x; capacity_2024_gwx=37 [S1]")
