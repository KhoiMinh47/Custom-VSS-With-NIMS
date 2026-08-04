# ADR-001: One-store, ten-camera PoC scope

- Status: Accepted
- Date: 2026-07-23

## Decision

Build a feature-complete miniature production architecture for one store and
approximately ten IP cameras. Scale, concurrency, retention and throughput are
reduced; feature contracts are not removed.

## Consequences

Every target capability keeps an API, schema, workflow and evaluation path.
Results from this PoC may not be extrapolated to 3,000 stores without measured
pilot sizing.

## Rollback

Scope changes require a superseding ADR and feature-matrix review.
