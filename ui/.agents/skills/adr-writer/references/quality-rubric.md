# ADR Quality Rubric

Use this reference before finalizing, reviewing, accepting, rejecting, amending, or superseding an ADR.

## Contents

- [Decision Fitness](#decision-fitness)
- [Context and Drivers](#context-and-drivers)
- [Decision Quality](#decision-quality)
- [Alternatives](#alternatives)
- [Consequences and Confirmation](#consequences-and-confirmation)
- [Lifecycle and Authority](#lifecycle-and-authority)
- [Traceability](#traceability)
- [Common Failure Modes](#common-failure-modes)
- [Final Review Questions](#final-review-questions)

## Decision Fitness

- The subject is architecturally significant rather than a routine local implementation choice.
- The record contains one coherent decision or an explicitly indivisible decision set.
- An existing accepted ADR, standard, or repository contract does not already resolve the question.
- The ADR records architecture and rationale rather than product scope or exhaustive implementation mechanics.
- The title names the decision outcome clearly.

## Context and Drivers

- The context explains why the decision is needed now.
- The decision question and scope are explicit.
- Current-state facts, constraints, assumptions, and requirements are distinguishable.
- Functional and non-functional requirements are included when they drive the choice.
- Critical user journeys are included only when the architecture materially affects them.
- Context does not advocate for the chosen option or present preferences as mandatory constraints.
- Drivers are specific enough to compare options and are prioritized when necessary.

## Decision Quality

- The decision is stated early, directly, and in active voice.
- Binding architectural invariants use unambiguous language.
- Ownership, authority, boundaries, and forbidden paths are explicit where relevant.
- The record contains enough specificity to prevent re-litigation without prescribing unnecessary private implementation details.
- The outcome follows from the documented drivers and evidence.
- Unknowns are labeled as assumptions, risks, or open questions rather than invented facts.

## Alternatives

- Credible alternatives are documented when they genuinely exist; the record does not manufacture options to satisfy a template.
- The current approach or `do nothing` appears when it is viable.
- Options are described at comparable depth and assessed against the same drivers.
- Rejected options include real strengths, not only weaknesses.
- The chosen option includes real costs and risks, not only benefits.
- No straw alternatives, hindsight bias, fabricated data, or invented stakeholder consensus appears.

## Consequences and Confirmation

- Material benefits state what becomes possible or easier.
- Material negative consequences state accepted costs, constraints, and follow-up work.
- Neutral consequences or risks state shifted responsibilities and uncertainty when any exist.
- Migration, compatibility, operations, security, cost, and organizational consequences appear when relevant.
- Mitigations do not conceal the underlying trade-offs.
- When conformance can usefully be checked, confirmation describes realistic tests, checks, reviews, metrics, or evidence.
- Manual governance is stated honestly when automation would provide false confidence.

## Lifecycle and Authority

- The status matches repository vocabulary and the actual governance state.
- A new unresolved decision remains `Proposed`.
- Acceptance, rejection, or withdrawal follows the repository's decision process and is not inferred from authorship, implementation, or silence.
- A proposal is not presented as an agreed decision; implementation permission is handled according to separate local governance.
- A proposal labels its outcome as recommended or conditional rather than falsely approved.
- A proposed replacement has not changed an accepted ADR's authority or normative downstream documents.
- An accepted historical ADR has not had its original rationale silently rewritten.
- Full supersession is used only when the earlier decision is wholly replaced.
- Partial changes identify exactly what remains and what changes.
- Deprecated decisions explain the transition or replacement direction.

## Traceability

- Filename, heading identifier, title, metadata, and index row agree.
- The ADR index contains the record exactly once and exposes its current status.
- The index exposes amendments and refinements that status alone cannot communicate.
- After acceptance of a changing decision, new and affected old ADRs contain bidirectional relationship links. A proposal names intended relationships without modifying accepted records.
- Relationship labels use precise semantics: supersedes, amends, refines, deprecates, or relates to.
- Links resolve and use durable repository-relative targets where possible.
- The ADR links an owning implementation or specification entry point when delivery work exists.
- Architecture guides, repository contracts, PRDs, TDDs, and checklists changed by the decision are synchronized or explicitly identified as follow-up.
- Accepted target architecture and current implementation state are distinguished when they differ.

## Common Failure Modes

Flag the ADR for revision when it:

- records only the chosen technology without the problem or rationale;
- uses `best practice`, `industry standard`, or `scalable` as unsupported justification;
- hides a product requirement or stakeholder preference as a technical constraint;
- lists alternatives after the decision but does not compare them fairly;
- treats implementation as proof of architectural acceptance;
- marks itself accepted without known decision authority;
- edits an old accepted record so readers cannot reconstruct the original decision;
- says `partially supersedes` without identifying retained and replaced clauses;
- duplicates a PRD, TDD, issue, or architecture guide;
- omits negative consequences;
- contains implementation phases, exhaustive schemas, or file-by-file instructions unrelated to the durable decision;
- points only to ephemeral chat discussions or inaccessible evidence; or
- updates the new ADR but leaves the old record and index claiming conflicting authority.

## Final Review Questions

1. Could a future contributor explain why this choice was made without finding the original authors?
2. Could a reviewer identify the decisive drivers and see why credible alternatives lost?
3. Are the accepted costs and risks visible enough to know when the decision should be revisited?
4. Is it clear which parts are authoritative architecture and which details belong to downstream specifications?
5. Is the approval state truthful?
6. Can a reader navigate both forward and backward through amendments or supersession?
7. Can an implementation team determine how conformance will be confirmed?
8. Do the index and related documents present one consistent decision history?
