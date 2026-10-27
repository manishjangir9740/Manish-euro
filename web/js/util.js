// DOM helpers, formatting, icons, toasts and modals. No framework: the till has to load fast on a tablet.

export function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === 'class') el.className = v;
    else if (k === 'html') el.innerHTML = v;
    else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
    else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2).toLowerCase(), v);
    else if (k === 'value' || k === 'checked' || k === 'disabled' || k === 'selected') el[k] = v;
    else el.setAttribute(k, v === true ? '' : v);
  }
  append(el, kids);
  return el;
}
function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k.nodeType ? k : document.createTextNode(String(k)));
  }
}
export function mount(el, ...kids) { el.replaceChildren(); append(el, kids); return el; }
export const $ = (sel, root = document) => root.querySelector(sel);

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 2, maximumFractionDigits: 2 });
const inr0 = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', minimumFractionDigits: 0, maximumFractionDigits: 0 });
export const money = (paise) => inr.format((paise || 0) / 100);
/** Whole rupees when there are no paise (catalog prices), otherwise exact. */
export const moneyShort = (paise) => (paise % 100 === 0 ? inr0 : inr).format(paise / 100);
export const pct = (bps) => `${bps / 100}%`;
export function fmtTime(iso) {
  if (!iso) return '';
  return new Date(iso).toLocaleTimeString('en-IN', { hour: '2-digit', minute: '2-digit', hour12: true });
}
export function fmtDate(iso) {
  if (!iso) return '';
  return new Date(iso.length === 10 ? iso + 'T00:00:00' : iso).toLocaleDateString('en-IN', { day: '2-digit', month: 'short', year: 'numeric' });
}
export const titleCase = (s) => String(s || '').replace(/[_:]/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
export const signed = (n) => (n == null ? '–' : (n > 0 ? '+' : '') + Number(n).toFixed(2));
export function debounce(fn, ms) {
  let t;
  const d = (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
  d.cancel = () => clearTimeout(t);
  return d;
}

/** Normalise whatever was typed into the E.164 number Shopify stores: +91XXXXXXXXXX. */
export function normalisePhone(raw) {
  const digits = String(raw || '').replace(/\D/g, '');
  if (!digits) return '';
  if (digits.length === 10) return '+91' + digits;
  if (digits.length === 12 && digits.startsWith('91')) return '+' + digits;
  return '+' + digits;
}

const P = {
  sell: 'M7 4h10l3 4v12H4V8l3-4zM4 8h16M9 12h6M9 16h4',
  orders: 'M9 14L4 9l5-5M4 9h10a6 6 0 010 12h-3',
  till: 'M3 7h16a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7zm0 0l2-3h12M16 14h2',
  report: 'M5 20V10M12 20V4M19 20v-7M3 20h18',
  activity: 'M12 7v5l3 2M21 12a9 9 0 11-3-6.7M21 4v5h-5',
  search: 'M11 4a7 7 0 100 14 7 7 0 000-14zm9 16l-4-4',
  check: 'M5 12.5l4.5 4.5L19 7.5',
  x: 'M6 6l12 12M18 6L6 18',
  print: 'M7 9V4h10v5M7 17H5a1 1 0 01-1-1v-5a2 2 0 012-2h12a2 2 0 012 2v5a1 1 0 01-1 1h-2M7 14h10v6H7z',
  alert: 'M12 3l10 18H2L12 3zm0 7v5m0 3h.01',
  info: 'M12 3a9 9 0 100 18 9 9 0 000-18zm0 8v5m0-8.5h.01',
  upi: 'M5 5h5v5H5zM14 5h5v5h-5zM5 14h5v5H5zM14 14h2v2h-2zM18 14h1v5h-5v-1',
  card: 'M3 6h18v12H3zM3 10h18M6 15h4',
  cash: 'M3 7h18v10H3zM12 9.5a2.5 2.5 0 100 5 2.5 2.5 0 000-5zM6 10v.01M18 14v.01',
  glasses: 'M2 12h2m16 0h2M6 8a4 4 0 100 8 4 4 0 000-8zm12 0a4 4 0 100 8 4 4 0 000-8zM10 12h4',
  plus: 'M12 5v14M5 12h14',
  tag: 'M3 12V4h8l10 10-8 8L3 12zm5-4h.01',
  user: 'M12 12a4 4 0 100-8 4 4 0 000 8zM4 21a8 8 0 0116 0',
  refresh: 'M4 12a8 8 0 0114-5.3L20 9M20 4v5h-5M20 12a8 8 0 01-14 5.3L4 15M4 20v-5h5',
  lock: 'M6 11h12v9H6zM8 11V8a4 4 0 118 0v3',
};
export function icon(name, cls) {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24');
  s.setAttribute('fill', 'none');
  s.setAttribute('stroke', 'currentColor');
  s.setAttribute('stroke-width', '1.8');
  s.setAttribute('stroke-linecap', 'round');
  s.setAttribute('stroke-linejoin', 'round');
  s.setAttribute('aria-hidden', 'true');
  if (cls) s.setAttribute('class', cls);
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', P[name] || P.info);
  s.append(p);
  return s;
}

export function frameArt() {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 70 30');
  s.setAttribute('fill', 'none');
  s.setAttribute('stroke', 'currentColor');
  s.setAttribute('stroke-width', '2.4');
  s.setAttribute('stroke-linecap', 'round');
  s.innerHTML = '<rect x="3" y="6" width="25" height="18" rx="8"/><rect x="42" y="6" width="25" height="18" rx="8"/><path d="M28 13c4-3 10-3 14 0"/><path d="M3 12L0 9m67 3l3-3"/>';
  return s;
}

export function spinner() { return h('span', { class: 'spinner', role: 'status', 'aria-label': 'Loading' }); }

export function toast(message, kind = 'ok') {
  const root = document.getElementById('toasts');
  const t = h('div', { class: 'toast' + (kind === 'err' ? ' err' : '') }, icon(kind === 'err' ? 'alert' : 'check'), h('div', null, message));
  t.querySelector('svg').style.cssText = 'width:20px;height:20px;flex:none;color:' + (kind === 'err' ? '#ff7a7a' : '#f88e2b');
  root.append(t);
  setTimeout(() => t.remove(), kind === 'err' ? 7000 : 3800);
}

/** Opens a modal. `build(close)` returns {head, body, foot} nodes. Resolves when closed. */
export function openModal(build, { wide = false, dismissable = true } = {}) {
  const root = document.getElementById('modal-root');
  const prevFocus = document.activeElement;
  return new Promise((resolve) => {
    const overlay = h('div', { class: 'overlay', role: 'dialog', 'aria-modal': 'true' });
    const close = (val) => { document.removeEventListener('keydown', onKey); overlay.remove(); document.body.classList.remove('printing-modal'); prevFocus?.focus?.(); resolve(val); };
    const onKey = (e) => { if (e.key === 'Escape' && dismissable) close(undefined); };
    const parts = build(close);
    const modal = h('div', { class: 'modal' + (wide ? ' wide' : '') },
      parts.head && h('div', { class: 'modal-head' }, parts.head),
      h('div', { class: 'modal-body' }, parts.body),
      parts.foot && h('div', { class: 'modal-foot' }, parts.foot));
    overlay.append(modal);
    if (dismissable) overlay.addEventListener('mousedown', (e) => { if (e.target === overlay) close(undefined); });
    document.addEventListener('keydown', onKey);
    root.append(overlay);
    (modal.querySelector('[autofocus]') || modal.querySelector('button, input, select'))?.focus();
  });
}

export async function confirmDialog({ title, body, confirmLabel = 'Confirm', danger = false }) {
  return openModal((close) => ({
    head: h('h2', null, title),
    body: body,
    foot: [
      h('button', { class: 'btn btn-ghost', onclick: () => close(false) }, 'Cancel'),
      h('button', { class: 'btn ' + (danger ? 'btn-dark' : 'btn-primary'), onclick: () => close(true), autofocus: true }, confirmLabel),
    ],
  }));
}

export function alertBox(kind, ...kids) {
  return h('div', { class: 'alert ' + kind, role: kind === 'err' ? 'alert' : 'status' }, icon(kind === 'err' || kind === 'warn' ? 'alert' : kind === 'ok' ? 'check' : 'info'), h('div', { class: 'grow' }, kids));
}

export function printNode(node) {
  document.body.classList.add('printing-modal');
  const clone = node.cloneNode(true);
  const wrap = h('div', { class: 'overlay', style: { position: 'static' } }, clone);
  wrap.id = 'print-sheet';
  document.getElementById('modal-root').append(wrap);
  window.print();
  wrap.remove();
  document.body.classList.remove('printing-modal');
}
