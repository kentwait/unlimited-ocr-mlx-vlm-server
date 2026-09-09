# ADR System and Lifecycle

Use this reference to decide whether an ADR is warranted, bootstrap an ADR collection, apply lifecycle transitions, and maintain decision history.

## Contents

- [ADR Threshold](#adr-threshold)
- [Document Ownership](#document-ownership)
- [Minimal Repository System](#minimal-repository-system)
- [Common Norms and Local Policy](#common-norms-and-local-policy)
- [Default Lifecycle](#default-lifecycle)
- [Changing Accepted Decisions](#changing-accepted-decisions)
- [Relationship Semantics](#relationship-semantics)
- [Synchronization](#synchronization)
- [Source Basis](#source-basis)

## ADR Threshold

Create an ADR when the choice is architecturally significant and its rationale will matter after the immediate discussion. Strong signals include:

- changes to system decomposition, service or package boundaries, dependency direction, or ownership;
- new or changed public interfaces, integration protocols, data models, persistence strategies, or consistency boundaries;
- material effects on security, privacy, compliance, reliability, availability, latency, scalability, cost, operability, or maintainability;
- adoption or removal of a major platform, framework, datastore, provider, or construction technique;
- migration, compatibility, release, or deployment strategy that constrains later work;
- a decision spanning teams or repositories;
- a choice that is expensive, risky, or difficult to reverse; or
- recurring debate that needs a durable documented resolution.

Do not create an ADR merely because a technical choice exists. Routine local implementation, formatting, private helper design, and choices already resolved by an applicable standard usually belong in code, a TDD, or ordinary review discussion.

Ask four questions:

1. Are there at least two credible approaches, including retaining the current state?
2. Will the choice constrain future design or operations beyond one isolated change?
3. Would a future contributor reasonably ask why this approach exists?
4. Would reversing the choice require coordination, migration, or meaningful cost?

One strong `yes` may be enough. If all answers are `no`, prefer a lighter artifact.

## Document Ownership

Use the repository's declared authority rules. When none exist, assign authority by subject rather than forcing unlike documents into one global ranking:

| Artifact | Subject it owns |
| --- | --- |
| Accepted ADR | The architectural decision and rationale it records |
| Package or specification README | Local status, reading order, and source-precedence rules |
| PRD | Product scope, actors, outcomes, and requirements |
| Approved TDD or implementation contract | Technical design for its implementation slice |
| Architecture guide | The current consolidated system model and operational rules |
| Current code | Implementation evidence, including migration state |

A proposed ADR records a recommendation rather than an agreed decision. Whether a proposal permits prototypes or implementation is separate local governance. Do not resolve a cross-subject conflict mechanically by rank; surface it to the owners of the affected product, architecture, or implementation contract.

## Minimal Repository System

When `docs/adr/` does not exist and the user requests full lifecycle support, create:

```text
docs/adr/
├── README.md
├── template.md
└── 0001-<decision-title>.md  # only when a real decision is in scope
```

Use `docs/adr/` relative to the repository root as the canonical ADR collection. An empty collection containing only `README.md` and `template.md` is valid. Do not manufacture a first decision or implicitly accept the use of ADRs merely to populate the directory. Creating a meta-ADR that adopts ADRs is an optional adr-tools convention, not a universal requirement.

### README responsibilities

Define:

- what warrants an ADR;
- where ADRs live;
- the filename and heading convention;
- how to allocate the next identifier;
- who can accept decisions;
- allowed statuses and their meanings;
- how to amend, deprecate, and supersede decisions;
- the rule that historical ADRs are retained; and
- a linked index containing identifier, title, current status, and material amendment or refinement relationships.

### Default naming

- Filename: `NNNN-short-kebab-case-title.md`
- Heading: `# ADR-NNNN: Decision-focused title`
- Number: four-digit, zero-padded, monotonically increasing, never reused
- Date: ISO 8601 `YYYY-MM-DD`

Allocate identifiers from the target branch's current collection. Before merging concurrent ADR work, check for number collisions and renumber one branch if necessary. Contiguous numbering is convenient but historical gaps are preferable to reused identities.

### Index discipline

Maintain the index in the same change as an ADR lifecycle transition. Ensure:

- every ADR file appears exactly once;
- every link resolves;
- title and status match the record;
- replaced records show their replacement; and
- accepted records expose amendments or refinements that affect how they must be read; and
- proposed records are visibly distinguishable from accepted authority.

For very large collections, categories or subdirectories may improve discovery, but first make a meta-decision about identifier uniqueness, ownership, and indexing. Do not introduce local numbering per category accidentally.

## Common Norms and Local Policy

Treat these as broadly established ADR norms:

- record an architecturally significant decision with its context and consequences;
- keep each record focused and accessible to the affected team;
- preserve historical decisions and create a linked new record when a decision changes;
- distinguish lifecycle status from implementation progress; and
- follow one consistent project template and decision log.

Treat these as configurable governance policy rather than universal ADR requirements:

- exact statuses beyond `Proposed`, `Accepted`, and `Superseded`;
- who may approve and whether consensus, a council, or pull-request approval is required;
- filename numbering, index shape, and metadata fields within `docs/adr/`;
- whether accepted records permit only relationship/status annotations or dated appended notes;
- partial-change labels such as `Amends` and `Refines`;
- periodic review cadence, confidence scores, and compliance automation; and
- whether proposals may authorize exploratory implementation.

Choose and document local policy when bootstrapping. Do not present optional policy as an industry mandate.

## Default Lifecycle

Use repository-defined statuses when present. Otherwise use:

| Status | Meaning |
| --- | --- |
| `Proposed` | Recommendation under review; not yet an agreed architecture decision |
| `Accepted` | Approved and authoritative for its decision |
| `Rejected` | Considered and deliberately not adopted |
| `Withdrawn` | Removed from consideration without a decision on its merits |
| `Deprecated` | Still relevant or implemented but being phased out |
| `Retired` | No longer applicable after removal of the governed system or capability, with no replacement decision |
| `Superseded` | No longer authoritative; replaced by a linked ADR |

Use `Rejected` when retaining the proposal and rejection rationale prevents repeated debate. Use `Withdrawn` when the question became irrelevant, was duplicated, or was abandoned before a merits decision. `Withdrawn`, `Deprecated`, and `Retired` are useful extensions, not universal statuses.

Keep status and relationships separate by default: use status `Superseded` plus `Superseded by: ADR-NNNN`. If the repository uses a compound status such as `Superseded by ADR-NNNN`, preserve that convention consistently in records and the index.

Do not mark a record `Accepted` merely because its implementation exists. Acceptance records agreement through the local decision process; implementation state and permission to begin work are separate concerns.

## Changing Accepted Decisions

Preserve accepted and rejected ADRs as historical records. When context or requirements change:

1. Create a new proposed ADR describing the new context and decision.
2. Identify the precise relationship to earlier ADRs.
3. Obtain acceptance through the repository's decision process.
4. Update the old ADR's status or add a concise forward relationship note only after the new ADR is accepted.
5. Link the accepted new ADR back to every affected record.
6. Update the index and downstream authority documents together.

Before acceptance, index the new record as `Proposed` and let the proposal name the relationships it would establish. Under the conservative default, do not change an accepted record's status, add a backlink that claims the proposal is in force, or rewrite normative downstream documents based only on a proposal. If local policy tracks pending relationships on old records, label them explicitly as proposed.

Under this skill's conservative default, edits to an accepted or rejected historical ADR should normally be limited to:

- valid forward lifecycle transitions: `Accepted` may become `Deprecated`, `Retired`, or `Superseded`; an amendment or refinement normally leaves it `Accepted`; `Rejected` remains `Rejected`;
- `Superseded by`, `Amended by`, `Refined by`, `Deprecated by`, or retirement links;
- corrections that do not alter meaning; and
- a concise note directing readers to the current decision.

Do not rewrite original context, alternatives, or consequences in light of later knowledge. Git history alone is not a substitute for readable decision lineage. If local policy permits living ADRs, append dated observations and preserve the original decision text rather than silently revising it.

## Relationship Semantics

Use precise relationships:

- **Supersedes**: replaces the earlier decision completely; the old ADR is no longer authoritative.
- **Amends**: changes a bounded part while the earlier core decision remains authoritative.
- **Refines**: adds specificity without reversing the earlier decision.
- **Deprecates**: announces phased retirement while the earlier decision remains authoritative only for the explicitly identified legacy scope until a stated cutoff or retirement condition; the new accepted decision governs new work and target architecture.
- **Retires**: marks a decision inapplicable because its governed system or capability was removed without a replacement architecture.
- **Related to**: supplies context without changing authority.

If local statuses do not model partial changes, keep the old status `Accepted` and add explicit `Amended by ADR-NNNN` or `Refined by ADR-NNNN` metadata or prose. In the new ADR, state:

- what remains authoritative;
- what changes;
- why the two cannot be read independently; and
- which record governs if their wording conflicts.

Avoid ambiguous statements such as `supersedes parts of ADR-0004` without identifying those parts.

Revisit a decision when its drivers, assumptions, requirements, ownership, technology constraints, observed consequences, or risk profile materially change. Use an optional review date or confidence field only when the team has an owner and process that will maintain it.

## Synchronization

An ADR captures why. Other documents often capture the current rules and delivery state. When a decision changes, inspect and update:

- architecture overviews and diagrams;
- repository and agent contracts;
- dependency or boundary rules;
- specification indexes and feature README files;
- PRDs whose product constraints depend on the architecture;
- TDDs and shared contracts based on the old decision;
- API, operations, security, and migration documentation;
- implementation or release checklists; and
- generated documentation sources and outputs when the repository requires both.

Keep target and current state explicit. An accepted ADR may define target architecture while implementation is pending. Link the owning delivery package and state that gap rather than presenting current code as compliant.
Do not alter normative product scope merely to fit an architectural decision. If an accepted ADR and PRD conflict, surface the conflict for product and architecture resolution before updating implementation contracts.

## Source Basis

This guidance synthesizes [Michael Nygard's original ADR format](https://cognitect.com/blog/2011/11/15/documenting-architecture-decisions), [MADR](https://adr.github.io/madr/), [adr-tools](https://github.com/npryce/adr-tools), [Google Cloud's ADR overview](https://docs.cloud.google.com/architecture/architecture-decision-records), [AWS Prescriptive Guidance](https://docs.aws.amazon.com/prescriptive-guidance/latest/architectural-decision-records/adr-process.html), [Microsoft Azure Well-Architected guidance](https://learn.microsoft.com/en-us/azure/well-architected/architect-role/architecture-decision-record), and [Thoughtworks' lightweight ADR guidance](https://www.thoughtworks.com/radar/techniques/lightweight-architecture-decision-records). These sources agree on lightweight rationale and preserved history but differ on exact templates, mutation policy, and governance.
