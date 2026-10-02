---
id: PM-2025-007
title: Search results empty after index rebuild
service: search-api
started_at: 2025-07-21T13:05:00Z
resolved_at: 2025-07-21T14:10:00Z
severity: SEV2
source: postmortems
url: https://example.com/postmortems/PM-2025-007
tags: [search, elasticsearch]
---

# Search results empty after index rebuild

## Summary

About 30% of search requests returned zero results for an hour. Error rate stayed flat,
so the first alert came from a drop in search click-through rather than from errors.

## Root cause

The nightly index rebuild switched the search alias to the new index before the bulk load
finished, so queries hit a half-empty index.

## Resolution

Pointed the alias back to the previous index, then changed the rebuild job to switch the
alias only after the document count matches the source within 1%.

## Outcome

Results recovered immediately after the alias switch. No repeat since the job change.

## Timeline

- 13:05 click-through on search drops by 40%
- 13:30 on-call notices zero-result rate at 30%
- 14:10 alias reverted, results back to normal
