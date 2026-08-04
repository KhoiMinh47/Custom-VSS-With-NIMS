# Hybrid CV→VLM versus direct RT-VLM

## Executive result

The Phase 11 direct path ran successfully on the physical `cam-01` stream with
the pinned VSS RT-VLM 3.2.1 image and the cached Cosmos3 Nano Reasoner. Two
clean eight-second chunks, sampled at five frames each, produced structured
real-model responses. The direct workflow is technically viable for a small
number of high-value semantic checks, but it should not replace the Phase 10
hybrid path as the default on this single-GPU PoC.

Accuracy and false-alert comparison remains `PARTIAL`: direct has no operator
labels and hybrid has one. The results below compare runtime behavior, not
business accuracy.

## Measured snapshot

| Measure | Phase 10 hybrid | Phase 11 direct |
|---|---:|---:|
| Camera scope | `cam-01` | `cam-01` |
| Trigger | Phase 09 CV/rule candidate | Every configured live chunk |
| Media unit | Selected pre/post-roll clip | 8 s live chunk |
| Frame sampling | 8 frames per selected clip | 5 fixed frames per chunk |
| Clean measured results | 3 persisted latency samples | 2 clean benchmark responses |
| Verdicts in clean run | 2 rejected, 1 uncertain audit result | 1 rejected, 1 confirmed |
| Latency | p50 3,451 ms; max 11,243 ms | 7,981–14,739 ms |
| Input/output tokens | Not captured in Phase 10 contract | 9,732 / 56 total |
| Peak aggregate VRAM | 43,587 MiB | 46,348 MiB |
| Peak GPU utilization | Not retained in Phase 10 report | 100% |
| Peak sampled power | Not retained in Phase 10 report | 303.67 W |
| Operator labels | 1 | 0 |
| Accuracy/false-alert status | Insufficient labels | Insufficient labels |

Phase 11's two clean responses used 4,866 input tokens per chunk and 20–36
output tokens. No dollar cost is assigned because inference is local and the
PoC has no approved hardware amortization or energy tariff. Token count,
inference latency, sampled power and GPU duty are retained as cost proxies.

## Trade-off

Hybrid verification is event-driven. CV/rules reduce the number of VLM calls,
incidents queue durably while Cosmos3 is stopped, and the local VLM consumes
GPU only during an admitted verification window. It is appropriate for
counting, ROI, dwell, queue and restricted-zone rules where CV already provides
a reliable candidate.

Direct RT-VLM evaluates every configured chunk and can express semantic
conditions that do not map cleanly to a detector/rule. It avoids waiting for a
CV candidate but consumes tokens and GPU continuously while enabled. On the
selected host it peaked at about 94.7% of VRAM, leaving too little headroom for
RT-CV overlap or multi-camera extrapolation.

## Recommendation

Use Phase 10 hybrid by default for frequent, detector-friendly events and for
deployments where GPU duty, queue durability and predictable cost matter.

Use direct RT-VLM only for a small, explicitly admitted camera set when:

- the alert is semantic and difficult to express as CV geometry/rules;
- an eight-second chunk and 5-frame sample provide enough context;
- higher continuous GPU/token cost is acceptable;
- operator review and a labeled evaluation set are available.

Do not enable direct RT-VLM across ten cameras on this profile. Keep RT-CV and
Cosmos3/RT-VLM serialized. Before any production recommendation, collect at
least 20 operator labels for a provisional false-alert check and rerun with a
balanced real-camera evaluation set.

## Approved runtime policy

The recommendation was accepted on 2026-07-29 and is encoded in
`config/runtime/single-gpu-poc.yaml`:

- `hybrid_candidate_verification` is the default alerting mode;
- the stable runtime keeps RT-CV, Behavior Analytics and the Phase 10 durable
  incident/review services active;
- local Cosmos3 runs only in an admitted event-driven verification window;
- direct RT-VLM is `explicit_only`, limited to `cam-01` and one concurrent
  camera on the measured profile.

Operators activate and verify the stable policy with
`make alerts-default-start` and `make alerts-default-health`. The existing
`make phase11-direct-start` remains the explicit opt-in action for a bounded
semantic experiment.

## Known implementation observations

- Cosmos3 accepts at most five images in this path. The initial eight-frame
  configuration returned HTTP 422 and is retained as audit evidence.
- The RT-VLM image reported an optional `PyNvVideoCodec` library mismatch and
  used its available fallback path; clean chunks still produced Cosmos3 HTTP
  200 responses and Kafka protobuf results.
- RTX PRO 5000 Blackwell remains an experimental host for this topology. These
  measurements are PoC evidence, not NVIDIA validation.
