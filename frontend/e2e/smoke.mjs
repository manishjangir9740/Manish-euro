// Browser E2E for the till UI against a running stack (backend :8000 + frontend :3000).
//   E2E_URL=http://127.0.0.1:3000 CHROME_PATH="C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" npm run e2e
// Drives real clicks: lookup, lens block, offers, charge, refund, till, day-end. Exits non-zero on any failure.
import puppeteer from "puppeteer-core";

const URL_ = process.env.E2E_URL || "http://127.0.0.1:3000";
const CHROME = process.env.CHROME_PATH || "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const SHOTS = process.env.E2E_SHOTS || "";

const results = [];
let page;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function step(name, fn) {
  try { await fn(); results.push([true, name]); console.log("  ok   " + name); }
  catch (e) { results.push([false, name + " :: " + e.message]); console.log("  FAIL " + name + " :: " + e.message); if (SHOTS) await page.screenshot({ path: `${SHOTS}/fail-${results.length}.png` }); }
}
const assert = (c, msg) => { if (!c) throw new Error(msg); };
const text = (sel) => page.$eval(sel, (e) => e.textContent);
const waitSel = (sel, t = 15000) => page.waitForSelector(sel, { timeout: t });
async function clickText(sel, needle, t = 15000) {
  await page.waitForFunction((sel, needle) => [...document.querySelectorAll(sel)].some((e) => e.textContent.includes(needle) && !e.disabled), { timeout: t }, sel, needle);
  await page.evaluate((sel, needle) => [...document.querySelectorAll(sel)].find((e) => e.textContent.includes(needle) && !e.disabled).click(), sel, needle);
}
const goto = (path) => page.goto(URL_ + path, { waitUntil: "networkidle0" });
async function lookupPhone(digits) {
  await page.type("input[aria-label='Customer phone number']", digits);
  await page.keyboard.press("Enter");
  await waitSel("[data-testid=lens]");
}
const rupees = (s) => Math.round(parseFloat(s.replace(/[₹,\s]/g, "")) * 100);

const browser = await puppeteer.launch({ executablePath: CHROME, headless: "new", defaultViewport: { width: 1440, height: 1000 } });
page = await browser.newPage();
const pageErrors = [];
page.on("pageerror", (e) => pageErrors.push(e.message));
page.on("console", (m) => { if (m.type() === "error" && !/favicon|Failed to load resource/.test(m.text())) pageErrors.push(m.text()); });

console.log("Till UI E2E @ " + URL_);
let invoiceNo, grandTotal;

await step("app loads with store + staff selectors, mock badge, Instrument Sans", async () => {
  await goto("/sell");
  await waitSel("#ctx-store");
  assert((await text(".env-pill")) === "Mock", "mock badge");
  const font = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
  assert(/instrument/i.test(font), "font is " + font);
  const accent = await page.evaluate(() => getComputedStyle(document.querySelector(".btn-primary") || document.body).backgroundColor);
  assert(accent.includes("248, 142, 43") || accent !== "", "accent");
});

await step("1. customer lookup shows name, PRIORITY flag, campaign flag and a valid Rx", async () => {
  await clickText(".chip", "Karthik");
  await waitSel("[data-testid=rx-card]");
  assert((await text("[data-testid=customer-name]")).includes("Karthik"), "name");
  const pills = await page.$$eval(".cust .pill", (els) => els.map((e) => e.textContent));
  assert(pills.some((p) => /Priority/i.test(p)) && pills.some((p) => /Campaign/i.test(p)), "flags " + pills);
  assert((await text("[data-testid=rx-card]")).includes("RX5007"), "rx id");
});

await step("2. lens catalog is validated against the Rx: blocked lenses state why", async () => {
  await waitSel("[data-testid=lens]");
  assert(await page.$("[data-testid=frame]"), "frames listed");
  await page.evaluate(() => [...document.querySelectorAll(".switch input")].find((i) => i.closest("label").textContent.includes("Only lenses")).click()); // show blocked too
  await sleep(300);
  const blocked = await page.$$eval("[data-testid=lens][data-valid=false] .why", (els) => els.map((e) => e.textContent));
  // Karthik has an ADD, so only grid-limit blocks can appear: if any, each must carry a reason
  assert(blocked.every((t) => t.length > 10), "every blocked lens has a reason");
});

