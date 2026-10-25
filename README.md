# Eluno POS — v1 till app

A till app that replaces Shopify POS in Eluno stores. Shopify stays the system of record: every order, payment transaction, refund and restock lands in Shopify through the Admin API. Prescriptions come from the store tool; cash till, invoice series, offers and day-end are owned here.

Python 3.8+, standard library only. No `pip install`.

## Run it

```bash
# terminal 1 - the mock Shopify Admin + store tool + payment terminal
python starter-kit/mock-apis/mock_server.py            # flaky: ~10% 429s, 30% terminal 503s
python starter-kit/mock-apis/mock_server.py --no-flake # calm

# terminal 2
python run_pos.py demo      # the whole Must flow, plus cash till and day-end
python run_pos.py test      # 91 unit tests, no network needed
```

The mock is in memory: restart it to reset Shopify. Local state (invoice series, till, audit log, pending-bill outbox) is in `state/`; delete `state/*.json` when you restart the mock, otherwise invoice numbers continue from the old run. (A fresh store always starts after the highest invoice already in Shopify, so seed numbers are never reused.) `ELUNO_MOCK_SERVER_URL` and `ELUNO_STATE_DIR` override the defaults.

## Commands

```bash
python run_pos.py lookup  --phone +919000000005
python run_pos.py lenses  --phone +919000000005 --type progressive        # only lenses that pass the Rx
python run_pos.py checkout --phone +919000000005 --store HSR --frame 91000003 --lens 91000083 \
                           --staff S105 --method upi --channel walk_in
python run_pos.py checkout ... --manager-discount 8 --approver S108 --reason-code WALKOUT_RISK
python run_pos.py refund  --order-id <id> --staff S105 --reason CHANGED_MIND            # full
python run_pos.py refund  --order-id <id> --staff S105 --lines <line_id>                # partial
python run_pos.py day-end --store JN --date 2026-10-06
python run_pos.py till open  --store HSR --staff S108 --float 3000
python run_pos.py till move  --session TILL-HSR-<date> --type paid_out --amount 120 --reason courier --staff S108
python run_pos.py till close --session TILL-HSR-<date> --staff S108 --counted 9327
python run_pos.py serve --port 8000  # optional HTTP API (see below)
python run_pos.py sync-pending       # replay paid bills that never reached Shopify
python run_pos.py bench --n 12       # time 12 bills against the mock (creates orders in the mock)
```

## What is built

**Must (all seven, end to end)**

| # | Requirement | Where |
|---|---|---|
| 1 | Customer by phone (Shopify) + latest *valid* Rx (store tool). Priority / campaign flags shown at billing | `PosService.lookup_customer_and_rx`, `Customer.billing_flags` |
| 2 | Lens validated against the Rx: sphere, cylinder, ADD presence and range, expiry, Rx belongs to this customer, cylinder needs an axis. Errors say what to do; `lenses` lists options that pass. Off-grid axis on an external Rx is a *warning* for the optometrist, not a block | `domain/rx_validator.py` |
| 3 | Offers from `offers.json`: dates, conditions, stackability, priority | `domain/offers.py` |
| 4 | GST per line by HSN, date-effective, backed out of the inclusive price, taxable + CGST + SGST = gross to the paisa | `domain/tax.py` |
| 5 | Charge the terminal, then create the Shopify order with line items, tax lines, discount allocations, sale transaction, Rx on the lens line, and the per-store invoice number in `note_attributes` | `PosService.checkout`, `ShopifyAdapter.build_order_payload` |
| 6 | Full (and partial) refund through Shopify's refund flow: tax reversed per line, frame restocked at the billing store, lens not restocked, refund transaction against the sale, credit note number referencing the invoice | `domain/refunds.py`, `ShopifyAdapter.create_refund` |
| 7 | Day-end for store + date from Shopify orders: bills, gross, taxable, tax, discounts, refunds, payment-method split | `PosService.generate_day_end_report` |

