"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useLoad } from "@/lib/useLoad";
import { money, titleCase } from "@/lib/format";
import type { AuditEvent } from "@/lib/types";
import { useSession } from "../Providers";
import { Alert, Empty, Icon, Skeleton } from "../ui";

function detail(d: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [k, v] of Object.entries(d || {})) {
    if (v == null) continue;
    if (k.endsWith("_paise") && typeof v === "number") parts.push(`${titleCase(k.replace("_paise", ""))} ${money(v)}`);
    else if (Array.isArray(v)) parts.push(`${titleCase(k)}: ${v.length ? v.map((x) => (typeof x === "object" ? JSON.stringify(x) : String(x))).join(", ") : "none"}`);
    else parts.push(`${titleCase(k)}: ${String(v)}`);
  }
  return parts.join(" · ");
}

export function ActivityView() {
  const s = useSession();
  const [q, setQ] = useState("");
  const { data, loading, error: err, reload: load } = useLoad("audit", () => api.audit());
  const events: AuditEvent[] = data?.events || [];

  const rows = events.filter((e) => !q || JSON.stringify(e).toLowerCase().includes(q.toLowerCase()));
  return (
    <>
      <div className="page-head"><div><h1>Audit trail</h1><p>Who did what, when, with which reason code and reference. Newest first.</p></div></div>
      <div className="row wrap" style={{ marginBottom: 14 }}>
        <input type="search" placeholder="Filter by person, action or reference" aria-label="Filter audit trail" style={{ maxWidth: 360 }} value={q} onChange={(e) => setQ(e.target.value)} />
        <button className="btn btn-ghost btn-sm" style={{ marginLeft: "auto" }} onClick={load}><Icon name="refresh" />Reload</button>
      </div>
      <div className="card">
        {loading ? <Skeleton h={120} /> : err ? <Alert kind="err">{err}</Alert> : rows.length === 0 ? <Empty icon="activity">No activity yet.</Empty> : (
          <div className="scroll-x"><table className="t">
            <thead><tr><th>When</th><th>Who</th><th>Action</th><th>Reference</th><th>Reason</th><th>Details</th></tr></thead>
            <tbody>{rows.map((e, i) => (
              <tr key={i}>
                <td className="small" style={{ whiteSpace: "nowrap" }}>{new Date(e.timestamp).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</td>
                <td>{s.person(e.who)?.name || e.who}</td>
                <td><span className={"pill " + (/FAIL|CANCEL|MISMATCH/.test(e.what) ? "bad" : /REFUND/.test(e.what) ? "soft" : "")}>{titleCase(e.what)}</span></td>
                <td className="small">{e.ref || ""}</td><td>{e.reason_code ? titleCase(e.reason_code) : ""}</td><td className="small muted">{detail(e.details)}</td>
              </tr>
            ))}</tbody></table></div>
        )}
      </div>
    </>
  );
}
