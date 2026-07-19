---
id: "2026-07-18-fastmcp-pydantic-floor"
title: "FastMCP tool registration crashes with stale pydantic"
domain:
  - "python"
  - "mcp"
  - "fastmcp"
error_signature: "PydanticUserError: A non-annotated attribute was detected"
created_at: "2026-07-18T12:00:00Z"
confidence: confirmed
---

## Symptom

Server crashes at import time when registering any tool with a bare return type annotation.

## Approaches that FAILED (do not repeat)

- Upgrading only the mcp package without checking pydantic's floor
- Adding explicit Pydantic BaseModel wrappers to every tool return type

## Root cause

Global python3's pydantic (2.9.2) predates the floor mcp==1.27.0 requires (>=2.11.0); create_model() with a bare annotation is rejected by the old version.

## Fix

Run the server via `uv run --with-requirements server/requirements.txt server/main.py` so a compliant pydantic is resolved in an ephemeral environment.

## Tags for retrieval

- pydantic
- fastmcp
- dependency-conflict
- mcp-sdk
