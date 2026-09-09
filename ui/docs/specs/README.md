# Application Specification Governance

This directory owns product requirements and implementation designs for the current
application. Reusable architecture guidance lives under `arch_docs/`, remains
subordinate to `AGENTS.md`, and informs technical designs.

## Delivery Sequence

```text
Master PRD (Vision)
    -> focused feature or foundational-release PRD (Normative)
    -> complete or phased technical design (Normative)
    -> implementation and acceptance evidence
```

A master PRD supplies direction but does not authorize implementation. A focused PRD
owns bounded product behavior. A technical design owns implementation structure and
acceptance for its slice.

## Status

| Status        | Meaning                                                     |
| ------------- | ----------------------------------------------------------- |
| `Vision`      | Directional product source with no implementation authority |
| `Proposed`    | Under review and not authoritative                          |
| `Normative`   | Approved authority for the document's subject               |
| `Implemented` | Normative scope has accepted implementation evidence        |
| `Deferred`    | Valid scope intentionally postponed                         |
| `Withdrawn`   | Removed from consideration                                  |
| `Superseded`  | Replaced by a named document                                |

## Package Layout

Every specification package has an owning README that records status, reading order,
source precedence, dependencies, and progress. Only this governance file is loose under
`docs/specs/`.

Use one complete `technical-design.md` for a coherent capability. Create `phase-N/`
only for genuine predecessor relationships, independently verifiable outcomes,
substantial migration or rollout risk, or separate handoffs. Phases must not merely
mirror routes, components, functions, and server modules.

Significant features and architecture changes require normative focused requirements
and a normative design. Routine fixes and isolated maintenance may use ordinary issue
and review flow when current contracts already authorize the behavior.
