"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { api, ApiError, type QuoteBody } from "@/lib/api";
import { useLoad } from "@/lib/useLoad";
import { fmtDate, money, moneyShort, normalisePhone, printText, signed, titleCase } from "@/lib/format";
import type { CheckoutResult, Customer, Frame, Lens, Quote, Rx } from "@/lib/types";
import { useModal, useSession, useToast } from "../Providers";
import { Alert, Empty, FrameArt, Icon, Skeleton, Spinner } from "../ui";

const DEMO = [
  { phone: "9000000005", label: "Karthik · priority + campaign" },
  { phone: "9000000001", label: "Rahul · no ADD on Rx" },
  { phone: "9000000011", label: "Manish · priority" },
  { phone: "9000000000", label: "Priya" },
];
const METHODS: [string, string, string][] = [["upi", "UPI", "upi"], ["card", "Card", "card"], ["cash", "Cash", "cash"]];
const CHANNEL_LABEL: Record<string, string> = { walk_in: "Walk-in", whatsapp_booked: "WhatsApp", online_pickup: "Online pickup" };

interface Pair { frame: Frame | null; lens: Lens | null }

export function SellView() {
  const s = useSession();
  const toast = useToast();
  const openModal = useModal();
  const router = useRouter();

  const [phoneInput, setPhoneInput] = useState("");
  const [lookingUp, setLookingUp] = useState(false);
  const [lookupErr, setLookupErr] = useState<string | null>(null);
  const [phone, setPhone] = useState("");
  const [customer, setCustomer] = useState<Customer | null>(null);
  const [rx, setRx] = useState<Rx | null>(null);
  const [catalog, setCatalog] = useState<{ frames: Frame[]; lenses: Lens[] } | null>(null);
  const [catalogLoading, setCatalogLoading] = useState(false);

  const [pairs, setPairs] = useState<Pair[]>([{ frame: null, lens: null }]);
  const [active, setActive] = useState(0);
  const [frameQ, setFrameQ] = useState("");
  const [lensType, setLensType] = useState("all");
  const [lensIndex, setLensIndex] = useState("all");
  const [lensCoating, setLensCoating] = useState("all");
  const [onlyValid, setOnlyValid] = useState(true);
  const [lensNotice, setLensNotice] = useState<Lens | null>(null);

  const [qr, setQr] = useState<{ key: string; quote?: Quote; err?: ApiError; mgrErr?: string } | null>(null);

  const [channel, setChannel] = useState("walk_in");
  const [method, setMethod] = useState("upi");
  const [mgr, setMgr] = useState({ on: false, percent: "", approver: "", reason: "" });
  const [busy, setBusy] = useState(false);
  const [checkoutErr, setCheckoutErr] = useState<ApiError | null>(null);

  const phoneRef = useRef<HTMLInputElement>(null);
  useEffect(() => { if (!customer) phoneRef.current?.focus(); }, [customer]);

  const tillLoad = useLoad(s.store, () => api.till(s.store));
  const till = tillLoad.loading ? undefined : (tillLoad.data?.session ?? null);

  /* ---------- customer ---------- */
  async function lookup(raw: string) {
    const p = normalisePhone(raw);
    if (p.length < 11) { setLookupErr("Enter the 10-digit mobile number."); return; }
    setLookingUp(true); setLookupErr(null);
    try {
      const r = await api.customer(p);
      setPhone(p); setCustomer(r.customer); setRx(r.prescription);
      setCatalogLoading(true);
      try { setCatalog(await api.catalog(s.store, p)); } catch (e) { toast((e as Error).message, "err"); }
      setCatalogLoading(false);
    } catch (e) {
      const err = e as ApiError;
      setLookupErr(err.status === 404 ? `No customer found for ${p}. Check the number, or create the customer in Shopify first.` : err.message);
    }
    setLookingUp(false);
  }

  function newSale() {
    setPhoneInput(""); setPhone(""); setCustomer(null); setRx(null); setCatalog(null);
    setPairs([{ frame: null, lens: null }]); setActive(0); setQr(null); setCheckoutErr(null);
    setMgr({ on: false, percent: "", approver: "", reason: "" }); setLensNotice(null); setLookupErr(null);
    setFrameQ("");
  }

  /* ---------- pricing ---------- */
  const activePairs = useMemo(
    () => pairs.map((p, i) => ({ frame_id: p.frame?.id, lens_id: p.lens?.id, pair_ref: String(i + 1) })).filter((p) => p.frame_id || p.lens_id),
    [pairs],
  );
  const body = useMemo<QuoteBody>(() => ({
    phone, store: s.store, staff_id: s.staff, channel, pairs: activePairs,
    manager_discount: mgr.on && mgr.percent ? { percent: mgr.percent, approver_id: mgr.approver, reason_code: mgr.reason } : null,
  }), [phone, s.store, s.staff, channel, activePairs, mgr]);

  const bodyKey = JSON.stringify(body);
  useEffect(() => {
    if (!customer || body.pairs.length === 0) return;
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      try {
        let q: Quote; let mgrErr: string | undefined;
        try { q = await api.quote(body, ctrl.signal); }
        catch (e) {
          if (e instanceof ApiError && e.code === "ManagerDiscountRejected") {
            mgrErr = e.message;
            q = await api.quote({ ...body, manager_discount: null }, ctrl.signal);
          } else throw e;
        }
        setQr({ key: bodyKey, quote: q, mgrErr });
      } catch (e) {
        if (e instanceof DOMException && e.name === "AbortError") return;
        setQr({ key: bodyKey, err: e as ApiError });
      }
    }, 120);
    return () => { clearTimeout(t); ctrl.abort(); };
  }, [body, bodyKey, customer]);

  const priced = !!customer && body.pairs.length > 0;
  const quoting = priced && qr?.key !== bodyKey;
  const quote: Quote | null = priced ? qr?.quote ?? null : null;
  const quoteErr: ApiError | null = priced && qr?.key === bodyKey ? qr.err ?? null : null;
  const mgrErr: string | null = priced && qr?.key === bodyKey ? qr.mgrErr ?? null : null;

  /* ---------- cart edits ---------- */
  const pair = pairs[active];
  const editPair = (i: number, patch: Partial<Pair>) => { setPairs((ps) => ps.map((p, j) => (j === i ? { ...p, ...patch } : p))); setCheckoutErr(null); };
  const addPair = () => { setPairs((ps) => [...ps, { frame: null, lens: null }]); setActive(pairs.length); setLensNotice(null); };
  const removePair = (i: number) => { setPairs((ps) => ps.filter((_, j) => j !== i)); setActive((a) => Math.max(0, Math.min(a, pairs.length - 2))); };

  /* ---------- derived catalog views ---------- */
  const frames = (catalog?.frames || []).filter((f) => !frameQ || (f.name + f.sku).toLowerCase().includes(frameQ.toLowerCase()));
  const allLenses = catalog?.lenses || [];
  const passing = allLenses.filter((l) => l.verdict?.valid).length;
  const types = ["all", ...new Set(allLenses.map((l) => l.lens_type))];
  const indexes = ["all", ...[...new Set(allLenses.map((l) => String(l.index)))].sort((a, b) => Number(a) - Number(b))];
  const coatings = ["all", ...new Set(allLenses.map((l) => l.coating))];
  const filteredLenses = allLenses.filter((l) => (lensType === "all" || l.lens_type === lensType) && (lensIndex === "all" || String(l.index) === lensIndex) && (lensCoating === "all" || l.coating === lensCoating));
  const hiddenBlocked = filteredLenses.filter((l) => !l.verdict?.valid).length;
  const shownLenses = onlyValid ? filteredLenses.filter((l) => l.verdict?.valid) : filteredLenses;

  /* ---------- charge ---------- */
  const needTill = method === "cash" && till !== undefined && !(till && till.is_open);
  const mgrIncomplete = mgr.on && (!mgr.percent || !mgr.approver || !mgr.reason || !!mgrErr);
  const canCharge = !!customer && !!quote && quote.lines.length > 0 && !busy && !quoting && !mgrIncomplete && !needTill;

  async function charge() {
    if (!canCharge) return;
    setBusy(true); setCheckoutErr(null);
    try {
      const res = await api.checkout({ ...body, payment_method: method });
      setBusy(false);
      s.refreshPending();
      tillLoad.reload();
      await showReceipt(res);
    } catch (e) {
      setBusy(false); setCheckoutErr(e as ApiError); toast((e as Error).message, "err");
    }
  }

  async function showReceipt(res: CheckoutResult) {
    const pending = res.status === "pending_sync";
    const act = await openModal((close) => ({
      head: (<>
        <div className="success-mark"><Icon name="check" /></div>
        <div><h2>Paid {money(res.totals.total)}</h2><div className="muted">{titleCase(res.payment_method)} · {res.invoice_no}</div></div>
      </>),
      body: (<>
        {pending
          ? <Alert kind="warn"><b>Paid, but Shopify was unreachable. </b>The bill is saved on this till and will be sent to Shopify without duplicating (use “Sync pending bills” at the top).</Alert>
          : <Alert kind="ok">Saved in Shopify{res.order_number ? ` as order #${res.order_number}` : ""}. Invoice number issued from the store series.</Alert>}
        {res.warnings.map((w) => <Alert key={w} kind="warn">{w}</Alert>)}
        <pre className="invoice" data-testid="invoice-text">{res.invoice_text}</pre>
      </>),
      foot: (<>
        <button className="btn btn-ghost" onClick={() => printText(res.invoice_no, res.invoice_text)}><Icon name="print" />Print invoice</button>
        {!pending && <button className="btn btn-ghost" onClick={() => close("refund")}><Icon name="orders" />Refund this bill</button>}
        <button className="btn btn-primary" data-autofocus onClick={() => close("new")}><Icon name="plus" />New sale</button>
      </>),
    }), { wide: true, dismissable: false });
    if (act === "refund" && res.order_id) {
      try { sessionStorage.setItem("eluno.focusOrder", String(res.order_id)); } catch { /* ignore */ }
      newSale(); router.push("/refunds"); return;
    }
    newSale();
  }

  /* ---------- render ---------- */
  const locked = !customer;
  const cgst = quote?.lines.reduce((a, l) => a + (l.tax_lines.find((x) => x.title === "CGST")?.amount || 0), 0) || 0;
  const sgst = quote?.lines.reduce((a, l) => a + (l.tax_lines.find((x) => x.title === "SGST")?.amount || 0), 0) || 0;
  const hasItems = activePairs.length > 0;

  const pairTabs = (
    <div className="pair-tabs" style={{ marginLeft: "auto" }}>
      {pairs.map((_, i) => (
        <span key={i} className="pair-tab" role="button" tabIndex={0} aria-pressed={i === active}
          onClick={() => { setActive(i); setLensNotice(null); }} onKeyDown={(e) => { if (e.key === "Enter") setActive(i); }}>
          Pair {i + 1}
          {pairs.length > 1 && <button className="x" title="Remove pair" aria-label={`Remove pair ${i + 1}`} onClick={(e) => { e.stopPropagation(); removePair(i); }}>×</button>}
        </span>
      ))}
      <button className="chip" onClick={addPair} title="e.g. second-pair offers need two pairs">+ Add pair</button>
    </div>
  );

  const chips = (vals: string[], cur: string, set: (v: string) => void, label: string) => (
    <div className="chips" role="group" aria-label={label}>
      {vals.map((v) => <button key={v} className="chip" aria-pressed={cur === v} onClick={() => set(v)}>{v === "all" ? `All ${label}` : label === "indexes" ? v : titleCase(v)}</button>)}
    </div>
  );

  return (
    <>
      <div className="page-head"><div><h1>New sale</h1><p>{s.storeName} · frame, lens validated against the prescription, offers, GST, charge.</p></div></div>
      <div className="sell">
        <div className="sell-col">
          {/* 1. customer */}
          <section className="card" aria-label="Customer">
            <div className="card-head">
              <div className={"step-no" + (customer ? " done" : "")}>{customer ? <Icon name="check" /> : "1"}</div>
              <h2>Customer &amp; prescription</h2>
              {customer && <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={newSale}>Change customer</button>}
            </div>
            {!customer && (<>
              <form className="lookup" onSubmit={(e) => { e.preventDefault(); lookup(phoneInput); }}>
                <div className="phone-wrap">
                  <span className="prefix">+91</span>
                  <input ref={phoneRef} type="tel" inputMode="numeric" autoComplete="off" placeholder="98765 43210" aria-label="Customer phone number" maxLength={16}
                    value={phoneInput} onChange={(e) => setPhoneInput(e.target.value)} />
                </div>
                <button className="btn btn-dark" type="submit" disabled={lookingUp}>{lookingUp ? <Spinner /> : <Icon name="search" />}Find</button>
              </form>
              <div className="row wrap demo-phones">
                <span className="small muted">Demo customers</span>
                <div className="chips">{DEMO.map((d) => <button key={d.phone} type="button" className="chip" onClick={() => { setPhoneInput(d.phone); lookup(d.phone); }}>{d.label}</button>)}</div>
              </div>
              {lookupErr && <div style={{ marginTop: 12 }}><Alert kind="err">{lookupErr}</Alert></div>}
            </>)}
            {customer && (
              <div>
                <div className="cust" style={{ marginTop: 0, paddingTop: 0, borderTop: 0 }}>
                  <div className="avatar">{customer.name.split(" ").map((p) => p[0]).slice(0, 2).join("")}</div>
                  <div>
                    <div className="row wrap">
                      <h2 data-testid="customer-name">{customer.name}</h2>
                      {customer.flags.map((f) => <span key={f} className={"pill " + (f === "PRIORITY" ? "orange" : "black")}>{f === "PRIORITY" ? "★ Priority" : titleCase(f.replace("CAMPAIGN:", "Campaign · "))}</span>)}
                    </div>
                    <div className="small muted">{customer.phone} · lifetime spend {moneyShort(customer.total_spent)}</div>
                  </div>
                </div>
                {rx ? <RxCard rx={rx} optometrist={s.person(rx.optometrist_id)?.name} /> : (
                  <div style={{ marginTop: 14 }}><Alert kind="warn"><b>No valid prescription on file. </b>Frames can still be billed. For lenses, book an eye test or have the external Rx entered in the store tool.</Alert></div>
                )}
              </div>
            )}
          </section>

          {/* 2. frames */}
          <section className={"card" + (locked ? " locked" : "")} aria-label="Frames">
            <div className="card-head">
              <div className={"step-no" + (pair.frame ? " done" : "")}>{pair.frame ? <Icon name="check" /> : "2"}</div>
              <h2>Frame</h2>
              {catalog && <span className="small muted">{frames.length} in range · stock at {s.storeName}</span>}
              {pairTabs}
            </div>
            <div className="filters"><input type="search" placeholder="Search frames by name or SKU" aria-label="Search frames" value={frameQ} onChange={(e) => setFrameQ(e.target.value)} /></div>
            {catalogLoading ? <div className="frames">{Array.from({ length: 6 }, (_, i) => <Skeleton key={i} h={130} />)}</div>
              : frames.length === 0 ? <Empty icon="glasses">{catalog ? "No frames match." : "Find a customer to start."}</Empty>
              : (
                <div className="frames">
                  {frames.map((f) => {
                    const used = pairs.filter((p, i) => i !== active && p.frame?.id === f.id).length;
                    const stock = f.stock == null ? null : f.stock - used;
                    const out = stock != null && stock <= 0;
                    const sel = pair.frame?.id === f.id;
                    return (
                      <button key={f.id} className="frame" aria-pressed={sel} disabled={out && !sel} data-testid="frame"
                        onClick={() => editPair(active, { frame: sel ? null : f })}>
                        <span className="tick"><Icon name="check" /></span>
                        <div className="art"><FrameArt /></div>
                        <div className="nm">{f.name}</div>
                        <div className="row between">
                          <span className="pr">{moneyShort(f.price)}</span>
                          {out ? <span className="pill bad">Out of stock</span> : <span className={"pill " + (stock != null && stock <= 2 ? "soft" : "")}>{stock == null ? "In stock" : `${stock} left`}</span>}
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
          </section>

          {/* 3. lenses */}
          <section className={"card" + (locked ? " locked" : "")} aria-label="Lenses">
            <div className="card-head">
              <div className={"step-no" + (pair.lens ? " done" : "")}>{pair.lens ? <Icon name="check" /> : "3"}</div>
              <h2>Lens</h2>
              {catalog && rx && <span className="small muted">{passing} of {allLenses.length} suit this prescription</span>}
              <label className="switch" style={{ marginLeft: "auto" }}>
                <input type="checkbox" checked={onlyValid} onChange={(e) => setOnlyValid(e.target.checked)} />Only lenses that pass
              </label>
            </div>
            {allLenses.length > 0 && (
              <div className="stack-sm" style={{ marginBottom: 14 }}>
                {chips(types, lensType, setLensType, "types")}{chips(indexes, lensIndex, setLensIndex, "indexes")}{chips(coatings, lensCoating, setLensCoating, "coatings")}
              </div>
            )}
            {lensNotice && (
              <div style={{ marginBottom: 12 }}>
                <Alert kind="err"><b>{titleCase(lensNotice.lens_type)} {lensNotice.index} {titleCase(lensNotice.coating)} cannot be billed. </b>
                  <ul>{lensNotice.verdict?.errors.map((e) => <li key={e}>{e}</li>)}</ul></Alert>
              </div>
            )}
            {catalogLoading ? <div className="lens-list">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} h={58} />)}</div>
              : allLenses.length === 0 ? <Empty icon="glasses">Find a customer to see lenses.</Empty>
              : shownLenses.length === 0 ? (
                <Empty icon="glasses">{rx ? "No lens in this filter passes the prescription." : "No lens can be billed without a valid prescription."}
                  {hiddenBlocked > 0 && <div style={{ marginTop: 10 }}><button className="link" onClick={() => setOnlyValid(false)}>Show {hiddenBlocked} blocked lenses and why</button></div>}</Empty>
              ) : (
                <div className="lens-list">
                  {shownLenses.map((l) => {
                    const ok = !!l.verdict?.valid;
                    return (
                      <button key={l.id} className={"lens" + (ok ? "" : " blocked")} aria-pressed={pair.lens?.id === l.id} aria-disabled={ok ? undefined : true} data-testid="lens" data-valid={ok}
                        onClick={() => {
                          if (!ok) { setLensNotice(l); return; }
                          setLensNotice(null); editPair(active, { lens: pair.lens?.id === l.id ? null : l });
                        }}>
                        <div>
                          <div className="nm">{titleCase(l.lens_type)} · {l.index}</div>
                          <div className="meta"><span>{titleCase(l.coating)}</span><span>{l.lab_tat_days}-day lab</span><span>SPH {l.limits.sph_min} to {l.limits.sph_max}, CYL ≤ {l.limits.cyl_abs_max}</span></div>
                        </div>
                        <div className="pr">{moneyShort(l.price)}{!ok && <div><span className="pill bad">Blocked</span></div>}</div>
                        {!ok && <div className="why">{l.verdict?.errors[0]}</div>}
                        {ok && l.verdict?.warnings.map((w) => <div key={w} className="warnline">⚠ {w}</div>)}
                      </button>
                    );
                  })}
                </div>
              )}
          </section>
        </div>

        {/* ---------------- cart + payment ---------------- */}
        <div className="cart-col">
          <section className="card cart" aria-label="Bill">
            <div className="cart-head">
              <Icon name="sell" /><h2>Bill</h2>
              {quoting && <span className="spinner" style={{ marginLeft: 6, borderColor: "rgba(255,255,255,.25)", borderTopColor: "#f88e2b" }} />}
              {customer && <span className="pill orange">{customer.name.split(" ")[0]}</span>}
            </div>
            {!hasItems && <Empty icon="sell">Pick a frame and a lens to start the bill.</Empty>}
            {quoteErr && (
              <div style={{ padding: "14px 18px 0" }}>
                <Alert kind="err"><b>{quoteErr.code === "RxValidationFailed" ? "Lens blocked. " : "Cannot price this bill. "}</b>
                  {quoteErr.details.length ? <ul>{quoteErr.details.map((d) => <li key={d}>{d}</li>)}</ul> : quoteErr.message}</Alert>
              </div>
            )}
            {hasItems && (
              <div className="cart-body">
                {pairs.map((p, i) => {
                  if (!p.frame && !p.lens) return null;
                  const lines = quote?.lines.filter((l) => l.pair_ref === String(i + 1)) || [];
                  const one = (item: Frame | Lens | null, kind: "frame" | "lens") => {
                    if (!item) return null;
                    const ln = lines.find((l) => l.variant_id === item.id);
                    return (
                      <div className="line" key={kind}>
                        <div className="nm">{item.name}</div><div className="amt num">{moneyShort(item.price)}</div>
                        <div className="sub">
                          <span>{kind === "frame" ? "Frame" : "Lens"}</span>
                          {ln?.offers.map((o) => <span key={o.offer_id} className="off">− {money(o.amount)} {o.name}</span>)}
                          {ln?.warnings.map((w) => <span key={w} className="off">⚠ {w}</span>)}
                          <button className="rm" onClick={() => editPair(i, { [kind]: null })}>Remove</button>
                        </div>
                      </div>
                    );
                  };
                  return (
                    <div className="pair-block" key={i}>
                      {pairs.length > 1 && <div className="pair-title">Pair {i + 1}{!(p.frame && p.lens) && <span style={{ textTransform: "none", letterSpacing: 0 }}>incomplete</span>}</div>}
                      {one(p.frame, "frame")}{one(p.lens, "lens")}
                    </div>
                  );
                })}
              </div>
            )}
            {quote && (<>
              <div className="totals" data-testid="totals">
                <div className="tr"><span>Subtotal (MRP, incl. GST)</span><span className="num">{money(quote.totals.mrp)}</span></div>
                {quote.totals.discount > 0 && quote.applied_offers.map((o) => <div key={o.offer_id} className="tr off"><span>{o.name}</span><span className="num">− {money(o.amount)}</span></div>)}
                <div className="tr sub"><span>Taxable value</span><span className="num">{money(quote.totals.taxable)}</span></div>
                <div className="tr sub"><span>CGST</span><span className="num">{money(cgst)}</span></div>
                <div className="tr sub"><span>SGST</span><span className="num">{money(sgst)}</span></div>
                <div className="grand"><span style={{ fontWeight: 650 }}>Total payable</span><b className="num" data-testid="grand-total">{money(quote.totals.total)}</b></div>
                {quote.totals.discount > 0 && <div className="small" style={{ color: "#8a4a05", fontWeight: 600, textAlign: "right" }}>You save {money(quote.totals.discount)}</div>}
              </div>
              <details className="disc">
                <summary>Offers · {quote.applied_offers.length} applied</summary>
                <div className="inner">
                  {[...quote.offer_evaluations].sort((a, b) => Number(b.applied) - Number(a.applied)).map((e) => (
                    <div key={e.offer_id} className={"ev" + (e.applied ? " on" : "")}>
                      <span className="ic"><Icon name={e.applied ? "check" : "x"} /></span>
                      <div><div className="nm">{e.name}</div><div className="why">{e.why}</div></div>
                      <div className="num" style={{ fontWeight: 600 }}>{e.applied ? "− " + money(e.amount) : ""}</div>
                    </div>
                  ))}
                </div>
              </details>
              <details className="disc">
                <summary>GST breakup per line</summary>
                <div className="inner">
                  <div className="scroll-x">
                    <table className="gst-table">
                      <thead><tr><th>Item</th><th>Taxable</th><th>CGST</th><th>SGST</th><th>Line total</th></tr></thead>
                      <tbody>
                        {quote.lines.map((l) => {
                          const c = l.tax_lines.find((x) => x.title === "CGST"); const g = l.tax_lines.find((x) => x.title === "SGST");
                          return (
                            <tr key={l.index}>
                              <td><div>{l.name}</div><div className="muted">HSN {l.hsn}</div></td>
                              <td className="num">{money(l.taxable)}</td>
                              <td className="num">{money(c?.amount)} ({(c?.rate_bps || 0) / 100}%)</td>
                              <td className="num">{money(g?.amount)} ({(g?.rate_bps || 0) / 100}%)</td>
                              <td className="num">{money(l.gross)}</td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </div>
                  <div className="small muted">Prices include GST. Tax is backed out per line by HSN; taxable + CGST + SGST equals the line total to the paisa.</div>
                </div>
              </details>
            </>)}
          </section>

          <section className="card pay" aria-label="Payment">
            <div className="stack-sm">
              <h3>Sales channel</h3>
              <div className="seg full" role="group" aria-label="Sales channel">
                {s.boot.channels.map((c) => <button key={c} aria-pressed={channel === c} onClick={() => setChannel(c)}>{CHANNEL_LABEL[c] || titleCase(c)}</button>)}
              </div>
            </div>
            <div className="stack-sm">
              <h3>Payment</h3>
              <div className="method">
                {METHODS.map(([v, label, ic]) => <button key={v} aria-pressed={method === v} onClick={() => setMethod(v)}><Icon name={ic} />{label}</button>)}
              </div>
            </div>
            {needTill && <Alert kind="warn">No open cash till for today. <Link className="link" href="/till">Open the till</Link> before taking cash.</Alert>}
            <div className="mgr">
              <label className="switch">
                <input type="checkbox" checked={mgr.on} disabled={s.managers.length === 0}
                  onChange={(e) => { setMgr({ ...mgr, on: e.target.checked }); }} />
                Manager discount (max {s.boot.manager_max_percent}%)
              </label>
              {s.managers.length === 0 && <div className="small muted">No manager at this store can approve discounts.</div>}
              {mgr.on && (
                <div className="stack-sm">
                  <div className="grid2">
                    <label className="field">Discount %<input type="number" min="0" max={s.boot.manager_max_percent} step="0.5" value={mgr.percent} placeholder="e.g. 8" onChange={(e) => setMgr({ ...mgr, percent: e.target.value })} /></label>
                    <label className="field">Approved by
                      <select value={mgr.approver} onChange={(e) => setMgr({ ...mgr, approver: e.target.value })}>
                        <option value="">Select manager</option>{s.managers.map((m) => <option key={m.id} value={m.id}>{m.name} ({m.id})</option>)}
                      </select></label>
                  </div>
                  <label className="field">Reason code
                    <select value={mgr.reason} onChange={(e) => setMgr({ ...mgr, reason: e.target.value })}>
                      <option value="">Select reason</option>{s.boot.discount_reason_codes.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}
                    </select></label>
                  <div className="small muted">Approver and reason are written to the Shopify order and the audit trail.</div>
                  {mgrErr && <Alert kind="err">{mgrErr}</Alert>}
                </div>
              )}
            </div>
            {checkoutErr && <Alert kind="err"><b>{checkoutErr.code === "TillClosed" ? "Till closed. " : "Payment not completed. "}</b>{checkoutErr.message}</Alert>}
            <button className="btn btn-primary btn-lg" disabled={!canCharge} onClick={charge} data-testid="charge">
              {busy && <Spinner />}{busy ? "Waiting for the terminal…" : method === "cash" ? "Take cash" : "Charge terminal"}
              {quote && !busy && <b className="num">{money(quote.totals.total)}</b>}
            </button>
          </section>
        </div>
      </div>
    </>
  );
}

function RxCard({ rx, optometrist }: { rx: Rx; optometrist?: string }) {
  const eye = (label: string, e: Rx["od"]) => (
    <tr><td>{label}</td><td>{signed(e.sph)}</td><td>{signed(e.cyl)}</td><td>{e.axis ?? "–"}</td><td>{e.add != null ? "+" + e.add.toFixed(2) : "–"}</td></tr>
  );
  return (
    <div className="rx" data-testid="rx-card">
      <div className="rx-head"><Icon name="glasses" /><b>{rx.rx_id}</b><span>{rx.source === "external" ? "External Rx" : "In-store eye test"}</span><span className="muted" style={{ marginLeft: "auto" }}>Valid until {fmtDate(rx.valid_until)}</span></div>
      <table><thead><tr><th>Eye</th><th>SPH</th><th>CYL</th><th>AXIS</th><th>ADD</th></tr></thead><tbody>{eye("OD · right", rx.od)}{eye("OS · left", rx.os)}</tbody></table>
      <div className="rx-foot"><span>Tested {fmtDate(rx.date)}</span>{rx.pd?.binocular && <span>PD {rx.pd.binocular} mm</span>}{rx.optometrist_id && <span>Optometrist {optometrist || rx.optometrist_id}</span>}{rx.notes && <span>{rx.notes}</span>}</div>
    </div>
  );
}
