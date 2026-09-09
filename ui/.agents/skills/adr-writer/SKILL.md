---
name: adr-writer
description: 'Write and govern Architecture Decision Records (ADRs) for software projects. Use when identifying architecturally significant decisions, bootstrapping an ADR system, drafting or reviewing ADRs, evaluating architectural alternatives and trade-offs, recording architectural rationale, accepting or rejecting proposals, deprecating or superseding decisions, maintaining ADR indexes and relationship links, or aligning architecture decisions with PRDs, TDDs, implementation packages, and repository contracts.'
---

# ADR Writer

Use this skill to preserve significant software architecture decisions and the reasoning behind them. Produce short, durable records that tell future contributors and coding agents what was decided, which forces shaped the choice, which credible alternatives were rejected, and what the choice makes better or harder.

An ADR owns one architectural decision and its rationale. It does not replace a PRD, TDD, architecture guide, runbook, or implementation plan. An accepted ADR records an agreed decision; a proposed ADR records a recommendation under review. Whether either status authorizes implementation is a separate repository-governance question.

## Core Principles

- Store ADRs, their index, and their template under `docs/adr/` relative to the repository root. Follow repository-local templates, statuses, numbering, authority, and approval rules within that collection.
- Record decisions that materially affect system structure, boundaries, dependencies, interfaces, data ownership, quality attributes, operations, security, delivery, or construction techniques.
- Keep one coherent decision per ADR. Split independently reversible choices when doing so improves lifecycle clarity.
- Write context as facts and forces, not as advocacy for a preferred answer.
- Compare credible options against explicit decision drivers. Do not invent weak alternatives to make the chosen option look inevitable.
- State the decision in direct, active language and make its architectural invariants testable where practical.
- Record positive, negative, and neutral consequences. Every meaningful choice has costs.
- Keep accepted records as historical evidence. Change an accepted decision with a new ADR and explicit relationships rather than silently rewriting its rationale.
- After a changing decision is accepted, make supersession or amendment links bidirectional by updating the new record, affected old records, and index together.
- Link to an owning specification or architecture entry point instead of duplicating detailed implementation design in the ADR.
- Default a new ADR to `Proposed`. Mark it `Accepted` only when agreement is explicit and satisfies the repository's decision process; do not infer acceptance from authorship, implementation, or silence.

## When to Load References

- Before choosing whether an ADR is warranted, creating an ADR collection, assigning status, or changing an accepted decision, read [ADR System and Lifecycle](./references/adr-system-and-lifecycle.md).
- Before drafting or substantially revising an ADR, read [Document Structure](./references/document-structure.md).
- Before finalizing or reviewing an ADR, read [Quality Rubric](./references/quality-rubric.md). Also read [ADR System and Lifecycle](./references/adr-system-and-lifecycle.md) when the review covers status, authority, historical edits, or relationships.

## Workflow Routing

- For threshold assessment, complete steps 1-2 and report whether an ADR is warranted.
- For bootstrap-only work, complete step 1 and create only the governance files requested. Do not invent a decision.
- For a new draft or revision, complete steps 1-5 and 8. Apply steps 6-7 only when a lifecycle change is requested and authorized.
- For review-only work, inspect through step 5, apply the quality rubric, and report findings without changing status, relationships, indexes, or downstream documents.
- For an authorized lifecycle transition, complete steps 1, 3, and 6-8; evaluate alternatives again only when the decision itself changes.

## Workflow

1. Discover the repository contract.
   - Inspect `docs/adr/` for its README, template, index, and existing records. Also inspect architecture guides, specification guides, accepted ADRs, and contributor or agent instructions that govern the decision.
   - Determine the local filename convention, next number, metadata, statuses, approval authority, source precedence, and synchronization requirements.
   - Read accepted ADRs related to the subject before proposing a decision. Treat current code as evidence, not as a substitute for documented rationale.
   - If `docs/adr/` does not exist and the user wants full lifecycle support, bootstrap the minimal collection described in [ADR System and Lifecycle](./references/adr-system-and-lifecycle.md).
   - Do not bootstrap a README, template, or index merely because `docs/adr/` lacks them. For an individual ADR request, create the requested record under `docs/adr/` and preserve the requested scope.

2. Decide whether the subject warrants an ADR.
   - Write an ADR when the choice is architecturally significant and its rationale will matter later. Multiple credible options are a strong signal, not a prerequisite.
   - Prefer an existing standard, accepted ADR, or architecture contract when it already resolves the question and remains valid.
   - Use a PRD for product scope and outcomes, a TDD for implementation design and sequencing, an architecture guide for the current system model, and an ordinary issue or code comment for local or routine choices.
   - If several decisions are entangled, identify the governing decision and split independently reversible choices when each needs its own rationale or lifecycle.

3. Establish the decision frame.
   - State the decision question, scope, responsible team or deciders, functional and non-functional requirements, constraints, and affected systems or critical user journeys where relevant.
   - Extract decision drivers before evaluating options. Distinguish mandatory constraints from preferences.
   - Identify existing ADRs or contracts that the proposed decision retains, refines, amends, deprecates, or supersedes.
   - Ask only about ambiguity that would change the decision, credible option set, approval authority, or relationship to an accepted ADR. Record other uncertainty as assumptions, risks, or open questions.

