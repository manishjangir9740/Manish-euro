import type { AuditEvent, Bootstrap, CheckoutResult, Customer, DayEnd, Frame, Lens, Order, Quote, RefundResult, Rx, TillSession } from "./types";

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details: string[] = []) {
    super(message);
  }
}

interface Opts { method?: "GET" | "POST"; body?: unknown; signal?: AbortSignal }

async function request<T>(path: string, opts: Opts = {}): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: opts.method || "GET",
      headers: opts.body ? { "Content-Type": "application/json" } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
      cache: "no-store",
    });
  } catch (e) {
    if (e instanceof DOMException && e.name === "AbortError") throw e;
    throw new ApiError(0, "Offline", "Cannot reach the till server. Check the connection and try again.");
  }
  let data: { error?: string; message?: string; details?: string[] } | null = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) throw new ApiError(res.status, data?.error || "Error", data?.message || `Request failed (${res.status})`, data?.details || []);
  return data as T;
}

const qs = (o: Record<string, string | undefined>) =>
  Object.entries(o).filter(([, v]) => v != null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(v as string)}`).join("&");

export interface QuoteBody {
  phone: string; store: string; staff_id?: string; channel: string;
  pairs: { frame_id?: number; lens_id?: number; pair_ref: string }[];
  manager_discount: { percent: string; approver_id: string; reason_code: string } | null;
}

export const api = {
  bootstrap: () => request<Bootstrap>("/api/bootstrap"),
  customer: (phone: string) => request<{ customer: Customer; prescription: Rx | null }>("/api/customer?" + qs({ phone })),
  catalog: (store: string, phone: string) => request<{ frames: Frame[]; lenses: Lens[] }>("/api/catalog?" + qs({ store, phone })),
  quote: (body: QuoteBody, signal?: AbortSignal) => request<Quote>("/api/quote", { method: "POST", body, signal }),
  checkout: (body: QuoteBody & { payment_method: string }) => request<CheckoutResult>("/api/checkout", { method: "POST", body }),
  orders: (store: string, date: string) => request<{ orders: Order[] }>("/api/orders?" + qs({ store, date })),
  refund: (body: { order_id: number; staff_id: string; reason: string; line_ids: number[] }) => request<RefundResult>("/api/refund", { method: "POST", body }),
  dayEnd: (store: string, date: string) => request<DayEnd>("/api/day-end?" + qs({ store, date })),
  till: (store: string, date?: string) => request<{ session: TillSession | null }>("/api/till?" + qs({ store, date })),
  tillOpen: (body: { store: string; staff_id: string; float: string }) => request<{ session: TillSession }>("/api/till/open", { method: "POST", body }),
  tillMove: (body: { session_id: string; type: string; amount: string; reason: string; staff_id: string }) => request<{ session: TillSession }>("/api/till/move", { method: "POST", body }),
  tillClose: (body: { session_id: string; staff_id: string; counted: string; note: string }) => request<{ session: TillSession }>("/api/till/close", { method: "POST", body }),
  audit: () => request<{ events: AuditEvent[] }>("/api/audit?limit=300"),
  pending: () => request<{ pending: { invoice_no: string }[] }>("/api/pending"),
  syncPending: () => request<{ results: { invoice_no: string; status: string }[] }>("/api/sync-pending", { method: "POST", body: {} }),
};
