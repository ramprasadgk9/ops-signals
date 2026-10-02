---
id: PM-2025-038
title: Payments CPU spike from database connection storm
service: payments
started_at: 2025-09-03T06:00:00Z
resolved_at: 2025-09-03T06:45:00Z
severity: SEV2
source: postmortems
tags: [cpu, database]
---

## Summary

After a database failover, payments CPU jumped to 97% and stayed there for 40 minutes.

## Root cause

Every payments pod reconnected to the database at the same moment with no backoff. TLS handshakes
for thousands of new connections saturated CPU.

## Resolution

Added jittered exponential backoff to database reconnects and limited the pool's connection
creation rate.

## Outcome

A failover drill a week later caused no CPU spike.
