# Azure working baseline

One Linux Azure App Service runs FastAPI and serves the built React app.
React calls `/api/scenarios` on the same HTTPS origin. No browser requests
point to localhost in production. `/health` is the health endpoint and
`/api/status` identifies the API. No mortgage cases are persisted.

## Prerequisites

Azure CLI authenticated with `az login`, Node.js 24, and the local Python 3.14
virtual environment (`python -m venv .venv`, then
`.venv/Scripts/python -m pip install -r backend/requirements.txt`).
The subscription must permit a Linux Python 3.14 web app and the selected SKU.
The B1 default is a paid plan; confirm the subscription, region and SKU before provisioning.

## Deploy from PowerShell in the repository root

```powershell
./scripts/deploy-azure.ps1 -SubscriptionId '<subscription-id>' -ResourceGroup '<group>' -Location 'uksouth' -AppName '<globally-unique-app-name>'
```

The script installs frontend dependencies from the lockfile, builds React,
creates `artifacts/app.zip`, provisions the web app, enables HTTPS, configures
the explicit Uvicorn startup command, and deploys with Azure build automation.
Azure installs the root production requirements. No database, secrets, local
virtual environments, node_modules, or Git history are uploaded.
The script verifies the deployed frontend, API health and known calculation
answers; a failed check exits with an error. Inspect deployment logs if the
first startup has not finished and rerun the smoke check after it is ready.

```powershell
.venv/Scripts/python scripts/verify_deployment.py https://<actual-default-hostname>
```

## Local checks and development

```powershell
.venv/Scripts/python -m pytest -q
# Terminal 1
.venv/Scripts/python -m uvicorn backend.app.main:app --reload --port 8000
# Terminal 2
cd frontend
npm ci
npm run dev
```

Vite proxies `/api` to FastAPI for local development. To verify the production
layout locally, build React, restart FastAPI and visit port 8000.

## Calculation scope

Overpayments happen immediately; monthly payments and interest rate stay
constant until renewal. Interest is rounded to pennies each month. Property
value stays constant. No lender charges, savings interest, or future rate
quotes are modelled. LTV milestones use the balance and property value rather
than the displayed percentage rounded to two decimal places.

## Database decision

Azure SQL can be added when saving cases is required. Before storing financial
inputs, implement user authentication, per-user access, deletion and retention
rules; use App Service managed identity for database access. A database is not
needed for the current stateless calculations.

## Improvement and rollback

Keep a verified ZIP per release outside the repository. Re-deploy the previous
ZIP with `az webapp deploy` to roll back. This initial B1 setup has no staging
slot; deploy changes during an acceptable restart window. Promote to a plan
with slots when uninterrupted releases become necessary.

References: https://learn.microsoft.com/azure/app-service/quickstart-python
and https://learn.microsoft.com/azure/app-service/configure-language-python
