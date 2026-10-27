// Thin fetch wrapper. Every failure becomes an ApiError whose message is safe to show to staff.

export class ApiError extends Error {
  constructor(status, code, message, details = []) {
    super(message);
    this.status = status; this.code = code; this.details = details;
  }
}

async function request(path, opts = {}) {
  let res;
  try {
    res = await fetch(path, {
      method: opts.method || 'GET',
      headers: opts.body ? { 'Content-Type': 'application/json' } : undefined,
      body: opts.body ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    });
  } catch (e) {
    if (e.name === 'AbortError') throw e;
    throw new ApiError(0, 'Offline', 'Cannot reach the till server. Check the connection and try again.');
  }
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error page */ }
  if (!res.ok) {
    throw new ApiError(res.status, data?.error || 'Error', data?.message || `Request failed (${res.status})`, data?.details || []);
  }
  return data;
}

const qs = (o) => Object.entries(o).filter(([, v]) => v != null && v !== '').map(([k, v]) => `${k}=${encodeURIComponent(v)}`).join('&');

export const api = {
  bootstrap: () => request('/api/bootstrap'),
  customer: (phone) => request('/api/customer?' + qs({ phone })),
  catalog: (store, phone) => request('/api/catalog?' + qs({ store, phone })),
  quote: (body, signal) => request('/api/quote', { method: 'POST', body, signal }),
  checkout: (body) => request('/api/checkout', { method: 'POST', body }),
  orders: (store, date) => request('/api/orders?' + qs({ store, date })),
  refund: (body) => request('/api/refund', { method: 'POST', body }),
  dayEnd: (store, date) => request('/api/day-end?' + qs({ store, date })),
  till: (store, date) => request('/api/till?' + qs({ store, date })),
  tillOpen: (body) => request('/api/till/open', { method: 'POST', body }),
  tillMove: (body) => request('/api/till/move', { method: 'POST', body }),
  tillClose: (body) => request('/api/till/close', { method: 'POST', body }),
  audit: () => request('/api/audit?limit=300'),
  pending: () => request('/api/pending'),
  syncPending: () => request('/api/sync-pending', { method: 'POST', body: {} }),
};
