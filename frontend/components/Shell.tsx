"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { api } from "@/lib/api";
import { Icon } from "./ui";
import { useSession, useToast } from "./Providers";

const ROUTES = [
  { href: "/sell", label: "Sell", icon: "sell", title: "New sale" },
  { href: "/refunds", label: "Refunds", icon: "orders", title: "Bills & refunds" },
  { href: "/till", label: "Till", icon: "till", title: "Cash till" },
  { href: "/day-end", label: "Day-end", icon: "report", title: "Day-end report" },
  { href: "/activity", label: "Activity", icon: "activity", title: "Audit trail" },
];

export function Shell({ children }: { children: ReactNode }) {
  const s = useSession();
  const toast = useToast();
  const path = usePathname();
  const route = ROUTES.find((r) => path.startsWith(r.href)) || ROUTES[0];

  async function sync() {
    try {
      const { results } = await api.syncPending();
      const ok = results.filter((r) => r.status === "synced").length;
      toast(`${ok} of ${results.length} pending bills synced to Shopify`, ok === results.length ? "ok" : "err");
    } catch (e) { toast((e as Error).message, "err"); }
    await s.refreshPending();
  }

  return (
    <div className="shell">
      <aside className="rail" aria-label="Main">
        <div className="brand" title="Eluno">
          <svg viewBox="0 0 40 40" aria-hidden="true"><circle cx="20" cy="20" r="14" fill="none" stroke="#f88e2b" strokeWidth="5" /><circle cx="20" cy="20" r="5" fill="#fff" /></svg>
        </div>
        {ROUTES.map((r) => (
          <Link key={r.href} href={r.href} className="nav-item" aria-current={r === route ? "page" : undefined}>
            <Icon name={r.icon} />{r.label}
            {r.href === "/sell" && s.pending > 0 && <span className="dot" title={`${s.pending} paid bill(s) not yet in Shopify`} />}
          </Link>
        ))}
        <div className="spacer" />
      </aside>
      <div className="main">
        <header className="topbar">
          <div className="title">{route.title}<span className="env-pill" title="Running against the bundled mock of Shopify, the store tool and the payment terminal">Mock</span></div>
          {s.pending > 0 && <button className="btn btn-sm btn-primary" onClick={sync}><Icon name="refresh" />Sync {s.pending} pending bill{s.pending > 1 ? "s" : ""}</button>}
          <div className="ctx">
            <label htmlFor="ctx-store">Store</label>
            <select id="ctx-store" value={s.store} onChange={(e) => s.setStore(e.target.value)}>
              {s.boot.stores.map((x) => <option key={x.code} value={x.code}>{x.name}</option>)}
            </select>
          </div>
          <div className="ctx">
            <label htmlFor="ctx-staff">Staff</label>
            <select id="ctx-staff" value={s.staff} onChange={(e) => s.setStaff(e.target.value)}>
              {s.staffHere.map((x) => <option key={x.id} value={x.id}>{x.name} · {x.role.replace("_", " ")}</option>)}
            </select>
          </div>
        </header>
        <main id="view">{children}</main>
      </div>
    </div>
  );
}
