# ITD-008: CI/CD deployment strategy

- **Status:** Accepted
- **Date:** 2026-08-01
- **Deciders:** Project team

## Context

Infrastructure, database changes, and function code must be deployed in the correct order.
Manual deployment makes it easy to skip a migration, role grant, or configuration step.

The repository is hosted on GitHub. CI/CD also needs secure Azure authentication.

## Recommendation Options

1. **GitHub Actions with Azure OIDC authentication — selected**
2. GitHub Actions with a stored service-principal secret
3. Azure DevOps Pipelines
4. Keep deployment manual

## Decision

Use GitHub Actions. Authenticate to Azure through an OpenID Connect (OIDC) federated credential.
GitHub exchanges a short-lived identity token for an Azure token during each run. No long-lived
Azure client secret is stored in GitHub.

OIDC needs one manual setup: create the Azure app registration, add the federated credential for
this repo/branch, and assign its Azure roles. After that, each workflow run logs in automatically
with short-lived tokens.

The workflows have separate jobs with a fixed order:

1. `ci.yml` checks formatting, lint, tests, and Terraform validation without Azure access.
2. `deploy.yml` applies Terraform, grants the Function App database role, runs pending migrations,
   and then publishes the function code.

Each deployment job depends on the previous job. Code is not published before its infrastructure
and schema are ready.

## Why not the others

**Stored service-principal secret:** It works, but creates a long-lived credential that must be
protected and rotated.

**Azure DevOps:** It would add another platform when the repository and suitable CI/CD features
already exist in GitHub.

**Manual deployment:** It relies on people remembering every step and its order.

## Consequences

- New `db/NNN_*.sql` migrations run automatically after they merge to `main`.
- Terraform needs remote state so each run sees the last deployed state.
- Initial setup remains manual: create the state storage and configure Azure OIDC trust.
- The workflow is written and locally validated but has not yet run against a real Azure
  subscription.

## Revisit if

- another environment needs separate state and deployment rules; or
- the team needs approval gates or stricter environment protection.
