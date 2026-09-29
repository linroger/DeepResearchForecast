"""Offline unit tests for the ENV-1 pin-divergence audit + the preserved
doc-drift mode of backend/scripts/check_env_drift.py.

All tests are hermetic: they feed the analyzer in-memory config/example text and
a tmp .env file (never the real repo files), so results don't depend on the
developer's machine. Covers: config-default introspection, .env parsing,
divergence detection, secret masking (incl. the token-COUNT false-positive
guard), performance-critical flagging, and every exit-code path.
"""

import os
import sys

import pytest

# The script lives in backend/scripts/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts"))

import check_env_drift as ed  # noqa: E402


# A miniature config.py source exercising every default shape the real file uses:
# int(...or...), plain int(...), .strip().lower(), bool compare, empty default,
# a non-empty secret default, and a token-COUNT knob (must NOT be masked).
FAKE_CONFIG = """
import os
class Config:
    REPORT_SECTION_CONCURRENCY = int(os.environ.get('REPORT_SECTION_CONCURRENCY', '6') or '6')
    OASIS_SEMAPHORE = int(os.environ.get('OASIS_SEMAPHORE', '24') or '24')
    ONTOLOGY_TEMPLATE = os.environ.get('ONTOLOGY_TEMPLATE', 'social_opinion').strip().lower()
    REPORT_BILINGUAL = os.environ.get('REPORT_BILINGUAL', 'true').strip().lower() == 'true'
    REPORT_AGENT_SECTION_MAX_TOKENS = int(os.environ.get('REPORT_AGENT_SECTION_MAX_TOKENS', '32768'))
    LLM_API_KEY = os.environ.get('LLM_API_KEY', '')
    DEMO_API_KEY = os.environ.get('DEMO_API_KEY', 'placeholder-secret')
    # doc-comment mention must NOT shadow the real default above:
    # os.environ.get('REPORT_SECTION_CONCURRENCY', 'ignore-me')
"""

FAKE_EXAMPLE = """
# guidance only
ONLY_IN_EXAMPLE=exdefault
REPORT_SECTION_CONCURRENCY=6
"""


