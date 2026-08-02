---
name: evaluate-project
description: Runs an independent, evidence-backed end-to-end evaluation of this student data ingestion project against technical_challenge_cloud.pdf, scoring the six official criteria (architecture, data correctness, cloud readiness, reliability, scalability, maintainability) out of 100. Use when the user asks to evaluate, grade, score, audit, or assess the project, check submission readiness, or verify the claims in docs/TEST_RESULTS.md.
disable-model-invocation: true
---

# Project Evaluation

Evaluate the project at `D:\Data_ingestion` against `technical_challenge_cloud.pdf`.

Act as an independent principal engineer reviewing a submission: data platform, Azure, PostgreSQL,
security, and test quality. Be honest. Do not flatter, do not nitpick. Read-only — change no files.
Return the report in your reply; create no new files.

## Non-negotiables

- The PDF is the only source of requirements. Score challenge fit, not personal preference.
- Verify before believing. Docs, comments, and `docs/TEST_RESULTS.md` are claims, not proof.
- `terraform validate` is not a deployment. Local emulation is not Azure.
- A green pytest run with skipped DB tests is not a full pass. Report skips explicitly.
- Existence of a file, test, or Terraform resource earns nothing. Check that it works and is wired in.
- Do not require what the PDF does not: no Kubernetes, no queues, no `.xlsx` parsing.
- Never print `.env` contents, DSNs, keys, or tokens. Never run `terraform apply` or the deploy workflow.
- Evaluate the current working tree (including untracked files), and say so. Record branch + commit.

## Evidence labels

Tag every material claim: **VERIFIED** (fresh command output), **IMPLEMENTED** (code at `path:line`,
not executed), **DOCUMENTED** (docs only), **MISSING**, **BLOCKED** (state the blocker).

Findings use: observation → evidence (`path:line` or command output) → impact → recommendation →
acceptance test. No claim without an anchor.

## Steps

**1. Requirements.** Read `technical_challenge_cloud.pdf`. Extract the 5 core requirements, the
cloud hosting requirement, the expected deliverables, and the 6 evaluation criteria. Record
`git status --short --untracked-files=all`, branch, and commit.

**2. Code.** Read all of `src/`, `src/ingest/`, `triggers/`, `db/`, `infra/`, `.github/workflows/`,
`samples/`, `function_app.py`, `host.json`, `pyproject.toml`, `.env.example`. Trace end to end:
CSV upload/scan → chunked parse → validate → transform → quarantine → conditional upsert; API auth →
pagination → retry/`Retry-After` → watermark; run claims, checkpoints, ETag archival, structured
logs, alerts, CI/deploy ordering, managed identity, RBAC, Key Vault. Check failure paths, not just
happy paths.

**3. Tests.** Read `tests/conftest.py` first, then every test file. Build a requirement-to-test map:
malformed CSV, invalid email, missing fields, wrong types, duplicate `student_id` within and across
chunks/files, deterministic transform, idempotent upsert, older-update-loses, quarantine + batch
continues, interrupted-run resume, API pagination shapes, 401 refresh, 429/5xx retry, large batch,
migrations, upload guards. Judge assertion strength and mock realism. Test count is not quality.

**4. Run.** Execute and record exact output, exit codes, and pass/fail/skip counts:

```powershell
python -m pytest --collect-only -q
python -m pytest -ra
python -m ruff check .
python -m black --check .
terraform -chdir=infra fmt -check -recursive
terraform -chdir=infra init -backend=false
terraform -chdir=infra validate
```

Determine whether the ~32 PostgreSQL-backed tests actually ran or skipped, and name the exact skip
condition in `tests/conftest.py`. Run them if a local PostgreSQL is available per `docs/DEPLOY.md`;
otherwise mark DB runtime verification BLOCKED. Separate environment failures from real assertion
failures. Note that `docs/DEPLOY.md` and `docs/TEST_RESULTS.md` disagree on the test DB port.

