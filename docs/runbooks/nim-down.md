# Nemotron or Cosmos3 unavailable

## Symptom

An on-demand provider is `standby` or a caption/summary/critic request waits
for GPU.

## Detection

- Confirm the service is expected `on_demand` in the Phase 15 registry.
- Inspect admission state and provider readiness.
- Check the relevant job queue and last error type.

## Immediate mitigation

Do not classify normal standby as failure. For an approved inference window,
use only the phase-specific start target so admission, readiness and RT-CV
serialization are enforced.

## Root-cause checklist

- Correct pinned image digest and approved profile ID.
- Persistent model cache mounted at the expected project path.
- No competing GPU lease.
- Request context, frame count and output budget within the tested profile.

## Recovery validation

Run an actual provider request required by the phase, stop the provider through
its safe target, confirm lease revocation and restore RT-CV.

## Data-loss assessment

Inspect durable queue/checkpoint/DLQ state. Never generate a mock completion.
