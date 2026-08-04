# PHASE-04 HANDOFF

## Result

PASS_WITH_RISK

## Scope completed

- Pulled and digest-pinned both NIM images.
- Discovered compatible BF16 TP1 profiles on the target GPU without forcing a
  profile from another GPU.
- Downloaded exactly the selected Nemotron and Cosmos3 Nano profiles to
  persistent project-local cache backed by `/mnt/storage1`.
- Downloaded the official RT-DETR Warehouse v1.0.2 and SigLIP2 v1.1 artifacts.
- Downloaded Cosmos-Embed1, exported ONNX, built TensorRT 10.14.1 engines and
  passed ready/restart-cache-reuse tests.
- Ran Nemotron and Cosmos3 smoke tests separately; both `/v1/health/ready` and
  `/v1/models` checks passed.
- Pinned artifact/image digests and recorded file inventories.

## Validation evidence

- `artifacts/manifests/model-digests.json`
- `artifacts/manifests/model-cache-inventory.tsv`
- `artifacts/manifests/nim-cache-sizes.txt`
- `artifacts/benchmarks/nim-smoke-test/`
- `artifacts/benchmarks/cosmos-embed-ready.json`
- `artifacts/benchmarks/cosmos-embed-restart-ready.json`
- `artifacts/benchmarks/cosmos-embed-restart-container.log`
- `docs/reports/model-compatibility-report.md`

The restart log confirms cached model use and skipped ONNX/TensorRT creation.
No NIM or model smoke container remains running.

## Known risks

- Phase 02 host versions are outside NVIDIA's documented baseline; execution
  continued only under the user's explicit acknowledgement.
- Phase 03 remains partial because the Docker disk guard stopped before the
  RT-VLM image.
- The topology must remain `LOCAL_SERIALIZED` on this single 48 GB GPU.

## Rollback

Stop only the named profile/model containers. Preserve all image, model and
TensorRT caches. No prune command is provided.

## Exact next phase

Review Phase 02 risk and move Docker data storage before completing the
remaining Phase 03 image pull or starting a full VSS profile.

## Approval required

YES before starting the full VSS/10-camera runtime.

