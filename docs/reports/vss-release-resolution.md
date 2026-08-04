# VSS 3.2.1 release resolution

- Status: **PARTIAL / BLOCKED BY PHASE-02**
- Official repository:
  `https://github.com/NVIDIA-AI-Blueprints/video-search-and-summarization.git`
- Tag: `v3.2.1`
- Commit: `7640d917047cf7b0fd3085eefb8282754b56bc94`

The official release notes state that VSS 3.2.1 is a bug-fix release and that
its deployment assets intentionally mix 3.2.1 and unchanged 3.2.0 image tags:
https://docs.nvidia.com/vss/3.2.1/release-notes.html

## Resolved profiles

The pinned upstream source was resolved for:

- Base
- Alerts verification
- Alerts real-time
- Search
- Long-video summarization (LVS)

Each profile uses hardware setting `OTHER`, project-local `VSS_DATA_DIR`, and
sanitized generated environment files. Generated files contain no API key.

Artifacts:

- `artifacts/manifests/vss-git-revision.txt`
- `artifacts/manifests/resolved-*-compose.yml`
- `artifacts/manifests/resolved-*-compose.json`
- `artifacts/manifests/vss-*-images.txt`
- `artifacts/manifests/vss-images.txt`
- `artifacts/manifests/vss-resolved-ports.tsv`

## Gate behavior

`scripts/pull-vss-core.sh` refuses to authenticate or pull unless
`artifacts/preflight/preflight-result.env` contains `RESULT=PASS`. On this host
the result is `BLOCKED`, so no VSS/NIM image pull was performed.

No upstream tag was changed. In particular, valid 3.2.0 tags remain as selected
by the 3.2.1 assets.

## Port review

The resolved port inventory must be compared to currently bound ports after
host remediation. Phase 05 currently owns localhost ports 3000, 5432, 6379,
9000, 9001, 9090, 9092 and 9200; the VSS project overlay must avoid duplicating
those services or remap ports before start.

## Rollback

The source tree is external and ignored by Git. To roll back resolution, stop
before any pull/start and revert project-owned scripts/reports. Preserve
existing Docker images and caches.
