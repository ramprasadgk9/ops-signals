# ADR-004: PostgreSQL System of Record

## Status

Accepted

## Decision

Store durable operational state in PostgreSQL.

## Consequences

- transactional integrity for core entities
- clear source of truth for the application
