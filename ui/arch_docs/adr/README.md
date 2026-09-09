# Template Architecture Decision Records

This directory contains decisions intended to govern applications derived from the
template. Application-specific decisions belong in [`docs/adr/`](../../docs/adr/README.md).

## When To Write A TADR

Write a template ADR when a durable decision intended for derived applications changes
the source decomposition, runtime boundaries, dependency direction, validation model,
testing baseline, security posture, or supported deployment construction.

Routine implementation belongs in code or a technical design. Product behavior belongs
in an application PRD. A database, identity provider, or application deployment choice
normally belongs in `docs/adr/`.

## Lifecycle

1. Copy `template.md` to `TADR-NNNN-short-kebab-case-title.md`.
2. Allocate a monotonically increasing four-digit identifier that is never reused.
3. Default unresolved decisions to `Proposed`.
4. Maintainers accept, reject, or withdraw records through review.
5. Preserve accepted and rejected records. Change an accepted decision with a new linked
   TADR and synchronize affected contracts.

| Status       | Meaning                                                          |
| ------------ | ---------------------------------------------------------------- |
| `Proposed`   | Recommendation under review and not authoritative                |
| `Accepted`   | Authoritative for its stated template scope                      |
| `Rejected`   | Deliberately not adopted                                         |
| `Withdrawn`  | Removed without a decision on its merits                         |
| `Deprecated` | Still applicable to legacy scope while being phased out          |
| `Retired`    | No longer applicable because its governed capability was removed |
| `Superseded` | Replaced by a linked record                                      |

## Index

No template ADRs have been recorded. The current baseline is established directly by
the repository contract and implemented reference; this empty log does not manufacture
retrospective rationale or approval evidence.