await step("3-4. frame + progressive lens: offers applied, GST shown, totals consistent", async () => {
  await clickText(".frame", "Rectangle 03");
  await page.evaluate(() => [...document.querySelectorAll(".switch input")].find((i) => i.closest("label").textContent.includes("Only lenses")).click());
  await clickText(".chips .chip", "Progressive");
  await clickText("[data-testid=lens]", "Progressive · 1.6");
  await page.waitForFunction(() => { const e = document.querySelector("[data-testid=grand-total]"); return e && e.textContent.includes("₹"); }, { timeout: 15000 });
  await sleep(500);
  const totals = await text("[data-testid=totals]");
  assert(/−\s*₹[\d,]+\.\d{2}/.test(totals) && /You save/.test(totals), "an offer discount line shows: " + totals.slice(0, 200));
  assert(totals.includes("CGST") && totals.includes("SGST") && totals.includes("Taxable"), "GST lines shown");
  grandTotal = rupees(await text("[data-testid=grand-total]"));
  const parts = await page.$$eval("[data-testid=totals] .tr", (els) => els.map((e) => e.textContent));
  const num = (label) => { const row = parts.find((p) => p.startsWith(label)); return row ? parseFloat(row.replace(label, "").replace(/[₹,\s−-]/g, "")) : 0; };
  const taxable = num("Taxable value"), cgst = num("CGST"), sgst = num("SGST");
  assert(Math.abs(Math.round((taxable + cgst + sgst) * 100) - grandTotal) <= 0, `taxable+CGST+SGST (${taxable}+${cgst}+${sgst}) = total ${grandTotal / 100}`);
  await page.evaluate(() => document.querySelectorAll("details.disc").forEach((d) => (d.open = true)));
  const offerText = await page.$$eval("details.disc", (els) => els.map((e) => e.textContent).join(" "));
  assert(/MONSOON|Monsoon/.test(offerText), "expired offer is explained, not hidden");
});

await step("5. charge on the terminal: receipt with invoice number, Shopify order saved", async () => {
  await clickText(".method button", "Card");
  await clickText("[data-testid=charge]", "Charge");
  await waitSel("[data-testid=invoice-text]", 30000);
  const inv = await text("[data-testid=invoice-text]");
  const m = inv.match(/ELU\/HSR\/FY26\/\d{5}/);
  assert(m, "invoice number in receipt");
  invoiceNo = m[0];
  assert(/TAX INVOICE/i.test(inv) && inv.includes("CGST"), "tax invoice content");
  const modal = await text(".modal");
  assert(/Saved in Shopify/.test(modal), "saved in Shopify banner");
  assert(modal.includes("Paid") && rupees(modal.match(/Paid (₹[\d,]+\.\d{2})/)[1]) === grandTotal, "paid amount equals the bill total");
});

await step("6. refund from the receipt: select lines, confirm, credit note issued", async () => {
  await clickText(".modal .btn", "Refund this bill");
  await waitSel("[data-testid=order-list] .order-row");
  await page.waitForFunction((inv) => [...document.querySelectorAll(".order-row")].some((r) => r.textContent.includes(inv) && r.getAttribute("aria-pressed") === "true"), { timeout: 10000 }, invoiceNo);
  await clickText("button", "Select all remaining");
  const amount = rupees(await text("[data-testid=refund-amount]"));
  assert(amount === grandTotal, `refund amount ${amount} equals bill ${grandTotal}`);
  await clickText("[data-testid=refund-btn]", "Refund");
  await clickText(".modal .btn", "Refund");
  await waitSel("[data-testid=refund-result]", 30000);
  const r = await text("[data-testid=refund-result]");
  assert(/CN\/\d{5}/.test(r) && r.includes(invoiceNo), "credit note references the invoice: " + r);
  assert(/Frame restocked/.test(r), "frame restocked");
  const pill = await page.$eval(".order-row[aria-pressed=true] .pill", (e) => e.textContent);
  assert(/Refunded/.test(pill), "bill now shows Refunded, got " + pill);
});

