# GPU control worker

Host-side executor for LLM/VLM power controls and bounded model workflows. The
browser never receives Docker access. The same-origin API writes a confirmed,
role-checked command into a project-local queue; this worker acquires a file
lock, validates the fixed command schema and runs only allowlisted scripts.

```text
UI ON/OFF -> API permission + audit -> command queue -> host worker
          -> stop conflicts -> admission lease -> allowlisted start/stop
          -> readiness/status file -> UI notification
```

LLM and VLM are mutually exclusive under the current single-GPU policy.
RT-CV is not a general UI power toggle: the file-batch instance is started only
inside Upload → RT-CV → VLM, then stopped before Cosmos3 starts. Stop actions
preserve images, caches, volumes, selected media and runtime data.
