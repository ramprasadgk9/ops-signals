---
id: PM-2025-031
title: Checkout CPU and latency up from GC pauses
service: checkout
started_at: 2025-08-12T10:15:00Z
resolved_at: 2025-08-12T12:40:00Z
severity: SEV2
source: postmortems
url: https://wiki.example.com/postmortems/PM-2025-031
tags: [cpu, jvm, gc]
---

# Checkout CPU and latency up from GC pauses

## Summary

CPU usage on checkout rose from 45% to 88% and p99 latency reached 3 seconds. Error rate stayed
under 1%, so the first page came from the CPU alert, not from errors.

## Root cause

A config change halved the checkout container memory limit. The JVM heap shrank with it and the
garbage collector ran almost continuously, which showed up as high CPU.

## Resolution

Restored the memory limit and set the heap size explicitly instead of deriving it from the
container limit.

## Outcome

CPU back to 45% within 15 minutes of the rollout. Added an alert on GC time above 10%.

## Timeline

- 10:15 CPU alert on checkout
- 10:50 GC logs show back-to-back full collections
- 12:30 memory limit restored
