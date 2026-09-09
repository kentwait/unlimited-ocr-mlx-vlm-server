# Application Architecture Decision Records

This directory contains decisions specific to the current Notes application or the
successor application created from this template. Reusable template decisions belong in
[`arch_docs/adr/`](../../arch_docs/adr/README.md).

Use an application ADR for a durable project choice such as persistence, authentication,
deployment topology, an external provider, or an application-specific consistency
policy. Product behavior belongs in `docs/specs/`; implementation mechanics belong in
the owning technical design.

## Placement Test

If the decision is intended to govern applications derived from this template, it
belongs in `arch_docs/adr/`. If it governs this application, even across feature
replacement, it belongs here.

## Lifecycle

1. Copy `template.md` to `NNNN-short-kebab-case-title.md`.
2. Allocate a monotonically increasing four-digit identifier that is never reused.
3. Default unresolved decisions to `Proposed`.
4. Maintainers approve lifecycle changes through review.
5. Preserve accepted and rejected decisions and update the index with every transition.

## Index

No application-specific ADRs have been recorded.
