# ITD-005: Invalid-record policy

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Project team

## Context

CSV and API records can have missing, malformed, or invalid fields. The pipeline needs one
predictable rule for both sources. One bad record must not stop a batch.

## Recommendation Options

1. **Quarantine the whole record when any validation rule fails — selected**
2. Reject required-field errors but fill optional fields with defaults
3. Guess or replace invalid values and keep the record

## Decision

Quarantine a record when any field fails validation. This includes invalid email addresses and a
missing or unparseable `updated_at`.

Each rejected record stores the original data and one stable, machine-readable `ReasonCode`. The
batch continues with the remaining records.

This policy avoids silent data changes. It is especially important for `updated_at`, which decides
whether a database row may be updated. Guessing that value could let older data replace newer
data.

Blank values are allowed only where the schema explicitly permits them. That rule belongs in the
normal transform, not in an error fallback.

### Why not the others

**Fill optional fields with defaults:** A default can change the meaning of the source data and
hide an upstream issue.

**Guess or replace invalid values:** Ambiguous values are not safe to invent. A wrong timestamp can
break the stale-write protection from [ITD-002](./ITD-002-database.md).

## Consequences

- Strict validation creates more quarantined records than a lenient policy.
- Every validation rule needs a clear `ReasonCode`.
- Operators reprocess data by fixing the source and submitting it again.

## Revisit if

- valid production records are quarantined often because a rule does not match the real source; or
- a field gains a documented, always-safe default.
