# ITD-007: CSV trigger strategy

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Project team

## Context

CSV files arrive in the `landing` container. They can be copied there directly or uploaded through
the simple HTTP endpoint. Processing is still scheduled, not near-real-time.

Flex Consumption can react to new blobs through Event Grid. A timer can instead scan `landing` on
a configurable schedule. Both choices still need database claims because either trigger can
process the same file more than once.

## Recommendation Options

1. **Stage files in `landing`, then scan with a timer trigger — selected**
2. Use an Event Grid blob-created trigger
3. Process CSVs synchronously inside an HTTP upload endpoint

## Decision

Use `CSV_SCHEDULE_CRON` to scan `landing`.

Files may reach `landing` by direct Blob upload or by `POST /api/csv/upload`. The HTTP endpoint
only stores the file; it does not validate, transform, or write database records.

For each blob version, the timer job claims a unique `(source, source_object_id, source_version)`
record before processing. Completed or active versions are skipped.

This directly meets the configurable schedule requirement. The expected workload is a small number
of daily files, so immediate reaction to file arrival has little value. A scheduled batch window
also gives the vendor time to finish uploads, retries, and same-day corrections before processing
starts.

### Why not the others

**Event Grid:** It provides lower latency, but adds trigger configuration and still needs the same
duplicate-processing protection. It can also turn repeated uploads or corrections into repeated
processing attempts. The timer scan batches those changes into one predictable processing window.

**Synchronous HTTP processing:** It adds cold-start sensitivity and makes users wait for validation
and database writes. The upload endpoint is safe because it only stages the CSV into `landing`.

## Consequences

- A file waits until the next scheduled scan.
- Every scan lists the files currently in `landing`.
- If no new CSV exists, the scan logs success with zero processed files and makes no data changes.
- Each download must match the ETag found by the scan. A changed file fails without stopping other
files and is retried as a new version on a later scan.
- No Event Grid subscription is required.
- The upload endpoint is an intake convenience, not a processing trigger.

## Revisit if

- files must be processed within minutes of arrival; or
- `landing` regularly contains enough files that listing it becomes slow or expensive.
