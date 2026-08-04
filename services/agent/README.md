# Phase 15 agent routing

The app uses an evidence-only router for system status and grounded workspace
answers. It does not start Nemotron automatically: the operator must explicitly
turn the LLM on and the GPU admission worker must grant its lease.

When Nemotron is online, the UI can use the local OpenAI-compatible chat
provider. Deterministic routing and persisted evidence remain available while
the provider is offline. Autonomous, unrestricted model-selected tool
execution is intentionally not claimed; mutations continue through explicit
permission-checked API operations.
