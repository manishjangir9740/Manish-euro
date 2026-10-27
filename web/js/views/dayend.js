import { api } from '../api.js';
import { h, mount, icon, money, fmtDate, titleCase, alertBox, printNode } from '../util.js';

export function dayEndView(root, ctx) {
  const S = { date: ctx.boot.today, rep: null, loading: true, err: null, showText: false };
  const holder = h('div', { class: 'stack' });
  const dateInput = h('input', { type: 'date', value: S.date, 'aria-label': 'Report date', style: { width: 'auto' }, onchange: (e) => { S.date = e.target.value; load(); } });
  const setDate = (d) => { dateInput.value = S.date = d; load(); };
  mount(root,
    h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Day-end report'), h('p', null, 'Computed from the Shopify orders for the store and date, then reconciled against this till’s invoice register and cash drawer.'))),
    h('div', { class: 'row wrap', style: { marginBottom: '16px' } }, dateInput,
      h('div', { class: 'chips' }, h('button', { class: 'chip', onclick: () => setDate(ctx.boot.today) }, 'Today'), h('button', { class: 'chip', onclick: () => setDate('2026-10-06') }, 'Seed day · 6 Oct')),
      h('button', { class: 'btn btn-ghost btn-sm', style: { marginLeft: 'auto' }, onclick: () => printNode(document.getElementById('report-print')) }, icon('print'), 'Print')),
    holder);

  async function load() {
    S.loading = true; render();
    try { S.rep = await api.dayEnd(ctx.store, S.date); S.err = null; } catch (e) { S.err = e.message; S.rep = null; }
    S.loading = false; render();
  }

  function kpi(lb, v, sub, cls = '') { return h('div', { class: 'kpi ' + cls }, h('div', { class: 'lb' }, lb), h('div', { class: 'v num' }, v), sub && h('div', { class: 's' }, sub)); }

  function bars(title, rows, total, dark) {
    const max = Math.max(1, ...rows.map((r) => r.v));
    return h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, title)),
      rows.length === 0 ? h('div', { class: 'muted' }, 'No bills.') : rows.map((r) => h('div', { class: 'bar-row' },
        h('div', { style: { fontWeight: 600 } }, r.label, r.sub && h('div', { class: 'small muted' }, r.sub)),
        h('div', { class: 'bar' + (dark ? ' blk' : '') }, h('i', { style: { width: Math.max(2, (r.v / max) * 100) + '%' } })),
        h('div', { class: 'right num', style: { fontWeight: 600 } }, money(r.v)))));
  }

  function render() {
    if (S.loading) return mount(holder, h('div', { class: 'kpis' }, Array.from({ length: 4 }, () => h('div', { class: 'skeleton', style: { height: '90px' } }))));
    if (S.err) return mount(holder, alertBox('err', S.err));
    const r = S.rep;
    const methods = Object.keys({ ...r.payment_splits, ...r.payment_refunds });
    const pay = methods.map((m) => ({ label: m.toUpperCase(), v: r.payment_splits[m] || 0, sub: r.payment_refunds[m] ? `refunded ${money(r.payment_refunds[m])} · net ${money(r.payment_net[m])}` : null }));
    const ch = Object.keys(r.channel_totals).map((c) => ({ label: titleCase(c), v: r.channel_totals[c], sub: `${r.channel_splits[c]} bill${r.channel_splits[c] > 1 ? 's' : ''}` }));
    mount(holder,
      h('div', { id: 'report-print', class: 'stack' },
        h('div', { class: 'row' }, h('h2', null, `${ctx.storeName()} · ${fmtDate(r.date)}`), h('span', { class: 'pill ' + (r.mismatches.length ? 'bad' : 'ok') }, r.mismatches.length ? `${r.mismatches.length} mismatch${r.mismatches.length > 1 ? 'es' : ''}` : 'Reconciled')),
        r.bill_count === 0 && alertBox('info', `No bills at ${ctx.storeName()} on ${fmtDate(r.date)}. Try the seed day (6 Oct) or make a sale.`),
        h('div', { class: 'kpis' },
          kpi('Net billed', money(r.net_billed), `${r.bill_count} bill${r.bill_count === 1 ? '' : 's'} · avg ${money(r.average_bill)}`, 'hero'),
          kpi('Gross (MRP)', money(r.gross_sales)), kpi('Discounts', money(r.total_discounts)),
          kpi('Taxable value', money(r.total_taxable)), kpi('GST (CGST + SGST)', money(r.total_tax), `CGST ${money(Math.floor(r.total_tax / 2))} · SGST ${money(r.total_tax - Math.floor(r.total_tax / 2))}`),
          kpi('Refunds', money(r.total_refunds), `GST reversed ${money(r.refund_tax)}`), kpi('Net after refunds', money(r.net_billed - r.total_refunds))),
        h('div', { class: 'two' }, bars('By payment method', pay, r.net_billed, true), bars('By sales channel', ch, r.net_billed, false)),
        h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Reconciliation')),
          r.mismatches.length ? h('div', { class: 'stack-sm' }, r.mismatches.map((m) => alertBox('err', m))) : alertBox('ok', 'Invoice register and cash till agree with Shopify.')),
        h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Printable report'), h('button', { class: 'btn btn-ghost btn-sm', style: { marginLeft: 'auto' }, onclick: () => { S.showText = !S.showText; render(); } }, S.showText ? 'Hide' : 'Show text version')),
          S.showText && h('pre', { class: 'report' }, r.report_text))));
  }

  load();
  return { destroy() {}, onContext() { load(); } };
}
