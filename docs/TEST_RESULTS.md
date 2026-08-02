# Test Results

Run date: 2026-08-02.

Verified after this update:

- `python -m pytest`: 149 passed, 0 skipped, 0 failed.
- `python -m ruff check .`: passed.
- `python -m black --check .`: passed.

## How to Reproduce

Run unit and non-database tests:

```powershell
python -m pytest
python -m ruff check .
python -m black --check .
```

Run database tests too:

```powershell
$env:PG_TEST_DSN = "postgresql://postgres:<password>@localhost:5433/postgres"
python -m pytest
```

Or put `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, and `PG_SSLMODE` in `.env`. Pytest loads
`.env` and builds the test DSN if `PG_TEST_DSN` is not set.

Database tests need a writable local PostgreSQL server. The fixture connects to the `postgres`
maintenance database, then creates and drops `students_test`.

## Manual End-to-End Runs

These runs were recorded from the local database path before the automated scenarios were added.

- CSV run: `samples/students_valid.csv`, 1 file, 1 chunk, 5 read, 5 valid, 0 quarantined,
  5 inserted. The row with empty `grade_level` and `guardian_contact` was accepted because both
  fields are optional.
- API run: mock API, 1 page, 5 read, 4 valid, 1 quarantined for a bad email, 2 inserted,
  1 updated, 1 skipped as older than what was already stored. The watermark moved forward.

## Automated Scenarios

### 1. Messy CSV From Excel

Input: `samples/students_excel_export.csv`, rewritten in the test with CRLF line endings.
It includes quoted commas, a quoted line break, blank rows, extra spaces, accented names,
changed column order, and duplicate `email` headers.

Expected result: 3 valid students, no quarantine records, values parsed without losing commas,
line breaks, accents, or the final `email` value.

Real result: Passed. The parser produced `S9001`, `S9002`, and `S9003`. The address line break,
accented names, grade values, and duplicate `email` header behavior matched the assertions.

Recommended changes: Done as policy. Duplicate CSV headers use the last matching header value.

### 2. Wrong File Dropped In Landing

Input: `samples/students_valid.csv` and `samples/students_wrong_schema.csv` in the same scan.
The wrong file is a teacher export with no student columns.

Expected result: The good file loads. Every teacher row is quarantined. The run still completes.

Real result: Passed. The good file wrote 5 students. The teacher file read 2 rows, wrote 0 rows,
and quarantined 2 rows with `MISSING_REQUIRED_FIELD`.

Recommended changes: Partly done. The upload API now rejects unsupported file types before they
reach `landing`. Direct blob drops still quarantine row-by-row; add a file-level schema reason later
if operators need a clearer "wrong export type" alert.

### 3. Grade Values From Real Systems

Input: `10.0`, `9.5`, `09`, `TK`, `Grade 9`, `9th`, `-2`, and `999`.

Expected result: The current behavior is pinned so future changes are intentional.

Real result: Passed. `10.0` became `10`, `09` became `9`, and unsupported labels were rejected.
`9.5` is now rejected instead of truncated.

Recommended changes: Done. Non-integer decimal grades are invalid.

### 4. Bad And Future Dates

Input: Unix epoch number, `2026-13-45`, mixed timezones, `2099-01-01`, then a later-arriving real
update for the same student with `2026-08-01`.

Expected result: Bad dates quarantine. Timezones normalize to UTC. Future timestamps quarantine
instead of blocking real updates.

Real result: Passed. Epoch and impossible dates were quarantined. Mixed timezones normalized to
UTC. A `2099-01-01` update was quarantined, and the later real update landed.

Recommended changes: Done. Timestamps more than one day ahead are invalid.

### 5. Duplicate Students Across Chunks And Files

Input: duplicate `student_id` values in different chunks, in different files, and with an older
copy arriving second.

Expected result: The database ends with the newest record. Older copies do not overwrite newer
ones.

Real result: Passed. `S5001` ended as `New`, `S5002` ended as `Newer`, and the older copy was
skipped.

Recommended changes: No required code change. Add metrics later if cross-file duplicate frequency
needs monitoring.

### 6. Other API Response Shapes

Input: API bodies using `data`, `students`, `items`, `results`, a top-level list, a `null` item,
and a nested `profile` object.

Expected result: Supported list shapes are read. Nested objects stay in the source record.

Real result: Passed. Supported shapes were read and nested `profile` was preserved. Confirmed
policy: a `null` list item is dropped before validation.

Recommended changes: No code change. Dropping API `null` items is accepted.

### 7. Large Batch Load

Input: 50,000 generated CSV rows written to local test storage as `large_batch.csv`, with
`chunk_size=5000`.

Expected result: 10 chunks, 50,000 read, 50,000 valid, 0 quarantined, 50,000 inserted.

Real result: Passed. All counters matched, and the database had 50,000 rows.

Recommended changes: No required code change. Keep this as a database test so chunking and bulk
upsert stay covered.

### 8. Re-Running Quarantine

Input: The same bad chunk written twice for `run_id=42`, `chunk_index=3`.

Expected result: One deterministic JSONL path is reused. The second write overwrites the first.

Real result: Passed. Only `csv/42/chunk-00003.jsonl` existed, and its content was from the second
write.

Recommended changes: No required code change. Add retention rules later only if quarantine history
must keep every retry.

### 9. CSV-Only Input Guards

Input: Multipart uploads for `.csv`, `.xls`, `.xlsx`, `.pdf`, `.png`, `.docx`, `.txt`, and a file
with no extension. The landing container also included `.xlsx`, `.pdf`, `.png`, `.docx`, and a
folder-like path.

Expected result: `.csv` uploads are accepted. Native Excel, PDF, image, Word, unknown, and
extensionless files are rejected with a clear "Export as CSV" message. The scheduled CSV job only
processes `.csv` objects from `landing`.

Real result: Passed. CSV uploads, including Excel-exported CSV MIME type, were accepted. Unsupported
uploads were rejected with type-specific messages. Unsupported objects already in `landing` were
left untouched and were not processed.

Recommended changes: Done. Both upload and scheduled landing scans are CSV-only until native Excel
parsing is implemented.

## Findings

- Native Excel workbooks are not supported. Export them to CSV first.
- API `null` items are intentionally dropped before validation.
- Direct blob drops with the wrong schema still quarantine row-by-row, not as one file-level error.

## Totals From This Run

- `python -m pytest`: 149 passed, 0 skipped, 0 failed.
- Database tests ran from local `.env` PostgreSQL settings.
- `python -m ruff check .`: passed.
- `python -m black --check .`: passed.
