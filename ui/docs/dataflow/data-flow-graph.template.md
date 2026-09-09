<!-- pair-contract: urn:data-flow-graph:schema:3 -->
<!--
Canonical markdown template for a planned data-flow lifecycle narration.
One markdown = one lifecycle = one graph file sharing the same basename,
differing only by extension (e.g. upload-ingest.json + upload-ingest.md).
Pairs live under the run's chosen root (default docs/dataflow/ in the
target repo), alongside copies of the schema and this template.

Line 1 above is the contract stamp: KEEP it verbatim as the first line of
every filled copy (it pairs with the JSON's root "version" field). Only
guidance comments like the one you are reading get deleted.

Adapted for planning: the graph depicts the lifecycle as the world looks
AFTER the plan lands. Every element's truth comes from either code that
exists today (`evidence: "code"`, cited file:symbol) or the spec/plan that
introduces it (`evidence: "spec"`, cited to the spec passage). The narration
carries the same distinction everywhere prose meets the graph.

Section order is fixed. Sections may be empty only where explicitly allowed;
do not invent new top-level sections. HTML comments like this one are
guidance and must be deleted from the filled-in copy.

Conventions:
- Title MUST match the filename stem: `# <Stem>. <Lifecycle name>`.
- Every narrative element cites its graph coordinates (node IDs, seq numbers,
  outcome values) plus its source (spec passage or file:symbol) so prose
  joins back to the JSON and to reality deterministically.
- Failure = handled error surfaced to the caller (graph `outcome: "error"`).
  Exception = unhandled escape or mid-flight crash (ties to `dead-end` nodes).
  Anomaly = design-level finding: verified-absent paths, nonsensical or
  prematurely terminating paths, SPEC GAPS (promises missing from the spec,
  unspecified failure modes, ambiguous ownership of state)
  (`outcome: "anomaly"`). Keep the four apart.
-->

# <Stem>. <Lifecycle name>

<One-to-three sentence summary of what this lifecycle will accomplish
end-to-end once the plan lands.>

- **Status:** <Initialize | Extend | Restate — one clause on what exists today vs what the plan introduces>
- **Entry point:** <planned or existing — method + URL / server function / route loader, with source>
- **Trigger:** <the user action or system event that starts the request-response cycle>
- **Termination:** <where the lifecycle ends: sink node(s), dead-end(s), and/or return-to-initiator>
- **Response:**
  - **Success:** <what the caller receives on the happy path>
  - **Failure:** <what the caller receives when a handled error occurs>
  - **Exception:** <what happens when an unhandled escape or crash interrupts the flow>

## Participants

<!-- One row per node in the JSON graph, same order as nodes[].
     Group: integer per the project's documented group legend.
     Role: initiator | intermediary | sink | dead-end.
     Evidence: matches the node's `evidence` field — code | spec.
     Symbol: code identifier from the node's `symbol` field; em-dash if none.
     What: the node's `description`.
     Source: `file:symbol` read this run for existing nodes; the spec passage
     (issue/section/quote anchor) for planned nodes. -->

| Node ID | Group | Role | Evidence | Symbol | What | Source |
| --- | --- | --- | --- | --- | --- | --- |
| `<NODE_ID>` | <int> | <role> | <code\|spec> | `<symbol>` | <description> | <file:symbol or spec passage> |

## Sequence

<!--
Happy path only — errors and anomalies get their own sections below.
One numbered step per narrative beat, ordered by seq. Each step opens with
the seq value(s) it corresponds to in the JSON graph: `(seq N)`, `(seq N–M)`
for a range, `(seq N, M)` for scattered steps. Parallel interchangeable steps
share a seq — say so. Existing hops cite exact files/functions/types/schemas
read this run; planned hops cite the spec passage that promises them.
-->

1. (seq <N>) <Step description citing file:symbol or spec passage.>
2. (seq <N>) <Step description.>

## Error paths

<!--
One H3 per distinct failure mode the plan handles (handled errors,
`outcome: "error"`). Each subsection opens with a *Covers* line listing the
graph links it describes and cites its source (spec passage or code). If the
spec promises no handled-error paths, keep the section with "None promised by
the spec." — and treat a flow with obviously needed error handling and none
promised as a spec-gap anomaly below instead.
-->

### <Failure mode name>

_Covers:_ seq <N>, `<SOURCE>` → `<TARGET>` (outcome: error)

<Trigger condition, where it will be raised (file:symbol if the raising point
exists today), how it surfaces to the caller/user, and which spec passage
promises it.>

## Anomalies

<!--
One H3 per anomaly (`outcome: "anomaly"` or `dead-end` role). Two kinds:
- Code anomalies: expected-but-absent paths, swallowed errors, premature
  terminations in what exists today — cite file:symbol evidence.
- Spec gaps: error paths the spec never promises, failure modes it leaves
  unspecified, state whose owner is ambiguous across services — cite the
  spec's silence precisely (quote the surrounding text).
Each anomaly ends with a disposition line: test candidate, scope cut, or
question back to the spec author. If none, keep the section with "None."
-->

### <Anomaly or spec-gap name>

_Covers:_ seq <N>, `<SOURCE>` → `<TARGET>` (outcome: anomaly)

<What was expected or found missing, evidence (file:symbol or quoted spec
silence), why it matters. Disposition: test candidate | scope cut |
question for spec author.>

## Verification

<!--
How the graph was grounded in reality. One bullet per unit of evidence,
shaped as `<path-symbol-or-spec-anchor> — <what was confirmed>`. Distinguish
the two kinds: code read this run pins existing elements; spec passages pin
planned ones. Nothing may stand on memory alone.
-->

- `<path:symbol>` — <existing element confirmed here>
- `<spec §anchor>` — <planned element promised here>

## Serialization notes

<!--
Judgment calls ONLY — role assignments, seq ordering decisions, kind mapping
choices, evidence calls on elements the plan modifies rather than creates.
Keep it lean; rationale and findings belong in Anomalies, not here. Group
under short H3s when there is more than one cluster of decisions. If no
judgment calls were needed, keep the section with "None."
-->

### <Decision cluster name>

- <Decision and its justification.>

## Revisions

<!--
Present only after the pair was edited in place by a later planning run
(Restate mode). One bullet per revision, oldest first: what changed, which
graph coordinates moved (seq values added/removed/reordered), and the plan
change that motivated it. Omit this entire section on first authoring.
-->

- <What changed and why, citing seq coordinates and the motivating plan change.>

## References

<!-- Citations in three buckets, in this order. Use relative links for repo
     files; cite the governing spec first. -->

### Spec and decisions

- [<issue/plan/spec>](<path-or-anchor>) — <relevance; the authority this plan derives from>

### Related lifecycles

- [<name>](<slug>.md) — <what it shares with this lifecycle>

### Code

- `<path:symbol>` — <role in this lifecycle>
