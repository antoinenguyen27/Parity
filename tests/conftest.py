from __future__ import annotations

import json
from pathlib import Path

import pytest

from parity.models import BehaviorChangeManifest, EvalAnalysisManifest, EvalProposalManifest

_FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def sample_manifest() -> BehaviorChangeManifest:
    return BehaviorChangeManifest.model_validate(load_fixture("sample_manifest.json"))


@pytest.fixture()
def sample_analysis() -> EvalAnalysisManifest:
    return EvalAnalysisManifest.model_validate(load_fixture("sample_analysis.json"))


@pytest.fixture()
def sample_proposal() -> EvalProposalManifest:
    return EvalProposalManifest.model_validate(load_fixture("sample_proposal.json"))
