"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/useLoad";
import { fmtTime, money, titleCase } from "@/lib/format";
import type { Order, RefundResult } from "@/lib/types";
import { useModal, useSession, useToast } from "../Providers";
import { Alert, Empty, Icon, Skeleton, Spinner } from "../ui";

function StatusPill({ o }: { o: Order }) {
  if (o.cancelled) return <span className="pill bad">Cancelled</span>;
  if (o.lines.length && o.lines.every((l) => l.refunded)) return <span className="pill black">Refunded</span>;
  if (o.refunded > 0) return <span className="pill soft">Part refunded</span>;
  return <span className="pill ok">Paid</span>;
}

export function RefundsView() {
  const s = useSession();
  const toast = useToast();
  const openModal = useModal();
  const [date, setDate] = useState(s.boot.today);
  const { data, loading, error: err, reload } = useLoad(`${s.store}|${date}`, () => api.orders(s.store, date));
  const orders: Order[] = data?.orders || [];
  const [q, setQ] = useState("");
  const [selId, setSelId] = useState<number | null>(() => { // arriving from a receipt: open that bill
    try {
      const f = typeof window === "undefined" ? null : sessionStorage.getItem("eluno.focusOrder");
      if (f) sessionStorage.removeItem("eluno.focusOrder");
      return f ? Number(f) : null;
    } catch { return null; }
  });
  const [picked, setPicked] = useState<Set<number>>(new Set());
  const [reason, setReason] = useState("CHANGED_MIND");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<RefundResult | null>(null);
  const [refundErr, setRefundErr] = useState<string | null>(null);

  const sel = orders.find((o) => o.order_id === selId) || null;
  const rows = orders.filter((o) => !q || o.invoice_no.toLowerCase().includes(q.toLowerCase()));
  const open = sel ? sel.lines.filter((l) => !l.refunded) : [];
  const full = !!sel && open.length > 0 && open.length === sel.lines.length && picked.size === open.length;
  const chosen = sel ? sel.lines.filter((l) => picked.has(l.line_id)) : [];
  const amount = chosen.reduce((a, l) => a + l.gross, 0);
  const tax = chosen.reduce((a, l) => a + l.tax, 0);

  const toggle = (id: number, on: boolean) => setPicked((p) => { const n = new Set(p); if (on) n.add(id); else n.delete(id); return n; });
  const pick = (o: Order) => { setSelId(o.order_id); setPicked(new Set()); setResult(null); setRefundErr(null); };

  async function doRefund() {
    if (!sel) return;
    const ok = await openModal((close) => ({
      head: <h2>Refund {money(amount)}?</h2>,
      body: (<>
        <div>{full ? "Full refund" : "Partial refund"} of {sel.invoice_no} for:</div>
        <ul style={{ margin: 0, paddingLeft: 18 }}>{chosen.map((l) => <li key={l.line_id}>{l.name}</li>)}</ul>
        <div className="small muted">Reason: {titleCase(reason)}. The amount goes back to the original {sel.payment_method.toUpperCase()} payment. This cannot be undone.</div>
      </>),
      foot: (<>
        <button className="btn btn-ghost" onClick={() => close(false)}>Cancel</button>
        <button className="btn btn-dark" data-autofocus onClick={() => close(true)}>Refund</button>
      </>),
    }));
    if (!ok) return;
    setBusy(true); setRefundErr(null);
    try {
      const r = await api.refund({ order_id: sel.order_id, staff_id: s.staff, reason, line_ids: full ? [] : [...picked] });
      toast(`Credit note ${r.credit_note_no} issued`);
      setPicked(new Set()); setResult(r);
      reload();
    } catch (e) { setRefundErr((e as Error).message); toast((e as Error).message, "err"); }
    setBusy(false);
  }

  return (
    <>
      <div className="page-head"><div><h1>Bills &amp; refunds</h1><p>{s.storeName} · full or per-line refund through Shopify’s refund flow. Tax is reversed per line; frames go back to stock here, lenses do not.</p></div></div>
      <div className="row wrap" style={{ marginBottom: 14 }}>
        <input type="date" value={date} max={s.boot.today} aria-label="Bill date" style={{ width: "auto" }} onChange={(e) => { setDate(e.target.value); setSelId(null); }} />
        <input type="search" placeholder="Find invoice number" aria-label="Find invoice" style={{ maxWidth: 260 }} value={q} onChange={(e) => setQ(e.target.value)} />
        <div className="chips">
          <button className="chip" onClick={() => setDate(s.boot.today)}>Today</button>
          <button className="chip" title="Seed data from the starter kit" onClick={() => setDate("2026-10-06")}>Seed day · 6 Oct</button>
        </div>
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={reload}><Icon name="refresh" />Reload</button>
      </div>
      <div className="orders">
        <div className="order-list" data-testid="order-list">
          {loading ? Array.from({ length: 4 }, (_, i) => <Skeleton key={i} h={64} />)
            : err ? <Alert kind="err">{err}</Alert>
            : rows.length === 0 ? <div className="card"><Empty icon="orders">{orders.length ? "No invoice matches." : `No bills at ${s.storeName} on ${date}.`}</Empty></div>
            : rows.map((o) => (
              <button key={o.order_id} className="order-row" aria-pressed={sel?.order_id === o.order_id} onClick={() => pick(o)}>
                <div><div className="inv">{o.invoice_no}</div><div className="small muted">{fmtTime(o.created_at)} · {titleCase(o.channel)} · {o.payment_method.toUpperCase()} · {o.lines.length} line{o.lines.length > 1 ? "s" : ""}</div></div>
                <div className="right"><div className="num" style={{ fontWeight: 650 }}>{money(o.total)}</div><StatusPill o={o} /></div>
              </button>
            ))}
        </div>
        <section className="card" style={{ position: "sticky", top: 78 }} aria-label="Refund">
          {!sel ? <Empty icon="orders">Select a bill to refund.</Empty> : (<>
            <div className="card-head">
              <div><h2>{sel.invoice_no}</h2><div className="small muted">Shopify {sel.name} · {sel.payment_method.toUpperCase()} · staff {sel.staff_id || "–"}</div></div>
              <span style={{ marginLeft: "auto" }}><StatusPill o={sel} /></span>
            </div>
            <div className="stack-sm">
              {sel.lines.map((l) => (
                <label key={l.line_id} className={"check-line" + (l.refunded ? " disabled" : "")}>
                  <input type="checkbox" checked={picked.has(l.line_id)} disabled={l.refunded || sel.cancelled} onChange={(e) => toggle(l.line_id, e.target.checked)} aria-label={`Refund ${l.name}`} />
                  <div><div style={{ fontWeight: 600 }}>{l.name}</div>
                    <div className="small muted">{l.refunded ? "Already refunded" : l.line_type === "frame" ? "Frame · goes back to stock at this store" : "Lens · made to order, not restocked"} · GST {money(l.tax)}</div></div>
                  <div className="num" style={{ fontWeight: 650 }}>{money(l.gross)}</div>
                </label>
              ))}
            </div>
            {sel.refunds.length > 0 && <div className="small muted" style={{ marginTop: 10 }}>Credit notes: {sel.refunds.map((r) => `${r.credit_note_no} (${money(r.amount)})`).join(", ")}</div>}
            {open.length > 0 && !sel.cancelled && (
              <div className="stack-sm" style={{ marginTop: 14 }}>
                <div className="row">
                  <button className="btn btn-ghost btn-sm" onClick={() => setPicked(new Set(open.map((l) => l.line_id)))}>Select all remaining</button>
                  {picked.size > 0 && <button className="btn btn-ghost btn-sm" onClick={() => setPicked(new Set())}>Clear</button>}
                </div>
                <label className="field">Reason
                  <select value={reason} onChange={(e) => setReason(e.target.value)}>{s.boot.refund_reasons.map((r) => <option key={r} value={r}>{titleCase(r)}</option>)}</select>
                </label>
                <div className="totals" style={{ borderRadius: 12, border: "1px solid var(--line)" }}>
                  <div className="tr"><span>{full ? "Full" : picked.size ? "Partial" : "Refund"} · {picked.size} line{picked.size === 1 ? "" : "s"}</span><b className="num" data-testid="refund-amount">{money(amount)}</b></div>
                  <div className="tr sub"><span>of which GST reversed</span><span className="num">{money(tax)}</span></div>
                  {sel.payment_method === "cash" && <div className="tr sub"><span>Paid out of the cash drawer</span><span /></div>}
                </div>
                <button className="btn btn-dark btn-lg" disabled={picked.size === 0 || busy} onClick={doRefund} data-testid="refund-btn">{busy && <Spinner />}Refund {picked.size ? money(amount) : ""}</button>
              </div>
            )}
            {refundErr && <div style={{ marginTop: 14 }}><Alert kind="err"><b>Refund stopped. </b>{refundErr}</Alert></div>}
            {result && (
              <div style={{ marginTop: 14 }} data-testid="refund-result">
                <Alert kind="ok">
                  <b>Refunded {money(result.refund_amount)}</b>
                  <div className="small">Credit note {result.credit_note_no} against {result.original_invoice_no}. Taxable {money(result.taxable_reversed)} + GST {money(result.tax_reversed)} reversed. {result.lines.some((l) => l.restock) ? "Frame restocked at this store." : "Nothing restocked (lens only)."}{result.till_recorded ? " Recorded as a cash refund in the till." : ""}</div>
                </Alert>
              </div>
            )}
          </>)}
        </section>
      </div>
    </>
  );
}
