---
id: "2026-04-01-postgres-pool-exhausted"
title: "Postgres connection pool exhausted under load"
domain:
  - "postgres"
  - "database"
  - "backend"
error_signature: "FATAL: remaining connection slots are reserved for non-replication superuser connections"
created_at: "2026-04-01T08:15:00Z"
confidence: confirmed
---

## Symptom

API requests start timing out under moderate traffic with database connection errors in the logs.

## Approaches that FAILED (do not repeat)

- Increasing Postgres's max_connections setting without addressing app-side leaks

## Root cause

A connection leak in a request-scoped session that was never closed on the error path.

## Fix

Added a try/finally around the session so it always closes, and switched to a bounded connection pool.

## Tags for retrieval

- postgres
- connection-pool
- database-timeout
