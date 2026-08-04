# Agent contract

This repository implements the NVIDIA VSS Retail PoC for one store and
approximately ten cameras. Read the full phased plan, `PROJECT_STATE.md` and
the latest handoff before making changes.

## Non-negotiable architecture

- Keep the video/raw-storage plane independent from the AI plane.
- Raw storage may feed only media selection/preparation. Never implement a
  direct raw-storage-to-metadata/event/embedding/summary/report path.
- Keep `store_id`, stable `camera_id`, UTC timestamps, schema version and model
  version in all relevant contracts.
- VSS release baseline is 3.2.1. Respect the exact tags in its deployment
  assets, including intentional 3.2.0 tags.
- The selected GPU is experimental for VSS. Never claim that NVIDIA validates
  RTX PRO 5000 Blackwell for this topology.
- GPU-heavy services must use admission control and may be serialized.

## Safety and data policy

- Never run Docker/image/builder/volume prune.
- Never use `docker compose down -v`, `docker rmi`, `docker volume rm`, or
  delete an existing model/cache automatically.
- Stop scripts must preserve images, volumes and bind-mounted data.
- Never print, persist or commit `NGC_API_KEY`, camera passwords, tokens or
  real `.env` files.
- Camera configuration stores only secret references, never plaintext RTSP
  credentials.
- Do not install Python packages globally or with `sudo pip`.
- Keep `.venv`, model weights, generated engines, caches, runtime data, logs
  and temporary files under the project root.
- Do not download all NIM profiles. Discover compatibility and cache only an
  approved profile.
- Do not force a profile intended for another GPU.

## Change and validation policy

- Use project overlays instead of casually editing upstream VSS.
- Pin image digests after discovery/pull and record model source, version,
  hash/digest, license, cache path and build metadata.
- Every migration must be repeatable and have a rollback/restore path.
- Every service needs a health check, structured logs and tests proportionate
  to its phase.
- A failed hard gate must be reported as `BLOCKED` or `PARTIAL`; mocks may not
  be used as evidence that external infrastructure or GPU models ran.
- Before downloads, inventory current images/containers and available disk.
- Preserve evidence under `artifacts/` and update the phase handoff.

## Current implementation order exception

The user explicitly requested Phase 05 first, followed by Phase 00 through
Phase 04. Handoffs and project state must preserve this fact; it does not waive
any hard gate.
