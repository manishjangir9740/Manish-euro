"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/useLoad";
import { fmtTime, money, rupeesToPaise, titleCase } from "@/lib/format";
import type { TillSession } from "@/lib/types";
import { useModal, useSession, useToast } from "../Providers";
import { Alert, Empty, Icon, Skeleton, Spinner } from "../ui";

const TYPE_LABEL: Record<string, string> = { cash_sale: "Cash sale", cash_refund: "Cash refund", paid_in: "Paid in", paid_out: "Paid out" };

export function TillView() {
  const s = useSession();
  const toast = useToast();
  const openModal = useModal();
  const { data, loading, error: err, mutate } = useLoad(s.store, () => api.till(s.store));
  const session = data?.session ?? null;
  const setSession = (x: TillSession) => mutate({ session: x });

  if (loading) return <Shell title={s.storeName}><Skeleton h={160} /></Shell>;
  if (err) return <Shell title={s.storeName}><Alert kind="err">{err}</Alert></Shell>;
  if (!session) return <Shell title={s.storeName}><OpenCard onOpened={(x) => { setSession(x); toast("Till opened"); }} /></Shell>;
  const sum = (t: string) => session.movements.filter((m) => m.type === t).reduce((a, m) => a + m.amount_paise, 0);
  const kpi = (lb: string, v: number, sub?: string) => <div className="kpi"><div className="lb">{lb}</div><div className="v num">{money(v)}</div>{sub && <div className="s">{sub}</div>}</div>;

  return (
    <Shell title={s.storeName}>
      <div className="till-grid">
        <div className="stack">
          <div className="big-expected">
            <div className="lb">{session.is_open ? "Cash that should be in the drawer" : "Expected cash at close"}</div>
            <div className="v num" data-testid="expected-cash">{money(session.expected_cash_paise)}</div>
            <div className="small" style={{ color: "#bdbdbd" }}>{session.session_id} · opened {fmtTime(session.opened_at)} by {s.person(session.opened_by)?.name || session.opened_by}</div>
          </div>
          <div className="kpis">
            {kpi("Opening float", session.opening_float_paise)}{kpi("Cash sales", sum("cash_sale"), `${session.movements.filter((m) => m.type === "cash_sale").length} bills`)}
            {kpi("Cash refunds", sum("cash_refund"))}{kpi("Paid in", sum("paid_in"))}{kpi("Paid out", sum("paid_out"))}
          </div>
          <div className="card">
            <div className="card-head"><h2>Movements</h2></div>
            {session.movements.length === 0 ? <Empty icon="till">No cash movements yet.</Empty> : (
              <div className="scroll-x"><table className="t">
                <thead><tr><th>Time</th><th>Type</th><th>Reference</th><th>Reason</th><th>By</th><th className="r">Amount</th></tr></thead>
                <tbody>{[...session.movements].reverse().map((m, i) => (
                  <tr key={i}><td>{fmtTime(m.at)}</td><td><span className="mv-type">{TYPE_LABEL[m.type] || m.type}</span></td><td className="small">{m.ref}</td><td>{m.reason ? titleCase(m.reason) : ""}</td><td>{m.staff_id || ""}</td>
                    <td className={"r num " + (m.amount_paise < 0 ? "var-neg" : "var-pos")} style={{ fontWeight: 600 }}>{m.amount_paise > 0 ? "+" : ""}{money(m.amount_paise)}</td></tr>
                ))}</tbody></table></div>
            )}
          </div>
        </div>
        <div className="stack">
          {session.is_open ? (<>
            <MoveCard session={session} staff={s.staff} onDone={(x) => { setSession(x); toast("Recorded"); }} />
            <CloseCard session={session} staff={s.staff} alertLimit={s.boot.till_variance_alert} openModal={openModal} onDone={(x) => { setSession(x); toast("Till closed"); }} />
          </>) : <ClosedCard session={session} />}
        </div>
      </div>
    </Shell>
  );
}

function Shell({ title, children }: { title: string; children: React.ReactNode }) {
  return (<>
    <div className="page-head"><div><h1>Cash till</h1><p>{title} · one drawer per store per day. Cash sales and cash refunds post here automatically.</p></div></div>
    {children}
  </>);
}

function OpenCard({ onOpened }: { onOpened: (s: TillSession) => void }) {
  const s = useSession(); const toast = useToast();
  const [amount, setAmount] = useState("3000");
  const [busy, setBusy] = useState(false);
  return (
    <div className="card" style={{ maxWidth: 520 }}>
      <div className="card-head"><div className="step-no"><Icon name="till" /></div><h2>Open today’s till</h2></div>
      <p className="muted" style={{ marginBottom: 14 }}>No till session for {s.storeName} today. Count the drawer and enter the opening float (₹).</p>
      <label className="field">Opening float (₹)
        <input type="number" min="0" step="1" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Opening float in rupees" style={{ fontSize: 24, fontWeight: 650, minHeight: 56 }} />
      </label>
      <div style={{ height: 14 }} />
      <button className="btn btn-primary btn-lg" disabled={busy} onClick={async () => {
        setBusy(true);
        try { onOpened((await api.tillOpen({ store: s.store, staff_id: s.staff, float: amount })).session); } catch (e) { toast((e as Error).message, "err"); setBusy(false); }
      }}>{busy ? <Spinner /> : <Icon name="till" />}Open till</button>
    </div>
  );
}

