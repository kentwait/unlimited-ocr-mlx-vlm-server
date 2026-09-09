# ADR Document Structure

Use this reference when drafting or substantially revising an ADR. Follow a repository template first. Otherwise adapt the structure below to the decision's complexity.

## Contents

- [Default Structure](#default-structure)
- [Title and Metadata](#title-and-metadata)
- [Context and Problem Statement](#context-and-problem-statement)
- [Decision Drivers](#decision-drivers)
- [Decision](#decision)
- [Alternatives Considered](#alternatives-considered)
- [Consequences](#consequences)
- [Confirmation](#confirmation)
- [Relationships and References](#relationships-and-references)
- [Size and Decomposition](#size-and-decomposition)

## Default Structure

```markdown
# ADR-NNNN: <Decision-focused title>

- **Date**: YYYY-MM-DD
- **Status**: Proposed
- **Deciders**: <People, roles, or responsible team>

## Context and Problem Statement

<What situation requires a decision? Which forces are in tension? State the
decision question and relevant current-state facts without advocating a choice.>

## Decision Drivers

- <Mandatory constraint or quality attribute>
- <Business, technical, operational, security, cost, or delivery driver>

## Decision

<For a proposal, state the recommended option as "If accepted, we will ...".
For an accepted record, state "We will ...". Define durable boundaries and
invariants without implying approval that has not occurred.>

## Alternatives Considered

### Option A: <Name>

<Comparable description.>

- Benefits: <Why this option is credible>
- Costs and risks: <Why it was not selected or what it compromises>

### Option B (recommended): <Name>

<Comparable description.>

- Benefits: <Why it best satisfies the drivers>
- Costs and risks: <Trade-offs acceptance would commit the team to>

## Consequences

### Positive

- <New benefit or enabled capability>

### Negative

- <Cost, constraint, or required follow-up>

### Neutral / Risks

- <Uncertainty, shifted responsibility, or condition to monitor>

## Confirmation

<How conformance will be shown through tests, architecture checks, reviews,
metrics, operational evidence, or an implementation checklist.>

## Relationships and References

- Supersedes: <ADR link, if applicable>
- Superseded by: <ADR link, added to an old record after acceptance>
- Amends or refines: <ADR link, if applicable>
- Amended or refined by: <ADR link, added to an old record after acceptance>
- Deprecates or retires: <ADR link, if applicable>
- Deprecated or retired by: <ADR link, added to an old record after acceptance>
- Owning implementation package: <stable entry-point link>
- Supporting evidence: <issue, proposal, benchmark, or pull request link>
```

Remove optional headings that add no value. Add project-specific metadata and sections only when they materially govern the decision.

The common minimum is a title, status, context, decision outcome, and consequences or rationale. Decision drivers, a dedicated alternatives section, confirmation, relationship metadata, and expanded participant metadata are a richer default, not universal requirements. Include them when they improve the record or when local policy requires them. After acceptance, change `recommended` to `chosen` or use the repository's established wording.

## Title and Metadata

Use a short title that names the outcome, not the meeting or topic:

- Strong: `Use PostgreSQL advisory locks for singleton jobs`
- Weak: `Database discussion`
- Strong: `Separate workflow authorship from executable runtime`
- Weak: `Workflow architecture update`

Use metadata consistently with the repository. Common fields are:

- **Date**: authored or last decision date, according to local policy.
- **Status**: lifecycle state, not implementation progress.
- **Deciders**: people or roles authorized to approve the choice.
- **Authors**: writers or facilitators, when distinct from deciders.
- **Responsible team**: long-term owner of the affected architecture.
- **Consulted / Informed**: useful for cross-team, security, compliance, or regulated decisions.
- **Approval reference**: durable link to the acceptance record when required.
- **Confidence / review trigger**: optional when uncertainty is material and an owner will maintain it.

Do not add metadata fields that nobody will maintain.

## Context and Problem Statement

Explain why a decision is needed now. Include only facts necessary to evaluate the choice:

- current architecture and observed problem;
- scope and affected systems;
- technical, business, organizational, political, or delivery forces;
- functional and non-functional requirements;
- affected critical user journeys;
- compatibility or migration obligations;
- known constraints and assumptions; and
- the decision question.

Keep context value-neutral. Avoid naming the preferred option as if it were already required. Link to detailed source documents rather than restating entire PRDs or investigation reports.

## Decision Drivers

List the criteria that distinguish the options. Rank or label mandatory drivers when priority matters. Useful driver classes include:

- correctness and domain invariants;
- security, privacy, and compliance;
- reliability, recovery, and availability;
- performance and scalability;
- operability and observability;
- maintainability and ownership clarity;
- interoperability and compatibility;
- migration risk and reversibility;
- delivery time and team capability; and
- infrastructure and lifecycle cost.

Avoid vague drivers such as `best practice`, `clean`, `modern`, or `scalable` without measurable or contextual meaning.

## Decision

Lead a proposal with `If accepted, we will ...` or another clearly labeled recommendation. After acceptance, use a direct outcome such as `We will ...`. Then define only the durable rules needed to prevent the decision from being reinterpreted.

The decision may include:

- responsibility and ownership boundaries;
- permitted and forbidden dependency direction;
- authoritative data or lifecycle owner;
- selected technology or pattern and its constrained use;
- public integration or compatibility policy;
- consistency, security, or availability invariants;
- migration or cutover policy when it is part of the architecture choice; and
- explicit exclusions needed to preserve the boundary.

Use `must` and `must not` for binding invariants. Do not prescribe private types, helper methods, exhaustive schemas, file-by-file changes, phase sequencing, or test cases unless those details are themselves the durable architectural decision.
Do not invent binding invariants from general expertise. If a concern is important but not established by the source material, record it as an assumption, risk, or open question for the decision-makers.

## Alternatives Considered

Include credible options that informed the decision. Consider:

- retaining the current architecture;
- the simplest viable approach;
- a materially different ownership or consistency model;
- a managed versus self-operated solution; or
- deferring the decision when delay is viable.

Describe all options at comparable depth. Evaluate them against the same drivers. Separate evidence from predictions and label uncertainty. Use a compact comparison table when there are many criteria, but retain prose for decisive trade-offs.

Do not include:

- absurd or knowingly non-viable straw alternatives;
- options rejected by an unstated preference;
- vendor feature lists unrelated to the drivers; or
- retrospective claims that the chosen option was obvious.

## Consequences

Describe the resulting future context after applying the decision. Consequences differ from option comparison: they are obligations and effects the project accepts.

Cover relevant effects on:

- future design freedom;
- coupling and ownership;
- delivery and migration work;
- operations, failure handling, and support;
- security and compliance;
- cost and staffing;
- testing and enforcement;
- compatibility and deprecation; and
- new risks or follow-up decisions.

List negative consequences plainly. Mitigation does not erase a trade-off; state both.

## Confirmation

Describe how future contributors can tell whether the architecture follows the ADR. Examples include:

- dependency or architecture tests;
- contract and conformance fixtures;
- integration or recovery tests;
- security review or threat-model approval;
- deployment, latency, availability, or cost metrics;
- a required code-review checklist;
- an owning implementation package and evidence index; or
- manual review when automation would misrepresent coverage.

Do not promise an automated check that cannot validate the actual architectural responsibility.

## Relationships and References

Prefer durable relative Markdown links. Link to:

- records superseded, amended, refined, or retained;
- earlier decisions that constrain this one;
- architecture guides that operationalize the choice;
- the owning PRD or TDD package;
- implementation and release evidence entry points;
- issues, proposals, benchmarks, threat models, or pull requests that substantiate the decision.

Link to a stable package README or documentation entry point rather than a long list of source files likely to move.

## Size and Decomposition

Keep an ADR readable in one sitting. One or two pages is a useful aspiration, not a hard limit. A complex cross-service decision may need more detail to state boundaries honestly.

Split a record when:

- decisions can be accepted or reversed independently;
- options and drivers materially differ;
- one section is actually a product requirement or implementation design; or
- the record needs separate lifecycle states for different choices.

Keep one record when the clauses form one indivisible ownership or consistency model and splitting them would hide the trade-off. Link detailed product scope to a PRD and implementation mechanics to a TDD.
