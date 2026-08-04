# ADR-007: Lock Phase 14 and proceed to the Phase 15 control room

## Status

Accepted by explicit user instruction on 2026-07-30.

## Context

Phase 14 requires a concrete retail use case, shelf ROI, product master,
reference images and business-approved labels. None are currently approved.
Creating synthetic shelf/SKU evidence would not satisfy the retail hard gates.

The existing Phase 07–13 workflows already expose separate operational
dashboards and loopback ports. The user requested a unified application to
manage that experience before retail scope is selected.

## Decision

- Mark Phase 14 `LOCKED_BY_USER`, incomplete and unapproved.
- Proceed directly to Phase 15 as an explicit ordering exception.
- Build a CPU-only, read-only-by-default control room for dashboard discovery,
  port registry, service health, RBAC, audit and GPU admission visibility.
- Do not add a fake retail service or claim Phase 14 completion.
- Do not allow the control room to mount raw video, camera secrets or Docker's
  socket, or to bypass GPU admission.

## Consequences

Phase 15 remains `PARTIAL` until retail tools exist and production identity,
TLS termination, actual Nemotron tool selection, distributed tracing and all
security/observability gates are exercised. Phase 16 stays locked until the
user reviews the Phase 15 handoff.
