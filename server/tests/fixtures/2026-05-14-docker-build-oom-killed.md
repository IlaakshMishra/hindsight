---
id: "2026-05-14-docker-build-oom-killed"
title: "Docker image build gets OOM killed during webpack bundling"
domain:
  - "docker"
  - "devops"
  - "ci"
error_signature: "exit code 137"
created_at: "2026-05-14T18:00:00Z"
confidence: probable
---

## Symptom

The CI build step exits abruptly partway through the frontend bundling stage.

## Approaches that FAILED (do not repeat)

- Increasing the webpack cache size, which made memory pressure worse

## Root cause

The CI runner's container memory limit was lower than webpack's peak heap usage during minification.

## Fix

Raised the container memory limit and enabled webpack's memory-friendly minifier.

## Tags for retrieval

- docker
- oom
- webpack
- ci-build
