"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/useLoad";
import { fmtDate, money, printText, titleCase } from "@/lib/format";
import { useSession } from "../Providers";
import { Alert, Icon, Skeleton } from "../ui";

function Kpi({ label, value, sub, hero }: { label: string; value: string; sub?: string; hero?: boolean }) {
  return <div className={"kpi" + (hero ? " hero" : "")}><div className="lb">{label}</div><div className="v num">{value}</div>{sub && <div className="s">{sub}</div>}</div>;
}

function Bars({ title, rows, dark }: { title: string; rows: { label: string; v: number; sub?: string }[]; dark?: boolean }) {
  const max = Math.max(1, ...rows.map((r) => r.v));
  return (
    <div className="card">
      <div className="card-head"><h2>{title}</h2></div>
      {rows.length === 0 ? <div className="muted">No bills.</div> : rows.map((r) => (
        <div className="bar-row" key={r.label}>
          <div style={{ fontWeight: 600 }}>{r.label}{r.sub && <div className="small muted">{r.sub}</div>}</div>
          <div className={"bar" + (dark ? " blk" : "")}><i style={{ width: Math.max(2, (r.v / max) * 100) + "%" }} /></div>
          <div className="right num" style={{ fontWeight: 600 }}>{money(r.v)}</div>
        </div>
      ))}
    </div>
  );
}

export function DayEndView() {
  const s = useSession();
  const [date, setDate] = useState(s.boot.today);
  const [showText, setShowText] = useState(false);
  const { data: rep, loading, error: err } = useLoad(`${s.store}|${date}`, () => api.dayEnd(s.store, date));

  const methods = rep ? [...new Set([...Object.keys(rep.payment_splits), ...Object.keys(rep.payment_refunds)])] : [];
  const half = rep ? Math.floor(rep.total_tax / 2) : 0;

  return (
    <>
      <div className="page-head"><div><h1>Day-end report</h1><p>Computed from the Shopify orders for the store and date, then reconciled against this till’s invoice register and cash drawer.</p></div></div>
      <div className="row wrap" style={{ marginBottom: 16 }}>
        <input type="date" value={date} aria-label="Report date" style={{ width: "auto" }} onChange={(e) => setDate(e.target.value)} />
        <div className="chips"><button className="chip" onClick={() => setDate(s.boot.today)}>Today</button><button className="chip" onClick={() => setDate("2026-10-06")}>Seed day · 6 Oct</button></div>
        {rep && <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={() => printText(`Day-end ${rep.store_code} ${rep.date}`, rep.report_text)}><Icon name="print" />Print</button>}
      </div>
      {loading ? <div className="kpis">{Array.from({ length: 4 }, (_, i) => <Skeleton key={i} h={90} />)}</div>
        : err ? <Alert kind="err">{err}</Alert>
        : rep && (
          <div className="stack" data-testid="day-end">
            <div className="row">
              <h2>{s.storeName} · {fmtDate(rep.date)}</h2>
              <span className={"pill " + (rep.mismatches.length ? "bad" : "ok")}>{rep.mismatches.length ? `${rep.mismatches.length} mismatch${rep.mismatches.length > 1 ? "es" : ""}` : "Reconciled"}</span>
            </div>
            {rep.bill_count === 0 && <Alert kind="info">No bills at {s.storeName} on {fmtDate(rep.date)}. Try the seed day (6 Oct) or make a sale.</Alert>}
            <div className="kpis">
              <Kpi hero label="Net billed" value={money(rep.net_billed)} sub={`${rep.bill_count} bill${rep.bill_count === 1 ? "" : "s"} · avg ${money(rep.average_bill)}`} />
              <Kpi label="Gross (MRP)" value={money(rep.gross_sales)} />
              <Kpi label="Discounts" value={money(rep.total_discounts)} />
              <Kpi label="Taxable value" value={money(rep.total_taxable)} />
              <Kpi label="GST (CGST + SGST)" value={money(rep.total_tax)} sub={`CGST ${money(half)} · SGST ${money(rep.total_tax - half)}`} />
              <Kpi label="Refunds" value={money(rep.total_refunds)} sub={`GST reversed ${money(rep.refund_tax)}`} />
              <Kpi label="Net after refunds" value={money(rep.net_billed - rep.total_refunds)} />
            </div>
            <div className="two">
              <Bars dark title="By payment method" rows={methods.map((m) => ({ label: m.toUpperCase(), v: rep.payment_splits[m] || 0, sub: rep.payment_refunds[m] ? `refunded ${money(rep.payment_refunds[m])} · net ${money(rep.payment_net[m])}` : undefined }))} />
              <Bars title="By sales channel" rows={Object.keys(rep.channel_totals).map((c) => ({ label: titleCase(c), v: rep.channel_totals[c], sub: `${rep.channel_splits[c]} bill${rep.channel_splits[c] > 1 ? "s" : ""}` }))} />
            </div>
            <div className="card">
              <div className="card-head"><h2>Reconciliation</h2></div>
              {rep.mismatches.length ? <div className="stack-sm">{rep.mismatches.map((m) => <Alert key={m} kind="err">{m}</Alert>)}</div> : <Alert kind="ok">Invoice register and cash till agree with Shopify.</Alert>}
            </div>
            <div className="card">
              <div className="card-head"><h2>Printable report</h2><button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={() => setShowText(!showText)}>{showText ? "Hide" : "Show text version"}</button></div>
              {showText && <pre className="report">{rep.report_text}</pre>}
            </div>
          </div>
        )}
    </>
  );
}
