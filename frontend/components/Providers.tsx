"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api, ApiError } from "@/lib/api";
import type { Bootstrap, Staff } from "@/lib/types";
import { Icon } from "./ui";

/* ---------------- toast ---------------- */
type ToastKind = "ok" | "err";
const ToastCtx = createContext<(msg: string, kind?: ToastKind) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

/* ---------------- modal ---------------- */
type Close = (v?: unknown) => void;
type Renderer = (close: Close) => { head?: ReactNode; body: ReactNode; foot?: ReactNode };
interface ModalOpts { wide?: boolean; dismissable?: boolean }
const ModalCtx = createContext<(r: Renderer, o?: ModalOpts) => Promise<unknown>>(async () => undefined);
export const useModal = () => useContext(ModalCtx);

interface ActiveModal { id: number; render: Renderer; opts: ModalOpts; resolve: (v: unknown) => void }

function ModalHost({ modal, close }: { modal: ActiveModal; close: Close }) {
  const ref = useRef<HTMLDivElement>(null);
  const parts = modal.render(close);
  const dismissable = modal.opts.dismissable !== false;
  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    (ref.current?.querySelector("[data-autofocus]") as HTMLElement | null ?? ref.current?.querySelector("button, input, select"))?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape" && dismissable) close(undefined); };
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("keydown", onKey); prev?.focus?.(); };
  }, [close, dismissable]);
  return (
    <div className="overlay" role="dialog" aria-modal="true" onMouseDown={(e) => { if (e.target === e.currentTarget && dismissable) close(undefined); }}>
      <div className={"modal" + (modal.opts.wide ? " wide" : "")} ref={ref}>
        {parts.head && <div className="modal-head">{parts.head}</div>}
        <div className="modal-body">{parts.body}</div>
        {parts.foot && <div className="modal-foot">{parts.foot}</div>}
      </div>
    </div>
  );
}

/* ---------------- session (store, staff, boot data) ---------------- */
export interface Session {
  boot: Bootstrap; store: string; staff: string; pending: number;
  setStore: (code: string) => void; setStaff: (id: string) => void; refreshPending: () => Promise<void>;
  storeName: string; staffHere: Staff[]; managers: Staff[]; person: (id: string | null | undefined) => Staff | undefined;
}
const SessionCtx = createContext<Session | null>(null);
export function useSession(): Session {
  const s = useContext(SessionCtx);
  if (!s) throw new Error("useSession outside provider");
  return s;
}

function SessionProvider({ children }: { children: ReactNode }) {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [store, setStoreState] = useState("");
  const [staff, setStaffState] = useState("");
  const [pending, setPending] = useState(0);

  const refreshPending = useCallback(async () => {
    try { setPending((await api.pending()).pending.length); } catch { /* non-critical */ }
  }, []);

  useEffect(() => {
    api.bootstrap().then((b) => {
      let saved: { store?: string; staff?: string } = {};
      try { saved = JSON.parse(localStorage.getItem("eluno.ctx") || "{}"); } catch { /* ignore */ }
      const st = b.stores.some((s) => s.code === saved.store) ? saved.store! : (b.stores.find((s) => s.code === "HSR") || b.stores[0]).code;
      const here = b.staff.filter((s) => s.store === st);
      const who = here.some((s) => s.id === saved.staff) ? saved.staff! : (here.find((s) => s.role === "sales") || here[0])?.id || "";
      setBoot(b); setStoreState(st); setStaffState(who);
      refreshPending();
    }).catch((e: unknown) => setErr(e instanceof ApiError ? e.message : "Cannot start"));
  }, [refreshPending]);

  const persist = (s: string, w: string) => { try { localStorage.setItem("eluno.ctx", JSON.stringify({ store: s, staff: w })); } catch { /* private mode */ } };

  const value = useMemo<Session | null>(() => {
    if (!boot) return null;
    const staffHere = boot.staff.filter((s) => s.store === store);
    return {
      boot, store, staff, pending, refreshPending,
      setStore: (code) => {
        const first = boot.staff.find((s) => s.store === code && s.role === "sales") || boot.staff.find((s) => s.store === code);
        setStoreState(code); setStaffState(first?.id || ""); persist(code, first?.id || "");
      },
      setStaff: (id) => { setStaffState(id); persist(store, id); },
      storeName: boot.stores.find((s) => s.code === store)?.name || store,
      staffHere, managers: staffHere.filter((s) => s.can_approve_discount),
      person: (id) => boot.staff.find((s) => s.id === id),
    };
  }, [boot, store, staff, pending, refreshPending]);

  if (err) return <div style={{ padding: 40 }}><div className="alert err" role="alert"><Icon name="alert" /><div><b>The till cannot start. </b>{err}</div></div></div>;
  if (!value) return <div style={{ padding: 40 }}><span className="spinner" /></div>;
  return <SessionCtx.Provider value={value}>{children}</SessionCtx.Provider>;
}

/* ---------------- all providers ---------------- */
export function Providers({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<{ id: number; msg: string; kind: ToastKind }[]>([]);
  const [modals, setModals] = useState<ActiveModal[]>([]);
  const seq = useRef(0);

  const toast = useCallback((msg: string, kind: ToastKind = "ok") => {
    const id = ++seq.current;
    setToasts((t) => [...t, { id, msg, kind }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === "err" ? 7000 : 3800);
  }, []);

  const open = useCallback((render: Renderer, opts: ModalOpts = {}) =>
    new Promise<unknown>((resolve) => { setModals((m) => [...m, { id: ++seq.current, render, opts, resolve }]); }), []);

  const closeModal = (m: ActiveModal) => (v?: unknown) => {
    setModals((all) => all.filter((x) => x.id !== m.id));
    m.resolve(v);
  };

  return (
    <ToastCtx.Provider value={toast}>
      <ModalCtx.Provider value={open}>
        <SessionProvider>{children}</SessionProvider>
        {modals.map((m) => <ModalHost key={m.id} modal={m} close={closeModal(m)} />)}
        <div className="toasts" aria-live="polite">
          {toasts.map((t) => (
            <div key={t.id} className={"toast" + (t.kind === "err" ? " err" : "")}>
              <span style={{ width: 20, height: 20, flex: "none", color: t.kind === "err" ? "#ff7a7a" : "#f88e2b" }}><Icon name={t.kind === "err" ? "alert" : "check"} /></span>
              <div>{t.msg}</div>
            </div>
          ))}
        </div>
      </ModalCtx.Provider>
    </ToastCtx.Provider>
  );
}
