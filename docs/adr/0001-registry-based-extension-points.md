# 0001. Registry-based extension points

- Status: Accepted
- Date: 2026-11-21

## Context

The optimizer exposes many variable concepts: data providers, return and
covariance estimators, objectives, constraints, risk metrics, return simulators,
cost and slippage models, rebalance schedules and policies, universe filters and
backtest metrics. Each concept will gain multiple implementations over time, and
users should be able to choose among them from the UI.

Hard-coding variants as `if/else` or `switch` chains would spread change across
the codebase and make it impossible for the API to advertise what is available.

## Decision

Every variable concept is an **interface plus a registry**. A single generic
`Registry[T]` (in `packages/core/core/registry.py`) provides:

- a `register(...)` decorator that records an implementation under a stable
  `id`, with a display `name`, a `description` and an optional Pydantic
  parameter schema;
- `get(id)` to retrieve an implementation;
- `list()` to enumerate ids;
- `describe()` to return `id`, `name`, `description` and the JSON schema of the
  parameters, so the API can publish options and the UI can render them.

Adding a feature becomes *one new file plus one registration*. Deferred
features may ship their interface and empty registry, but not an implementation.

## Consequences

- New variants never require editing existing dispatch logic.
- The API can serve the catalogue of options, so the UI stays generic.
- Each concept gets a small, testable surface; registries are unit-tested.
- Contributors must remember to register implementations and keep parameter
  schemas accurate; `docs/EXTENDING.md` records this checklist.
