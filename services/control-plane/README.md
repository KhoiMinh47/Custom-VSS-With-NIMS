# Control-plane data contract

Phase 05 provides the persistent control-plane schema in
`migrations/001_control_plane.sql`.

The schema stores configuration, job state, role assignments and audit records.
Camera credentials are represented only by secret references. Raw video is not
stored in PostgreSQL and the raw-video plane has no direct path to analytics
indices.

Application APIs are intentionally deferred to the later unified API phase.
