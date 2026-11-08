# AI usage safeguards

Only `/api/ai/explain` is gated. The normal calculator has no dependency on
Azure OpenAI or the quota store. Publishing this code does not provision Azure
resources or deploy the safeguards.

## Policy

- Three admitted AI requests in a rolling 60 seconds per normalized client IP.
- Twenty admitted requests per IP per UTC calendar day.
- Fifty admitted requests per app per UTC day, configurable through
  `AI_GLOBAL_DAILY_LIMIT` (1–1000). This is a usage ceiling, not a monetary budget.
- One global in-flight request. Excess requests return 429 immediately.
- At most 16,384 request bytes, ten options, five milestones. The paid endpoint
  also rejects unexpected fields, fractional pennies, extreme amounts and rates
  above 25%. The existing calculator model and its limits are unchanged.
- Existing 2,000 output-token cap remains. No real-model quality test was
  authorized/performed to justify lowering it. There are no automatic AI retries.

Each admission uses one ETag-conditional update of a single shared JSON blob.
Visitor counters, global counter and reservation change together. A 412 conflict
re-reads the state and retries, up to eight times; ambiguous writes fail closed.
Only admitted attempts count. Provider failures and timeouts are not refunded.
Repeated identical requests count too; explanation caching is not implemented.

The body middleware buffers at most 16 KiB before passing a request to FastAPI.
It checks both Content-Length and actual received bytes, including chunked bodies
and missing/misleading lengths. Compressed requests are rejected. Oversized bodies
return 413; invalid option counts and values return 422 before the model is called.

Reservations expire after 300 seconds and are renewed every 30 seconds while the
server-side model operation is running. A worker releases only its own ticket.
Daily reset does not erase live reservations or rolling-minute history. A crash
keeps quota consumption and temporarily blocks AI until its reservation expires.
A release failure also leaves the ticket to expire. If renewal failed, a successful
model answer is withheld with 503. Browser disconnects do not release ongoing work.

Provider 429 errors become 429 with bounded Retry-After (1–3600 seconds, default
30). The shared state records a provider cooldown for all visitors. Other provider
failures remain sanitized 503 responses. Storage/configuration/identity failures
block AI; there is no process-local fallback. React displays the retry time and
disables its AI button during the cooldown. Direct API calls use the same guard.

The existing HTTPX timeouts remain 5 seconds for connection and 40 seconds for
read/write/pool phases, not a hard end-to-end deadline. Expiry recovery cannot
guarantee cancellation of an already accepted provider generation after a process
crash or network failure. Conservative attempt accounting still bounds dispatches.

On App Service, the credential calls the documented local managed identity
REST endpoint with a 15-second socket timeout and no retries, proxies or
redirects. It caches tokens in memory per resource and refreshes them two
minutes before expiry. The Blob SDK retains its 3-second connect and 5-second
read limits with no SDK retries. Missing platform identity configuration
fails closed. Local development continues to use Azure Identity. The
calculator does not initialise these clients.

## Azure prerequisites for a later, separately approved deployment

1. Reuse a suitable existing Storage account, subject to its owner's approval.
   Create a dedicated private container; never share a quota blob with staging.
   Use Hot block storage and a single common blob name for all production workers.
2. Grant the app's managed identity Storage Blob Data Contributor at that container
   scope. The runtime does not create containers or use account keys.
3. Initialize the blob exactly once with the complete JSON below. Replace the date
   with the current UTC date. Missing, corrupt or incomplete state fails closed;
   runtime initialization would otherwise allow accidental daily quota resets.

```json
{"version":1,"day":"2026-11-06","used":0,"visitors":{},"active":{},"cooldown":0.0}
```

Do not overwrite/delete this blob during releases. Container RBAC includes delete
permission: operators must treat quota resets as deliberate administrative actions.

4. Configure the settings in `backend/.env.example`. Use the same stable random
   HMAC secret (at least 32 bytes) across all workers and restarts. Rotating that
   secret resets per-IP identity but does not reset the global quota. Do not use
   a predictable value. The runtime enforces a minimum length, not randomness.
5. Add `--no-proxy-headers` to the existing Uvicorn startup command. This is
   essential: this application must receive the actual TCP peer, rather than an
   address already rewritten from an untrusted header by the server.
6. Set `AI_TRUSTED_PROXY_CIDRS` to the verified App Service ingress peer(s). Do not
   trust every private address or every forwarded header. The app walks the chain
   right to left, skipping only trusted proxies; a spoofed prefix cannot replace
   the observed client appended by the trusted ingress. IPv4-mapped IPv6 and
   observed client ports are normalized. Missing/malformed chains and unknown
   production peers fail closed. Before rollout, verify this behaviour using
   direct requests and deliberately forged forwarding headers against the actual
   Azure ingress. No diagnostic endpoint should expose IPs or identity secrets.

