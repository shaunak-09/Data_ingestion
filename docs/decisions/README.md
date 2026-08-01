# Technical decision index

Each ITD records one important technical choice. If a decision changes, use a new number. Keep the
old record only when it still provides useful history.

## Index

| ID | Title | Status | Date |
|---|---|---|---|
| [ITD-002](./ITD-002-database.md) | Database and idempotent writes | Accepted (verified) | 2026-07-31 |
| [ITD-003](./ITD-003-compute-model-verified.md) | Compute model | Accepted | 2026-07-31 |
| [ITD-004](./ITD-004-pipeline-topology.md) | Pipeline topology | Accepted | 2026-07-31 |
| [ITD-005](./ITD-005-bad-record-policy.md) | Invalid-record policy | Accepted | 2026-07-31 |
| [ITD-006](./ITD-006-api-incremental-and-auth.md) | Incremental API ingestion and authentication | Accepted | 2026-07-31 |
| [ITD-007](./ITD-007-csv-trigger-strategy.md) | CSV trigger strategy | Accepted | 2026-07-31 |
| [ITD-008](./ITD-008-cicd-deployment-strategy.md) | CI/CD deployment strategy | Accepted | 2026-08-01 |

Add every new ITD to this table.

## When an ITD is needed

Write an ITD when:

- there are real alternatives with meaningful trade-offs;
- the choice affects architecture, reliability, security, cost, or operations; or
- a future maintainer is likely to ask why this option was chosen.

Do not write an ITD for naming, formatting, routine implementation details, or a choice already
required by project rules.

## Steps

1. Copy [`ITD-000-template.md`](./ITD-000-template.md) → `ITD-NNN-short-title.md`
2. Use the next unused number. Never reuse a number.
3. Bold the selected option.
4. Explain why the other options were rejected.
5. Add clear conditions under `Revisit if`.
6. Add the ITD to the index.
7. If facts or requirements change, use a new ITD number. Mark the old record as superseded only
   when its history is still useful. Never reuse its number.
