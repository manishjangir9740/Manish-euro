import { api } from '../api.js';
import { h, mount, icon, money, fmtTime, titleCase, toast, alertBox, spinner, openModal, printNode } from '../util.js';

export function ordersView(root, ctx) {
  const S = { date: ctx.boot.today, orders: [], loading: true, err: null, q: '', sel: null, picked: new Set(), reason: 'CHANGED_MIND', busy: false };
  let focusId = null;
  try { focusId = sessionStorage.getItem('eluno.focusOrder'); sessionStorage.removeItem('eluno.focusOrder'); } catch { /* ignore */ }

  const listHolder = h('div', { class: 'order-list' });
  const detail = h('section', { class: 'card', style: { position: 'sticky', top: '78px' } });
  const dateInput = h('input', { type: 'date', value: S.date, max: S.date, 'aria-label': 'Bill date', style: { width: 'auto' }, onchange: (e) => { S.date = e.target.value; S.sel = null; load(); } });
  const search = h('input', { type: 'search', placeholder: 'Find invoice number', 'aria-label': 'Find invoice', style: { maxWidth: '260px' }, oninput: (e) => { S.q = e.target.value.toLowerCase(); renderList(); } });

  mount(root,
    h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Bills & refunds'), h('p', null, `${ctx.storeName()} · full or per-line refund through Shopify's refund flow. Tax is reversed per line; frames go back to stock here, lenses do not.`))),
    h('div', { class: 'row wrap', style: { marginBottom: '14px' } },
      dateInput, search,
      h('div', { class: 'chips' },
        h('button', { class: 'chip', onclick: () => { dateInput.value = S.date = ctx.boot.today; S.sel = null; load(); } }, 'Today'),
        h('button', { class: 'chip', title: 'Seed data from the starter kit', onclick: () => { dateInput.value = S.date = '2026-10-06'; S.sel = null; load(); } }, 'Seed day · 6 Oct')),
      h('button', { class: 'btn btn-ghost btn-sm', style: { marginLeft: 'auto' }, onclick: load }, icon('refresh'), 'Reload')),
    h('div', { class: 'orders' }, h('div', null, listHolder), detail));

  async function load() {
    S.loading = true; S.err = null; renderList(); renderDetail();
    try { S.orders = (await api.orders(ctx.store, S.date)).orders; }
    catch (e) { S.err = e.message; S.orders = []; }
    S.loading = false;
    if (focusId) { S.sel = S.orders.find((o) => String(o.order_id) === focusId) || null; focusId = null; S.picked = new Set(); }
    else if (S.sel) S.sel = S.orders.find((o) => o.order_id === S.sel.order_id) || null;
    renderList(); renderDetail();
  }

  const status = (o) => {
    if (o.cancelled) return h('span', { class: 'pill bad' }, 'Cancelled');
    if (o.lines.length && o.lines.every((l) => l.refunded)) return h('span', { class: 'pill black' }, 'Refunded');
    if (o.refunded > 0) return h('span', { class: 'pill soft' }, 'Part refunded');
    return h('span', { class: 'pill ok' }, 'Paid');
  };

  function renderList() {
    if (S.loading) return mount(listHolder, Array.from({ length: 4 }, () => h('div', { class: 'skeleton', style: { height: '64px' } })));
    if (S.err) return mount(listHolder, alertBox('err', S.err));
    const rows = S.orders.filter((o) => !S.q || o.invoice_no.toLowerCase().includes(S.q));
    if (!rows.length) return mount(listHolder, h('div', { class: 'card empty' }, icon('orders'), h('div', null, S.orders.length ? 'No invoice matches.' : `No bills at ${ctx.storeName()} on ${S.date}.`)));
    mount(listHolder, rows.map((o) => h('button', { class: 'order-row', 'aria-pressed': S.sel?.order_id === o.order_id ? 'true' : 'false', onclick: () => { S.sel = o; S.picked = new Set(); S.result = null; renderList(); renderDetail(); } },
      h('div', null, h('div', { class: 'inv' }, o.invoice_no), h('div', { class: 'small muted' }, `${fmtTime(o.created_at)} · ${titleCase(o.channel)} · ${o.payment_method.toUpperCase()} · ${o.lines.length} line${o.lines.length > 1 ? 's' : ''}`)),
      h('div', { class: 'right' }, h('div', { class: 'num', style: { fontWeight: 650 } }, money(o.total)), status(o)))));
  }

  function renderDetail() {
    const o = S.sel;
    if (!o) return mount(detail, h('div', { class: 'empty' }, icon('orders'), h('div', null, 'Select a bill to refund.')));
    const open = o.lines.filter((l) => !l.refunded);
    const full = open.length > 0 && open.length === o.lines.length && S.picked.size === open.length;
    const amount = o.lines.filter((l) => S.picked.has(l.line_id)).reduce((a, l) => a + l.gross, 0);
    const tax = o.lines.filter((l) => S.picked.has(l.line_id)).reduce((a, l) => a + l.tax, 0);
    mount(detail,
      h('div', { class: 'card-head' }, h('div', null, h('h2', null, o.invoice_no), h('div', { class: 'small muted' }, `Shopify ${o.name} · ${o.payment_method.toUpperCase()} · staff ${o.staff_id || '–'}`)), h('span', { style: { marginLeft: 'auto' } }, status(o))),
      h('div', { class: 'stack-sm' }, o.lines.map((l) => {
        const lbl = h('label', { class: 'check-line' + (l.refunded ? ' disabled' : '') },
          h('input', { type: 'checkbox', checked: S.picked.has(l.line_id), disabled: l.refunded || o.cancelled, onchange: (e) => { e.target.checked ? S.picked.add(l.line_id) : S.picked.delete(l.line_id); renderDetail(); } }),
          h('div', null, h('div', { style: { fontWeight: 600 } }, l.name), h('div', { class: 'small muted' }, l.refunded ? 'Already refunded' : l.line_type === 'frame' ? 'Frame · goes back to stock at this store' : 'Lens · made to order, not restocked', ` · GST ${money(l.tax)}`)),
          h('div', { class: 'num', style: { fontWeight: 650 } }, money(l.gross)));
        return lbl;
      })),
      o.refunds.length > 0 && h('div', { class: 'small muted', style: { marginTop: '10px' } }, 'Credit notes: ', o.refunds.map((r) => `${r.credit_note_no} (${money(r.amount)})`).join(', ')),
      open.length > 0 && !o.cancelled && h('div', { class: 'stack-sm', style: { marginTop: '14px' } },
        h('div', { class: 'row' },
          h('button', { class: 'btn btn-ghost btn-sm', onclick: () => { S.picked = new Set(open.map((l) => l.line_id)); renderDetail(); } }, 'Select all remaining'),
          S.picked.size > 0 && h('button', { class: 'btn btn-ghost btn-sm', onclick: () => { S.picked = new Set(); renderDetail(); } }, 'Clear')),
        h('label', { class: 'field' }, 'Reason', h('select', { onchange: (e) => { S.reason = e.target.value; } }, ctx.boot.refund_reasons.map((r) => h('option', { value: r, selected: r === S.reason }, titleCase(r))))),
        h('div', { class: 'totals', style: { borderRadius: '12px', border: '1px solid var(--line)' } },
          h('div', { class: 'tr' }, h('span', null, `${full ? 'Full' : S.picked.size ? 'Partial' : 'Refund'} · ${S.picked.size} line${S.picked.size === 1 ? '' : 's'}`), h('b', { class: 'num' }, money(amount))),
          h('div', { class: 'tr sub' }, h('span', null, 'of which GST reversed'), h('span', { class: 'num' }, money(tax))),
          o.payment_method === 'cash' && h('div', { class: 'tr sub' }, h('span', null, 'Paid out of the cash drawer'), h('span', null, ''))),
        h('button', { class: 'btn btn-dark btn-lg', disabled: S.picked.size === 0 || S.busy, onclick: () => doRefund(o, amount, full) }, S.busy && spinner(), 'Refund ', S.picked.size ? money(amount) : '')),
      S.result && resultCard(S.result));
  }

  function resultCard(r) {
    const sheet = h('div', { class: 'stack-sm' },
      h('div', { class: 'row' }, h('div', { class: 'success-mark', style: { width: '40px', height: '40px' } }, icon('check')), h('div', null, h('b', null, `Refunded ${money(r.refund_amount)}`), h('div', { class: 'small muted' }, `Credit note ${r.credit_note_no} against ${r.original_invoice_no}`))),
      h('div', { class: 'small' }, `Taxable ${money(r.taxable_reversed)} + GST ${money(r.tax_reversed)} reversed. `, r.lines.some((l) => l.restock) ? 'Frame restocked at this store.' : 'Nothing restocked (lens only).', r.till_recorded ? ' Recorded as a cash refund in the till.' : ''));
    return h('div', { class: 'alert ok', style: { marginTop: '14px' } }, icon('check'), sheet);
  }

  async function doRefund(o, amount, full) {
    const names = o.lines.filter((l) => S.picked.has(l.line_id)).map((l) => l.name);
    const ok = await openModal((close) => ({
      head: h('h2', null, `Refund ${money(amount)}?`),
      body: [h('div', null, `${full ? 'Full refund' : 'Partial refund'} of ${o.invoice_no} for:`), h('ul', { style: { margin: 0, paddingLeft: '18px' } }, names.map((n) => h('li', null, n))),
        h('div', { class: 'small muted' }, `Reason: ${titleCase(S.reason)}. The amount goes back to the original ${o.payment_method.toUpperCase()} payment. This cannot be undone.`)],
      foot: [h('button', { class: 'btn btn-ghost', onclick: () => close(false) }, 'Cancel'), h('button', { class: 'btn btn-dark', autofocus: true, onclick: () => close(true) }, 'Refund')],
    }));
    if (!ok) return;
    S.busy = true; renderDetail();
    try {
      S.result = await api.refund({ order_id: o.order_id, staff_id: ctx.staff, reason: S.reason, line_ids: full ? [] : [...S.picked] });
      toast(`Credit note ${S.result.credit_note_no} issued`);
      S.picked = new Set();
      const keep = S.result;
      S.busy = false;
      await load();
      S.result = keep; renderDetail();
    } catch (e) {
      S.busy = false; renderDetail(); toast(e.message, 'err');
    }
  }

  load();
  return { destroy() {}, onContext() { S.sel = null; load(); } };
}
