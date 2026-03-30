# Parity

[![PyPI](https://img.shields.io/pypi/v/parity-ai)](https://pypi.org/project/parity-ai/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](https://www.python.org/downloads/)

Parity discovers how your eval stack actually works, finds the coverage gaps introduced by an AI behavior change, and proposes native eval additions that fit the target suite instead of forcing everything through one generic probe row.

Parity is not an eval runner. It is a method-first eval synthesis system for LangSmith, Braintrust, Arize Phoenix, Promptfoo, and repo-local eval assets.

## What Parity Optimizes For

For every PR that touches prompts, instructions, guardrails, judges, validators, or other behavior-defining assets, Parity:

1. Detects the behavioral change.
2. Discovers the most relevant existing eval target and how that target actually works.
3. Validates which gaps are real against the discovered corpus, row shape, and evaluator regime.
4. Synthesizes ranked native eval additions for that concrete target.
5. Writes only `native_ready` evals after explicit approval.

Parity reuses the target's existing active evaluator regime when the platform manages evaluators outside the row itself. It does not create, rebind, or mutate hosted evaluator infrastructure.

## Pipeline

- `Stage 1`: Behavior Change Analysis
- `Stage 2`: Eval Analysis
- `Stage 3`: Native Eval Synthesis
- Deterministic writeback: `parity write-evals`

The main runtime artifacts are:

- `BehaviorChangeManifest`
- `EvalAnalysisManifest`
- `EvalProposalManifest`

## Bootstrap Behavior

If Parity cannot find a safe existing target, it falls back to bootstrap mode. Bootstrap means starter eval generation, not evaluator setup. These results remain proposal-oriented and are not auto-written unless they later become `native_ready`.

## Quick Start

```bash
pip install parity-ai
parity init
```

`parity init` generates `parity.yaml`, a GitHub Actions workflow, and `context/` stubs. Fill in the context files, add your API keys as GitHub secrets, and open a PR that changes agent behavior.

See [docs/configuration.md](docs/configuration.md) for config details, [docs/spec.md](docs/spec.md) for the technical architecture, and [parity.yaml.example](parity.yaml.example) for the full schema.

## License

[MIT](LICENSE)
