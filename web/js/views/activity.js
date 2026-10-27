import { api } from '../api.js';
import { h, mount, icon, money, titleCase, alertBox } from '../util.js';

export function activityView(root, ctx) {
  const S = { events: [], q: '', loading: true, err: null };
  const holder = h('div', { class: 'card' });
  mount(root,
    h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Audit trail'), h('p', null, 'Who did what, when, with which reason code and reference. Newest first.'))),
    h('div', { class: 'row wrap', style: { marginBottom: '14px' } },
      h('input', { type: 'search', placeholder: 'Filter by person, action or reference', 'aria-label': 'Filter audit trail', style: { maxWidth: '360px' }, oninput: (e) => { S.q = e.target.value.toLowerCase(); render(); } }),
      h('button', { class: 'btn btn-ghost btn-sm', style: { marginLeft: 'auto' }, onclick: load }, icon('refresh'), 'Reload')),
    holder);

  async function load() {
    S.loading = true; render();
    try { S.events = (await api.audit()).events; S.err = null; } catch (e) { S.err = e.message; }
    S.loading = false; render();
  }

  function detail(d) {
    const parts = [];
    for (const [k, v] of Object.entries(d || {})) {
      if (v == null) continue;
      if (k.endsWith('_paise')) parts.push(`${titleCase(k.replace('_paise', ''))} ${money(v)}`);
      else if (Array.isArray(v)) parts.push(`${titleCase(k)}: ${v.length ? v.map((x) => (typeof x === 'object' ? JSON.stringify(x) : x)).join(', ') : 'none'}`);
      else parts.push(`${titleCase(k)}: ${v}`);
    }
    return parts.join(' · ');
  }

  function render() {
    if (S.loading) return mount(holder, h('div', { class: 'skeleton', style: { height: '120px' } }));
    if (S.err) return mount(holder, alertBox('err', S.err));
    const rows = S.events.filter((e) => !S.q || JSON.stringify(e).toLowerCase().includes(S.q));
    if (!rows.length) return mount(holder, h('div', { class: 'empty' }, icon('activity'), h('div', null, 'No activity yet.')));
    mount(holder, h('div', { class: 'scroll-x' }, h('table', { class: 't' },
      h('thead', null, h('tr', null, ['When', 'Who', 'Action', 'Reference', 'Reason', 'Details'].map((x) => h('th', null, x)))),
      h('tbody', null, rows.map((e) => h('tr', null,
        h('td', { class: 'small', style: { whiteSpace: 'nowrap' } }, new Date(e.timestamp).toLocaleString('en-IN', { day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' })),
        h('td', null, ctx.person(e.who)?.name || e.who), h('td', null, h('span', { class: 'pill ' + (/FAIL|CANCEL|MISMATCH/.test(e.what) ? 'bad' : /REFUND/.test(e.what) ? 'soft' : '') }, titleCase(e.what))),
        h('td', { class: 'small' }, e.ref || ''), h('td', null, e.reason_code ? titleCase(e.reason_code) : ''), h('td', { class: 'small muted' }, detail(e.details))))))));
  }

  load();
  return { destroy() {}, onContext() {} };
}
