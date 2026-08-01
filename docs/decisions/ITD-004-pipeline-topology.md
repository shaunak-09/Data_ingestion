# ITD-004: Pipeline topology

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Project team

## Context

CSV and API records follow the same steps: validate, transform, and persist. Queues or a workflow
service could separate those steps, but the current workload is scheduled batch ingestion rather
than high-volume streaming.

The design already processes bounded chunks and stores checkpoints. It must also remain easy to
run and test without Azure.

## Recommendation Options

1. **Process each chunk in one job — selected**
2. Pass records between stages through a queue
3. Fan out chunks with Durable Functions

## Decision

Process one chunk at a time in a single job:

1. read;
2. validate and quarantine invalid rows;
3. transform valid rows;
4. write valid rows; and
5. save progress.

No queue or dead-letter queue is used. `ingest_run.last_chunk` stores progress so the next run can
resume after a failure.

This is the smallest design that meets the workload and reliability needs. It has one execution
path to understand and one path to test locally.

### Why not the others

**Queue between stages:** It would allow independent scaling and retries, but it adds another
Azure resource, another function, and another local dependency. Bounded chunks and checkpoints
already provide the recovery needed here.

**Durable Functions fan-out:** It adds orchestration state without a measured need for parallel
chunk processing.

## Consequences

- A technical failure stops the current run. The next run resumes from its saved chunk.
- Invalid records go to quarantine; they are not queue messages.
- Validation and persistence cannot scale independently.

## Revisit if

- one scheduled run cannot finish within its allowed window;
- records need independent retries that last across runs; or
- several consumers need the same ingested event.
