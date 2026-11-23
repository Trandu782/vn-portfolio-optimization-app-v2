# Architecture Decision Records

This directory records significant architectural decisions for the VN Portfolio
Optimizer. Each ADR is a short, append-only document that captures the context,
the decision and its consequences.

## Index

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-registry-based-extension-points.md) | Registry-based extension points | Accepted |
| [0002](0002-data-layer-failover.md) | Anonymous data providers behind a failover chain | Accepted |

## Template

Copy the structure below for a new record, naming the file
`NNNN-short-title.md`.

```markdown
# NNNN. Title

- Status: Proposed | Accepted | Superseded by NNNN
- Date: YYYY-MM-DD

## Context

What problem are we solving, and what constraints apply?

## Decision

What did we decide, and why?

## Consequences

What becomes easier, what becomes harder, and what follow-up work does this
imply?
```
