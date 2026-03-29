from __future__ import annotations

from parity.cli.init_cmd import render_workflow_template
from parity.config import ArizePhoenixPlatformConfig, BraintrustPlatformConfig, LangSmithPlatformConfig, ParityConfig, PlatformsConfig


def test_render_workflow_template_limits_writeback_secrets_to_configured_platforms() -> None:
    workflow = render_workflow_template(
        ParityConfig(
            platforms=PlatformsConfig(
                langsmith=LangSmithPlatformConfig(),
                braintrust=None,
                arize_phoenix=None,
            )
        )
    )

    assert "LANGSMITH_API_KEY" in workflow
    assert "BRAINTRUST_API_KEY" not in workflow[workflow.index("Write evals to platform") :]
    assert "PHOENIX_API_KEY" not in workflow[workflow.index("Write evals to platform") :]
    assert "post-write-comment" in workflow
    assert "--skip-comment" in workflow


def test_render_workflow_template_includes_multiple_platform_keys_when_configured() -> None:
    workflow = render_workflow_template(
        ParityConfig(
            platforms=PlatformsConfig(
                langsmith=LangSmithPlatformConfig(),
                braintrust=BraintrustPlatformConfig(),
                arize_phoenix=ArizePhoenixPlatformConfig(),
            )
        )
    )

    write_section = workflow[workflow.index("Write evals to platform") :]
    assert "LANGSMITH_API_KEY" in write_section
    assert "BRAINTRUST_API_KEY" in write_section
    assert "PHOENIX_API_KEY" in write_section
