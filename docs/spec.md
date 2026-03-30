# Parity Technical Specification

**Version:** 2.0  
**Status:** Implemented  
**Audience:** Engineers working on Parity and teams integrating it into their eval workflow

## 1. What Parity Is

Parity is a CI-integrated eval synthesis system for LLM products.

It does not run evals. It does not replace the team's eval platform. It analyzes a pull request, discovers how the team's existing eval setup works, identifies real coverage gaps against that setup, and proposes native eval additions that fit the target suite.

The key product idea is:

- discover the user's existing eval regime
- synthesize compatible additions for that regime
- write only deterministic, native-ready additions after explicit approval

Parity is method-first rather than platform-first. It cares first about how the target evaluates behavior, then about where that target lives.

## 2. Product Contract

Parity's implemented contract is:

1. inspect the behavioral change introduced by a PR
2. discover the relevant eval target, row shape, and evaluator regime
3. validate whether the target already covers the changed behavior
4. synthesize target-faithful eval additions
5. write only safe native additions after approval

Parity no longer revolves around a generic probe row. The runtime contracts are:

- `BehaviorChangeManifest`
- `EvalAnalysisManifest`
- `EvalProposalManifest`

Parity does not mutate hosted evaluator infrastructure. It discovers the active evaluator regime and reuses it when possible. If safe reuse cannot be confirmed, it falls back to `manual` rather than trying to create or rebind evaluators.

## 3. Pipeline Overview

Parity has three agentic analysis stages and one deterministic write step:

- `Stage 1`: Behavior Change Analysis
- `Stage 2`: Eval Analysis
- `Stage 3`: Native Eval Synthesis
- deterministic writeback via `parity write-evals`

At a high level:

```text
PR diff
  -> Stage 1: BehaviorChangeManifest
  -> Stage 2: EvalAnalysisManifest
  -> Stage 3: EvalProposalManifest
  -> write-evals: native_ready renderings only
```

The stages are intentionally separate:

- Stage 1 is repo-side behavior analysis
- Stage 2 is eval-estate investigation and gap validation
- Stage 3 is synthesis against the discovered target
- writeback is deterministic and host-owned

This split keeps context cleaner, makes reruns cheaper, and avoids lossy handoffs by giving Stage 3 direct evidence tools into Stage 2 output.

## 4. Stage 1: Behavior Change Analysis

### Purpose

Stage 1 determines whether a PR introduces behaviorally meaningful changes and, if so, which behavioral risks the later stages should care about.

### Inputs

- raw PR diff data from `parity get-behavior-diff`
- configured artifact hints from `parity.yaml`
- repo-local context files

### Outputs

Stage 1 produces `BehaviorChangeManifest`.

Important fields include:

- `changes[]`
- `inferred_intent`
- `change_summary`
- `unintended_risk_flags`
- `false_negative_risks`
- `false_positive_risks`
- `behavioral_signatures`
- `changed_entities`
- `observable_delta`
- `eval_search_hints`
- `validation_focus`
- `evidence_snippets`

These fields are intentionally richer than the old summary-only handoff. They exist so Stage 2 can discover the right eval surface with better retrieval precision.

### Tooling Model

Stage 1 is repo-focused and security-constrained. It is not the stage that reaches into external eval platforms.

## 5. Stage 2: Eval Analysis

### Purpose

Stage 2 is the main investigative stage.

It is responsible for:

- resolving the most relevant eval target or targets
- preserving native sample row shape
- understanding how the target evaluates behavior
- discovering the target's evaluator regime
- determining which gaps are real
- producing enough evidence for Stage 3 to synthesize native-feeling additions

### Inputs

- `BehaviorChangeManifest`
- eval rules and discovery policy from `parity.yaml`
- host-owned Stage 2 tools

### Host-Owned Tools

Stage 2 uses host-owned tooling rather than arbitrary shell access:

- `discover_eval_targets`
- `fetch_eval_target_snapshot`
- `discover_target_evaluators`
- `read_evaluator_binding`
- `verify_evaluator_binding`
- `discover_repo_eval_assets`
- `read_repo_eval_asset`
- `list_platform_evaluator_capabilities`
- `embed_batch`
- `find_similar`
- `find_similar_batch`

### What Stage 2 Discovers

Stage 2 discovers more than just a dataset name.

For each resolved target it aims to recover:

