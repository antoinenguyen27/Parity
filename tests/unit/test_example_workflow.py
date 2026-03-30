from __future__ import annotations

from pathlib import Path


def test_example_workflow_uses_current_stage3_contract() -> None:
    workflow = (
        Path(__file__).resolve().parents[2]
        / "examples"
        / "langgraph-agentic-rag"
        / ".github"
        / "workflows"
        / "parity.yml"
    ).read_text(encoding="utf-8")

    assert "--analysis .parity/stage2.json" in workflow
    assert "--gaps .parity/stage2.json" not in workflow
    assert "intent_count" in workflow
    assert "probe_count" not in workflow
    assert "parity write-evals" in workflow
    assert "parity write-probes" not in workflow