**5. Reconcile recorded test results.** `docs/TEST_RESULTS.md` claims 149 passed / 0 skipped /
0 failed plus 9 named scenarios (messy Excel-exported CSV, wrong file in landing, real-world grade
values, bad/future dates, cross-chunk duplicates, API response shapes, 50k-row batch, quarantine
re-run, CSV-only guards) and manual CSV/API runs. For each: find the test that backs it, confirm it
asserts what the doc says, and label it VERIFIED / IMPLEMENTED / DOCUMENTED / contradicted. Also
check whether the "all 98" test-count comment in `.github/workflows/ci.yml` is stale.

**6. Docs.** Read `README.md`, `docs/ARCHITECTURE.md`, `docs/DEPLOY.md`, `docs/SCALING.md`,
`docs/TRADEOFFS.md`, `docs/LEARNINGS.md`, `docs/decisions/README.md`, and every `ITD-*.md`. For each
significant claim: matches / partially matches / stale / contradicted. Check that the diagram matches
real flow, setup steps are reproducible, assumptions are explicit, ITDs name real alternatives and
consequences, trade-offs have mitigations and revisit conditions, scaling claims match the actual
sequential execution model, and operational notes cover retries, idempotency, alerting, and
reprocessing. List every document you read.

## Scoring

Score each of the PDF's six criteria 0–10 in 0.5 steps; equal weight (state that equal weighting is
your method, not the PDF's). Overall = sum / 60 × 100.

Anchors: 2 = token effort; 4 = prototype with real correctness gaps; 6 = credible challenge baseline;
8 = strong, production-minded, well verified locally; 10 = exceptional with no material gap.

| Criterion | Judge |
|---|---|
| Architecture | Separation of ingest / validate / transform / persist / monitor; CSV+API reuse; thin triggers; Azure-free testability; failure-path design |
| Data correctness | Field/type/email rules, duplicate handling, deterministic transforms, timestamp and timezone policy, constraints and indexes, idempotent upsert, no stale overwrite |
| Cloud readiness | Service fit, configurable schedules, managed identity and least privilege, Key Vault, complete and deployable Terraform, CI/CD ordering, monitoring — and the gap between "deployable" and "proven in Azure" |
| Reliability | Retry classification, backoff + jitter + `Retry-After`, pagination loop guards, quarantine with reason codes, one bad record never fails a batch, claims/leases/checkpoints/watermarks, ETag concurrency, correlation IDs and counters |
| Scalability | Streaming vs full load, bounded chunks and pages, bulk writes, indexing, memory and connections, large-batch evidence, sequential bottlenecks, growth path without redesign |
| Maintainability | Module boundaries, readability, config design, test organization, CI quality, doc accuracy and freshness, explicit assumptions, ease of adding a source or rule |

Per criterion give: score, confidence, verified strengths, confirmed defects, unverified risks, and
what would move it up one point.

## Findings

Severity: **P0** data loss / security exposure / unusable · **P1** missing core requirement or likely
production failure · **P2** material weakness, fix before production · **P3** polish. Do not inflate.

Group the plan into: before submission → before first Azure deploy → before production → later,
triggered by measured need.

## Report order

1. Verdict and overall score /100
2. Six criterion scores
3. Readiness: Ready / Ready with gaps / Not ready
4. Scope: branch, commit, working-tree state
5. Commands run, actual results, and what stayed BLOCKED
6. Core requirements and deliverables compliance
7. Six-criterion detail
8. Test suite assessment + requirement-to-test map
9. `docs/TEST_RESULTS.md` reconciliation
10. Cloud, security, deployment, operations
11. Docs, ITDs, trade-offs, assumptions
12. Prioritized findings
13. What is genuinely good
14. Ordered improvement plan
15. Scoring math and confidence

Close with: the 3 strongest parts, the 3 most important fixes if present, the single highest-risk unverified assumption, and whether the score reflects the implementation, its verification maturity, or both.

Before sending, re-check that no passing, failing, skipped, blocked, or documentation-only state has
been misrepresented.
