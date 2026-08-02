# Learnings

This file records mistakes that could be repeated. Keep each entry short and useful to future
work. Do not add normal progress notes.

## Entry format

```markdown
## L-NNN: Title
- **Date:** YYYY-MM-DD
- **Severity:** Low | Medium | High
- **Area:** Architecture | Data | Cloud | Reliability | Process | Docs

**Mistake:** What was wrong.
**Impact:** What problem it could cause.
**Signal:** What exposed the mistake.
**Correction:** What changed.
**Rule:** One instruction that prevents it next time.
```

If the rule should always apply, also add it to `AGENTS.md`.

---

## L-002: Used the wrong Azure Functions timeout

- **Date:** 2026-07-31
- **Severity:** Medium
- **Area:** Cloud

**Mistake:** The first compute comparison used classic Consumption limits for Flex Consumption.
It treated a 10-minute timeout as a major reason to avoid Functions.

**Impact:** The comparison overstated the timeout risk and could have caused an unnecessary move to
Container Apps Jobs.

**Signal:** A check against the current Microsoft Learn documentation showed that Flex Consumption
has a 30-minute default timeout and allows a higher limit. Container Apps Jobs also have a
configurable timeout.

**Correction:** [ITD-003](./decisions/ITD-003-compute-model-verified.md) now contains the verified
compute decision. The obsolete decision file was removed. Chunking remains a reliability measure
for retries, scale-in, and platform updates.

**Rule:** Verify cloud limits against current documentation for the exact service and SKU before
using them in a decision.

---



## L-003: Bind downloads to the claimed blob version

- **Date:** 2026-08-01
- **Severity:** High
- **Area:** Data

**Mistake:** CSV runs claimed an ETag but downloaded the blob by name without checking that ETag.

**Impact:** A vendor overwrite during processing could make a run read content different from the
version it claimed.

**Signal:** Review of the version claim and blob download paths showed that the ETag was not passed
to Azure Blob Storage.

**Correction:** CSV downloads now require the ETag found during the scan. A mismatch fails only
that file. Other files continue, and the new version can run on the next scan.

**Rule:** When work is claimed by object version, enforce that version on every object read.

---



## L-004: Bind archive moves to the claimed blob version

- **Date:** 2026-08-02
- **Severity:** High
- **Area:** Data

**Mistake:** CSV archive moves used the blob name but not the ETag claimed by the run.

**Impact:** A vendor overwrite after processing could move a newer, unprocessed blob to
`processed`.

**Signal:** Review of the completed-run path showed the download enforced the ETag but the archive
move did not.

**Correction:** Archive moves now require the scanned ETag for download and delete. On mismatch,
the committed run stays completed and the changed file remains in `landing`.

**Rule:** When work is claimed by object version, enforce that version on every object operation.

---



## L-005: Include chunk size in CSV resume identity

- **Date:** 2026-08-02
- **Severity:** High
- **Area:** Data

**Mistake:** CSV resume state stored `last_chunk` but the run identity did not include
`CHUNK_SIZE`.

**Impact:** Changing `CHUNK_SIZE` after a partial failure could skip rows that were never written.

**Signal:** Review of the resume loop showed it skips by chunk ordinal only.

**Correction:** CSV run identity now includes both blob version and chunk size. Changing the chunk
size starts a new run from chunk 1, and idempotent upserts make already-written rows no-ops.

**Rule:** Include any setting that changes checkpoint meaning in the checkpoint identity.

---



## L-006: Verify Terraform provider schema before using Flex-only attributes

- **Date:** 2026-08-02
- **Severity:** Medium
- **Area:** Cloud

**Mistake:** The plan assumed `azurerm_function_app_flex_consumption` supported
`key_vault_reference_identity_id`.

**Impact:** Terraform validation failed before deployment.

**Signal:** `terraform validate` returned `Unsupported argument` for the Function App resource.

**Correction:** The Function App now uses an AzAPI patch to set the ARM
`keyVaultReferenceIdentity` property.

**Rule:** Validate the locked provider schema before relying on Flex Consumption attributes.

---

## L-007: Real-data tests exposed policy gaps

- **Date:** 2026-08-02
- **Severity:** Medium
- **Area:** Data

**Mistake:** Some real source-data edge cases had no explicit policy.

**Impact:** Undefined edge cases can silently change data, block real updates, or confuse operators.

**Signal:** Real-data tests covered fractional grades, future dates, API `null` items, duplicate
CSV headers, wrong-schema files, and unsupported upload types.

**Correction:** Decimal grades are rejected, future dates quarantine, uploads and landing scans are
CSV-only, API `null` items are intentionally dropped, and duplicate CSV headers use the last value.
Remaining details are documented in [`docs/TEST_RESULTS.md`](./TEST_RESULTS.md).

**Rule:** Real-data edge cases need an explicit policy before implementation changes.

