# ADR-002: Separate video and AI planes

- Status: Accepted
- Date: 2026-07-23

## Decision

The VMS/VIOS layer owns ingest, raw recording, playback and selected media
extraction. AI receives RTSP, selected files, clips, frames or ROIs. Metadata,
events, embeddings, summaries and reports are outputs of VSS/model services.

No direct raw-storage-to-analytics-output connection is permitted.

## Consequences

Historical processing must request media through the preparation adapter.
Stopping AI must not stop recording. VSS does not retain a second complete copy
of the raw archive.

## Rollback

Any component violating the boundary must be disabled and replaced by an
adapter that performs explicit media selection/preparation.
