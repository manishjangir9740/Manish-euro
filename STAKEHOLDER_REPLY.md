# Re: [Retail-Requirement] Replace Shopify POS in stores — live by 15 Nov

**To:** Rohan, Priya · **Cc:** Meena, Dr. Iyer, Vikram, Farhan

Thanks all. Shopify stays the system of record; the new app replaces only the screen at the till. Below: my questions, what I'm building, where your asks collide, and what I need.

## 1. Questions (to whom, and why it matters for v1)

| To | Question | Why it matters |
|---|---|---|
| Vikram | If a customer has paid on the terminal but Shopify can't be reached, is a "paid, pending sync" bill acceptable for a few minutes, flagged at day-end until it syncs? | I save the bill locally and replay it; the invoice number is valid before Shopify has the order. I need your OK. |
| Vikram | Does a number burned by a failed payment stay in the series as "cancelled"? When does `FY26` roll? | Gapless series is non-negotiable; I assume yes. |
| Vikram | Should day-end count a refund on the day of the sale or the day of the refund? | Changes how refunds are attributed. |
| Meena | You want Festive 10% + second pair 50% + priority ₹500 together. `offers.json` marks Festive non-stackable. Data error, or intended? | The app follows the data; if all three should stack, the flag changes, not the code. Finance should see the margin. |
| Meena, Vikram | Is "manager's staff ID + reason code, no second approver" enough for auditors? | Meets "no approval chain" and "approver identity" together; production needs a real PIN/login. |
| Dr. Iyer | External Rx with axis 87° (off the 5° grid): block or let the optometrist confirm? | I warn and let the optometrist confirm; blocking loses the sale. |
| Dr. Iyer | With no valid Rx, can anyone override at the till? | v1 blocks the lens: "book an eye test". |
| Farhan, Dr. Iyer | Remake: who bears the lab cost, and is it a ₹0 lens-only order linked to the parent invoice? | Needs a written rule before I build it. |
| Rohan | Is the 10 seconds measured to the printed invoice, including UPI/card approval? | Terminal approval is outside our control. |

## 2. Building vs deferring

**Building for 15 Nov (tested):** customer + Rx lookup with priority/campaign flags; lens-vs-Rx validation that blocks with an actionable reason; data-driven offers choosing the best outcome for the customer; GST per line by HSN to the paisa; terminal charge, then Shopify order with per-store invoice number, Rx on the lens line, tax lines and discounts; full and partial refund (tax reversed per line, frame restocked at the billing store, lens scrapped, credit note); day-end from Shopify orders. Also cash till (float, paid-in/out with reasons, variance over ₹200 flagged), sales channel per order, manager discount (≤10%, approver + reason mandatory), audit log, and an outbox so a paid bill is never lost or duplicated.

**Deferring, with reasons:**
- **Family billing:** a Shopify order has one customer; whose record, and how one member's refund appears, is a Finance + Retail decision. v1: bill each person in turn. Next to build.
- **Remake flow:** needs the cost rule above; the data shape (₹0 lens-only order, `parent_invoice_no`, no frame line, no stock touched) is already in the seed.
- **10 am founder email:** numbers exist; scheduling and mail are a small follow-up.
- **Beverage question, Indiranagar footfall camera:** not billing; passing to the queue-tool owner / IT.

## 3. Contradictions and risks

1. **"Everything stacks" vs the offer data (Meena).** Staff don't pick combinations. The till compares all stackable offers together against each non-stackable offer alone, applies the best for the customer, and shows why each other offer was skipped. That also ends manual application. The floor pitch "Festive + second pair + priority" is currently forbidden by the data.
2. **Manager discount with no approval vs approver identity (Meena vs Vikram).** One tap for a reason code plus the manager's ID, no chain; both stored on the Shopify order; capped at 10%.
3. **10 seconds vs compliance checks (Rohan vs Vikram).** The checks are local and fast (about 0.05 s per bill locally; 3 s worst case with injected 429/503 failures). The real risk is store Wi-Fi and terminal approval, which I haven't measured.
4. **Wi-Fi drops (Farhan).** The bill is saved locally first; a retry looks up the invoice number in Shopify before creating, so it can't be created twice. Anything unsynced shows on the day-end.
5. **Timeline:** seven stores by 15 Nov with no pilot is the biggest risk. Pilot one store first.
6. **Rates change (Vikram):** dated rate table, no code change, no re-issuing past invoices.

## 4. What I need to ship v1 for real

- **Finance:** sign-off on invoice and credit-note formats and the FY rollover; GSTIN per store.
- **Shopify admin:** API token with orders/refunds/inventory scopes; an indexed invoice-number field so duplicate checks don't scan orders; a dev store to test against (I have only run against the mock).
- **Store tool team:** production Rx API, an "external Rx confirmed" flag, staff login so a manager ID can't be typed by anyone.
- **Terminal vendor:** confirmation that charge is idempotent on `order_ref`; a refund API.
- **Engineering:** invoice numbers allocated by one central service per store. The current local files are safe for several tills on one computer, not on different computers.
- **IT/Ops:** printer and scanner details; failover internet at Koramangala; one pilot store and a 3-day dry run (8–11 Nov); a daily cash-count routine.
- **Decisions:** stacking, remake cost, family billing.
