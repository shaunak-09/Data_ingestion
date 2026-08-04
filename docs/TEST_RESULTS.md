# Test Results

Run date: 2026-08-05.

Verified after this update:

- `python -m pytest`: 154 passed, 0 skipped, 0 failed.
- `python -m ruff check .`: passed.
- `python -m black --check .`: passed.

## How to Reproduce

```powershell
python -m pytest
python -m ruff check .
python -m black --check .
```

`pytest` also runs the database tests automatically, using the `PG_HOST`, `PG_PORT`, `PG_USER`,
`PG_PASSWORD`, and `PG_SSLMODE` already in `.env` — no extra setup needed. It connects to the
`postgres` maintenance database and creates/drops a scratch database named `students_test`.

Only set `PG_TEST_DSN` to point tests at a different PostgreSQL server than the one in `.env`:

```powershell
$env:PG_TEST_DSN = "postgresql://postgres:<password>@localhost:5433/postgres"
```

## Manual End-to-End Runs

Recorded from the local database path before the automated scenarios below existed.

- **CSV run:** `samples/students_valid.csv` — 1 file, 5 read, 5 valid, 0 quarantined, 5 inserted.
  A row with empty `grade_level` and `guardian_contact` was accepted; both fields are optional.
- **API run:** mock API — 1 page, 5 read, 4 valid, 1 quarantined (bad email), 2 inserted, 1
  updated, 1 skipped as older than the stored record. The watermark moved forward.

## Automated Scenarios

### 1. Messy CSV From Excel

**Input:** `samples/students_excel_export.csv` with CRLF endings, quoted commas, a quoted line
break, blank rows, extra spaces, accented names, reordered columns, and duplicate `email` headers.

**Expected:** 3 valid students, no quarantine, no data lost to commas/line breaks/accents/headers.

**Result:** Passed. Produced `S9001`, `S9002`, `S9003` with all values intact.

**Recommended change:** Done — duplicate CSV headers use the last matching value (policy).

### 2. Wrong File Dropped In Landing

**Input:** `samples/students_valid.csv` and `samples/students_wrong_schema.csv` (a teacher export
with no student columns) scanned together.

**Expected:** The good file loads; every teacher row is quarantined; the run still completes.

**Result:** Passed. 5 students written from the good file; 2 teacher rows quarantined with
`MISSING_REQUIRED_FIELD`.

**Recommended change:** Partly done. The upload API now rejects unsupported file types before
`landing`. Direct blob drops still quarantine row-by-row — add a file-level "wrong export type"
alert later if operators need one.

### 3. Grade Values From Real Systems

**Input:** `10.0`, `9.5`, `09`, `TK`, `Grade 9`, `9th`, `-2`, `999`.

**Expected:** Current behavior is pinned so future changes are intentional.

**Result:** Passed. `10.0` → `10`, `09` → `9`, unsupported labels rejected, `9.5` rejected
(not truncated).

**Recommended change:** Done — non-integer decimal grades are invalid.

### 4. Bad And Future Dates

**Input:** Unix epoch number, `2026-13-45`, ISO timestamps with offsets, `2099-01-01T00:00:00Z`, a
later real update (`2026-08-01T00:00:00Z`), and slash dates like `03/04/2026`.

**Expected:** ISO timestamps parse and normalize to UTC. Bad, future, and non-ISO dates quarantine.

**Result:** Passed. Invalid and non-ISO dates quarantined, timezone offsets normalized, and the
later real update landed.

**Recommended change:** Done — source timestamps use ISO 8601 UTC only.

### 5. Duplicate Students Across Chunks And Files

**Input:** Duplicate `student_id` values across chunks and files, with an older copy arriving
second.

**Expected:** The database ends with the newest record; older copies never overwrite newer ones.

**Result:** Passed. `S5001` ended as `New`, `S5002` ended as `Newer`, the older copy was skipped.

**Recommended change:** None required. Add metrics later if cross-file duplicate frequency needs
monitoring.

### 6. Other API Response Shapes

**Input:** API bodies using `data`, `students`, `items`, `results`, a top-level list, a `null`
item, and a nested `profile` object.

**Expected:** Supported list shapes are read; nested objects stay in the source record.

**Result:** Passed. All supported shapes read correctly; `null` items dropped before validation.

**Recommended change:** None. Dropping API `null` items is accepted policy.

### 7. Large Batch Load

**Input:** 50,000 generated CSV rows (`large_batch.csv`), `chunk_size=5000`.

**Expected:** 10 chunks, 50,000 read/valid/inserted, 0 quarantined.

**Result:** Passed. All counters matched; database ended with 50,000 rows.

**Recommended change:** None required. Keep as a database test to cover chunking and bulk upsert.

### 8. Re-Running Quarantine

**Input:** The same bad chunk written twice for `run_id=42`, `chunk_index=3`.

**Expected:** One deterministic JSONL path is reused; the second write overwrites the first.

**Result:** Passed. Only `csv/42/chunk-00003.jsonl` existed, with content from the second write.

**Recommended change:** None required. Add retention rules later only if quarantine history must
keep every retry.

### 9. CSV-Only Input Guards

**Input:** Multipart uploads for `.csv`, `.xls`, `.xlsx`, `.pdf`, `.png`, `.docx`, `.txt`, and a
file with no extension; `landing` also seeded with `.xlsx`, `.pdf`, `.png`, `.docx`, and a
folder-like path.

**Expected:** `.csv` uploads accepted; other types rejected with a clear "export as CSV" message;
the scheduled CSV job only processes `.csv` objects from `landing`.

**Result:** Passed. CSV uploads accepted (including Excel-exported CSV MIME type); unsupported
uploads rejected with type-specific messages; unsupported objects in `landing` left untouched.

**Recommended change:** Done — uploads and landing scans are CSV-only until native Excel parsing
is implemented.

## Findings

- Native Excel workbooks are not supported; export them to CSV first.
- API `null` items are intentionally dropped before validation.
- Direct blob drops with the wrong schema quarantine row-by-row, not as one file-level error.

## Totals From This Run

- `python -m pytest`: 154 passed, 0 skipped, 0 failed.
- Database tests ran using local `.env` PostgreSQL settings.
- `python -m ruff check .`: passed.
- `python -m black --check .`: passed.
