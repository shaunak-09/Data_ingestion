# ITD-003: Compute model

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Project team
- **Verified:** 2026-07-31 against Microsoft Learn

## Context

The pipeline runs scheduled CSV and API jobs. It needs low idle cost, managed Azure services, and
plain Python logic that can be tested without Azure.

The exact hosting plan matters. Flex Consumption has different limits from classic Consumption.

## Recommendation Options

1. **Azure Functions Flex Consumption with Python — selected**
2. Azure Container Apps Jobs
3. Azure Data Factory or Synapse
4. Virtual machines or Azure Batch

## Decision

Use Azure Functions Flex Consumption with Python.

It provides configurable timer triggers, scale-to-zero billing, managed identity, Key Vault, and
Application Insights. Azure-specific code stays in thin trigger modules. The ingestion,
validation, transformation, and persistence code remains plain Python.

Microsoft documents these Flex Consumption limits:

- the default function timeout is 30 minutes and can be increased;
- scale-in gives running functions about 60 minutes to finish;
- platform updates give running functions about 10 minutes to finish; and
- available instance memory sizes are 512 MB, 2,048 MB, and 4,096 MB.

See [Azure Functions scale and hosting](https://learn.microsoft.com/en-us/azure/azure-functions/functions-scale)
and [Flex Consumption](https://learn.microsoft.com/en-us/azure/azure-functions/flex-consumption-plan).

Chunking and checkpoints are still required for safe retries and interruptions. They are not a
workaround for a 10-minute timeout.

### Why not the others

**Container Apps Jobs:** A strong alternative when container parity or host control is more
important. It needs a registry, image builds, and more infrastructure.

**Data Factory or Synapse:** Less suitable for custom API authentication, pagination, retry logic,
and local unit tests.

**Virtual machines or Azure Batch:** Too much operational work for a low-duty scheduled pipeline.

## Consequences

- Set `functionTimeout` explicitly.
- Process records in chunks and save progress.
- Keep Azure Functions imports out of `src/`.
- Accept cold starts because users do not wait for these batch jobs.
- CSV files are discovered by the timer scan chosen in
  [ITD-007](./ITD-007-csv-trigger-strategy.md), not by a blob trigger.

## Revisit if

- jobs are often interrupted despite checkpointing;
- Docker parity or host control becomes important;
- the system needs a low-latency synchronous API;
- an always-on container becomes cheaper; or
- Flex Consumption is unavailable in the required Azure region.
