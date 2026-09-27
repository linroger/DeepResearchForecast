"""/api/settings provider list carries each provider's deep-research model.

The settings menu shows "research: <model>" per provider. It must come from
PROVIDER_META (the same table the pipeline uses to pick the deer-flow stanza),
not from a hand-kept frontend copy that drifted (Kimi was shown as Claude).
"""

from app.config import Config


def test_every_provider_reports_its_research_model():
    providers = {p["id"]: p for p in Config.provider_info()["providers"]}
    assert set(providers) == set(Config.PROVIDER_META)
    for pid, meta in Config.PROVIDER_META.items():
        assert providers[pid]["deerflow_model"] == meta["deerflow_model"]


def test_kimi_researches_with_its_own_model():
    providers = {p["id"]: p for p in Config.provider_info()["providers"]}
    assert providers["kimi"]["deerflow_model"] == "kimi"
    assert providers["openai"]["deerflow_model"] == "claude"


def test_research_models_exist_in_bridge_config():
    import pathlib
    import re

    cfg = pathlib.Path(__file__).resolve().parents[2] / "deerflow_bridge" / "config.yaml"
    stanzas = set(re.findall(r"^  - name: (\S+)\s*$", cfg.read_text(encoding="utf-8"), re.M))
    for meta in Config.PROVIDER_META.values():
        assert meta["deerflow_model"] in stanzas
