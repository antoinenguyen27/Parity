from __future__ import annotations

import asyncio
from pathlib import Path

from parity.stages.security import build_stage1_can_use_tool, build_stage1_options, build_stage3_options


def test_stage1_policy_allows_read_only_git_commands(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)

    result = asyncio.run(policy("Bash", {"command": "git show origin/main:app/router.py"}, None))  # type: ignore[arg-type]
    assert result.behavior == "allow"

    result = asyncio.run(
        policy("Bash", {"command": "git diff --unified=5 origin/main...HEAD -- app/router.py"}, None)  # type: ignore[arg-type]
    )
    assert result.behavior == "allow"


def test_stage1_policy_denies_broad_shell_commands(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)

    result = asyncio.run(policy("Bash", {"command": "env"}, None))  # type: ignore[arg-type]
    assert result.behavior == "deny"

    result = asyncio.run(policy("Bash", {"command": "git show origin/main:app/router.py | cat"}, None))  # type: ignore[arg-type]
    assert result.behavior == "deny"


def test_stage1_policy_denies_sensitive_git_inspection_paths(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)

    result = asyncio.run(policy("Bash", {"command": "git show origin/main:.env"}, None))  # type: ignore[arg-type]
    assert result.behavior == "deny"


def test_stage1_policy_denies_sensitive_file_reads(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)
    (tmp_path / ".env").write_text("SECRET=1", encoding="utf-8")

    result = asyncio.run(policy("Read", {"file_path": ".env"}, None))  # type: ignore[arg-type]
    assert result.behavior == "deny"


def test_stage1_policy_allows_repo_file_reads(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)
    path = tmp_path / "app" / "router.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ROUTER = 'ok'", encoding="utf-8")

    result = asyncio.run(policy("Read", {"file_path": "app/router.py"}, None))  # type: ignore[arg-type]
    assert result.behavior == "allow"


def test_stage1_policy_allows_non_secret_env_templates(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)
    path = tmp_path / ".env.example"
    path.write_text("OPENAI_API_KEY=", encoding="utf-8")

    result = asyncio.run(policy("Read", {"file_path": ".env.example"}, None))  # type: ignore[arg-type]
    assert result.behavior == "allow"


def test_stage1_policy_allows_absolute_glob_paths_within_repo(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)

    result = asyncio.run(policy("Glob", {"path": str(tmp_path), "pattern": "**/*.py"}, None))  # type: ignore[arg-type]
    assert result.behavior == "allow"


def test_stage1_policy_denies_paths_outside_repo(tmp_path: Path) -> None:
    policy = build_stage1_can_use_tool(tmp_path)

    result = asyncio.run(policy("Read", {"file_path": "../outside.txt"}, None))  # type: ignore[arg-type]
    assert result.behavior == "deny"


def test_stage1_options_use_narrow_tool_set(tmp_path: Path) -> None:
    options = build_stage1_options(
        cwd=tmp_path,
        max_turns=20,
        max_budget_usd=0.5,
        output_schema={"type": "object", "properties": {}},
    )

    assert options.tools == ["Read", "Glob", "Bash"]
    assert options.can_use_tool is not None


def test_stage3_options_disable_builtin_tools(tmp_path: Path) -> None:
    options = build_stage3_options(
        cwd=tmp_path,
        max_turns=10,
        max_budget_usd=0.25,
        output_schema={"type": "object", "properties": {}},
    )

    assert options.tools == []
    assert options.mcp_servers == {}
