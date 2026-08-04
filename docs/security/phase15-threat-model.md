# Phase 15 control-room security posture

The unified app is bound to loopback. Its container has no Docker socket,
raw-video mount, selected-media mount, camera secret mount or GPU device.
Anonymous sessions receive `viewer`; protected reads, tool execution and GPU
control require a bearer token whose SHA-256 digest is stored in the ignored
Phase 15 secret directory.

GPU profile switching is the only mutating control surface. The API can only
queue a catalog profile ID after explicit confirmation by an operator,
model-engineer or admin. A separate project-local host worker performs the
transition through fixed existing scripts. The API container cannot execute
Docker commands itself.

Security boundaries:

- CSP, frame denial, no-referrer and restrictive browser permissions.
- No permissive CORS.
- Tool allowlist contains only non-mutating operations.
- GPU requests are serialized; a second request receives conflict while one
  is queued, running or recovering.
- The worker fails closed for unknown leases and arbitrary script paths.
- Profile requests, completion/failure, tool calls and authorization denials
  are structured and auditable.
- Authorization headers, cookies, tokens and passwords are never logged.
- Stop/start paths preserve images, volumes, caches, checkpoints and data.
- TLS reverse-proxy configuration is supplied but not activated without an
  operator-managed certificate and internal DNS.

Known limitations:

- The current runtime uses loopback HTTP and bearer tokens in browser session
  storage. It must not be exposed to a LAN or Internet interface until TLS
  termination and an approved identity provider are configured and tested.
- The host worker has intentional local authority to run the allowlisted
  profile scripts. Access to the project tree and runtime queue therefore
  remains a trusted-host boundary.
- This is an experimental single-GPU topology, not an NVIDIA-validated RTX PRO
  5000 Blackwell deployment.
