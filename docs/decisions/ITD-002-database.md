# ITD-002: Database and idempotent writes

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Project team
- **Verified:** 2026-07-31

## Context

CSV and API loads can contain the same student and can arrive out of order. Retries also mean the
same record may be processed more than once. The database must prevent duplicates and must not
replace newer data with older data.

The data is tabular, and `student_id` is its stable key. Local tests must use the same database
engine as Azure.

## Recommendation Options

1. **Azure Database for PostgreSQL Flexible Server — selected**
2. Azure SQL Database
3. Azure Cosmos DB
4. Blob storage only

## Decision

Use PostgreSQL Flexible Server. Write students with one conditional upsert:

```sql
INSERT INTO students (...)
VALUES (...)
ON CONFLICT (student_id) DO UPDATE
SET ...
WHERE EXCLUDED.updated_at > students.updated_at;
```

This gives the database three guarantees:

- one row per `student_id`;
- older data cannot replace newer data; and
- processing the same input again changes no rows.

PostgreSQL also provides local engine parity through Docker, relational constraints, useful
indexes, `JSONB` for the original payload, and set-based bulk writes.

Azure supports Microsoft Entra authentication for Flexible Server. Built-in PgBouncer is available
if serverless connection churn becomes a problem. See the Microsoft documentation for
[managed identity connections](https://learn.microsoft.com/en-us/azure/postgresql/flexible-server/how-to-connect-with-managed-identity)
and [PgBouncer](https://learn.microsoft.com/en-us/azure/postgresql/connectivity/concepts-pgbouncer).

### Why not the others

**Azure SQL:** It can meet the requirements, but PostgreSQL has a simpler `ON CONFLICT` upsert and
easier local parity for this project.

**Cosmos DB:** The roster is relational. Safe conditional writes would require more application
logic around ETags.

**Blob storage only:** It cannot provide database constraints or a true row-level upsert.

## Consequences

- `student_id` is the primary key.
- `updated_at` controls whether an update is accepted.
- A missing or invalid `updated_at` is quarantined.
- Schema changes use ordered migrations.
- Azure uses Entra authentication. Local development uses a test password or developer identity.

## Revisit if

- the source no longer provides a stable student ID;
- most useful fields move into `JSONB`;
- one server cannot handle the write or connection load; or
- the target organization requires Azure SQL.