- target identity and locator
- native sample rows
- field and metadata conventions
- method kind
- assertion style
- evaluator scope
- execution surface
- reusable evaluator evidence

### Formal-First Evaluator Discovery

Evaluator discovery is formal-first where supported:

- Promptfoo: formal row-local assertion discovery
- LangSmith: formal-first discovery from platform feedback/evaluator surfaces where available
- Braintrust: repo-formal or scorer-surface discovery where available
- Phoenix: formal discovery where supported by the current client surface, otherwise fallback

Inference remains important, but only as fallback when formal recovery is partial or unavailable.

### Output

Stage 2 produces `EvalAnalysisManifest`.

Its main parts are:

- `resolved_targets[]`
- `coverage_by_target[]`
- `gaps[]`
- `runtime_metadata`

Each `ResolvedEvalTarget` includes:

- `profile`
- `method_profile`
- `samples`
- `evaluator_dossiers`
- `raw_field_patterns`
- `aggregate_method_hints`
- `resolution_notes`

Each `CoverageGap` is target-scoped and evidence-bearing. It can include:

- `target_id`
- `method_kind`
- `why_gap_is_real`
- `existing_coverage_notes`
- `recommended_eval_area`
- `recommended_eval_mode`
- `evaluator_dossier_ids`
- `native_shape_hints`
- `compatible_nearest_cases`
- `repo_asset_refs`

This is what prevents Stage 3 from degenerating into generic synthesis.

## 6. Stage 3: Native Eval Synthesis

### Purpose

Stage 3 is the constructive stage.

It takes the evidence gathered in Stage 2 and generates candidate eval intents that fit the resolved target's method, row shape, and evaluator conventions.

### Inputs

- `BehaviorChangeManifest`
- `EvalAnalysisManifest`
- context pack
- host-owned Stage 3 evidence tools

### Host-Owned Evidence Tools

Stage 3 does not rely only on a prompt summary. It can inspect Stage 2 evidence directly:

- `list_gap_dossiers`
- `read_gap_dossier`
- `list_targets`
- `read_target_profile`
- `list_evaluator_dossiers`
- `read_evaluator_dossier`
- `read_target_samples`
- `read_case_snapshot`
- `read_repo_eval_asset_excerpt`

### Output

Stage 3 first emits a candidate pool of intents. The host then reranks and diversifies them before constructing the final proposal.

The final output is `EvalProposalManifest`, which contains:

- `targets[]`
- `intents[]`
- `evaluator_plans[]`
- `renderings[]`
- `render_artifacts[]`
- `warnings[]`

`ProbeIntent` captures the semantic eval idea plus native hints such as:

- `native_input_binding`
- `native_output_binding`
- `native_reference_output`
- `evaluator_dossier_id`
- `preferred_evaluator_binding`
- `native_metadata_hints`
- `native_tag_hints`
- `native_assertion_hints`
- `native_shape_notes`

`NativeEvalRendering` captures the concrete native payload to write or export.

### Host Reranking

Stage 3 does not decide the final proposal list on its own. The host reranks and diversifies candidate intents based on:

- specificity
- testability
- novelty
- realism
- target fit

This keeps the final proposal bounded and predictable while still letting the model generate broadly.

## 7. Deterministic Writeback

Writeback happens outside the agent via:

```bash
parity write-evals --proposal <EvalProposalManifest.json>
```

### What `write-evals` Does

- groups renderings by target
- filters to safe write candidates
- writes only `native_ready` renderings
- skips `review_only`
- reports unsupported or failed targets
- can post a merged-PR results comment when running inside GitHub Actions

### What It Does Not Do

- it does not run evals
- it does not create or rebind hosted evaluators
- it does not write `unsupported` renderings

If a target is already wired to evaluate rows under its active regime, writing compatible new rows is enough. That reuse path is the intended product behavior.

## 8. Evaluator Regime Model

Parity distinguishes evaluator discovery from evaluator mutation.

Only discovery and reuse are in scope.

### Supported Evaluator Linkage Outcomes

`EvaluatorPlan.action` is limited to:

- `row_local`
- `none`
- `reuse_existing`
- `manual`

Interpretation:

- `row_local`: the evaluator logic is carried directly by the row or config entry
- `none`: no separate evaluator object is needed
- `reuse_existing`: the target already has an active evaluator regime that the new row can safely join
- `manual`: Parity could not safely confirm reuse

