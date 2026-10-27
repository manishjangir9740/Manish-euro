import type { ReactNode } from "react";

const PATHS: Record<string, string> = {
  sell: "M7 4h10l3 4v12H4V8l3-4zM4 8h16M9 12h6M9 16h4",
  orders: "M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3",
  till: "M3 7h16a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7zm0 0l2-3h12M16 14h2",
  report: "M5 20V10M12 20V4M19 20v-7M3 20h18",
  activity: "M12 7v5l3 2M21 12a9 9 0 11-3-6.7M21 4v5h-5",
  search: "M11 4a7 7 0 100 14 7 7 0 000-14zm9 16l-4-4",
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  print: "M7 9V4h10v5M7 17H5a1 1 0 01-1-1v-5a2 2 0 012-2h12a2 2 0 012 2v5a1 1 0 01-1 1h-2M7 14h10v6H7z",
  alert: "M12 3l10 18H2L12 3zm0 7v5m0 3h.01",
  info: "M12 3a9 9 0 100 18 9 9 0 000-18zm0 8v5m0-8.5h.01",
  upi: "M5 5h5v5H5zM14 5h5v5h-5zM5 14h5v5H5zM14 14h2v2h-2zM18 14h1v5h-5v-1",
  card: "M3 6h18v12H3zM3 10h18M6 15h4",
  cash: "M3 7h18v10H3zM12 9.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM6 10v.01M18 14v.01",
  glasses: "M2 12h2m16 0h2M6 8a4 4 0 100 8 4 4 0 000-8zm12 0a4 4 0 100 8 4 4 0 000-8zM10 12h4",
  plus: "M12 5v14M5 12h14",
  refresh: "M4 12a8 8 0 0114-5.3L20 9M20 4v5h-5M20 12a8 8 0 01-14 5.3L4 15M4 20v-5h5",
};

export function Icon({ name }: { name: string }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={PATHS[name] || PATHS.info} />
    </svg>
  );
}

export function FrameArt() {
  return (
    <svg viewBox="0 0 70 30" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true">
      <rect x="3" y="6" width="25" height="18" rx="8" /><rect x="42" y="6" width="25" height="18" rx="8" />
      <path d="M28 13c4-3 10-3 14 0" /><path d="M3 12L0 9m67 3l3-3" />
    </svg>
  );
}

export function Spinner() { return <span className="spinner" role="status" aria-label="Loading" />; }

export function Alert({ kind, children }: { kind: "err" | "warn" | "ok" | "info"; children: ReactNode }) {
  return (
    <div className={`alert ${kind}`} role={kind === "err" ? "alert" : "status"}>
      <Icon name={kind === "err" || kind === "warn" ? "alert" : kind === "ok" ? "check" : "info"} />
      <div className="grow">{children}</div>
    </div>
  );
}

export function Empty({ icon, children }: { icon: string; children: ReactNode }) {
  return <div className="empty"><Icon name={icon} /><div>{children}</div></div>;
}

export function Skeleton({ h = 16 }: { h?: number }) { return <div className="skeleton" style={{ height: h }} />; }
