# AGENTS.md — Project Orchestrator

Read this before any change. It defines the project, the rules, and where to write things down.
`CLAUDE.md` points here. This file wins over generic defaults.

---

## 1. What this project is

Periodic student data ingestion for a school district.
Source of truth for requirements: `technical_challenge_cloud.pdf`.

On a configurable schedule the pipeline must:

1. Ingest CSV files from cloud storage
2. Ingest updates from an authenticated, paginated REST API
3. Validate fields, types, duplicates, emails, malformed rows
4. Transform both sources into one canonical student schema
5. Idempotently upsert valid records; quarantine invalid ones

Cloud: **Azure**. IaC: **Terraform**.

### Grading areas

| Area | Meaning |
|---|---|
| Architecture | Separate modules: ingest, validate, transform, persist, monitor |
| Data correctness | Strong validation, duplicates handled, deterministic transforms, idempotent writes |
| Cloud readiness | Managed services, least-privilege identity, Key Vault secrets, deployable IaC |
| Reliability | Retries with backoff, quarantine, observability, safe reprocessing |
| Scalability | Small daily files → large batches without redesign |
| Maintainability | Readable modular code, tests, docs, explicit assumptions |

---

## 2. Documentation writing rules

**All docs must be:**

- Simple language — no jargon unless needed
- Concise — short sentences, short paragraphs
- Clear instructions — say exactly what to do
- No fluff — no filler, no restating the obvious, no long explanations when a bullet will do

If a sentence does not help someone act or decide, delete it.

---

## 3. Documentation contract

Write docs **as work happens**, not at the end. Each file has one job.

| File | Put here | Write when |
|---|---|---|
| `docs/decisions/ITD-NNN-*.md` | One tech decision + options + why | You pick between real alternatives |
| `docs/TRADEOFFS.md` | Accepted downsides and deferred work | You knowingly accept a downside |
| `docs/LEARNINGS.md` | Mistake → signal → fix | Something was wrong and got corrected |
| `docs/ARCHITECTURE.md` | Current system shape and data flow | A component or flow changes |
| `README.md` | Setup, local test, deploy, runbook | Setup or run steps change |

### When to log

**ITD:** choice between real alternatives, or "why is it done this way?" would be asked later.
Do **not** write ITDs for naming or formatting.

**TRADEOFFS:** accepted downside, deferred production need, or simpler option chosen over fuller one.

**LEARNINGS:** reversed approach, bug/wrong assumption, or user correction. Log even small mistakes.

**ARCHITECTURE:** new component/queue/table/trigger/dependency, or data-flow change.

### ITD format (do not change)

```markdown
# ITD-NNN: <Title>

- **Status:** Proposed | Accepted | Superseded by ITD-NNN
- **Date:** YYYY-MM-DD
- **Deciders:** <who>

## Context
<What forced the choice?>

## Recommendation Options
1. **Option A — selected**
2. Option B
3. Option C

## Decision
<What was chosen and why.>

### Why not the others
<Each rejected option + specific reason.>

## Consequences
<What this commits us to.>

## Revisit if
<Measurable conditions that reopen this.>
```

Numbers are sequential and never reused.
Template: `docs/decisions/ITD-000-template.md`
Index: `docs/decisions/README.md` — always update it.

---

## 4. Engineering rules

1. **No secrets** in code, Terraform, state, or committed config. Key Vault + Managed Identity only.
2. **Idempotent writes.** Same input twice → zero net row changes. Never overwrite newer data with older (`updated_at`).
3. **One bad record never fails a batch.** Quarantine with a machine-readable reason.
4. **Configurable items stay configurable.** Schedules, endpoints, credentials from config.
5. **Testable without Azure.** Emulated storage + container DB + mock API.
6. **Retries:** exponential backoff + jitter; honour `Retry-After`.
7. **Structured logs.** Correlation ID, counts (read / valid / quarantined / written), duration.
8. **Verify cloud SKU limits from current docs** before writing them into an ITD. Do not reuse classic Consumption numbers for Flex Consumption (see L-002).

---

## 5. Working conventions

- Plan first. Use a TODO list for multi-step work.
- Smallest correct change. Reuse before creating.
- Fix linter errors you introduce.
- Comment only non-obvious intent. No narrating comments.
- Imports at the top of the module.

---

## 6. Definition of done

- [ ] Code works; no new linter errors
- [ ] Decisions logged as ITDs (or noted as not needing one)
- [ ] Compromises in `docs/TRADEOFFS.md`
- [ ] Mistakes in `docs/LEARNINGS.md`
- [ ] `docs/ARCHITECTURE.md` matches reality if components changed
- [ ] `docs/decisions/README.md` index is up to date
- [ ] New/updated docs follow the writing rules in §2

---

## 7. Repo layout

```
.
├── AGENTS.md
├── CLAUDE.md
├── README.md
├── technical_challenge_cloud.pdf
├── docs/
│   ├── ARCHITECTURE.md
│   ├── TRADEOFFS.md
│   ├── LEARNINGS.md
│   └── decisions/
│       ├── README.md
│       ├── ITD-000-template.md
│       └── ITD-NNN-short-title.md
├── src/
├── infra/
├── db/
├── tests/
└── samples/
```

Create `src/`, `infra/`, `db/`, `tests/`, `samples/` as implementation starts.
