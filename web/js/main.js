import { api } from './api.js';
import { h, mount, icon, toast, alertBox } from './util.js';
import { sellView } from './views/sell.js';
import { ordersView } from './views/orders.js';
import { tillView } from './views/till.js';
import { dayEndView } from './views/dayend.js';
import { activityView } from './views/activity.js';

const ROUTES = [
  { id: 'sell', label: 'Sell', icon: 'sell', title: 'New sale', view: sellView },
  { id: 'orders', label: 'Refunds', icon: 'orders', title: 'Bills & refunds', view: ordersView },
  { id: 'till', label: 'Till', icon: 'till', title: 'Cash till', view: tillView },
  { id: 'dayend', label: 'Day-end', icon: 'report', title: 'Day-end report', view: dayEndView },
  { id: 'activity', label: 'Activity', icon: 'activity', title: 'Audit trail', view: activityView },
];

/** Shared session context: which store this till is in and who is at it. */
export const ctx = {
  boot: null, store: null, staff: null, pending: 0,
  listeners: new Set(),
  set(patch) {
    Object.assign(this, patch);
    try { localStorage.setItem('eluno.ctx', JSON.stringify({ store: this.store, staff: this.staff })); } catch { /* private mode */ }
    this.listeners.forEach((fn) => fn());
  },
  staffHere() { return this.boot.staff.filter((s) => s.store === this.store); },
  cashiers() { return this.staffHere().filter((s) => s.role !== 'optometrist'); },
  managers() { return this.staffHere().filter((s) => s.can_approve_discount); },
  storeName() { return this.boot.stores.find((s) => s.code === this.store)?.name || this.store; },
  person(id) { return this.boot.staff.find((s) => s.id === id); },
};

let current = null;

function logo() {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 40 40');
  s.innerHTML = '<circle cx="20" cy="20" r="14" fill="none" stroke="#f88e2b" stroke-width="5"/><circle cx="20" cy="20" r="5" fill="#fff"/>';
  return s;
}

function renderChrome() {
  const route = currentRoute();
  mount(document.getElementById('rail'),
    h('div', { class: 'brand', title: 'Eluno' }, logo()),
    ROUTES.map((r) => h('button', {
      class: 'nav-item', 'aria-current': r.id === route.id ? 'page' : null, onclick: () => { location.hash = '#/' + r.id; },
    }, icon(r.icon), r.label, r.id === 'sell' && ctx.pending > 0 && h('span', { class: 'dot', title: `${ctx.pending} paid bill(s) not yet in Shopify` }))),
    h('div', { class: 'spacer' }));

  const storeSel = h('select', { id: 'ctx-store', 'aria-label': 'Store', onchange: (e) => {
    const store = e.target.value;
    const first = ctx.boot.staff.find((s) => s.store === store && s.role === 'sales') || ctx.boot.staff.find((s) => s.store === store);
    ctx.set({ store, staff: first?.id });
  } }, ctx.boot.stores.map((s) => h('option', { value: s.code, selected: s.code === ctx.store }, `${s.name}`)));
  const staffSel = h('select', { id: 'ctx-staff', 'aria-label': 'Staff', onchange: (e) => ctx.set({ staff: e.target.value }) },
    ctx.staffHere().map((s) => h('option', { value: s.id, selected: s.id === ctx.staff }, `${s.name} · ${s.role.replace('_', ' ')}`)));

  mount(document.getElementById('topbar'),
    h('div', { class: 'title' }, route.title, h('span', { class: 'env-pill', title: 'Running against the bundled mock of Shopify, the store tool and the payment terminal' }, 'Mock')),
    ctx.pending > 0 && h('button', { class: 'btn btn-sm btn-primary', onclick: syncPending }, icon('refresh'), `Sync ${ctx.pending} pending bill${ctx.pending > 1 ? 's' : ''}`),
    h('div', { class: 'ctx' }, h('label', { for: 'ctx-store' }, 'Store'), storeSel),
    h('div', { class: 'ctx' }, h('label', { for: 'ctx-staff' }, 'Staff'), staffSel));
}

function currentRoute() {
  const id = (location.hash.replace(/^#\//, '') || 'sell').split('?')[0];
  return ROUTES.find((r) => r.id === id) || ROUTES[0];
}

async function refreshPending() {
  try { ctx.pending = (await api.pending()).pending.length; } catch { /* non-critical */ }
}

async function syncPending() {
  try {
    const { results } = await api.syncPending();
    const ok = results.filter((r) => r.status === 'synced').length;
    toast(`${ok} of ${results.length} pending bills synced to Shopify`, ok === results.length ? 'ok' : 'err');
  } catch (e) { toast(e.message, 'err'); }
  await refreshPending();
  renderChrome();
}

async function route() {
  const r = currentRoute();
  current?.destroy?.();
  renderChrome();
  const view = document.getElementById('view');
  mount(view);
  window.scrollTo(0, 0);
  current = r.view(view, ctx, { refreshPending: async () => { await refreshPending(); renderChrome(); } });
}

async function start() {
  const view = document.getElementById('view');
  try {
    ctx.boot = await api.bootstrap();
  } catch (e) {
    mount(view, alertBox('err', h('b', null, 'The till cannot start. '), e.message));
    return;
  }
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem('eluno.ctx') || '{}'); } catch { /* ignore */ }
  const store = ctx.boot.stores.some((s) => s.code === saved.store) ? saved.store : (ctx.boot.stores.find((s) => s.code === 'HSR') || ctx.boot.stores[0]).code;
  ctx.store = store;
  const here = ctx.staffHere();
  ctx.staff = here.some((s) => s.id === saved.staff) ? saved.staff : (here.find((s) => s.role === 'sales') || here[0])?.id;
  await refreshPending();
  // Store/staff changes: re-render chrome and let the active view react
  ctx.listeners.add(() => { renderChrome(); current?.onContext?.(); });
  window.addEventListener('hashchange', route);
  route();
}

start();
