# Costs and resource accounting

Open **Costs** in Studio to inspect charges by model, video or execution. The page refreshes every 15 seconds
while open. The initial period is the current month; **All history** removes the date limits. Dates and monthly
budgets use `TIMEZONE`, or the local timezone when it is unset. Stored timestamps use UTC.

## Charges and estimates

| State | Meaning |
|---|---|
| Confirmed | OpenRouter reported `usage.cost`, or the generation lookup returned the charge. Zero is a valid reported charge. |
| Estimated | Available consumption multiplied by the saved model price. The price applied to that call is retained. |
| Pending | An OpenRouter generation or video job identifier is available, but its charge has not arrived. |
| Not reported | No charge or usable estimate is available. This is an unknown amount. |
| No API charge | A local engine or free stock API was used. Hardware, electricity and subscriptions are outside this ledger. |

OpenRouter reconciliation runs in the background after Studio jobs and while Studio is open. **Refresh charges**
retries pending lookups, including calls that exhausted automatic retries. A confirmed charge replaces an estimate
in totals. Repeated lookups do not add another charge. Failed calls and paid invalid responses remain recorded.
Recording or lookup failures do not stop generation; the UI marks incomplete telemetry or unknown prices.

Under **Budgets & prices**, enter exact provider/model names from the ledger. Estimate prices support USD per
million input/output tokens, optional cache prices, per million characters, per image, per audio second and
per video second. Reasoning tokens are already part of output tokens and are not billed twice by the estimator.
Pricing changes apply to future calls. Original financial values are stored as integer nanodollars (10⁻⁹ USD)
and returned by the API as decimal strings.

## Video attribution

- Direct charges belong to one output. Shared charges are divided equally among completed outputs: transcript
  and selection for clips; original script and visuals for translated versions. Each version keeps its own voice cost.
- A draft has a persistent `usage_run_id` before its first model call. Studio retains this identifier when editing.
  Its charges are assigned to the first completed production from that draft. Later renders only add new calls
  and retain a reference to the reused script or source video.
- Planning charges are divided among the created ideas. Selecting an idea preserves its ID and transfers its
  share to the resulting video(s). Unused ideas, failed runs and unrendered drafts remain unassigned to videos.
- Global spending and budgets count each original charge once. Video totals show **Direct**, **Shared** and
  **Known total**, with an explicit warning for missing prices. Remainder allocation preserves every nanodollar.
- Deleting a video or an unused idea retains its financial records. Earlier videos display **Not recorded**;
  there is no retroactive cost reconstruction. Final speed changes output duration but does not reduce the
  resources that were generated.

The ledger also records requested and served models, call identifiers, retries as separate attempts, failures,
elapsed call/stage time, tokens and cached/reasoning tokens when provided, characters, images, audio/video seconds,
final MP4 size and retained artifact size. CPU/RAM sampling is not included. Provider responses determine which
metrics are available. Ledger records do not store API keys or request/response content.

## Budgets and BRL

Monthly budgets are always in USD. Set a total budget and optional provider/model budgets; leave a budget row's
model blank to include all models of that provider. Known confirmed and estimated costs count toward the budget.
Calls without prices make coverage incomplete. Alerts appear at 80% and 100%, are acknowledged persistently for
that month/scope, and never block production. BRL is an optional estimate using your manual rate; the rate and
date remain visible on the Costs page.

## HTTP API

| Route | Response or action |
|---|---|
| `GET /api/costs` | Summary, daily evolution, model breakdown, budgets and filter options. Defaults to current month; `all_time=1` uses all history. |
| `GET /api/costs/videos` | Paginated video attribution. |
| `GET /api/costs/events` | Paginated calls; `view=runs` groups executions, including runs with no calls. |
| `GET /api/videos/{id}/costs` | Lifetime details and stage attribution; retained after deletion. |
| `GET /api/costs/settings` | Budgets, model prices and optional exchange rate. |
| `POST /api/costs/settings` | Update `monthly_budget_usd`, `model_budgets`, `prices`, `brl_per_usd`. |
| `POST /api/costs/sync` | Start background reconciliation. |
| `POST /api/costs/alerts` | Persist acknowledgement of the displayed `alerts` array. |
| `GET /api/costs/export.csv` | Export filtered original calls, without pagination. |

Filters: `from` and `to` (inclusive local dates, YYYY-MM-DD), `provider`, `model`, `stage`, `status`, `cost_status`,
`run_id`. Pagination uses `page` (starting at 1) and `page_size` (1–100, default 25). Cost states use API values
`confirmed`, `estimated`, `pending`, `unknown`, `free`. Writes require the existing `X-Studio-Token` header.
Keys remain on the server. CLI and MCP calls write into the same configured SQLite history as Studio.
MCP `draft_script` returns `usage_run_id` inside its script JSON; pass the script or this identifier to `make_short`
to retain draft attribution.