Do not set `AI_QUOTA_CONNECTION_STRING` on App Service. Production requires
managed identity. The local connection-string path exists solely for Azurite.
Keep host clocks synchronized. UTC days avoid daylight-saving ambiguity.

The blob contains only HMAC IP identifiers, timestamps, counters and random
reservation IDs; no raw IPs, mortgage figures or model explanations. Old visitor
records are pruned on the next admitted UTC day (recent minute timestamps are
retained briefly). Storage diagnostics must not log request bodies or secrets.
Platform/web-server access logs may separately retain IPs under their own policy.

Anonymous IP limiting does not prove a person's identity: shared networks share
an allowance and network changes can evade per-IP quotas. The global ceiling is
the final model-usage bound. This is not a general DDoS or exact billing cap.
Aggressive rejected traffic may still incur Storage reads. The 128 KiB state-size
cap and bounded CAS retries fail closed rather than allowing unbounded state.

## Local verification

Install `backend/requirements.txt` in `.venv`. Start Microsoft's Azurite Blob
emulator (Node/npm is sufficient; Docker is optional):

```powershell
npm exec --yes --package=azurite -- azurite-blob --blobHost 127.0.0.1 --blobPort 10000 --location <local-test-data-directory> --skipApiVersionCheck
```

Then run the entire suite, including the Azurite integration tests:

Set `AI_AZURITE_CONNECTION_STRING` in your shell to your local emulator connection
string first. It must use HTTP, account `devstoreaccount1`, and the Blob endpoint
`http://127.0.0.1:10000/devstoreaccount1`. Do not commit the value. Tests validate
the endpoint before creating a container, so production accounts cannot be used.

```powershell
$env:AI_AZURITE_TESTS='1'
.venv/Scripts/python -m pytest -q
cd frontend
npm run lint
npm run build
```

Integration tests read emulator credentials from the environment and require the
fixed loopback endpoint. No connection string or emulator key is embedded in the
source. They create unique test containers and delete only those containers.
Tests include conditional-write races, UTC rollover, stale reservations and two
separately spawned Python/FastAPI processes with mocked model calls. Without the
opt-in environment variable, integration tests are explicitly skipped.

## Release and cost considerations

The only new direct backend dependency is `azure-storage-blob`. Include it and its
transitive dependencies when preparing the Linux release, as with Azure identity.
Do not install Windows native wheels into the Linux production package.

Reusing an account adds only a tiny blob and Storage transactions, not a new
fixed-price Azure service. At a 50-attempt/day ceiling, normal usage is roughly a
few thousand read/write operations monthly plus heartbeat, conflict and rejected
request traffic. Exact currency cost depends on account pricing and traffic;
large rejected floods can exceed that estimate. Existing B1 and model charges
continue. Azure budget alerts do not stop consumption.

For scale only: the public UK South Hot LRS retail meters checked on 6 November
2026 list USD 0.059 per 10,000 writes and USD 0.0047 per 10,000 reads. At 1,500
monthly admitted calls with one admission and one release each, roughly 3,000
writes plus 3,000 reads cost about USD 0.019, before heartbeats, rejected traffic,
conflicts, diagnostics and account-specific billing/FX. This is an estimate, not
a spending guarantee; roughly USD 0.10/month is a reasonable low-traffic planning
allowance for guard storage operations alone. See Microsoft's Blob pricing and
public Retail Prices API; model and App Service charges are excluded.

A later production deployment requires settings, container/RBAC setup and a
restart/code release. The current B1 plan has no zero-downtime slot guarantee.
Validate trusted proxy configuration before enabling AI. Keep the 2,000-token cap
until a small separately approved real-model evaluation supports reducing it.

## Troubleshooting a stalled AI request

Uvicorn emits AI stage records at INFO, and stage failures at WARNING. Search
for `AI trace=` to follow an anonymous request through body receipt, proxy
validation, SDK imports, managed identity, Blob reads and conditional writes,
quota admission, the model and the HTTP response. A stage with only a
`started` record identifies the last observed operation. The records include
stage names, durations, exception types and HTTP status codes. They omit
headers, addresses, quota contents, SDK exception messages and mortgage data.

For a production preflight, run a bounded Blob GET under the app's own
system-assigned identity before exercising the paid model. An Azure CLI read
under an operator identity does not test the app's access. Preserve the blob
and its ETag. During an AI smoke test, an unchanged ETag means no quota update
was committed, so check the body, proxy, SDK import, identity and Blob read
stages before investigating Azure OpenAI. A successful admission changes the
ETag before any model call. Use local Azurite and mocked calls to exhaust
quotas or run concurrent requests.

References:
- https://learn.microsoft.com/azure/storage/blobs/concurrency-manage
- https://learn.microsoft.com/azure/storage/common/storage-use-azurite
- https://azure.microsoft.com/pricing/details/storage/blobs/