function MoveCard({ session, staff, onDone }: { session: TillSession; staff: string; onDone: (s: TillSession) => void }) {
  const toast = useToast();
  const [type, setType] = useState("paid_out");
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("");
  return (
    <div className="card">
      <div className="card-head"><h2>Paid in / paid out</h2></div>
      <div className="stack-sm">
        <div className="seg full">{[["paid_out", "Paid out"], ["paid_in", "Paid in"]].map(([v, l]) => <button key={v} aria-pressed={type === v} onClick={() => setType(v)}>{l}</button>)}</div>
        <label className="field">Amount (₹)<input type="number" min="0" step="1" placeholder="120" value={amount} onChange={(e) => setAmount(e.target.value)} aria-label="Amount in rupees" /></label>
        <label className="field">Reason (required)<input type="text" placeholder="e.g. courier, tea & snacks" value={reason} onChange={(e) => setReason(e.target.value)} aria-label="Reason" /></label>
        <button className="btn btn-dark" onClick={async () => {
          if (!reason.trim()) return toast("A reason is required.", "err");
          try { onDone((await api.tillMove({ session_id: session.session_id, type, amount, reason, staff_id: staff })).session); setAmount(""); setReason(""); }
          catch (e) { toast((e as Error).message, "err"); }
        }}>Record</button>
      </div>
    </div>
  );
}

function CloseCard({ session, staff, alertLimit, openModal, onDone }: {
  session: TillSession; staff: string; alertLimit: number; openModal: ReturnType<typeof useModal>; onDone: (s: TillSession) => void;
}) {
  const toast = useToast();
  const [counted, setCounted] = useState("");
  const [note, setNote] = useState("");
  const paise = rupeesToPaise(counted);
  const v = paise == null ? null : paise - session.expected_cash_paise;
  return (
    <div className="card">
      <div className="card-head"><h2>Close till</h2></div>
      <div className="stack-sm">
        <label className="field">Counted cash (₹)<input type="number" min="0" step="0.01" value={counted} onChange={(e) => setCounted(e.target.value)} aria-label="Counted cash in rupees" style={{ fontSize: 20, fontWeight: 650 }} /></label>
        <div className={"small " + (v === 0 ? "var-pos" : v != null && Math.abs(v) > alertLimit ? "var-neg" : "muted")} data-testid="live-variance">
          {v == null ? "Variance appears as you type." : v === 0 ? "Drawer matches." : `${v > 0 ? "Over" : "Short"} by ${money(Math.abs(v))}${Math.abs(v) > alertLimit ? " · above the ₹200 limit, Finance will be alerted" : ""}`}
        </div>
        <label className="field">Note<input type="text" placeholder="Explain any difference (optional)" value={note} onChange={(e) => setNote(e.target.value)} aria-label="Variance note" /></label>
        <button className="btn btn-primary" onClick={async () => {
          if (paise == null) return toast("Enter the counted amount.", "err");
          const ok = await openModal((close) => ({
            head: <h2>Close the till for the day?</h2>,
            body: <div>Counted {money(paise)} against expected {money(session.expected_cash_paise)}. A closed till cannot take more cash sales today.</div>,
            foot: (<><button className="btn btn-ghost" onClick={() => close(false)}>Cancel</button><button className="btn btn-dark" data-autofocus onClick={() => close(true)}>Close till</button></>),
          }));
          if (!ok) return;
          try { onDone((await api.tillClose({ session_id: session.session_id, staff_id: staff, counted, note })).session); } catch (e) { toast((e as Error).message, "err"); }
        }}>Count &amp; close</button>
      </div>
    </div>
  );
}

function ClosedCard({ session }: { session: TillSession }) {
  const v = session.variance_paise ?? 0;
  return (
    <div className="card" data-testid="till-closed">
      <div className="card-head"><h2>Closed</h2><span className="pill black" style={{ marginLeft: "auto" }}>{fmtTime(session.closed_at)}</span></div>
      <div className="stack-sm">
        <div className="row between"><span>Expected</span><b className="num">{money(session.expected_cash_paise)}</b></div>
        <div className="row between"><span>Counted</span><b className="num">{money(session.counted_cash_paise)}</b></div>
        <div className="row between"><span>Variance</span><b className={"num " + (v === 0 ? "var-pos" : "var-neg")}>{v > 0 ? "+" : ""}{money(v)}</b></div>
        {session.variance_alert ? <Alert kind="err">{session.variance_note}</Alert> : session.variance_note ? <Alert kind="info">{session.variance_note}</Alert> : <Alert kind="ok">Within tolerance.</Alert>}
      </div>
    </div>
  );
}