**Should (picked)**: cash till (float, sales, refunds, paid-in/out with reasons, counted close, variance, >₹200 flagged), sales channel on every order and a channel split in the day-end, partial refund, printable text invoice matching `sample_invoice.txt`, audit trail (who / what / when / reason code / ref, including manager-discount approver).

**Beyond the brief, because the thread asked for it**: manager discount capped at 10% that *requires* the approver's staff id (must be a manager of that store) and a reason code, both written to the Shopify order; invoice numbers that stay in the series as `cancelled` when payment fails.

## Optional HTTP API

`python run_pos.py serve` starts `pos/server.py` on `127.0.0.1:8000` (the brief allows a CLI or an HTTP API; the CLI is the primary interface). Endpoints: `GET /health`, `GET /api/customer?phone=`, `POST /api/checkout`, `POST /api/refund`, `GET /api/day-end?store=&date=`. **It has no authentication**, so it binds to localhost only and must not be exposed on a store network as is. It does not expose manager discounts, partial refunds or the till; those are CLI-only for now. It has one test (`/health`); the checkout/refund endpoints are only exercised through the service layer tests.

## Decisions worth knowing

- **Shopify is behind an adapter.** `domain/` and `services/` import nothing from Shopify. The adapter turns Shopify JSON into domain types (`OrderRecord`, `Variant`, `Customer`…) and domain types into payloads. The *decisions* (what restocks, what the refund is, what the invoice number is) are made in the domain; the adapter only translates. Replacing Shopify in 2027 means writing one class with the same methods (`ShopifyAdapter` is the full list). Honest leak: the domain keeps `inventory_item_id` / `location_id` as opaque ids.
- **Money is integer paise** everywhere (`Money` refuses floats; percentages use integer basis points with half-up rounding; flat cart discounts are split with largest-remainder so lines sum exactly). Decimal strings appear only in the adapters. Tax rates are basis points; the 0.09 Shopify wants is derived at the boundary.
- **Tax and offers are data.** `tax_rates.json` (with effective dates) and `offers.json`. New rates or offers need no code change. An unknown HSN or overlapping rate dates is an error, never silently 0%.
- **Offer semantics** (defined in `offers.py`): stackable offers combine, applied in `priority` order (lower first), each line capped at what is left on it. A non-stackable offer never combines. The engine compares "all eligible stackable offers together" against "each non-stackable offer alone" and picks the largest saving for the customer (ties → lower priority number). Every offer gets a row `{offer_id, applied, amount, why}` so staff and finance can see why. Discounts apply to the inclusive price *before* tax is backed out.
- **Invoice numbers** are gapless per store (`ELU/HSR/FY26/00007`), allocated right before the terminal charge, after all validation, so numbers are only burned by a failed payment, and those are kept as `cancelled`. Credit notes have their own series and record the original invoice. Shopify's `order_number` is never used.
- **Idempotency.** The invoice number is the key. The terminal charge is keyed by `order_ref = invoice_no`, so retrying a 503 cannot double-charge. Shopify order create is *not* idempotent, so: a 429 is always retried (the request was refused); a timeout / 5xx on the create is treated as *unknown outcome*, the adapter looks the invoice number up in Shopify before ever re-posting, and returns the existing order if it landed. Before any create the full payload is written to `state/pending_bills.json`; if Shopify is unreachable the customer still gets their bill (`status: pending_sync`) and `sync-pending` replays it safely. The same lookup protects refunds (credit note number).
- **Refund safety.** Before refunding, the POS computes the amount itself and compares to Shopify's `refunds/calculate`; a mismatch stops everything and nothing is refunded. A failed refund cancels its credit-note number and is audited.
- **Day-end source of truth is Shopify**, as Finance asked. The report also reads the local invoice register and till and prints a `MISMATCH:` line for: an invoice paid but not in Shopify, till cash sales / refunds that differ from Shopify cash orders, and a till variance over ₹200.
- **Expired prescription**: the lookup returns only a currently valid Rx; if there is none, lens billing is blocked with "book an eye test". No override in v1 (a clinical decision for Dr. Iyer to make).

## Tests (`python run_pos.py test`, 91)

