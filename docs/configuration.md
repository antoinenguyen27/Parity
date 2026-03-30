# Configuration

## Prerequisites

- Python 3.11+
- Node.js 22+
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY` for embedding-backed coverage comparison
- Platform keys only for the platforms you actually use

## Core Sections

`parity.yaml` is now method-first.

- `behavior_artifacts` and `guardrail_artifacts` tell Stage 1 where behavioral changes are likely.
- `platforms` defines the available integrations.
- `evals.discovery` shapes where Parity is allowed to look for existing eval targets.
- `evals.evaluators` controls how strictly Parity confirms the target's existing evaluator regime before reusing it.
- `evals.rules` gives per-artifact preferences and constraints.
- `evals.write` controls write safety.
- `generation` controls how many candidate intents are generated and how many survive reranking.
- `approval` defines the explicit approval label used before writeback.
- `auto_run` controls whether the generated workflow should automatically write approved evals after merge.

## `evals.discovery`

Use this to shape discovery, not to hardcode write routing.

- `repo_asset_globs`
- `platform_discovery_order`
- `sample_limit_per_target`
- `allow_repo_asset_discovery`

Discovery now covers repo-local scorer/judge code as well as file-configured eval assets when the glob set allows it.

## `evals.rules`

Each rule matches an artifact glob and provides preferences:

- `preferred_platform`
- `preferred_target`
- `preferred_project`
- `allowed_methods`
- `preferred_methods`
- `repo_asset_hints`

If discovery finds a better same-platform target that respects the rule, Parity can recover to it. If nothing safe is found, later stages bootstrap and abstain from auto-write.

## `approval`

`approval.label` defines the approval label Parity is intended to look for before deterministic writeback.

This keeps the proposal path and the write path separate:

- Stage 1 to Stage 3 can run on every relevant PR
- `parity write-evals` only matters after explicit approval

Current limitation:

- the generated workflow still assumes the default `parity:approve` label
- changing `approval.label` in `parity.yaml` does not yet fully rewrite the generated workflow behavior on its own

## `auto_run`

`auto_run` is the workflow-policy section for post-approval writeback behavior.

- `enabled`
- `fail_on`
- `notify`

This is workflow policy, not model behavior.

Current limitation:

- these fields are present in the public config model
- the generated workflow still uses the default merged-PR approval/writeback flow
- changing `auto_run` values does not yet fully specialize the generated workflow on its own

## `evals.write`

These settings gate deterministic writeback:

- `require_native_rendering`
- `min_render_confidence`
- `create_missing_targets`
- `allow_review_only_exports`

`review_only` renderings can still be exported as artifacts for inspection, but `parity write-evals` only writes `native_ready` renderings.

## `evals.evaluators`

These settings gate evaluator-regime confirmation:

- `formal_discovery_required`
- `allow_inference_fallback`
- `require_binding_verification`
- `min_binding_confidence`

Default behavior is conservative:

- prefer formal evaluator discovery when the platform or repo harness exposes it
- fall back to inference when formal recovery is unavailable
- reuse the target's existing active evaluator regime when confidently discoverable
- keep bootstrap focused on starter eval generation, not evaluator infrastructure setup

This section is about evaluator discovery confidence, not evaluator mutation. Parity does not create or rebind hosted evaluator infrastructure.

## Generation Controls

- `generation.proposal_limit`
- `generation.candidate_intent_pool_limit`
- `generation.diversity_limit_per_gap`

Stage 3 generates a candidate pool of semantic intents. The host reranks by specificity, testability, novelty, realism, risk alignment, and target fit, then applies diversity control before producing the final proposal.

## Embedding and Similarity

`embedding` and `similarity` affect Stage 2's corpus comparison behavior.

- `embedding.model` selects the embedding model used for coverage comparison.
- `embedding.cache_path` controls where cached vectors are stored.
- `similarity.duplicate_threshold` and `similarity.boundary_threshold` shape how aggressively existing cases are treated as duplicates, boundary cases, or genuinely new gaps.

These settings influence evidence gathering and gap validation, not final writeback.

## Spend Caps

You can omit `spend:` entirely and use the default total analysis cap.

The total is allocated across:

- Stage 1 agent spend
- Stage 2 agent spend
- Stage 2 embedding spend
- Stage 3 synthesis budget

Advanced users can override all four stage-specific caps together.

## Artifacts and Commands

The main analysis/write commands are:

- `parity run-stage 1`
- `parity run-stage 2 --manifest`
- `parity run-stage 3 --manifest --analysis`
- `parity write-evals --proposal`

The main runtime manifests are:

- `BehaviorChangeManifest`
- `EvalAnalysisManifest`
- `EvalProposalManifest`

## Context Files

Parity still works without context, but bootstrap and synthesis quality drops sharply. At minimum, fill in:

- `context/product.md`
- `context/users.md`
- `context/interactions.md`
- `context/good_examples.md`
- `context/bad_examples.md`

If you add `context/traces/`, anonymize them before committing.

## Reference

See [parity.yaml.example](../parity.yaml.example) for the full example configuration.
