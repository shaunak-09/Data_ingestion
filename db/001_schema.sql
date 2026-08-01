-- Canonical student store plus the two bookkeeping tables the pipeline needs.
-- Safe to re-run. Apply with:  psql "<conninfo>" -f db/001_schema.sql
--
-- The idempotency rule lives here, not in application code: `students.student_id` is the
-- primary key and every write is a conditional upsert guarded by `updated_at`
-- (see src/persist.py). Bulk loads stage into a session TEMP table and merge in one statement.

CREATE TABLE IF NOT EXISTS students (
    student_id        text        PRIMARY KEY,
    first_name        text        NOT NULL,
    last_name         text        NOT NULL,
    grade_level       smallint,
    school_id         text        NOT NULL,
    email             text        NOT NULL,
    enrollment_status text        NOT NULL,
    updated_at        timestamptz NOT NULL,
    guardian_contact  text,
    source_system     text        NOT NULL,
    raw_payload       jsonb       NOT NULL DEFAULT '{}'::jsonb,
    ingested_at       timestamptz NOT NULL DEFAULT now(),
    last_written_at   timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT students_grade_level_range
        CHECK (grade_level IS NULL OR grade_level BETWEEN -1 AND 12),
    CONSTRAINT students_enrollment_status_allowed
        CHECK (enrollment_status IN ('active', 'inactive', 'graduated', 'transferred', 'withdrawn'))
);

-- Reporting reads by school; the freshness index also supports incremental extracts.
CREATE INDEX IF NOT EXISTS students_school_id_idx ON students (school_id);
CREATE INDEX IF NOT EXISTS students_updated_at_idx ON students (updated_at DESC);
CREATE INDEX IF NOT EXISTS students_enrollment_status_idx ON students (enrollment_status);

-- High-water mark per API source. Advanced only after a whole API sync succeeds, so a
-- failure on a later page can never cause records to be skipped.
CREATE TABLE IF NOT EXISTS api_checkpoint (
    source     text        PRIMARY KEY,
    watermark  timestamptz NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- One row per unit of work (one CSV blob version, or one API sync). The unique constraint is
-- what stops the same blob version from being processed twice.
CREATE TABLE IF NOT EXISTS ingest_run (
    id               bigserial   PRIMARY KEY,
    source           text        NOT NULL,
    source_object_id text        NOT NULL,
    source_version   text        NOT NULL,
    correlation_id   text        NOT NULL,
    status           text        NOT NULL DEFAULT 'running',
    last_chunk       integer     NOT NULL DEFAULT 0,
    rows_read        bigint      NOT NULL DEFAULT 0,
    rows_valid       bigint      NOT NULL DEFAULT 0,
    rows_quarantined bigint      NOT NULL DEFAULT 0,
    rows_written     bigint      NOT NULL DEFAULT 0,
    error            text,
    started_at       timestamptz NOT NULL DEFAULT now(),
    completed_at     timestamptz,
    CONSTRAINT ingest_run_identity UNIQUE (source, source_object_id, source_version),
    CONSTRAINT ingest_run_status_allowed CHECK (status IN ('running', 'completed', 'failed'))
);

CREATE INDEX IF NOT EXISTS ingest_run_status_idx ON ingest_run (status, started_at DESC);
