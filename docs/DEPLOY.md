# Deploy

This file lists what you must provide to run the pipeline locally or deploy it with CI/CD.

## Run Locally

Provide:

- Python 3.11+
- Local PostgreSQL
- `.env` copied from `.env.example`
- `PG_USER` and `PG_PASSWORD` in `.env`

Commands:

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements-dev.txt
copy .env.example .env
```

Edit `.env` and set `PG_USER` and `PG_PASSWORD`.

Then run:

```bash
psql -h localhost -U <PG_USER> -d postgres -c "CREATE DATABASE students;"
python -m src.cli init-db

mkdir .localstore\landing
copy samples\students_valid.csv .localstore\landing\
python -m src.cli csv
```

Run the API path:

```bash
python -m tests.mock_api.server  # terminal 1
python -m src.cli api            # terminal 2
```

Run tests:

```bash
python -m pytest
```

For database tests, also provide:

```bash
$env:PG_TEST_DSN = "postgresql://postgres:<password>@localhost:5433/postgres"
python -m pytest
```

If `.env` has `PG_HOST`, `PG_PORT`, `PG_USER`, `PG_PASSWORD`, and `PG_SSLMODE`, pytest loads it
and builds the test DSN automatically. It connects to the `postgres` maintenance database and
creates a scratch database named `students_test`.



## Deploy With GitHub Actions

Provide in Azure:

- An active Azure subscription.
- A Terraform state storage account and container. Put their names in `TFSTATE_*`.
- An Entra app registration for GitHub OIDC.
- A federated credential for `repo:<org>/<repo>:ref:refs/heads/main`.
- These roles for the app registration:
  - `Contributor` on the target subscription or resource group
  - `User Access Administrator` or `Owner` to create role assignments
  - `Storage Blob Data Contributor` on the Terraform state storage account
- A PostgreSQL admin security group with no spaces in its display name. Add the GitHub OIDC
service principal as a direct member. Use this group for `POSTGRES_ADMIN_OBJECT_ID`,
`POSTGRES_ADMIN_UPN`, and `POSTGRES_ADMIN_PRINCIPAL_TYPE=Group`.

Provide GitHub secrets:

- `AZURE_CLIENT_ID`
- `AZURE_TENANT_ID`
- `AZURE_SUBSCRIPTION_ID`
- `API_CLIENT_SECRET`

Provide GitHub variables:

- `TFSTATE_RESOURCE_GROUP`
- `TFSTATE_STORAGE_ACCOUNT`
- `TFSTATE_CONTAINER`
- `POSTGRES_ADMIN_OBJECT_ID`
- `POSTGRES_ADMIN_UPN`
- `POSTGRES_ADMIN_PRINCIPAL_TYPE`
- `ALERT_EMAIL`
- `API_BASE_URL`
- `API_TOKEN_URL`
- `API_CLIENT_ID`
- `API_CLIENT_SECRET_CONFIGURED`

Deploy:

```text
Push to main, or run Deploy manually from GitHub Actions.
```

The workflow does three things:

1. Applies Terraform.
2. Grants the Function App database role and runs pending `db/*.sql` migrations.
3. Publishes the Function App code.

