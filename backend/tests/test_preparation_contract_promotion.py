"""Actual v3 assessment survives promotion; incomplete replacements roll back."""
import json

import pytest

from app.services import pipeline_orchestrator as po
from test_research_assessment import bridge, _hermetic_env, RevisedWorld, fetched_page, base


@pytest.mark.parametrize("mutation", ["missing_record", "missing_pin", "changed_record", "removed_both_proofs"])
def test_real_assessment_promotes_reuses_and_rejects_incomplete_replacement(tmp_path, bridge, mutation):
    rc, meta, _, _, source = base.run_engine(tmp_path, bridge, RevisedWorld(), fetch=fetched_page)
    assert rc == 0, meta.get("error")
    target = tmp_path / "promoted"
    po._promote_research_contract(str(source), str(target))
    assert po._validate_research_contract(str(target))
    assert (target / "research_assessment.json").read_bytes() == (source / "research_assessment.json").read_bytes()
    manifest = json.loads((target / po._RESEARCH_CONTRACT_FILENAME).read_text())
    assert "research_assessment.json" in manifest["files"]
    before = {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()}
    if mutation == "missing_record":
        (source / "research_assessment.json").unlink()
    elif mutation == "missing_pin":
        metadata = json.loads((source / "meta.json").read_text())
        metadata.pop("research_assessment")
        (source / "meta.json").write_text(json.dumps(metadata))
    elif mutation == "removed_both_proofs":
        (source / "research_assessment.json").unlink()
        metadata = json.loads((source / "meta.json").read_text())
        metadata.pop("research_assessment")
        (source / "meta.json").write_text(json.dumps(metadata))
    else:
        record = json.loads((source / "research_assessment.json").read_text())
        record["stopping_reason"] = "forged"
        (source / "research_assessment.json").write_text(json.dumps(record))
    with pytest.raises(RuntimeError, match="assessment"):
        po._promote_research_contract(str(source), str(target))
    assert {p.relative_to(target).as_posix(): p.read_bytes() for p in target.rglob("*") if p.is_file()} == before
    assert po._validate_research_contract(str(target))
