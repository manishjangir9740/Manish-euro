import { api } from '../api.js';
import { h, mount, icon, money, fmtTime, titleCase, toast, alertBox, spinner, openModal } from '../util.js';

const TYPE_LABEL = { cash_sale: 'Cash sale', cash_refund: 'Cash refund', paid_in: 'Paid in', paid_out: 'Paid out' };

export function tillView(root, ctx) {
  const S = { session: null, loading: true, err: null };
  const holder = h('div');
  mount(root,
    h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Cash till'), h('p', null, `${ctx.storeName()} · one drawer per store per day. Cash sales and cash refunds post here automatically.`))),
    holder);

  async function load() {
    S.loading = true; render();
    try { S.session = (await api.till(ctx.store)).session; S.err = null; } catch (e) { S.err = e.message; }
    S.loading = false; render();
  }

  function render() {
    if (S.loading) return mount(holder, h('div', { class: 'skeleton', style: { height: '160px' } }));
    if (S.err) return mount(holder, alertBox('err', S.err));
    const s = S.session;
    if (!s) return mount(holder, openCard());
    mount(holder, h('div', { class: 'till-grid' }, h('div', { class: 'stack' }, summary(s), movements(s)), h('div', { class: 'stack' }, s.is_open ? [moveCard(s), closeCard(s)] : closedCard(s))));
  }

  function openCard() {
    const f = h('input', { type: 'number', min: '0', step: '1', value: '3000', 'aria-label': 'Opening float in rupees', style: { fontSize: '24px', fontWeight: 650, minHeight: '56px' } });
    let busy = false;
    const btn = h('button', { class: 'btn btn-primary btn-lg', onclick: async () => {
      if (busy) return; busy = true; btn.disabled = true;
      try { S.session = (await api.tillOpen({ store: ctx.store, staff_id: ctx.staff, float: f.value })).session; toast('Till opened'); render(); }
      catch (e) { toast(e.message, 'err'); busy = false; btn.disabled = false; }
    } }, icon('till'), 'Open till');
    return h('div', { class: 'card', style: { maxWidth: '520px' } },
      h('div', { class: 'card-head' }, h('div', { class: 'step-no' }, icon('till')), h('h2', null, 'Open today’s till')),
      h('p', { class: 'muted', style: { marginBottom: '14px' } }, `No till session for ${ctx.storeName()} today. Count the drawer and enter the opening float (₹).`),
      h('label', { class: 'field' }, 'Opening float (₹)', f), h('div', { style: { height: '14px' } }), btn);
  }

  function summary(s) {
    const sum = (t) => s.movements.filter((m) => m.type === t).reduce((a, m) => a + m.amount_paise, 0);
    const kpi = (lb, v, sub) => h('div', { class: 'kpi' }, h('div', { class: 'lb' }, lb), h('div', { class: 'v num' }, money(v)), sub && h('div', { class: 's' }, sub));
    return h('div', { class: 'stack' },
      h('div', { class: 'big-expected' }, h('div', { class: 'lb' }, s.is_open ? 'Cash that should be in the drawer' : 'Expected cash at close'), h('div', { class: 'v num' }, money(s.expected_cash_paise)),
        h('div', { class: 'small', style: { color: '#bdbdbd' } }, `${s.session_id} · opened ${fmtTime(s.opened_at)} by ${ctx.person(s.opened_by)?.name || s.opened_by}`)),
      h('div', { class: 'kpis' }, kpi('Opening float', s.opening_float_paise), kpi('Cash sales', sum('cash_sale'), `${s.movements.filter((m) => m.type === 'cash_sale').length} bills`), kpi('Cash refunds', sum('cash_refund')), kpi('Paid in', sum('paid_in')), kpi('Paid out', sum('paid_out'))));
  }

  function movements(s) {
    return h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Movements')),
      s.movements.length === 0 ? h('div', { class: 'empty' }, icon('till'), h('div', null, 'No cash movements yet.')) :
        h('div', { class: 'scroll-x' }, h('table', { class: 't' },
          h('thead', null, h('tr', null, ['Time', 'Type', 'Reference', 'Reason', 'By', 'Amount'].map((x, i) => h('th', { class: i === 5 ? 'r' : '' }, x)))),
          h('tbody', null, [...s.movements].reverse().map((m) => h('tr', null,
            h('td', null, fmtTime(m.at)), h('td', null, h('span', { class: 'mv-type' }, TYPE_LABEL[m.type] || m.type)), h('td', { class: 'small' }, m.ref), h('td', null, m.reason ? titleCase(m.reason) : ''), h('td', null, m.staff_id || ''),
            h('td', { class: 'r num ' + (m.amount_paise < 0 ? 'var-neg' : 'var-pos'), style: { fontWeight: 600 } }, (m.amount_paise > 0 ? '+' : '') + money(m.amount_paise))))))));
  }

  function moveCard(s) {
    let type = 'paid_out';
    const amt = h('input', { type: 'number', min: '0', step: '1', placeholder: '120', 'aria-label': 'Amount in rupees' });
    const reason = h('input', { type: 'text', placeholder: 'e.g. courier, tea & snacks', 'aria-label': 'Reason' });
    const segHolder = h('div');
    const drawSeg = () => mount(segHolder, h('div', { class: 'seg full' }, [['paid_out', 'Paid out'], ['paid_in', 'Paid in']].map(([v, l]) => h('button', { 'aria-pressed': type === v ? 'true' : 'false', onclick: () => { type = v; drawSeg(); } }, l))));
    drawSeg();
    return h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Paid in / paid out')),
      h('div', { class: 'stack-sm' }, segHolder,
        h('label', { class: 'field' }, 'Amount (₹)', amt), h('label', { class: 'field' }, 'Reason (required)', reason),
        h('button', { class: 'btn btn-dark', onclick: async () => {
          if (!reason.value.trim()) return toast('A reason is required.', 'err');
          try { S.session = (await api.tillMove({ session_id: s.session_id, type, amount: amt.value, reason: reason.value, staff_id: ctx.staff })).session; toast('Recorded'); render(); }
          catch (e) { toast(e.message, 'err'); }
        } }, 'Record')));
  }

  function closeCard(s) {
    const counted = h('input', { type: 'number', min: '0', step: '0.01', placeholder: money(s.expected_cash_paise).replace(/[₹,]/g, ''), 'aria-label': 'Counted cash in rupees', style: { fontSize: '20px', fontWeight: 650 } });
    const note = h('input', { type: 'text', placeholder: 'Explain any difference (optional)', 'aria-label': 'Variance note' });
    const live = h('div', { class: 'small muted' }, 'Variance appears as you type.');
    counted.addEventListener('input', () => {
      if (counted.value === '') return live.replaceChildren('Variance appears as you type.');
      const v = Math.round(parseFloat(counted.value) * 100) - s.expected_cash_paise;
      live.className = 'small ' + (v === 0 ? 'var-pos' : Math.abs(v) > ctx.boot.till_variance_alert ? 'var-neg' : 'muted');
      live.textContent = v === 0 ? 'Drawer matches.' : `${v > 0 ? 'Over' : 'Short'} by ${money(Math.abs(v))}` + (Math.abs(v) > ctx.boot.till_variance_alert ? ' · above the ₹200 limit, Finance will be alerted' : '');
    });
    return h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Close till')),
      h('div', { class: 'stack-sm' }, h('label', { class: 'field' }, 'Counted cash (₹)', counted), live, h('label', { class: 'field' }, 'Note', note),
        h('button', { class: 'btn btn-primary', onclick: async () => {
          if (counted.value === '') return toast('Enter the counted amount.', 'err');
          const ok = await openModal((close) => ({ head: h('h2', null, 'Close the till for the day?'), body: h('div', null, `Counted ${money(Math.round(parseFloat(counted.value) * 100))} against expected ${money(s.expected_cash_paise)}. A closed till cannot take more cash sales today.`),
            foot: [h('button', { class: 'btn btn-ghost', onclick: () => close(false) }, 'Cancel'), h('button', { class: 'btn btn-dark', autofocus: true, onclick: () => close(true) }, 'Close till')] }));
          if (!ok) return;
          try { S.session = (await api.tillClose({ session_id: s.session_id, staff_id: ctx.staff, counted: counted.value, note: note.value })).session; toast('Till closed'); render(); }
          catch (e) { toast(e.message, 'err'); }
        } }, 'Count & close')));
  }

  function closedCard(s) {
    const v = s.variance_paise;
    return h('div', { class: 'card' }, h('div', { class: 'card-head' }, h('h2', null, 'Closed'), h('span', { class: 'pill black', style: { marginLeft: 'auto' } }, fmtTime(s.closed_at))),
      h('div', { class: 'stack-sm' },
        h('div', { class: 'row between' }, h('span', null, 'Expected'), h('b', { class: 'num' }, money(s.expected_cash_paise))),
        h('div', { class: 'row between' }, h('span', null, 'Counted'), h('b', { class: 'num' }, money(s.counted_cash_paise))),
        h('div', { class: 'row between' }, h('span', null, 'Variance'), h('b', { class: 'num ' + (v === 0 ? 'var-pos' : 'var-neg') }, (v > 0 ? '+' : '') + money(v))),
        s.variance_alert ? alertBox('err', s.variance_note) : s.variance_note ? alertBox('info', s.variance_note) : alertBox('ok', 'Within tolerance.')));
  }

  load();
  return { destroy() {}, onContext() { load(); } };
}
