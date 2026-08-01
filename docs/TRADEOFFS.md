# Trade-offs

This file records important downsides that the project accepts on purpose.

Add an entry only when the downside affects reliability, scale, cost, security, operations, or
future work. Do not record routine implementation details.

## Entry format

```markdown
### T-NNN: Title
- **Date:** YYYY-MM-DD
- **Status:** Accepted | Resolved | Revisit
- **Related:** ITD-NNN, if useful

**Choice:** What we chose.
**Downside:** What we gave up or made harder.
**Reason:** Why the benefit is worth the downside.
**Mitigation:** How the current design limits the cost.
**Revisit if:** A clear condition that would justify a change.
```

---

### T-001: Azure Functions host limits

- **Date:** 2026-07-31
- **Status:** Accepted
- **Related:** [ITD-003](./decisions/ITD-003-compute-model-verified.md)

**Choice:** Run the pipeline on Azure Functions Flex Consumption.

**Downside:** Cold starts can delay scheduled jobs by a few seconds. Scale-in and platform updates
can interrupt long work. The host also has platform-specific behavior that is not identical to a
local container.

**Reason:** The workload is short and scheduled. Flex Consumption provides low idle cost, timer
triggers, managed identity, and monitoring with less infrastructure than Container Apps Jobs.

**Mitigation:** Process bounded chunks, store checkpoints, and keep Functions imports outside
`src/`. CSV ingestion uses a scheduled scan, so it does not depend on Event Grid.

**Revisit if:** Interruptions remain common after checkpointing, or container parity becomes more
valuable than the simpler host.

### T-003: Fixed canonical schema

- **Date:** 2026-07-31
- **Status:** Accepted
- **Related:** [ITD-002](./decisions/ITD-002-database.md)

**Choice:** Store students in one relational PostgreSQL schema.

**Downside:** Every source field needs an explicit mapping. Making a field searchable or enforced
requires a database migration.

**Reason:** Relational constraints and a conditional upsert provide strong duplicate and stale-data
protection.

**Mitigation:** Keep the original record in `raw_payload` JSONB so unmapped data is not lost.

**Revisit if:** Most useful data no longer fits the relational columns.

### T-004: At-least-once processing

- **Date:** 2026-07-31
- **Status:** Accepted
- **Related:** [ITD-002](./decisions/ITD-002-database.md)

**Choice:** Allow retries and repeated delivery instead of trying to provide end-to-end
exactly-once processing.

**Downside:** The same student may be read and submitted to the database more than once.

**Reason:** Exactly-once delivery across Blob Storage, an external API, and PostgreSQL would need
more coordination and still would not remove every failure case.

**Mitigation:** The database has one row per `student_id` and updates it only when the incoming
`updated_at` is newer. Repeating the same input changes no rows.

**Revisit if:** None. Idempotent writes are the permanent control for repeated delivery.

### T-006: Strict validation creates more quarantine

- **Date:** 2026-07-31
- **Status:** Accepted
- **Related:** [ITD-005](./decisions/ITD-005-bad-record-policy.md)

**Choice:** Quarantine the whole record when any field fails validation.

**Downside:** More records need operator review than in a pipeline that guesses or fills invalid
values.

**Reason:** A guessed value can hide source problems. A guessed `updated_at` can also let old data
replace new data.

**Mitigation:** Every rejection has a machine-readable reason. Monitoring alerts on an unusual
quarantine increase.

**Revisit if:** Valid production records are rejected regularly because a rule does not match the  
real source.

