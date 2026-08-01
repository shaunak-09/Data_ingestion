# ITD-006: Incremental API ingestion and authentication

- **Status:** Accepted
- **Date:** 2026-07-31
- **Deciders:** Project team

## Context

The challenge does not name a real vendor API. Pagination and authentication must therefore be
easy to adapt. The pipeline also needs retries, rate-limit handling, and incremental loads that do
not fetch every student on every run.

## Recommendation Options

1. **Use an `updated_at` watermark and a replaceable authentication interface — selected**
2. Fetch all records on every run
3. Put vendor-specific authentication inside the API client

## Decision

Store one watermark per API source in `api_checkpoint.watermark`. Send it as `updated_since` with
each request. Update the watermark only after the complete API run succeeds.

If a later page fails, the watermark stays unchanged. The next run can safely request the same
range again, while the database upsert prevents duplicate or stale writes.

Keep authentication behind the `ApiAuth` interface. The current
`OAuth2ClientCredentialsAuth` implementation:

- treats access tokens as opaque strings;
- caches a token until shortly before it expires;
- reads the lifetime from `expires_in`; and
- refreshes once after a `401` response.

This separates authentication from pagination. A different vendor can use an API key, mTLS, or
another token flow without changing the shared pipeline.

### Why not the others

**Fetch all records every run:** Its cost and duration grow with the full dataset instead of the
number of changes.

**Vendor-specific authentication in the client:** No vendor is known yet. Coupling auth to
pagination would make future integrations harder to test and replace.

## Consequences

- The sample contract uses `updated_since`, `page`, `page_size`, and `next` or `next_page`.
- A real vendor may require changes inside the API adapter.
- The strategy depends on a trustworthy vendor `updated_at` value.
- A new authentication method should be a new `ApiAuth` implementation.

## Revisit if

- the vendor provides webhooks instead of polling;
- `updated_at` is not a safe change marker; or
- another source cannot fit the current pagination or authentication interfaces.