def _write(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(p)


# --------------------------------------------------------------- config_defaults
def test_config_defaults_regex_shapes():
    d = ed.config_defaults(FAKE_CONFIG)
    assert d["REPORT_SECTION_CONCURRENCY"] == "6"   # int(...or...)
    assert d["OASIS_SEMAPHORE"] == "24"
    assert d["ONTOLOGY_TEMPLATE"] == "social_opinion"
    assert d["REPORT_BILINGUAL"] == "true"
    assert d["REPORT_AGENT_SECTION_MAX_TOKENS"] == "32768"  # plain int(...)
    assert d["LLM_API_KEY"] == ""                   # empty default captured
    assert d["DEMO_API_KEY"] == "placeholder-secret"


def test_config_defaults_first_definition_wins():
    # The real assignment precedes the doc-comment mention; first wins.
    assert ed.config_defaults(FAKE_CONFIG)["REPORT_SECTION_CONCURRENCY"] == "6"


# --------------------------------------------------------------- parse_env_text
def test_parse_env_text_dotenv_semantics():
    txt = "\n".join([
        "# comment",
        "",
        "export EXPORTED=yes   # trailing note",
        'QUOTED="  spaced  "',
        "INLINE=foo  # note",
        "HASHVAL=sk-abc#notcomment",
        "not a var line",
        "lowercase=skip",   # non [A-Za-z_] first? actually valid key; keep as-is
    ])
    got = ed.parse_env_text(txt)
    assert got["EXPORTED"] == "yes"                 # export prefix + inline comment stripped
    assert got["QUOTED"] == "  spaced  "            # quotes preserved contents, not stripped inside
    assert got["INLINE"] == "foo"                   # unquoted inline comment stripped
    assert got["HASHVAL"] == "sk-abc#notcomment"    # no space before # → kept intact
    assert "not a var line" not in got
    assert got["lowercase"] == "skip"


def test_parse_env_file_missing(tmp_path):
    assert ed.parse_env_file(str(tmp_path / "nope.env")) == {}


# --------------------------------------------------------------- divergence
def test_divergence_detection_core(tmp_path):
    env = _write(tmp_path, ".env", [
        "REPORT_SECTION_CONCURRENCY=1",     # 1 vs 6  → divergent, critical
        "OASIS_SEMAPHORE=24",               # matches default → NOT divergent
        "ONTOLOGY_TEMPLATE=general_forecast",  # vs social_opinion → divergent, not critical
        "REPORT_BILINGUAL=True",            # True vs true → bool-fold → NOT divergent
    ])
    rows = ed.find_divergent_pins(env, FAKE_CONFIG, FAKE_EXAMPLE)
    vars_ = [r["var"] for r in rows]
    assert vars_ == ["REPORT_SECTION_CONCURRENCY", "ONTOLOGY_TEMPLATE"]  # critical-first ordering
    assert "OASIS_SEMAPHORE" not in vars_
    assert "REPORT_BILINGUAL" not in vars_
    r0 = rows[0]
    assert r0["critical"] is True and r0["pinned"] == "1" and r0["current_default"] == "6"
    assert r0["default_source"] == "config"
    assert rows[1]["critical"] is False


def test_empty_default_pin_is_not_divergent(tmp_path):
    # LLM_API_KEY default is '' (unset-by-default); pinning a real key is expected.
    env = _write(tmp_path, ".env", ["LLM_API_KEY=sk-live-value"])
    rows = ed.find_divergent_pins(env, FAKE_CONFIG, FAKE_EXAMPLE)
    assert [r["var"] for r in rows] == []


def test_example_value_is_fallback_reference(tmp_path):
    # ONLY_IN_EXAMPLE has no config default → reference comes from .env.example.
    env = _write(tmp_path, ".env", ["ONLY_IN_EXAMPLE=changed"])
    rows = ed.find_divergent_pins(env, FAKE_CONFIG, FAKE_EXAMPLE)
    assert len(rows) == 1
    assert rows[0]["var"] == "ONLY_IN_EXAMPLE"
    assert rows[0]["default_source"] == "env.example"
    assert rows[0]["current_default"] == "exdefault"


def test_infra_vars_ignored(tmp_path):
    env = _write(tmp_path, ".env", ["FLASK_PORT=9999", "ZEP_API_KEY=whatever"])
    rows = ed.find_divergent_pins(env, FAKE_CONFIG, FAKE_EXAMPLE)
    assert rows == []


# --------------------------------------------------------------- masking
def test_is_secret_segment_aware():
    assert ed.is_secret("LLM_API_KEY") is True
    assert ed.is_secret("APP_API_TOKEN") is True
    assert ed.is_secret("SECRET_KEY") is True
    assert ed.is_secret("DB_PASSWORD") is True
    # token-COUNT knob and 'contains KEY' names must NOT be treated as secret:
    assert ed.is_secret("REPORT_AGENT_SECTION_MAX_TOKENS") is False
    assert ed.is_secret("MONKEY_INDEX") is False
    assert ed.is_secret("OASIS_SEMAPHORE") is False


def test_mask_value():
    assert ed.mask_value("LLM_API_KEY", "sk-supersecret") == "***"
    assert ed.mask_value("OASIS_SEMAPHORE", "24") == "24"


def test_secret_value_never_leaks_in_record(tmp_path):
    # DEMO_API_KEY has a NON-empty default → it CAN diverge; the raw value must
    # be masked in every record field (and the token-count knob stays unmasked).
    env = _write(tmp_path, ".env", [
        "DEMO_API_KEY=sk-different-value",
        "REPORT_AGENT_SECTION_MAX_TOKENS=8192",
    ])
    rows = ed.find_divergent_pins(env, FAKE_CONFIG, FAKE_EXAMPLE)
    by_var = {r["var"]: r for r in rows}
    assert by_var["DEMO_API_KEY"]["secret"] is True
    assert by_var["DEMO_API_KEY"]["pinned"] == "***"
    assert by_var["DEMO_API_KEY"]["current_default"] == "***"
    # nothing in the record leaks the actual secret text
    assert "sk-different-value" not in repr(by_var["DEMO_API_KEY"])
    assert "placeholder-secret" not in repr(by_var["DEMO_API_KEY"])
    # token-count knob: genuinely divergent, but shown in the clear
    assert by_var["REPORT_AGENT_SECTION_MAX_TOKENS"]["secret"] is False
    assert by_var["REPORT_AGENT_SECTION_MAX_TOKENS"]["pinned"] == "8192"


# --------------------------------------------------------------- exit codes
def _run_main(monkeypatch, argv, env_file=None, config=FAKE_CONFIG, example=FAKE_EXAMPLE, tmp_path=None):
    """Drive main() with module globals pointed at fixtures + a chosen argv."""
    cfg = _write(tmp_path, "config_src.py", [config])
    exm = _write(tmp_path, "example.env", [example])
    monkeypatch.setattr(ed, "CONFIG", cfg)
    monkeypatch.setattr(ed, "ENV_EXAMPLE", exm)
    monkeypatch.setattr(ed, "ENV_FILE", env_file or str(tmp_path / "absent.env"))
    monkeypatch.setattr(sys, "argv", ["check_env_drift.py", *argv])
    return ed.main()


def test_pins_always_exit_zero_without_strict(monkeypatch, tmp_path, capsys):
    env = _write(tmp_path, ".env", ["REPORT_SECTION_CONCURRENCY=1"])  # critical divergence
    assert _run_main(monkeypatch, ["--pins"], env_file=env, tmp_path=tmp_path) == 0
    out = capsys.readouterr().out
    assert "REPORT_SECTION_CONCURRENCY" in out and "performance-critical" in out


def test_pins_strict_exit_one_on_critical(monkeypatch, tmp_path):
    env = _write(tmp_path, ".env", ["REPORT_SECTION_CONCURRENCY=1"])
    assert _run_main(monkeypatch, ["--pins", "--strict"], env_file=env, tmp_path=tmp_path) == 1


def test_pins_strict_exit_zero_on_noncritical_only(monkeypatch, tmp_path):
    env = _write(tmp_path, ".env", ["ONTOLOGY_TEMPLATE=general_forecast"])  # not critical
    assert _run_main(monkeypatch, ["--pins", "--strict"], env_file=env, tmp_path=tmp_path) == 0


def test_pins_no_env_file_exit_zero(monkeypatch, tmp_path, capsys):
    # ENV_FILE absent → no pins → clean advisory, exit 0 even with --strict.
    assert _run_main(monkeypatch, ["--pins", "--strict"], tmp_path=tmp_path) == 0
    assert "no .env pins diverge" in capsys.readouterr().out


def test_pins_json_output(monkeypatch, tmp_path, capsys):
    import json
    env = _write(tmp_path, ".env", ["REPORT_SECTION_CONCURRENCY=1", "ONTOLOGY_TEMPLATE=general_forecast"])
    assert _run_main(monkeypatch, ["--pins", "--json"], env_file=env, tmp_path=tmp_path) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["critical_count"] == 1
    assert {r["var"] for r in payload["divergent_pins"]} == {"REPORT_SECTION_CONCURRENCY", "ONTOLOGY_TEMPLATE"}


# --------------------------------------------------------------- doc-drift preserved
def test_docdrift_strict_flags_missing(monkeypatch, tmp_path):
    # Config reads vars that the example documents none of → missing → strict exit 1.
    assert _run_main(monkeypatch, ["--strict"], config=FAKE_CONFIG,
                    example="# nothing documented\n", tmp_path=tmp_path) == 1


def test_docdrift_strict_clean_when_documented(monkeypatch, tmp_path):
    documented = "\n".join([
        "REPORT_SECTION_CONCURRENCY=6", "OASIS_SEMAPHORE=24", "ONTOLOGY_TEMPLATE=social_opinion",
        "REPORT_BILINGUAL=true", "REPORT_AGENT_SECTION_MAX_TOKENS=32768",
        "LLM_API_KEY=", "DEMO_API_KEY=",
    ])
    assert _run_main(monkeypatch, ["--strict"], config=FAKE_CONFIG,
                    example=documented, tmp_path=tmp_path) == 0


# --------------------------------------------------------------- EVAL-15 honesty pins
HONESTY_CONFIG = FAKE_CONFIG + """
    REPORT_PUBLISH_GATE = os.environ.get('REPORT_PUBLISH_GATE', 'True').strip().lower() == 'true'
    REPORT_PUBLISH_GATE_MIN_COVERAGE = float(os.environ.get('REPORT_PUBLISH_GATE_MIN_COVERAGE', '0.75') or '0.75')
"""


def test_honesty_pins_flagged(monkeypatch, tmp_path, capsys):
    import json

    env = _write(tmp_path, ".env", [
        "REPORT_PUBLISH_GATE_MIN_COVERAGE=0.05",   # relaxes the publish gate → honesty-critical
        "REPORT_PUBLISH_GATE=true",                # matches default → not divergent
        "ONTOLOGY_TEMPLATE=general_forecast",      # divergent, neither critical class
    ])
    rows = ed.find_divergent_pins(env, HONESTY_CONFIG, FAKE_EXAMPLE)
    assert [r["var"] for r in rows] == ["REPORT_PUBLISH_GATE_MIN_COVERAGE", "ONTOLOGY_TEMPLATE"]
    gate = rows[0]
    assert gate["honesty_critical"] is True and gate["critical"] is False
    assert gate["pinned"] == "0.05" and gate["current_default"] == "0.75"
    assert rows[1]["honesty_critical"] is False

    # Reported loudly by --pins, and --pins --strict exits 1 on it alone.
    assert _run_main(monkeypatch, ["--pins"], env_file=env, config=HONESTY_CONFIG,
                     tmp_path=tmp_path) == 0
    out = capsys.readouterr().out
    assert "honesty-critical" in out and "‼H" in out
    assert "(0 performance-critical, 1 honesty-critical)" in out
    assert _run_main(monkeypatch, ["--pins", "--strict"], env_file=env, config=HONESTY_CONFIG,
                     tmp_path=tmp_path) == 1
    capsys.readouterr()
    assert _run_main(monkeypatch, ["--pins", "--json"], env_file=env, config=HONESTY_CONFIG,
                     tmp_path=tmp_path) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["honesty_critical_count"] == 1 and payload["critical_count"] == 0

    # Doc-drift mode is unchanged: documented honesty knobs exit 0 under --strict.
    documented = "\n".join([
        "REPORT_SECTION_CONCURRENCY=6", "OASIS_SEMAPHORE=24", "ONTOLOGY_TEMPLATE=social_opinion",
        "REPORT_BILINGUAL=true", "REPORT_AGENT_SECTION_MAX_TOKENS=32768",
        "LLM_API_KEY=", "DEMO_API_KEY=", "REPORT_PUBLISH_GATE=true",
        "REPORT_PUBLISH_GATE_MIN_COVERAGE=0.75",
    ])
    assert _run_main(monkeypatch, ["--strict"], env_file=env, config=HONESTY_CONFIG,
                     example=documented, tmp_path=tmp_path) == 0


def test_honesty_critical_vars_have_real_config_defaults():
    # Every honesty-critical knob has a code default in the real config.py, so a
    # divergent pin is always judged against it (never silently skipped).
    defaults = ed.config_defaults()
    assert ed.HONESTY_CRITICAL_VARS <= set(defaults)
    assert defaults["REPORT_PUBLISH_GATE_MIN_COVERAGE"] == "0.75"
    assert not ed.HONESTY_CRITICAL_VARS & ed.PERF_CRITICAL_VARS
