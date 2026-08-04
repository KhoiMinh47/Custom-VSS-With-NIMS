# Phase 15 uploaded-media intake

This project-owned, CPU-only service is the upload and media-preparation
boundary for the unified workspace. It is not part of upstream NVIDIA VSS and
does not modify `third_party/`.

The browser sends a bounded MP4/MKV file to port 39510. The BFF forwards it
only to the fixed loopback service ID `media-intake` on port 39420. The
service validates filename, MIME, container signature, H.264 marker and
content SHA-256 before writing an active record. Supported MP4 is copied into
the prepared directory and exposed to Phase 13 as an exact
`uploaded-media://<sha256>.mp4` manifest. Phase 13 mounts only the prepared
directory read-only.

MKV is accepted only when its container/H.264 markers validate. It remains
`summary_ready=false` because the pinned runtime has no approved remux binary.
The UI reports this state and does not claim preparation succeeded.

Delete is quarantine, not physical purge. Restore moves the exact asset back.
The BFF rejects deletion with 409 when a persisted Phase 13 job references the
uploaded asset. Alert evidence under `runtime/incidents/clips` is outside this
service's mount and cannot be deleted by this contract.

Runtime state is project-local under `runtime/media-intake-data/` and must be
preserved during stop, rollback and recovery. Never use Docker volume removal,
prune or recursive deletion as a rollback.
