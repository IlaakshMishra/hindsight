---
id: "2026-06-02-react-useeffect-infinite-loop"
title: "React useEffect infinite loop from missing dependency array"
domain:
  - "javascript"
  - "react"
  - "frontend"
error_signature: "Maximum update depth exceeded"
created_at: "2026-06-02T09:30:00Z"
confidence: confirmed
---

## Symptom

Component re-renders continuously and the browser tab freezes shortly after mount.

## Approaches that FAILED (do not repeat)

- Wrapping the state setter in useCallback without fixing the effect's dependency array

## Root cause

useEffect had no dependency array, so it ran after every render, and the effect itself called a state setter, triggering another render.

## Fix

Added the correct dependency array so the effect only runs when its inputs change.

## Tags for retrieval

- react
- hooks
- infinite-loop
- useeffect