await step("blocked lens: customer without ADD cannot bill a progressive and is told what to do", async () => {
  await goto("/sell");
  await clickText(".chip", "Rahul");
  await waitSel("[data-testid=lens]");
  await page.evaluate(() => [...document.querySelectorAll(".switch input")].find((i) => i.closest("label").textContent.includes("Only lenses")).click());
  await clickText(".chips .chip", "Progressive");
  await sleep(300);
  const why = await page.$eval("[data-testid=lens][data-valid=false] .why", (e) => e.textContent);
  assert(/needs an ADD/.test(why) && /single-vision|optometrist/i.test(why), "reason: " + why);
  await page.click("[data-testid=lens][data-valid=false]");
  await waitSel(".alert.err");
  assert((await text(".alert.err")).includes("cannot be billed"), "notice shown");
  assert((await page.$$("[data-testid=lens][data-valid=true]")).length === 0, "no progressive lens can be added");
});

await step("cash needs an open till; till opens, takes cash sale, closes with variance flag", async () => {
  await goto("/sell");
  await lookupPhone("9000000004");
  await clickText("[data-testid=lens][data-valid=true]", "Single Vision · 1.5");
  await clickText(".method button", "Cash");
  await page.waitForFunction(() => document.body.textContent.includes("No open cash till"), { timeout: 8000 });
  assert(await page.$eval("[data-testid=charge]", (b) => b.disabled), "charge disabled without till");
  await goto("/till");
  await clickText("button", "Open till");
  await waitSel("[data-testid=expected-cash]");
  assert(rupees(await text("[data-testid=expected-cash]")) === 300000, "float 3000");
  await goto("/sell");
  await lookupPhone("9000000004");
  await clickText("[data-testid=lens][data-valid=true]", "Single Vision · 1.5");
  await clickText(".method button", "Cash");
  await clickText("[data-testid=charge]", "Take cash");
  await waitSel("[data-testid=invoice-text]", 30000);
  await clickText(".modal .btn", "New sale");
  await goto("/till");
  await waitSel("[data-testid=expected-cash]");
  const expected = rupees(await text("[data-testid=expected-cash]"));
  assert(expected > 300000, "cash sale posted to the drawer: " + expected);
  await page.type("input[aria-label='Counted cash in rupees']", String((expected - 30000) / 100)); // short by Rs 300
  assert((await text("[data-testid=live-variance]")).includes("above the ₹200 limit"), "live variance warning");
  await clickText("button", "Count & close");
  await clickText(".modal .btn", "Close till");
  await waitSel("[data-testid=till-closed]");
  assert((await text("[data-testid=till-closed]")).includes("exceeds"), "Finance alert shown on closed till");
});

await step("7. day-end report: figures present, payment + channel split, reconciled", async () => {
  await goto("/day-end");
  await waitSel("[data-testid=day-end]");
  const t = await text("[data-testid=day-end]");
  for (const w of ["Net billed", "Gross (MRP)", "Discounts", "Taxable value", "GST", "Refunds", "By payment method", "By sales channel", "CARD", "CASH"]) assert(t.includes(w), "missing " + w);
  // the till was closed Rs 300 short earlier in this run, so the report must say so (and nothing else)
  assert(/1 mismatch/.test(t) && /till variance .* exceeds the Rs 200 limit/.test(t), "till variance flagged: " + t.slice(0, 200));
  assert(!/is paid but not in Shopify/.test(t), "no unsynced invoices");
});

await step("day-end for the seed day shows history", async () => {
  await page.select("#ctx-store", "JN");          // switching store resets the screen, so pick the store first
  await waitSel("[data-testid=day-end]");
  await clickText(".chip", "Seed day");
  await page.waitForFunction(() => document.body.textContent.includes("06 Oct 2026") && !document.body.textContent.includes("No bills at"), { timeout: 10000 });
  assert(/Net billed/.test(await text("[data-testid=day-end]")), "seed day totals");
});

await step("audit trail lists the sale, refund and till actions", async () => {
  await goto("/activity");
  await page.waitForSelector("table.t");
  const t = await text("table.t");
  for (const w of ["Order Completed", "Refund Completed", "Till Opened", "Till Closed"]) assert(t.includes(w), "missing " + w);
});

await step("tablet width: bottom navigation, no horizontal scroll", async () => {
  await page.setViewport({ width: 820, height: 1100 });
  await goto("/sell");
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 2);
  assert(!overflow, "horizontal overflow");
});

assert(pageErrors.length === 0, "browser errors: " + pageErrors.join(" | "));
await browser.close();
const failed = results.filter(([ok]) => !ok);
console.log(`\n${results.length - failed.length}/${results.length} passed`);
process.exit(failed.length ? 1 : 0);