### Not in Scope

Parity does not currently model or execute:

- evaluator creation
- evaluator rebinding
- evaluator mutation workflows

This is intentional. It keeps the product focused on compatible coverage generation rather than evaluation-infrastructure orchestration.

## 9. Bootstrap and Abstention

Bootstrap exists for cases where Parity cannot find a safe, usable target.

Bootstrap means:

- generate plausible starter evals
- preserve the same intent and native-shape reasoning discipline where possible
- avoid pretending there is existing evaluator infrastructure
- keep outputs proposal-oriented or `review_only` unless they later become clearly native-safe

Bootstrap does not mean:

- standing up hosted evaluator infrastructure
- inventing target-side evaluator mutation

When Parity cannot safely render or safely reuse an evaluator regime, it abstains into `review_only`, `unsupported`, or `manual` rather than forcing a write.

## 10. Platform Integration Model

Parity supports multiple integration styles.

### Promptfoo

Promptfoo is the strongest fully native path because assertions live in config rows themselves. Discovery and synthesis can preserve row-local evaluator semantics directly.

### LangSmith

LangSmith typically separates dataset examples from evaluator or experiment configuration. Parity therefore focuses on:

- discovering the relevant dataset/project surface
- understanding the active evaluator regime
- writing compatible example rows
- reusing the existing active evaluator setup when it already exists

### Braintrust

Braintrust often expresses evaluator logic through scorers and harnesses rather than row-local assertions. Parity treats this as a repo-formal or scorer-surface discovery problem, then writes compatible rows into the relevant dataset.

### Arize Phoenix

Phoenix often separates dataset examples from evaluator execution surfaces. Parity discovers what it can formally, falls back when needed, and writes compatible examples rather than trying to manage evaluator infrastructure.

## 11. Configuration Model

Parity's config is policy-and-hints first, not rigid routing truth.

The main sections are:

- `behavior_artifacts`
- `guardrail_artifacts`
- `context`
- `platforms`
- `evals.discovery`
- `evals.rules`
- `evals.write`
- `evals.evaluators`
- `generation`
- `approval`
- `auto_run`
- `spend`

Important design points:

- `evals.discovery` shapes where Parity can look
- `evals.rules` expresses preferences and constraints, not absolute routing
- `evals.evaluators` governs how strictly Parity confirms evaluator reuse
- `evals.write` governs deterministic write safety
- `approval` and `auto_run` are workflow-facing config surfaces, but the generated workflow still assumes the default approval and merged-PR writeback flow unless the template/runtime is updated alongside config changes

See [configuration.md](./configuration.md) and [parity.yaml.example](../parity.yaml.example) for the current public config contract.

## 12. Commands and Artifacts

### Main Commands

- `parity init`
- `parity get-behavior-diff`
- `parity run-stage 1`
- `parity run-stage 2 --manifest <stage1.json>`
- `parity run-stage 3 --manifest <stage1.json> --analysis <stage2.json>`
- `parity write-evals --proposal <stage3.json>`

### Runtime Artifacts

Run artifacts are exported under `.parity/runs/<commit_sha>/` and typically include:

- `BehaviorChangeManifest.json`
- `EvalAnalysisManifest.json`
- `EvalProposalManifest.json`
- `summary.md`
- `render_artifacts/`
- `metadata.json`

These artifacts are the main debugging surface for developers working on Parity itself.

## 13. Non-Goals and Current Constraints

The following are intentionally out of scope for the current product:

- executing eval suites
- mutating hosted evaluator infrastructure
- forcing all targets through one generic row schema
- blocking merges on proposal generation
- writing low-confidence review-only suggestions automatically

Current practical constraints:

- formal evaluator discovery varies by platform surface
- some targets are heterogeneous and therefore less clean than ideal
- bootstrap is useful but inherently lower-confidence than target-aligned synthesis

These are handled with evidence-rich manifests, confidence gating, and explicit abstention rather than with hidden heuristics or infrastructure mutation.

## 14. Design Principles

Parity should continue to optimize for:

- method-first target understanding
- evidence-rich handoffs between stages
- deterministic writeback
- minimal surprise surface area
- compatibility with the team's current eval system

If a future change weakens one of those principles, it should be treated as an architectural regression rather than a neutral refactor.
