# Re: [Retail-Requirement] Replace Shopify POS in stores — live by 15 Nov

**To:** Rohan, Priya · **Cc:** Meena, Dr. Iyer, Vikram, Farhan

Thanks all. Here is what I will build for v1, what I won't, where your asks collide, and what I need from you. Shopify stays the system of record; the new app only replaces the screen at the till.

## 1. Questions (who, and why it matters for v1)

| To | Question | Why it matters |
|---|---|---|
| Vikram | If the customer has paid on the terminal but the Shopify order can't be created (Wi-Fi), is a bill that is "paid, pending sync" acceptable for a few minutes, with a day-end flag until it syncs? | I will save the bill locally and replay it; I need your OK that the invoice number is valid before Shopify has the order. |
| Vikram | Which invoice date/financial year rolls the series (`FY26`), and what happens to a number when payment fails: kept as "cancelled"? | Gapless series is non-negotiable; I assume failed-payment numbers stay as cancelled. |
| Vikram | Is "Day-end matches Shopify to the rupee" measured on bills made that day, or including refunds made that day against older bills? | Changes how refunds are attributed in the report. |
| Meena | You asked for Festive 10% + second pair 50% + priority ₹500 together. `offers.json` marks Festive as non-stackable (the others stack). Is that a data error or intended? | The app follows the data. If Retail really wants all three, the flag changes, not the code, but Finance should see the margin. |
| Meena / Vikram | Manager discount: is "the manager's staff ID + a reason code, no second approver" enough for the auditors? | Satisfies "no approval chain" and "approver identity" together, but real PIN login is needed in production. |
| Dr. Iyer | An external Rx with axis 87° (not on the 5° grid): block, or let the optometrist confirm? | I show a warning for the optometrist to confirm and do not block. Blocking loses the sale. |
| Dr. Iyer | If there is no valid Rx (expired), can anyone override at the till? | v1 blocks lens billing with "book an eye test". |
| Farhan / Dr. Iyer | Remake: who bears the lab cost, and is it a ₹0 lens-only order linked to the parent invoice? | Needs a written rule before I can build it. |
| Rohan | What counts as "10 seconds": from the customer saying yes to the printed invoice, including card/UPI approval? | Terminal approval alone can take several seconds; I can control only our part. |

## 2. What I'm building, and deferring

**Building for 15 Nov (all seven Must items, tested):** customer + Rx lookup with priority/campaign flags; lens-vs-Rx validation that blocks bad choices with an actionable reason; data-driven offers with best-for-customer selection; GST per line by HSN to the paisa; terminal charge then Shopify order with per-store invoice number, Rx on the lens line, tax lines and discounts; full and partial refund with tax reversed per line, frame restocked at the billing store, lens not restocked, credit note; day-end from Shopify orders. Also: cash till (float, paid-in/out with reasons, variance flagged over ₹200), sales channel on every order and a channel split, manager discount (≤10%, approver + reason code mandatory), audit log, and a "paid but not yet in Shopify" outbox that can't create duplicates.

**Deferring, with reasons:**
- **Family billing (3 people, 3 Rxs, 1 bill)**: a Shopify order has one customer; whose record, and how a single member's refund appears, is a Finance + Retail decision. v1: bill each person in turn. It's the next thing I'd build.
- **Remake flow**: needs the cost-ownership rule above. The data shape (₹0 lens-only order with `parent_invoice_no`, no frame line, no stock touched) is already in the seed.
- **10 am founder email**: the numbers exist; scheduling and mail are a small follow-up, not on the critical path for billing.
- **Beverage question and the Indiranagar footfall camera**: not billing. Passing to the queue-tool owner / IT.

## 3. Contradictions and risks

1. **"Everything stacks" vs. the offer data (Meena).** I do not hand-pick combinations. The till tries "all stackable offers together" against each non-stackable offer alone and applies whichever gives the customer the most, and shows why every other offer was skipped. That also fixes the "half the stores apply them manually" problem. Where the floor pitch is "Festive + second pair + priority", the data currently forbids it.
2. **Manager discount with no approval vs. approver identity + reason (Meena vs. Vikram).** Both can hold: one tap for a reason code and the manager's ID, no approval chain. Both are stored on the Shopify order. Capped at 10%.
3. **10 seconds vs. compliance checks (Rohan vs. Vikram).** The checks (Rx, tax, invoice number) are local and fast; the risk is the network and the terminal. I will measure end-to-end time on real store Wi-Fi before launch; I haven't yet.
4. **Wi-Fi drops (Farhan).** The customer may have paid when Shopify can't be reached. Handling: the bill is saved locally first, and a retry first looks up the invoice number in Shopify, so it can't be created twice. A day-end line shows anything not yet synced.
5. **Rx in the thread:** a −6.00 customer on a 1.56 lens is exactly what the validator blocks; the 1° axis confusion is handled by showing only the grid and warning on off-grid values.
6. **Rates change (Vikram).** Rates are in a dated table; no code change and no re-issuing invoices for past dates.
7. **Timeline risk:** seven stores by 15 Nov with no pilot is the biggest risk. I'd pilot one store first.

## 4. What I need to ship v1 for real

- **Finance:** sign-off on invoice/credit-note number formats and the FY rollover; GSTIN per store on the invoice.
- **Shopify admin:** an API token with orders/refunds/inventory scopes; a decision on an indexed invoice-number field (metafield) so duplicate checks don't scan orders.
- **Store tool team:** the Rx API in production, an "external Rx confirmed by optometrist" flag, and staff login so a manager ID can't be typed by anyone.
- **Payment terminal vendor:** confirmation that charge is idempotent on `order_ref` in production, and a refund API.
- **Hardware / IT:** receipt printer and barcode scanner details; failover internet at Koramangala.
- **Ops:** one pilot store and a 3-day dry run (8–11 Nov); a daily cash-count routine so the till variance is meaningful.
- **Decisions:** the stacking, remake-cost and family-billing answers above.
