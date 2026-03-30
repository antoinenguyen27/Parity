from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions
from claude_agent_sdk.types import PermissionResultAllow, PermissionResultDeny, ToolPermissionContext

_SENSITIVE_PATH_PATTERNS = (
    ".env",
    ".env.*",
    ".netrc",
    ".npmrc",
    ".pypirc",
    ".claude/**",
    ".git/**",
    ".parity/**",
    "secrets/**",
    "**/secrets/**",
    "**/*.pem",
    "**/*.key",
    "**/*.p12",
    "**/*.pfx",
    "**/id_rsa*",
    "**/id_ed25519*",
    "**/*credentials*",
)
_NON_SECRET_ENV_TEMPLATES = {".env.example", ".env.sample"}

_BASH_META_TOKENS = ("|", ";", "&", ">", "<", "$", "`", "\n", "\r", "(", ")", "{", "}")
_ALLOWED_STAGE1_BASH_PATTERNS = (
    re.compile(r"^git show origin/[^\s:]+:[^\n\r]+$"),
    re.compile(r"^git diff --unified=\d+ origin/[^\s]+\.{3}HEAD -- [^\n\r]+$"),
    re.compile(r"^git ls-files(?: [^\n\r]+)?$"),
)


def build_stage1_options(
    *,
    cwd: str | Path,
    max_turns: int,
    max_budget_usd: float,
    output_schema: dict[str, Any],
) -> ClaudeAgentOptions:
    repo_root = Path(cwd).resolve()
    return ClaudeAgentOptions(
        tools=["Read", "Glob", "Bash"],
        can_use_tool=build_stage1_can_use_tool(repo_root),
        mcp_servers={},
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        cwd=str(repo_root),
        output_format={
            "type": "json_schema",
            "schema": output_schema,
        },
    )


def build_stage3_options(
    *,
    cwd: str | Path,
    max_turns: int,
    max_budget_usd: float,
    output_schema: dict[str, Any],
    mcp_servers: dict[str, Any] | None = None,
) -> ClaudeAgentOptions:
    return ClaudeAgentOptions(
        tools=[],
        mcp_servers=mcp_servers or {},
        max_turns=max_turns,
        max_budget_usd=max_budget_usd,
        cwd=str(Path(cwd).resolve()),
        output_format={
            "type": "json_schema",
            "schema": output_schema,
        },
    )


def build_stage1_can_use_tool(repo_root: Path):
    repo_root = repo_root.resolve()

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        _context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        if tool_name == "Bash":
            command = _extract_command(tool_input)
            if not command:
                return PermissionResultDeny(message="Stage 1 only permits specific read-only git commands.")
            if any(token in command for token in _BASH_META_TOKENS):
                return PermissionResultDeny(message="Stage 1 Bash is restricted to simple read-only git commands.")
            if not any(pattern.fullmatch(command) for pattern in _ALLOWED_STAGE1_BASH_PATTERNS):
                return PermissionResultDeny(
                    message=(
                        "Stage 1 Bash is restricted to read-only git inspection commands: "
                        "`git show`, `git diff --unified=...`, and `git ls-files`."
                    )
                )
            if _bash_targets_sensitive_path(command):
                return PermissionResultDeny(message="Stage 1 cannot inspect secret-bearing or generated paths.")
            return PermissionResultAllow()

        if tool_name == "Read":
            for candidate in _extract_string_values(tool_input):
                resolved = _resolve_candidate_path(candidate, repo_root)
                if resolved is None:
                    return PermissionResultDeny(message="Stage 1 file reads must stay within the repository.")
                if _matches_sensitive_path(resolved.relative_to(repo_root).as_posix()):
                    return PermissionResultDeny(message="Stage 1 cannot read secret-bearing or generated files.")
            return PermissionResultAllow()

        if tool_name == "Glob":
            for key in ("path", "cwd", "directory"):
                candidate = tool_input.get(key)
                if not isinstance(candidate, str):
                    continue
                resolved = _resolve_candidate_path(candidate, repo_root)
                if resolved is None:
                    return PermissionResultDeny(message="Stage 1 glob paths must stay within the repository.")
                if _matches_sensitive_path(resolved.relative_to(repo_root).as_posix()):
                    return PermissionResultDeny(message="Stage 1 cannot glob secret-bearing or generated paths.")

            for key in ("pattern", "glob"):
                candidate = tool_input.get(key)
                if not isinstance(candidate, str):
                    continue
                normalized = candidate.strip()
                if not normalized:
                    continue
                if normalized.startswith("/") or normalized.startswith(".."):
                    return PermissionResultDeny(message="Stage 1 glob patterns must stay within the repository.")
                if _targets_sensitive_pattern(normalized):
                    return PermissionResultDeny(message="Stage 1 cannot glob secret-bearing or generated paths.")
            return PermissionResultAllow()

        return PermissionResultDeny(message=f"Stage 1 tool `{tool_name}` is not permitted.")

    return can_use_tool


def _extract_command(tool_input: dict[str, Any]) -> str:
    for key in ("command", "cmd"):
        value = tool_input.get(key)
        if isinstance(value, str):
            return value.strip()
    return ""


def _extract_string_values(value: Any) -> list[str]:
    values: list[str] = []
    if isinstance(value, str):
        values.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            values.extend(_extract_string_values(item))
    elif isinstance(value, list):
        for item in value:
            values.extend(_extract_string_values(item))
    return values


def _resolve_candidate_path(candidate: str, repo_root: Path) -> Path | None:
    try:
        path = Path(candidate)
        resolved = path.resolve() if path.is_absolute() else (repo_root / path).resolve()
    except Exception:
        return None
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        return None
    return resolved


def _matches_sensitive_path(relative_path: str) -> bool:
    if Path(relative_path).name in _NON_SECRET_ENV_TEMPLATES:
        return False
    return any(Path(relative_path).match(pattern) for pattern in _SENSITIVE_PATH_PATTERNS)


def _targets_sensitive_pattern(pattern: str) -> bool:
    normalized = pattern.lstrip("./")
    if not normalized:
        return False
    return any(
        normalized.startswith(prefix)
        for prefix in (".env", ".claude", ".git", ".parity")
    )


def _bash_targets_sensitive_path(command: str) -> bool:
    if command.startswith("git show origin/"):
        _, _, repo_path = command.partition(":")
        return _matches_sensitive_path(repo_path.strip())

    if " -- " in command:
        _, _, repo_path = command.partition(" -- ")
        return _matches_sensitive_path(repo_path.strip())

    if command.startswith("git ls-files "):
        repo_path = command.removeprefix("git ls-files ").strip()
        if repo_path:
            return _targets_sensitive_pattern(repo_path)

    return False
