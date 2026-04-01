![Parity banner](assets/Parity%20Banner.png)

# Parity

[![PyPI](https://img.shields.io/pypi/v/parity-ai)](https://pypi.org/project/parity-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)

> *Parity is early. We’re moving fast, so you may hit a few rough edges while we keep improving the product.*

Parity analyzes behavior-defining AI changes in pull requests, discovers the most relevant existing eval target, validates the real coverage gaps, and proposes native eval additions that fit the target suite.

Parity is not an eval runner. It does not create or mutate hosted evaluator infrastructure. It reuses the eval system you already have.

## How Parity Works

The normal developer loop is:

1. Run `parity init` once in your repo.
2. Point Parity at your behavior-defining files, context, and eval platforms in `parity.yaml`.
3. Open a PR that changes prompts, instructions, guardrails, judges, or related behavior.
4. Let Parity analyze the PR and propose native eval additions against the best matching existing target.
5. Review the proposal in the PR.
6. Merge with the `parity:approve` label if you want approved `native_ready` evals written back after merge.

If no safe native target is found, Parity falls back to bootstrap mode and proposes starter evals without unsafe writeback.

## What Parity Does

For each PR that changes prompts, instructions, guardrails, judges, validators, or similar behavior-defining assets, Parity:

1. Detects the behavioral change.
2. Resolves the best matching eval target and method.
3. Validates which gaps are actually uncovered.
4. Synthesizes native eval additions for that target.
5. Writes only `native_ready` evals after explicit approval.

## Support

| Path | Status | Notes |
|---|---|---|
| Promptfoo | Strong | Best fully native path. Assertions are row-local and writeback is straightforward. |
| LangSmith | Strong | Strong dataset discovery and writeback. Evaluator reuse is supported; evaluator mutation is out of scope. |
| Braintrust | Supported with limitations | Writeback works. Target discovery is weaker and evaluator recovery depends more on repo assets. |
| Arize Phoenix | Supported with limitations | Dataset read/write works. Evaluator discovery is weaker than Promptfoo and LangSmith. |
| Bootstrap mode | Built in | If no safe target is found, Parity proposes starter evals and abstains from unsafe writeback. |

More detail: [docs/platforms.md](docs/platforms.md)

## Public Commands

These are the commands most users need:

- `parity init` — scaffold `parity.yaml`, the GitHub Actions workflow, and `context/` stubs
- `parity doctor` — verify your setup and environment
- `parity run-stage 1` — detect behavioral artifact changes in a PR
- `parity run-stage 2` — analyze coverage gaps against existing evals
- `parity run-stage 3` — synthesize native eval proposals
- `parity write-evals` — write approved evals to your platform after merge
- `parity setup-mcp` — generate an MCP server config from `parity.yaml` (for local agent tooling)

Internal CI commands (`post-comment`, `resolve-run-id`, etc.) are used by the generated workflow and are not intended to be called directly.

## Quick Start

```bash
pip install parity-ai
parity init
```

`parity init` creates the scaffold:

- `parity.yaml`
- `.github/workflows/parity.yml`
- `context/` stub files

It does not fill in your API keys, product context, or eval target mappings for you.

Then:

1. Fill in the generated `context/` files.
2. Add GitHub secrets: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and any platform keys you use.
3. Commit `parity.yaml`, `.github/workflows/parity.yml`, and `context/`.
4. Open a PR that changes AI behavior.
5. Add the fixed approval label `parity:approve` before merging if you want Parity to write approved evals back after merge.

For a quick setup check, run:

```bash
parity doctor
```

## Bare Minimum Local Run

If you want to step through the stages locally before wiring up the full PR workflow, this is the minimum practical path:

1. Run `parity init`.
2. Fill in at least `context/product.md`, `context/users.md`, and `context/interactions.md`.
3. Set `ANTHROPIC_API_KEY`.
4. Set `OPENAI_API_KEY` if you want normal coverage-aware Stage 2 analysis.
5. Add one or two `evals.rules` entries or declare a platform Parity can discover from.
6. Run `parity doctor`.
7. Run `parity run-stage 1`, `parity run-stage 2`, and `parity run-stage 3` manually.

The GitHub Actions workflow is not required for local stage-by-stage runs. It is only required for automated PR analysis and merge-time writeback.

## Docs

Start here:

- [Configuration](docs/configuration.md) — what goes in `parity.yaml`, what matters most, and how to think about the config surface
- [Platform support](docs/platforms.md) — which integrations are strongest today and where Parity stays conservative

Understand the product:

- [Architecture](docs/spec.md) — the stage model, runtime flow, and product contract

See a full worked example:

- [LangGraph example quickstart](examples/langgraph-agentic-rag/docs/quickstart.md) — an end-to-end demo repo that shows the full PR-to-writeback flow with LangSmith

Maintaining Parity itself:

- [Maintainer guide](docs/maintainers.md) — local development, testing, packaging, and public-surface rules for this repo

## License

[MIT](LICENSE)