Tax (paisa invariant, date-effective rates), money/rounding/allocation, offers (stacking, best combination, expiry, caps, manager rules), Rx validation (every block reason, grid warning), refunds (per-line tax, restock location, partial, double refund, mismatch guard, cash/till), resilience (429 Retry-After, 503 on idempotent vs non-idempotent calls, timeout-after-create does not duplicate, paid-but-offline bill syncs exactly once, declined payment leaves a cancelled number), invoice series, till variance, manager-discount audit rules, day-end totals and mismatch reporting. Also: four parallel processes issuing invoice numbers from one file get 60 unique, gapless numbers. Tests use temp state and mocks; they never touch `state/` or the network.

## Where I stopped, and known gaps

Must is complete. Not built:

- **Family billing** (one bill, three Rxs). The line model already carries `rx` per lens line, so the order shape works; the open question is whose customer record the order belongs to (Shopify has one customer per order) and how a partial refund of one family member is shown. Needs a decision from Retail + Finance. Today: bill each person in turn.
- **Remake flow** (₹0 lens-only order with `parent_invoice_no`, no frame line, no stock touched). Not built; the seed's remake order (#1009) is the template. Who bears the lab cost needs a rule from Dr. Iyer / Finance first.
- **Founder's 10 am email.** The day-end data exists as a function; scheduling + email is not built.
- **Cancel-after-sale** of an issued invoice (only payment-failed bills are cancelled).
- **Anomaly flags / offer authoring / Rx assist** (Stretch): none.
- **Several tills on one machine are safe; tills on different machines are not.** The invoice series and till files are guarded by a cross-process lock (`domain/filelock.py`, tested with 4 parallel processes issuing 60 numbers: unique and gapless). Two tills on *different* computers each have their own file, so they would issue the same numbers. Production needs one service (or a DB sequence) per store to allocate invoice numbers. This is the main thing to fix before a multi-till store goes live.
- **Never run against real Shopify.** Only the mock. The adapter is written to Shopify's REST shapes, and the mock is documented to match them, but auth (access token header), API version, real rate limits and `tax_lines` validation are untested. Needs a Shopify dev store and a token to confirm.
- **Idempotency lookup scans** the store's orders (`limit=250`). Production should use an indexed metafield / tag search; the invoice number is already in the order `tags` for that.
- **Day-end refunds** are attributed to the day the *order* was billed, not the day the refund was made, because the report is built from the day's orders. A refund-date view needs the refund list by date.
- **Day-end timezone** is fixed at +05:30. **Offers** support the shapes in `offers.json` (frame / lens / pair / cart, percent / flat, tag / lens / pairs conditions); a new rule *shape* needs code.
- **Manager identity is a staff id**, not a PIN or login. Production needs real auth so an id can't be typed by someone else.
- **Speed vs the 10-second target** (`python run_pos.py bench --n 12`, measured from the checkout call, i.e. "the customer said yes", to the finished invoice): average 0.05s against the calm mock; against the flaky mock (random 429s and terminal 503s, real retry sleeps) average 0.8s, worst 3.1s. These numbers exclude real store Wi-Fi latency and the customer's UPI/card approval time on the physical terminal, which will dominate. Each bill is about 6 round trips; catalog and locations are cached. On Windows use `127.0.0.1`, not `localhost` (the default now): `localhost` added about 2 s to every request here because of an IPv6 fallback, which made a bill take 4 s instead of 0.05 s.
- Tests do not run the mock; the demo and manual runs did, with flakiness on.

## Layout

```
STAKEHOLDER_REPLY.md   Part A
run_pos.py             entry point (demo, test, and every CLI command)
pos/domain/            money, models, tax, offers, rx_validator, refunds, invoice_series, till, audit  (no Shopify)
pos/adapters/          shopify_adapter (only place Shopify shapes exist), smt_adapter, terminal_adapter, http_client
pos/services/          pos_service (orchestration), invoice_formatter, outbox
pos/server.py          optional localhost HTTP API
tests/                 91 tests
starter-kit/           provided mock + seed data (unchanged)
```
#   e u r o -  
 