from __future__ import annotations

import json
from pathlib import Path

from parity.cli.write_evals import write_evals_from_proposal
from parity.config import ParityConfig, PlatformsConfig, PromptfooPlatformConfig
from parity.models import EvalProposalManifest

_FIXTURES = Path(__file__).parents[1] / "fixtures"


def _load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


def test_write_evals_uses_target_locator_and_counts_success(tmp_path: Path) -> None:
    proposal = EvalProposalManifest.model_validate(_load_fixture("sample_proposal.json"))
    proposal.targets[0].locator = str(tmp_path / "promptfooconfig.yaml")
    config = ParityConfig(
        platforms=PlatformsConfig(promptfoo=PromptfooPlatformConfig(config_path=str(tmp_path / "promptfooconfig.yaml")))
    )

    outcome = write_evals_from_proposal(
        proposal,
        config=config,
        repo_root=tmp_path,
    )

    assert outcome.exit_code == 0
    assert outcome.total_written == 2
    assert outcome.written_targets == [f"promptfoo:{proposal.targets[0].target_name}"]
    assert (tmp_path / "promptfooconfig.yaml").exists()


def test_write_evals_skips_review_only_and_unsupported_renderings(tmp_path: Path) -> None:
    proposal = EvalProposalManifest.model_validate(_load_fixture("sample_proposal.json"))
    proposal.targets[0].locator = str(tmp_path / "promptfooconfig.yaml")
    proposal.renderings[0].write_status = "review_only"
    proposal.renderings[1].write_status = "unsupported"
    proposal.renderings[1].abstention_reason = "Unsupported method."

    outcome = write_evals_from_proposal(
        proposal,
        config=ParityConfig(
            platforms=PlatformsConfig(promptfoo=PromptfooPlatformConfig(config_path=str(tmp_path / "promptfooconfig.yaml")))
        ),
        repo_root=tmp_path,
    )

    assert outcome.exit_code == 0
    assert outcome.total_written == 0
    assert outcome.skipped_review_only == [f"promptfoo:{proposal.targets[0].target_name}"]
    assert outcome.unsupported_targets == [f"promptfoo:{proposal.targets[0].target_name}"]


def test_write_evals_rejects_promptfoo_targets_outside_repo_root(tmp_path: Path) -> None:
    proposal = EvalProposalManifest.model_validate(_load_fixture("sample_proposal.json"))
    outside_target = tmp_path.parent / "outside-promptfoo.yaml"
    proposal.targets[0].locator = str(outside_target)

    outcome = write_evals_from_proposal(
        proposal,
        config=ParityConfig(
            platforms=PlatformsConfig(promptfoo=PromptfooPlatformConfig(config_path=str(outside_target)))
        ),
        repo_root=tmp_path,
    )

    assert outcome.exit_code == 2
    assert outcome.total_written == 0
    assert outcome.failures == [
        f"promptfoo:{proposal.targets[0].target_name}: Promptfoo write target must stay within the repository root: {outside_target}"
    ]
