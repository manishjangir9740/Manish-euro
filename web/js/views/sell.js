import { api } from '../api.js';
import {
  h, mount, icon, money, moneyShort, signed, titleCase, fmtDate, normalisePhone, debounce, toast,
  openModal, alertBox, spinner, frameArt, printNode,
} from '../util.js';

const DEMO = [
  { phone: '+919000000005', label: 'Karthik · priority + campaign' },
  { phone: '+919000000001', label: 'Rahul · no ADD on Rx' },
  { phone: '+919000000011', label: 'Manish · priority' },
  { phone: '+919000000000', label: 'Priya' },
];
const METHODS = [['upi', 'UPI', 'upi'], ['card', 'Card', 'card'], ['cash', 'Cash', 'cash']];
const CHANNEL_LABEL = { walk_in: 'Walk-in', whatsapp_booked: 'WhatsApp', online_pickup: 'Online pickup' };

export function sellView(root, ctx, app) {
  const S = fresh();
  function fresh() {
    return {
      phone: '', customer: null, rx: null, catalog: null, catalogLoading: false,
      pairs: [{ frame: null, lens: null }], active: 0,
      frameQ: '', lensType: 'all', lensIndex: 'all', lensCoating: 'all', onlyValid: true, lensNotice: null,
      quote: null, quoteErr: null, quoting: false,
      channel: 'walk_in', method: 'upi', mgr: { on: false, percent: '', approver: '', reason: '' }, mgrErr: null,
      till: null, busy: false, checkoutErr: null, lookupErr: null, lookingUp: false,
    };
  }
  let st = S;
  const storeAtStart = ctx.store;
  let quoteSeq = 0;
  let abort = null;

  const secCustomer = h('section', { class: 'card' });
  const secFrames = h('section', { class: 'card' });
  const secLenses = h('section', { class: 'card' });
  const secCart = h('section', { class: 'card cart' });
  const secPay = h('section', { class: 'card pay' });
  const payBtnSlot = h('div');
  const phoneInput = h('input', { type: 'tel', inputmode: 'numeric', autocomplete: 'off', placeholder: '98765 43210', 'aria-label': 'Customer phone number', maxlength: 16 });

  mount(root,
    h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'New sale'), h('p', null, `${ctx.storeName()} · frame, lens validated against the prescription, offers, GST, charge.`))),
    h('div', { class: 'sell' },
      h('div', { class: 'sell-col' }, secCustomer, secFrames, secLenses),
      h('div', { class: 'cart-col' }, secCart, secPay)));

  // ------------------------------------------------------------------ customer
  function renderCustomer() {
    const c = st.customer;
    mount(secCustomer,
      h('div', { class: 'card-head' }, h('div', { class: 'step-no' + (c ? ' done' : '') }, c ? icon('check') : '1'), h('h2', null, 'Customer & prescription'),
        c && h('button', { class: 'btn btn-ghost btn-sm', style: { marginLeft: 'auto' }, onclick: newSale }, 'Change customer')),
      !c && h('form', { class: 'lookup', onsubmit: (e) => { e.preventDefault(); lookup(); } },
        h('div', { class: 'phone-wrap' }, h('span', { class: 'prefix' }, '+91'), phoneInput),
        h('button', { class: 'btn btn-dark', type: 'submit', disabled: st.lookingUp }, st.lookingUp ? spinner() : icon('search'), 'Find')),
      !c && h('div', { class: 'row wrap demo-phones' }, h('span', { class: 'small muted' }, 'Demo customers'),
        h('div', { class: 'chips' }, DEMO.map((d) => h('button', { class: 'chip', type: 'button', onclick: () => { phoneInput.value = d.phone.slice(3); lookup(); } }, d.label)))),
      st.lookupErr && h('div', { style: { marginTop: '12px' } }, alertBox('err', st.lookupErr)),
      c && customerBlock(c));
    if (!c) setTimeout(() => phoneInput.focus(), 0);
  }

  function customerBlock(c) {
    const rx = st.rx;
    return h('div', null,
      h('div', { class: 'cust', style: { marginTop: 0, paddingTop: 0, borderTop: 0 } },
        h('div', { class: 'avatar' }, c.name.split(' ').map((p) => p[0]).slice(0, 2).join('')),
        h('div', null,
          h('div', { class: 'row wrap' }, h('h2', null, c.name),
            c.flags.map((f) => h('span', { class: 'pill ' + (f === 'PRIORITY' ? 'orange' : 'black') }, f === 'PRIORITY' ? '★ Priority' : titleCase(f.replace('CAMPAIGN:', 'Campaign · '))))),
          h('div', { class: 'small muted' }, `${c.phone} · lifetime spend ${moneyShort(c.total_spent)}`))),
      rx ? rxCard(rx) : h('div', { style: { marginTop: '14px' } }, alertBox('warn', h('b', null, 'No valid prescription on file. '), 'Frames can still be billed. For lenses, book an eye test or have the external Rx entered in the store tool.')));
  }

  function rxCard(rx) {
    const eye = (lbl, e) => h('tr', null, h('td', null, lbl), h('td', null, signed(e.sph)), h('td', null, signed(e.cyl)), h('td', null, e.axis ?? '–'), h('td', null, e.add != null ? '+' + e.add.toFixed(2) : '–'));
    return h('div', { class: 'rx' },
      h('div', { class: 'rx-head' }, icon('glasses'), h('b', null, rx.rx_id), h('span', null, rx.source === 'external' ? 'External Rx' : 'In-store eye test'), h('span', { style: { marginLeft: 'auto' }, class: 'muted' }, `Valid until ${fmtDate(rx.valid_until)}`)),
      h('table', null, h('thead', null, h('tr', null, ['Eye', 'SPH', 'CYL', 'AXIS', 'ADD'].map((x) => h('th', null, x)))), h('tbody', null, eye('OD · right', rx.od), eye('OS · left', rx.os))),
      h('div', { class: 'rx-foot' }, h('span', null, `Tested ${fmtDate(rx.date)}`), rx.pd?.binocular && h('span', null, `PD ${rx.pd.binocular} mm`), rx.optometrist_id && h('span', null, `Optometrist ${ctx.person(rx.optometrist_id)?.name || rx.optometrist_id}`), rx.notes && h('span', null, rx.notes)));
  }

  async function lookup() {
    const phone = normalisePhone(phoneInput.value);
    if (phone.length < 11) { st.lookupErr = 'Enter the 10-digit mobile number.'; renderCustomer(); return; }
    st.lookingUp = true; st.lookupErr = null; renderCustomer();
    try {
      const r = await api.customer(phone);
      st.phone = phone; st.customer = r.customer; st.rx = r.prescription;
      await loadCatalog();
    } catch (e) {
      st.lookupErr = e.status === 404 ? `No customer found for ${phone}. Check the number, or create the customer in Shopify first.` : e.message;
    }
    st.lookingUp = false;
    renderAll();
  }

  async function loadCatalog() {
    st.catalogLoading = true; renderFrames(); renderLenses();
    try { st.catalog = await api.catalog(ctx.store, st.phone); }
    catch (e) { toast(e.message, 'err'); }
    st.catalogLoading = false;
  }

  // ------------------------------------------------------------------ frames
  function renderFrames() {
    const locked = !st.customer;
    secFrames.className = 'card' + (locked ? ' locked' : '');
    const pair = st.pairs[st.active];
    const frames = (st.catalog?.frames || []).filter((f) => !st.frameQ || (f.name + f.sku).toLowerCase().includes(st.frameQ.toLowerCase()));
    mount(secFrames,
      h('div', { class: 'card-head' }, h('div', { class: 'step-no' + (pair.frame ? ' done' : '') }, pair.frame ? icon('check') : '2'), h('h2', null, 'Frame'),
        st.catalog && h('span', { class: 'small muted' }, `${frames.length} in range · stock at ${ctx.storeName()}`), pairTabs()),
      h('div', { class: 'filters' }, h('input', { type: 'search', placeholder: 'Search frames by name or SKU', value: st.frameQ, 'aria-label': 'Search frames', oninput: (e) => { st.frameQ = e.target.value; renderFrameGrid(); } })),
      frameGridHolder());
  }
  let frameHolder;
  function frameGridHolder() { frameHolder = h('div'); renderFrameGrid(); return frameHolder; }
  function renderFrameGrid() {
    if (!frameHolder) return;
    if (st.catalogLoading) { mount(frameHolder, h('div', { class: 'frames' }, Array.from({ length: 6 }, () => h('div', { class: 'skeleton', style: { height: '130px' } })))); return; }
    const pair = st.pairs[st.active];
    const frames = (st.catalog?.frames || []).filter((f) => !st.frameQ || (f.name + f.sku).toLowerCase().includes(st.frameQ.toLowerCase()));
    if (!frames.length) { mount(frameHolder, h('div', { class: 'empty' }, icon('glasses'), h('div', null, st.catalog ? 'No frames match.' : 'Find a customer to start.'))); return; }
    mount(frameHolder, h('div', { class: 'frames' }, frames.map((f) => {
      const inOtherPairs = st.pairs.filter((p, i) => i !== st.active && p.frame?.id === f.id).length;
      const stock = f.stock == null ? null : f.stock - inOtherPairs;
      const out = stock != null && stock <= 0;
      return h('button', { class: 'frame', 'aria-pressed': pair.frame?.id === f.id ? 'true' : 'false', disabled: out && pair.frame?.id !== f.id,
        onclick: () => { pair.frame = pair.frame?.id === f.id ? null : f; afterCartChange(); } },
        h('span', { class: 'tick' }, icon('check')), h('div', { class: 'art' }, frameArt()),
        h('div', { class: 'nm' }, f.name),
        h('div', { class: 'row between' }, h('span', { class: 'pr' }, moneyShort(f.price)),
          out ? h('span', { class: 'pill bad' }, 'Out of stock') : h('span', { class: 'pill ' + (stock != null && stock <= 2 ? 'soft' : '') }, stock == null ? 'In stock' : `${stock} left`)));
    })));
  }

  function pairTabs() {
    return h('div', { class: 'pair-tabs', style: { marginLeft: 'auto' } },
      st.pairs.map((p, i) => h('span', { class: 'pair-tab', role: 'button', tabindex: 0, 'aria-pressed': i === st.active ? 'true' : 'false',
        onclick: () => { st.active = i; st.lensNotice = null; renderPairsUI(); }, onkeydown: (e) => { if (e.key === 'Enter') { st.active = i; renderPairsUI(); } } },
        `Pair ${i + 1}`, st.pairs.length > 1 && h('button', { class: 'x', title: 'Remove pair', onclick: (e) => { e.stopPropagation(); removePair(i); } }, '×'))),
      h('button', { class: 'chip', onclick: addPair, title: 'e.g. second-pair offers need two pairs' }, '+ Add pair'));
  }
  function addPair() { st.pairs.push({ frame: null, lens: null }); st.active = st.pairs.length - 1; st.lensNotice = null; renderPairsUI(); }
  function removePair(i) { st.pairs.splice(i, 1); st.active = Math.min(st.active, st.pairs.length - 1); afterCartChange(); }
  function renderPairsUI() { renderFrames(); renderLenses(); renderCart(); }

  // ------------------------------------------------------------------ lenses
  function renderLenses() {
    const locked = !st.customer;
    secLenses.className = 'card' + (locked ? ' locked' : '');
    const pair = st.pairs[st.active];
    const all = st.catalog?.lenses || [];
    const passing = all.filter((l) => l.verdict?.valid).length;
    const types = ['all', ...new Set(all.map((l) => l.lens_type))];
    const idx = ['all', ...[...new Set(all.map((l) => l.index))].sort((a, b) => a - b)];
    const coat = ['all', ...new Set(all.map((l) => l.coating))];
    const seg = (key, vals, label) => h('div', { class: 'chips', role: 'group', 'aria-label': label }, vals.map((v) => h('button', { class: 'chip', 'aria-pressed': st[key] === v ? 'true' : 'false',
      onclick: () => { st[key] = v; renderLenses(); } }, v === 'all' ? `All ${label}` : key === 'lensIndex' ? String(v) : titleCase(v))));
    mount(secLenses,
      h('div', { class: 'card-head' }, h('div', { class: 'step-no' + (pair.lens ? ' done' : '') }, pair.lens ? icon('check') : '3'), h('h2', null, 'Lens'),
        st.catalog && st.rx && h('span', { class: 'small muted' }, `${passing} of ${all.length} suit this prescription`),
        h('label', { class: 'switch', style: { marginLeft: 'auto' } }, h('input', { type: 'checkbox', checked: st.onlyValid, onchange: (e) => { st.onlyValid = e.target.checked; renderLenses(); } }), 'Only lenses that pass')),
      all.length > 0 && h('div', { class: 'stack-sm', style: { marginBottom: '14px' } }, seg('lensType', types, 'types'), seg('lensIndex', idx, 'indexes'), seg('lensCoating', coat, 'coatings')),
      st.lensNotice && h('div', { style: { marginBottom: '12px' } }, st.lensNotice),
      lensList(all, pair));
  }

  function lensList(all, pair) {
    if (st.catalogLoading) return h('div', { class: 'lens-list' }, Array.from({ length: 4 }, () => h('div', { class: 'skeleton', style: { height: '58px' } })));
    if (!all.length) return h('div', { class: 'empty' }, icon('glasses'), h('div', null, 'Find a customer to see lenses.'));
    let list = all.filter((l) => (st.lensType === 'all' || l.lens_type === st.lensType) && (st.lensIndex === 'all' || l.index === st.lensIndex) && (st.lensCoating === 'all' || l.coating === st.lensCoating));
    const hidden = list.filter((l) => !l.verdict.valid).length;
    if (st.onlyValid) list = list.filter((l) => l.verdict.valid);
    if (!list.length) {
      return h('div', { class: 'empty' }, icon('glasses'), h('div', null, st.rx ? 'No lens in this filter passes the prescription.' : 'No lens can be billed without a valid prescription.'),
        hidden > 0 && h('div', { style: { marginTop: '10px' } }, h('button', { class: 'link', onclick: () => { st.onlyValid = false; renderLenses(); } }, `Show ${hidden} blocked lenses and why`)));
    }
    return h('div', { class: 'lens-list' }, list.map((l) => {
      const ok = l.verdict.valid;
      return h('button', { class: 'lens' + (ok ? '' : ' blocked'), 'aria-pressed': pair.lens?.id === l.id ? 'true' : 'false', 'aria-disabled': ok ? null : 'true',
        onclick: () => pickLens(l, pair) },
        h('div', null, h('div', { class: 'nm' }, `${titleCase(l.lens_type)} · ${l.index}`),
          h('div', { class: 'meta' }, h('span', null, titleCase(l.coating)), h('span', null, `${l.lab_tat_days}-day lab`), h('span', null, `SPH ${l.limits.sph_min} to ${l.limits.sph_max}`, `, CYL ≤ ${l.limits.cyl_abs_max}`))),
        h('div', { class: 'pr' }, moneyShort(l.price), !ok && h('div', null, h('span', { class: 'pill bad' }, 'Blocked'))),
        !ok && h('div', { class: 'why' }, l.verdict.errors[0]),
        ok && l.verdict.warnings.map((w) => h('div', { class: 'warnline' }, '⚠ ' + w)));
    }));
  }

  function pickLens(l, pair) {
    if (!l.verdict.valid) {
      st.lensNotice = alertBox('err', h('b', null, `${titleCase(l.lens_type)} ${l.index} ${titleCase(l.coating)} cannot be billed. `), h('ul', null, l.verdict.errors.map((e) => h('li', null, e))));
      renderLenses(); return;
    }
    st.lensNotice = null;
    pair.lens = pair.lens?.id === l.id ? null : l;
    afterCartChange();
  }

  // ------------------------------------------------------------------ pricing
  function activePairs() { return st.pairs.map((p, i) => ({ frame_id: p.frame?.id, lens_id: p.lens?.id, pair_ref: String(i + 1) })).filter((p) => p.frame_id || p.lens_id); }
  function quoteBody() {
    const m = st.mgr;
    return {
      phone: st.phone, store: ctx.store, staff_id: ctx.staff, channel: st.channel, pairs: activePairs(),
      manager_discount: m.on && m.percent ? { percent: m.percent, approver_id: m.approver, reason_code: m.reason } : null,
    };
  }
  function afterCartChange() { renderFrames(); renderLenses(); st.checkoutErr = null; scheduleQuote(); renderCart(); }
  const scheduleQuote = debounce(runQuote, 120);

  async function runQuote(retryWithoutMgr = false) {
    abort?.abort();
    const body = quoteBody();
    if (!body.pairs.length) { st.quote = null; st.quoteErr = null; st.quoting = false; renderCart(); renderPay(); return; }
    if (retryWithoutMgr === true) body.manager_discount = null;
    const seq = ++quoteSeq;
    abort = new AbortController();
    st.quoting = true;
    try {
      const q = await api.quote(body, abort.signal);
      if (seq !== quoteSeq) return;
      st.quote = q; st.quoteErr = null;
      if (retryWithoutMgr !== true) st.mgrErr = null;
    } catch (e) {
      if (e.name === 'AbortError' || seq !== quoteSeq) return;
      if (e.code === 'ManagerDiscountRejected') { st.mgrErr = e.message; st.quoting = false; return runQuote(true); }
      st.quote = null; st.quoteErr = e;
    }
    st.quoting = false;
    renderCart(); renderPay();
  }

  // ------------------------------------------------------------------ cart
  function renderCart() {
    const q = st.quote;
    const hasItems = activePairs().length > 0;
    mount(secCart,
      h('div', { class: 'cart-head' }, icon('sell'), h('h2', null, 'Bill'), st.quoting && h('span', { class: 'spinner', style: { marginLeft: '6px', borderColor: 'rgba(255,255,255,.25)', borderTopColor: '#f88e2b' } }),
        st.customer && h('span', { class: 'pill orange' }, st.customer.name.split(' ')[0])),
      !hasItems && h('div', { class: 'empty' }, icon('sell'), h('div', null, 'Pick a frame and a lens to start the bill.')),
      st.quoteErr && h('div', { style: { padding: '14px 18px 0' } }, alertBox('err', h('b', null, st.quoteErr.code === 'RxValidationFailed' ? 'Lens blocked. ' : 'Cannot price this bill. '), st.quoteErr.details?.length ? h('ul', null, st.quoteErr.details.map((d) => h('li', null, d))) : st.quoteErr.message)),
      hasItems && h('div', { class: 'cart-body' }, cartPairs(q)),
      q && totals(q), q && offersBlock(q), q && gstBlock(q));
  }

  function cartPairs(q) {
    const pairs = st.pairs.map((p, i) => ({ p, i })).filter(({ p }) => p.frame || p.lens);
    return pairs.map(({ p, i }) => {
      const lines = q?.lines.filter((l) => l.pair_ref === String(i + 1)) || [];
      const one = (item, kind) => {
        if (!item) return null;
        const ln = lines.find((l) => l.variant_id === item.id);
        return h('div', { class: 'line' },
          h('div', { class: 'nm' }, item.name), h('div', { class: 'amt num' }, moneyShort(item.price)),
          h('div', { class: 'sub' }, h('span', null, kind === 'frame' ? 'Frame' : 'Lens'), ln?.offers.map((o) => h('span', { class: 'off' }, `− ${money(o.amount)} ${o.name}`)), ln?.warnings.map((w) => h('span', { class: 'off' }, '⚠ ' + w)),
            h('button', { class: 'rm', onclick: () => { p[kind] = null; afterCartChange(); } }, 'Remove')));
      };
      return h('div', { class: 'pair-block' }, st.pairs.length > 1 && h('div', { class: 'pair-title' }, `Pair ${i + 1}`, !(p.frame && p.lens) && h('span', { style: { textTransform: 'none', letterSpacing: 0 } }, 'incomplete')), one(p.frame, 'frame'), one(p.lens, 'lens'));
    });
  }

  function totals(q) {
    const t = q.totals;
    const cgst = q.lines.reduce((a, l) => a + (l.tax_lines.find((x) => x.title === 'CGST')?.amount || 0), 0);
    const sgst = q.lines.reduce((a, l) => a + (l.tax_lines.find((x) => x.title === 'SGST')?.amount || 0), 0);
    return h('div', { class: 'totals' },
      h('div', { class: 'tr' }, h('span', null, 'Subtotal (MRP, incl. GST)'), h('span', { class: 'num' }, money(t.mrp))),
      t.discount > 0 && q.applied_offers.map((o) => h('div', { class: 'tr off' }, h('span', null, o.name), h('span', { class: 'num' }, '− ' + money(o.amount)))),
      h('div', { class: 'tr sub' }, h('span', null, 'Taxable value'), h('span', { class: 'num' }, money(t.taxable))),
      h('div', { class: 'tr sub' }, h('span', null, 'CGST'), h('span', { class: 'num' }, money(cgst))),
      h('div', { class: 'tr sub' }, h('span', null, 'SGST'), h('span', { class: 'num' }, money(sgst))),
      h('div', { class: 'grand' }, h('span', { style: { fontWeight: 650 } }, 'Total payable'), h('b', { class: 'num' }, money(t.total))),
      t.discount > 0 && h('div', { class: 'small', style: { color: '#8a4a05', fontWeight: 600, textAlign: 'right' } }, `You save ${money(t.discount)}`));
  }

  function offersBlock(q) {
    const ev = [...q.offer_evaluations].sort((a, b) => Number(b.applied) - Number(a.applied));
    return h('details', { class: 'disc', open: q.applied_offers.length === 0 ? null : null },
      h('summary', null, `Offers · ${q.applied_offers.length} applied`),
      h('div', { class: 'inner' }, ev.map((e) => h('div', { class: 'ev' + (e.applied ? ' on' : '') },
        h('span', { class: 'ic' }, icon(e.applied ? 'check' : 'x')),
        h('div', null, h('div', { class: 'nm' }, e.name), h('div', { class: 'why' }, e.why)),
        h('div', { class: 'num', style: { fontWeight: 600 } }, e.applied ? '− ' + money(e.amount) : '')))));
  }

  function gstBlock(q) {
    return h('details', { class: 'disc' },
      h('summary', null, 'GST breakup per line'),
      h('div', { class: 'inner' }, h('div', { class: 'scroll-x' }, h('table', { class: 'gst-table' },
        h('thead', null, h('tr', null, ['Item', 'Taxable', 'CGST', 'SGST', 'Line total'].map((x) => h('th', null, x)))),
        h('tbody', null, q.lines.map((l) => {
          const c = l.tax_lines.find((x) => x.title === 'CGST'), s = l.tax_lines.find((x) => x.title === 'SGST');
          return h('tr', null, h('td', null, h('div', null, l.name), h('div', { class: 'muted' }, `HSN ${l.hsn}`)),
            h('td', { class: 'num' }, money(l.taxable)), h('td', { class: 'num' }, `${money(c?.amount)} (${(c?.rate_bps || 0) / 100}%)`), h('td', { class: 'num' }, `${money(s?.amount)} (${(s?.rate_bps || 0) / 100}%)`), h('td', { class: 'num' }, money(l.gross)));
        })))), h('div', { class: 'small muted' }, 'Prices include GST. Tax is backed out per line by HSN; taxable + CGST + SGST equals the line total to the paisa.')));
  }

  // ------------------------------------------------------------------ payment
  function renderPay() {
    const m = st.mgr;
    const managers = ctx.managers();
    const q = st.quote;
    const needTill = st.method === 'cash' && st.till && !st.till.is_open;
    mount(secPay,
      h('div', { class: 'stack-sm' }, h('h3', null, 'Sales channel'),
        h('div', { class: 'seg full', role: 'group', 'aria-label': 'Sales channel' }, ctx.boot.channels.map((c) => h('button', { 'aria-pressed': st.channel === c ? 'true' : 'false', onclick: () => { st.channel = c; renderPay(); } }, CHANNEL_LABEL[c] || titleCase(c))))),
      h('div', { class: 'stack-sm' }, h('h3', null, 'Payment'),
        h('div', { class: 'method' }, METHODS.map(([v, label, ic]) => h('button', { 'aria-pressed': st.method === v ? 'true' : 'false', onclick: () => { st.method = v; if (v === 'cash') loadTill(); renderPay(); } }, icon(ic), label)))),
      needTill && alertBox('warn', 'No open cash till for today. ', h('a', { class: 'link', href: '#/till' }, 'Open the till'), ' before taking cash.'),
      h('div', { class: 'mgr' },
        h('label', { class: 'switch' }, h('input', { type: 'checkbox', checked: m.on, disabled: managers.length === 0, onchange: (e) => { m.on = e.target.checked; if (!m.on) st.mgrErr = null; renderPay(); scheduleQuote(); } }), `Manager discount (max ${ctx.boot.manager_max_percent}%)`),
        managers.length === 0 && h('div', { class: 'small muted' }, 'No manager at this store can approve discounts.'),
        m.on && h('div', { class: 'stack-sm' },
          h('div', { class: 'grid2' },
            h('label', { class: 'field' }, 'Discount %', h('input', { type: 'number', min: '0', max: String(ctx.boot.manager_max_percent), step: '0.5', value: m.percent, placeholder: 'e.g. 8', oninput: (e) => { m.percent = e.target.value; scheduleQuote(); updatePayButton(); } })),
            h('label', { class: 'field' }, 'Approved by', h('select', { onchange: (e) => { m.approver = e.target.value; scheduleQuote(); } }, h('option', { value: '' }, 'Select manager'), managers.map((s) => h('option', { value: s.id, selected: m.approver === s.id }, `${s.name} (${s.id})`))))),
          h('label', { class: 'field' }, 'Reason code', h('select', { onchange: (e) => { m.reason = e.target.value; scheduleQuote(); } }, h('option', { value: '' }, 'Select reason'), ctx.boot.discount_reason_codes.map((r) => h('option', { value: r, selected: m.reason === r }, titleCase(r))))),
          h('div', { class: 'small muted' }, 'Approver and reason are written to the Shopify order and the audit trail.'),
          st.mgrErr && alertBox('err', st.mgrErr))),
      st.checkoutErr && alertBox('err', h('b', null, st.checkoutErr.code === 'TillClosed' ? 'Till closed. ' : 'Payment not completed. '), st.checkoutErr.message),
      payBtnSlot);
    updatePayButton();
  }

  function canCharge() {
    const q = st.quote;
    if (!st.customer || !q || !q.lines.length || st.busy || st.quoting) return false;
    if (st.mgr.on && (!st.mgr.percent || !st.mgr.approver || !st.mgr.reason || st.mgrErr)) return false;
    if (st.method === 'cash' && st.till && !st.till.is_open) return false;
    return true;
  }
  function updatePayButton() {
    const q = st.quote;
    const label = st.busy ? 'Waiting for the terminal…' : st.method === 'cash' ? 'Take cash' : 'Charge terminal';
    mount(payBtnSlot, h('button', { class: 'btn btn-primary btn-lg', disabled: !canCharge(), onclick: charge },
      st.busy && spinner(), label, q && !st.busy && h('b', { class: 'num' }, money(q.totals.total))));
  }

  async function loadTill() {
    try { st.till = (await api.till(ctx.store)).session; if (st.till) st.till.is_open = !st.till.closed_at; else st.till = { is_open: false }; }
    catch { st.till = null; }
    renderPay();
  }

  async function charge() {
    if (!canCharge()) return;
    st.busy = true; st.checkoutErr = null; updatePayButton();
    try {
      const res = await api.checkout({ ...quoteBody(), payment_method: st.method });
      st.busy = false; updatePayButton();
      app.refreshPending?.();
      receipt(res);
    } catch (e) {
      st.busy = false;
      st.checkoutErr = e;
      renderPay();
      toast(e.message, 'err');
    }
  }

  async function receipt(res) {
    const pending = res.status === 'pending_sync';
    const sheet = h('pre', { class: 'invoice' }, res.invoice_text);
    const act = await openModal((close) => ({
      head: [h('div', { class: 'success-mark' }, icon('check')), h('div', null, h('h2', null, `Paid ${money(res.totals.total)}`), h('div', { class: 'muted' }, `${titleCase(res.payment_method)} · ${res.invoice_no}`))],
      body: [
        pending ? alertBox('warn', h('b', null, 'Paid, but Shopify was unreachable. '), 'The bill is saved on this till and will be sent to Shopify without duplicating (use “Sync pending bills” at the top).')
          : alertBox('ok', 'Saved in Shopify', res.order_number ? ` as order #${res.order_number}` : '', '. Invoice number issued from the store series.'),
        res.warnings.map((w) => alertBox('warn', w)),
        sheet,
      ],
      foot: [
        h('button', { class: 'btn btn-ghost', onclick: () => printNode(sheet) }, icon('print'), 'Print invoice'),
        !pending && h('button', { class: 'btn btn-ghost', onclick: () => close('refund') }, icon('orders'), 'Refund this bill'),
        h('button', { class: 'btn btn-primary', onclick: () => close('new'), autofocus: true }, icon('plus'), 'New sale'),
      ],
    }), { wide: true, dismissable: false });
    if (act === 'refund' && res.order_id) { try { sessionStorage.setItem('eluno.focusOrder', String(res.order_id)); } catch { /* ignore */ } location.hash = '#/orders'; return; }
    newSale();
  }

  function newSale() {
    abort?.abort();
    st = fresh();
    phoneInput.value = '';
    renderAll();
  }

  function renderAll() { renderCustomer(); renderFrames(); renderLenses(); renderCart(); renderPay(); }

  renderAll();
  loadTill();
  return {
    destroy() { abort?.abort(); scheduleQuote.cancel(); },
    onContext() { // staff switches keep the cart; a store switch changes stock and approvers, so start clean
      if (ctx.store === storeAtStart) return;
      toast('Store changed: cart cleared.');
      location.reload();
    },
  };
}
