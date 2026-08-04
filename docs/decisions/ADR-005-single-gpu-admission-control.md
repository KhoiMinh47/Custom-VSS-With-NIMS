# ADR-005: Single-GPU admission control

- Status: Accepted
- Date: 2026-07-23

## Decision

RTX PRO 5000 Blackwell is treated as experimental for VSS 3.2.1. RT-CV has
highest priority. VLM, LLM, RT-Embedding, summarization and retail batch work
must pass admission control and initially use strict mutual exclusion.

Two supported PoC topologies are retained:

- `poc-single-gpu-local-serialized`
- `poc-feature-complete-online` with remote/LAN OpenAI-compatible LLM/VLM
  endpoints

## Consequences

Feature completeness does not imply peak simultaneous execution. Batch jobs
may queue, pause or resume. No performance commitment is valid without a
benchmark on this exact host.

## Rollback

Stop the active GPU worker profile without deleting its image/cache, then
return to the last benchmark-approved profile.
