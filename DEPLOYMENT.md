# Deployment Guide

Finance Controller has two deployable services:

- the Python/FastAPI API, which runs reconciliation and owns workflow state;
- the React web app, which calls the API from the user's browser.

The supplied `compose.yaml`, `Dockerfile.api`, and `web/Dockerfile` are the
reference container setup.

## Local container validation

```bash
docker compose up --build
```

Open <http://localhost:3000> and verify <http://localhost:8000/api/health>.

## Hosted deployment

1. Deploy `Dockerfile.api` to a persistent container service.
2. Attach a persistent volume at `/app/results`.
3. Run exactly one API replica while SQLite is used.
4. Set `FINCTRL_ALLOWED_ORIGINS` to the final HTTPS web origin.
5. Deploy `web/Dockerfile` with build argument `NEXT_PUBLIC_API_URL` set to the
   public HTTPS API URL. This value is compiled into the browser bundle.
6. Put provider and Razorpay Test Mode credentials in the platform's secret
   store, never in the image or repository.
7. Add HTTPS, access logs, health checks, resource limits, alerting, and backups.

Example build:

```bash
docker build -f Dockerfile.api -t finance-controller-api .
docker build -f web/Dockerfile \
  --build-arg NEXT_PUBLIC_API_URL=https://api.example.com \
  -t finance-controller-web .
```

The multiline command uses POSIX shell syntax. In PowerShell, place the command
on one line or use PowerShell backticks.

## Minimum environment configuration

API:

```dotenv
FINCTRL_ALLOWED_ORIGINS=https://finance.example.com
FINCTRL_MODEL_PROVIDER=none
```

Web build:

```dotenv
NEXT_PUBLIC_API_URL=https://api.example.com
```

For hosted explanations, add one provider key as documented in the README. The
API key belongs only on the API service. Never expose it through a `NEXT_PUBLIC_`
variable.

## Capacity and cost shape

The reconciliation workload is CPU-bound and batch-oriented; the web service is
lightweight. A small always-on CPU API plus a static/small web container is
enough for a simulation pilot. A hosted language model removes the GPU cost and
is called only when a user asks a question. Exact prices and free quotas change,
so size and price against the chosen platform immediately before launch.

Track these cost drivers:

- API uptime, CPU, and persistent-disk size;
- batch frequency and largest candidate component;
- web hosting/egress;
- AI explanation requests and token volume; and
- log and backup retention.

## Production gap checklist

Do not introduce real financial data until the organization has implemented and
reviewed:

- identity, SSO/MFA, role-based authorization, and separation of duties;
- tenant isolation and row-level access controls;
- a managed database with migrations, concurrency control, and point-in-time
  recovery;
- encrypted source-object storage and managed key rotation;
- immutable/tamper-evident audit retention;
- approved bank and ERP connectors with retry and completeness controls;
- observability, alerting, incident response, disaster recovery, and SLAs;
- privacy, data-residency, retention, and vendor-processing policies;
- penetration testing and dependency/image scanning; and
- independent accounting validation of journal mappings and close procedures.

The current repository is suitable for demonstration, evaluation, and a
simulation-only internal pilot. It is not a production accounting system.
