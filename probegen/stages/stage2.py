from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from pathlib import Path

from claude_agent_sdk import ClaudeAgentOptions
from pydantic.json_schema import model_json_schema

from probegen.config import ProbegenConfig
from probegen.context import count_tokens
from probegen.models import CoverageGapManifest
from probegen.prompts.stage2_template import render_stage2_prompt
from probegen.stages._common import StageRunResult, run_stage_with_retry


def run_stage2(
    stage1_manifest: dict,
    config: ProbegenConfig,
    *,
    cwd: str | Path | None = None,
    mcp_servers: str | Path | dict | None = None,
) -> StageRunResult:
    run_id = f"stage2-{int(time.time())}"
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    prompt = render_stage2_prompt(stage1_manifest)

    # Generate JSON schema for structured output validation
    output_schema = model_json_schema(
        CoverageGapManifest,
        mode="serialization",
        by_alias=True,
    )

    options = ClaudeAgentOptions(
        allowed_tools=[],  # empty = all tools permitted, including MCP server tools
        mcp_servers=mcp_servers or {},
        max_turns=40,
        max_budget_usd=config.budgets.stage2_usd,
        cwd=str(cwd or Path.cwd()),
        output_format={
            "type": "json_schema",
            "schema": output_schema,
        },
    )
    result = asyncio.run(
        run_stage_with_retry(
            stage_num=2,
            prompt=prompt,
            options=options,
            output_model=CoverageGapManifest,
            inject_fields={
                "run_id": run_id,
                "stage1_run_id": stage1_manifest.get("run_id", ""),
                "timestamp": timestamp,
            },
        )
    )
    result.extras = {"prompt_tokens": count_tokens(prompt)}
    return result
