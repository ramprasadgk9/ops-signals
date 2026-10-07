---
title: Search cache stampede at midnight
service: search-api
started_at: 2025-09-20T00:00:00Z
severity: SEV3
---

## What happened

Search latency spiked every night at midnight for about five minutes.

## Why it happened

All cache keys were written with the same 24-hour TTL, so they expired together and every request
went to the backend at once.

## Fix

Added random jitter to cache TTLs.
