# ADR-004: Project-local environment and cache

- Status: Accepted
- Date: 2026-07-23

## Decision

Python tooling uses `.venv`. Caches, NIM weights, model artifacts, TensorRT
engines, runtime state, logs and temporary files live below the project root.
Containers bind-mount these paths.

The current mode is `host-docker-safe`: Docker image layers remain in the
existing host daemon while project data remains local. A project-scoped
rootless daemon may be evaluated only after GPU CDI validation.

## Consequences

Scripts must export project-local cache variables and verify path containment.
No global Python install is allowed. Existing host Docker images and volumes
must be preserved.

## Rollback

Deactivate `.venv` and stop project services. Preserve caches and runtime data
unless a separately approved retention action exists.