4. Evaluate credible options.
   - Include the current approach or `do nothing` when it is genuinely viable.
   - Describe every option at comparable depth and assess it against the same drivers.
   - Capture meaningful benefits, costs, risks, operational effects, migration implications, and reversibility.
   - If evidence is missing, label the uncertainty. Do not fabricate benchmarks, stakeholder agreement, or requirements.
   - Do not turn domain knowledge into binding project constraints without source support. Record a necessary but unverified concern as an assumption, risk, or open question.

5. Draft the record.
   - Follow the repository template when one exists; otherwise use the adaptable structure in [Document Structure](./references/document-structure.md).
   - For a proposal, state the recommended outcome early without implying approval. For an accepted record, state the decided outcome directly.
   - Separate the consequences of the decision from the pros and cons used to compare options.
   - Define confirmation through tests, architecture checks, reviews, metrics, or linked delivery evidence when compliance can be verified.
   - Use durable relative links to related ADRs, architecture contracts, owning specs, issues, and pull requests.

6. Apply the lifecycle transition.
   - For a new unresolved decision, use `Proposed`.
   - Accept, reject, or withdraw a proposal only through the repository's decision process. Record the decision participants and evidence when available.
   - For a changed accepted decision, create a new ADR. State exactly what is retained and what changes.
   - Use full supersession only when the old decision is no longer authoritative. Use amendment or refinement language for partial changes when the repository supports it.
   - Preserve accepted and rejected content except for valid forward lifecycle changes, relationship links, and a concise dated pointer to newer information. Do not retrofit old rationale to make history appear cleaner.

7. Synchronize the decision graph.
   - Under the conservative default, index a proposed replacement as proposed and link its intended relationships from the proposal, but do not make the old ADR or normative downstream documents claim that the proposal is already in force. Follow a different local proposal policy when explicitly documented.
   - After an authorized lifecycle transition, add or update the ADR index with the identifier, title, exact status, and material relationship when status alone is insufficient.
   - Add forward links from affected older ADRs and backlinks from the new ADR after acceptance. A proposal may point to accepted records without changing them.
   - Update architecture guides, repository or agent contracts, feature-package reading order, PRDs, TDDs, and implementation checklists whose authority or assumptions changed.
   - Do not rewrite normative product scope to accommodate an architectural choice. Surface a conflict with a PRD for product-level resolution; update implementation documents only after their governing sources agree.
   - Distinguish accepted target architecture, approved implementation plans, and current implementation state when they differ.
   - Do not silently alter lower-level documents to contradict an accepted ADR. Surface unresolved conflicts.

8. Review and report.
   - Apply [Quality Rubric](./references/quality-rubric.md).
   - Verify filename, heading identifier, status, index row, and relationship links agree.
   - Verify the record answers why the choice was made and exposes its costs, not merely what will be built.
   - Report the created or changed record, lifecycle state, related records, synchronized documents, and any approval or implementation follow-up still required.

## Decision Rules

- Follow local templates, numbering, statuses, and decision processes unless they would erase history or falsely represent agreement. Keep `docs/adr/` as the canonical location required by this skill; surface conflicting location conventions instead of silently using them.
- If the decision is already governed by an accepted ADR and its context has not materially changed, cite it rather than creating a duplicate.
- If the request is mainly choosing product behavior or release scope, place that material in the owning product requirements artifact; record only architecture-significant consequences in an ADR.
- If the request is mainly package layout, APIs, schemas, algorithms, migrations, rollout steps, or test plans for an already-settled decision, place that material in an owning technical design artifact rather than the ADR.
- If an ADR grows into a detailed delivery specification, keep the durable decision, constraints, and rationale in the ADR and move implementation mechanics to an owning TDD or specification package.
- If only one option satisfies a mandatory constraint, explain that constraint and still document plausible rejected approaches when they help future readers understand the boundary.
- If no credible decision has been reached, produce a `Proposed` ADR with explicit open questions rather than inventing consensus.
- If the acceptance process or outcome is unknown, do not self-accept the ADR.
- If reconstructing a brownfield decision, use verifiable historical evidence, label it retrospective, and do not invent alternatives, rationale, dates, or approval.
- If a later decision changes only part of an accepted ADR, name retained and changed clauses explicitly; do not use vague `supersedes` wording that obscures what remains in force.
- If an accepted target differs from current code, document the gap and owning implementation package without weakening the accepted decision to match the code.

## Output Expectations

- For bootstrap work, use the minimal repository system in [ADR System and Lifecycle](./references/adr-system-and-lifecycle.md) only when requested.
- For drafting, use the adaptable format and conditional fields in [Document Structure](./references/document-structure.md).
- For review or lifecycle work, satisfy [Quality Rubric](./references/quality-rubric.md) and report any unresolved authority, evidence, relationship, or synchronization gaps.
- Prefer a concise record that stands alone as a decision and rationale. Link supporting detail rather than omitting essential reasoning or duplicating implementation design.
