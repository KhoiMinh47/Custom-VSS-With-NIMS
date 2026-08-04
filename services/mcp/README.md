# Phase 15 tool catalog

The initial MCP-compatible application catalog is deliberately read-only:
dashboard discovery, service health, port mapping and admission state.
Every execution goes through the unified API permission check and audit log.
This MCP-compatible catalog remains read-only. LLM/VLM power mutations now
exist on a separate narrow same-origin API: they require explicit confirmation,
an operator-capable role, audit logging, the host command queue and GPU
admission. They are not exposed as generic MCP mutation tools. Production LAN
exposure remains locked until a production IdP/TLS boundary is approved.
