(() => {
  'use strict';

  /* ------------------------------------------------------------ helpers */
  const $ = (sel, root = document) => root.querySelector(sel);

  // Builds DOM with textContent only: scraped job text can never inject markup.
  function h(tag, attrs, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return el;
  }

  const csrf = () => (document.cookie.match(/(?:^|; )csrftoken=([^;]+)/) || [])[1] || '';

  async function api(path, { method = 'GET', body } = {}) {
    const res = await fetch(path, {
      method,
      credentials: 'same-origin',
      headers: { Accept: 'application/json', ...(body ? { 'Content-Type': 'application/json' } : {}), 'X-CSRFToken': csrf() },
      body: body ? JSON.stringify(body) : undefined,
    });
    if (res.status === 401) { location.href = '/login/'; throw new Error('Signed out'); }
    let data = {};
    try { data = await res.json(); } catch (_) { /* non-JSON */ }
    if (!res.ok) {
      const err = new Error(data.error || `Request failed (${res.status})`);
      err.status = res.status; err.data = data;
      throw err;
    }
    return data;
  }

  const rtf = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' });
  function ago(iso) {
    if (!iso) return 'never';
    const s = (new Date(iso) - Date.now()) / 1000;
    const units = [['year', 31536000], ['month', 2592000], ['day', 86400], ['hour', 3600], ['minute', 60]];
    for (const [u, secs] of units) if (Math.abs(s) >= secs) return rtf.format(Math.round(s / secs), u);
    return 'just now';
  }
  const full = (iso) => (iso ? new Date(iso).toLocaleString() : '');
  const num = (n) => Number(n || 0).toLocaleString();
  function duration(a, b) {
    if (!a) return '';
    const secs = Math.max(0, Math.round(((b ? new Date(b) : new Date()) - new Date(a)) / 1000));
    return secs < 60 ? `${secs}s` : `${Math.floor(secs / 60)}m ${secs % 60}s`;
  }
  const safeHref = (u) => (/^https?:\/\//i.test(u || '') ? u : null);
  const label = (s) => (s || '').replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());

  // Small stroke icons (inline SVG, decorative: hidden from screen readers).
  const ICONS = {
    search: ['M21 21l-4.35-4.35', 'M11 18a7 7 0 1 0 0-14 7 7 0 0 0 0 14z'],
    pin: ['M12 21s-7-6.2-7-11a7 7 0 0 1 14 0c0 4.8-7 11-7 11z', 'M12 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z'],
    clock: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M12 7v5l3 2'],
    external: ['M14 4h6v6', 'M20 4L10 14', 'M19 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V6a1 1 0 0 1 1-1h5'],
    send: ['M22 2L11 13', 'M22 2l-7 20-4-9-9-4 20-7z'],
    sparkle: ['M12 3l1.8 4.7L18.5 9.5l-4.7 1.8L12 16l-1.8-4.7L5.5 9.5l4.7-1.8z', 'M19 15l.7 1.8 1.8.7-1.8.7L19 20l-.7-1.8-1.8-.7 1.8-.7z'],
    building: ['M3 21h18', 'M5 21V8l7-5 7 5v13', 'M9 21v-6h6v6', 'M9 11h.01M15 11h.01'],
    briefcase: ['M3 9a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z', 'M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2', 'M3 13h18'],
    refresh: ['M21 12a9 9 0 1 1-2.64-6.36', 'M21 4v5h-5'],
    x: ['M18 6L6 18', 'M6 6l12 12'],
    sliders: ['M4 6h10M18 6h2', 'M4 12h4M12 12h8', 'M4 18h12M20 18h0', 'M16 4v4M10 10v4M18 16v4'],
    cap: ['M2 9l10-5 10 5-10 5z', 'M6 11v5c3 2 9 2 12 0v-5'],
    globe: ['M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z', 'M3 12h18', 'M12 3c2.5 2.7 2.5 15.3 0 18M12 3c-2.5 2.7-2.5 15.3 0 18'],
    sprout: ['M12 21v-8', 'M12 13c0-4 3-6 7-6 0 4-3 6-7 6z', 'M12 15c0-3-2-5-6-5 0 3 2 5 6 5z'],
    calendar: ['M4 6a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v13a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z', 'M4 10h16', 'M9 2v4M15 2v4'],
    plus: ['M12 5v14', 'M5 12h14'],
  };
  function icon(name) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('class', 'ico'); svg.setAttribute('aria-hidden', 'true');
    for (const d of ICONS[name] || []) {
      const path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d); svg.append(path);
    }
    return svg;
  }
  // Company monogram: up to two initials on a soft colour picked from the name (stable per company).
  const LOGO_COLORS = [['#e2f1f1', '#064a50'], ['#ece8fb', '#45348a'], ['#e4eefc', '#1f4e9a'], ['#fde9cf', '#8a4b08'],
    ['#dcf2e7', '#17663f'], ['#fbe3ea', '#8d2346'], ['#eef1f5', '#334155'], ['#f3ecdf', '#6b4a12']];
  function initials(name) {
    const words = (name || '?').replace(/[^\p{L}\p{N}\s]/gu, ' ').split(/\s+/).filter(Boolean);
    if (!words.length) return '?';
    return (words.length === 1 ? words[0].slice(0, 2) : words[0][0] + words[1][0]).toUpperCase();
  }
  function logo(name) {
    let hsh = 0; for (const c of name || '') hsh = (hsh * 31 + c.charCodeAt(0)) >>> 0;
    const [bg, fg] = LOGO_COLORS[hsh % LOGO_COLORS.length];
    return h('span', { class: 'logo', style: `background:${bg};color:${fg}`, 'aria-hidden': 'true' }, initials(name));
  }

  function toast(msg, bad = false) {
    const t = h('div', { class: 'toast' + (bad ? ' bad' : '') }, msg);
    $('#toasts').append(t);
    setTimeout(() => t.remove(), bad ? 7000 : 4000);
  }

  /* ------------------------------------------------------------ state */
  const state = {
    me: null, sources: [], adapters: [], overview: null, filters: null,
    query: { q: '', sector: '', source: '', employment_type: '', workplace_type: '', city: '', experience: '', include_unspecified: '1', discovered: '', status: 'active', ordering: 'newest', page: 1 },
    selected: new Map(), rowJobs: new Map(),
    sourceFilter: 'all',
    poll: null, wasActive: false, refreshView: null,
  };

  /* ------------------------------------------------------------ status strip */
  function sourceState(s) {
    if (!s.active) return { cls: 'inactive', text: 'Paused', chip: 'skipped' };
    if (s.adapter === 'unsupported') return { cls: 'skipped', text: 'Needs adapter', chip: 'unsupported' };
    if (s.last_status === 'success') return { cls: 'ok', text: 'Collecting', chip: 'success' };
    if (s.last_status === 'failed') return { cls: 'failed', text: 'Failed', chip: 'failed' };
    return { cls: '', text: 'Not fetched yet', chip: '' };
  }

  function healthCounts() {
    const c = { total: state.sources.length, ok: 0, failed: 0, skipped: 0, inactive: 0, never: 0 };
    state.sources.forEach((s) => { const k = sourceState(s).cls || 'never'; c[k] = (c[k] || 0) + 1; });
    return c;
  }

  // Short status line used in the Jobs search band.
  function statusLine() {
    const o = state.overview, c = healthCounts(), parts = [];
    parts.push(h('span', null, h('strong', null, num(c.ok)), ` of ${num(c.total)} sources collecting`));
    if (c.failed) parts.push(h('span', { class: 'health-warn' }, `${num(c.failed)} failing`));
    if (o.active_run) parts.push(h('span', null, 'Fetching now'));
    else if (o.last_run) parts.push(h('span', null, `Updated ${ago(o.last_run.completed_at)}`));
    else parts.push(h('span', null, 'Not fetched yet'));
    parts.push(h('span', null, `Daily refresh ${state.me.daily_fetch_time} ${state.me.time_zone}`));
    return parts;
  }

  function renderStatus() {
    const o = state.overview;
    const live = $('#status-line');
    if (live) live.replaceChildren(...statusLine());
    const grid = $('#grid');
    if (grid) renderHealth();

    const run = o.active_run, btn = $('#fetch-btn'), box = $('#run-progress');
    btn.hidden = !state.me.is_admin;
    btn.disabled = !!run;
    btn.replaceChildren(...(run ? [h('span', { class: 'spinner', 'aria-hidden': 'true' }), 'Fetching…']
      : [icon('refresh'), h('span', null, 'Fetch', h('span', { class: 'label-long' }, ' jobs'))]));
    if (run) {
      const done = run.successful_sources + run.failed_sources + run.skipped_sources;
      const pct = run.total_sources ? Math.round((done / run.total_sources) * 100) : 0;
      box.hidden = false;
      box.className = 'run-banner' + (!run.total_sources ? ' indeterminate' : '');
      const stopping = run.cancel_requested;
      const stopBtn = state.me.is_admin && h('button', { class: 'btn small', type: 'button', disabled: stopping,
        onclick: async () => {
          stopBtn.disabled = true;
          try {
            const r = await api(`/api/fetch-runs/${run.id}/cancel`, { method: 'POST', body: {} });
            toast(r.outcome === 'stopped' ? `Fetch #${run.id} stopped. Jobs collected so far were kept.`
              : `Fetch #${run.id} will stop after the company it is collecting now.`);
          } catch (e) { toast(e.message, true); stopBtn.disabled = false; }
          await refreshStatus({ withSources: true });
          if (state.refreshView) state.refreshView({});
        } }, stopping ? 'Stopping…' : 'Stop fetch');
      box.replaceChildren(h('div', { class: 'run-banner-inner' },
        h('div', { class: 'progress-head' },
          h('strong', null, stopping ? `Stopping after ${run.current_step.replace(/^Collecting\s+/, '') || 'the current company'}`
            : run.status === 'queued' ? 'Waiting for the worker to pick up the fetch' : run.current_step || 'Working'),
          stopBtn),
        h('div', { class: 'progress-sub' }, `${num(run.jobs_created)} new jobs, ${num(run.jobs_updated)} updated so far`),
        h('div', { class: 'bar', role: 'progressbar', 'aria-valuemin': '0', 'aria-valuemax': '100', 'aria-valuenow': String(pct), 'aria-label': 'Fetch progress' },
          h('i', { style: `width:${pct}%` }))));
    } else { box.hidden = true; box.replaceChildren(); }
  }

  function renderHealth() {
    const grid = $('#grid'); if (!grid) return;
    const c = healthCounts(), o = state.overview;
    grid.replaceChildren(...state.sources.map((s) => {
      const st = sourceState(s);
      return h('button', { class: 'cell ' + st.cls, type: 'button', title: `${s.company}: ${st.text}`, 'aria-label': `${s.company}: ${st.text}`,
        onclick: () => { const row = document.querySelector(`[data-source-row="${s.id}"]`); if (row) { row.scrollIntoView({ block: 'center' }); row.querySelector('a')?.focus(); } } });
    }));
    const stats = $('#health-stats');
    if (stats) stats.replaceChildren(
      h('div', { class: 'hstat' }, h('b', null, num(c.ok)), h('span', null, 'Collecting')),
      h('div', { class: 'hstat' }, h('b', null, num(c.failed)), h('span', null, 'Last fetch failed')),
      h('div', { class: 'hstat' }, h('b', null, num(c.skipped)), h('span', null, 'Need an adapter')),
      h('div', { class: 'hstat' }, h('b', null, num(c.inactive)), h('span', null, 'Paused')),
      h('div', { class: 'hstat' }, h('b', null, num(o.jobs_active)), h('span', null, 'Open jobs stored')));
  }

  async function refreshStatus({ withSources = true } = {}) {
    const [o, s] = await Promise.all([api('/api/overview'), withSources ? api('/api/sources') : null]);
    state.overview = o;
    if (s) { state.sources = s.results; state.adapters = s.adapters; }
    renderStatus();
    managePolling();
  }

  function managePolling() {
    const active = !!(state.overview && state.overview.active_run);
    if (active && !state.poll) {
      state.poll = setInterval(async () => {
        try {
          await refreshStatus({ withSources: false });
          if (state.refreshView) state.refreshView({ quiet: true });
        } catch (_) { /* transient */ }
      }, 2000);
    }
    if (!active && state.poll) {
      clearInterval(state.poll); state.poll = null;
    }
    if (state.wasActive && !active) onRunFinished();
    state.wasActive = active;
  }

  async function onRunFinished() {
    const r = state.overview.last_run;
    await refreshStatus();
    state.filters = null;
    if (r) toast(`Fetch #${r.id} ${label(r.status).toLowerCase()}: ${num(r.jobs_created)} new, ${num(r.jobs_updated)} updated, ${r.failed_sources} failed.`, r.status === 'failed' || r.status === 'cancelled');
    if (state.refreshView) state.refreshView({});
  }

  /* ------------------------------------------------------------ fetch button */
  async function startFetch(sourceIds) {
    try {
      await api('/api/fetch-runs', { method: 'POST', body: sourceIds ? { source_ids: sourceIds } : {} });
      toast('Fetch started.');
    } catch (e) {
      toast(e.status === 409 ? 'A fetch is already running.' : e.message, true);
    }
    await refreshStatus({ withSources: false });
  }

  function confirmFetch() {
    const active = state.sources.filter((s) => s.active && s.adapter !== 'unsupported').length;
    const where = state.me.country_filter === 'IN' ? ' Only jobs located in India are kept.' : '';
    const parts = [`This asks ${active} configured source${active === 1 ? '' : 's'} for their current job postings.${where}`,
      'No AI summaries are generated during a fetch. You choose which jobs to summarise.'];
    $('#confirm-text').textContent = parts.join(' ');
    const dlg = $('#confirm-dialog');
    dlg.showModal();
  }

  /* ------------------------------------------------------------ on-demand AI summaries */
  state.rows = new Map();
  function quotaText() {
    const m = state.me;
    if (!m.ai_enabled) return 'AI summaries are off (no OpenAI key is set)';
    if (!m.quota.remaining) return 'Daily AI summary limit reached. It resets at midnight.';
    return `${m.quota.remaining} AI summar${m.quota.remaining === 1 ? 'y' : 'ies'} left today`;
  }
  function updateQuotaLabel() {
    document.querySelectorAll('.quota-live').forEach((el) => { el.textContent = quotaText(); });
    // When the daily limit is used up, disable every visible "summarise" button (busy ones re-enable themselves only on failure).
    if (state.me.quota.remaining <= 0) {
      document.querySelectorAll('button[data-summarise]:not([data-busy])').forEach((b) => { b.disabled = true; b.title = quotaText(); });
    }
  }
  function updateRowFor(j) {
    const li = state.rows.get(j.id);
    if (li && li.isConnected) li.replaceWith(jobRow(j));
  }
  async function requestSummary(job) {
    try {
      const j = await api(`/api/jobs/${job.id}/summary`, { method: 'POST', body: {} });
      state.me.quota = j.quota; updateQuotaLabel(); updateRowFor(j);
      // every other posting of the same role on screen gets the stored summary too
      state.rowJobs.forEach((r) => {
        if (r.id !== j.id && r.role_key === j.role_key && r.summary_status !== 'ai') updateRowFor({ ...r, summary: j.summary, summary_status: 'ai', excerpt: '' });
      });
      if (j.reused) toast('Saved summary for this role reused (no AI call).');
      return j;
    } catch (e) {
      if (e.data && e.data.quota) { state.me.quota = e.data.quota; updateQuotaLabel(); }
      toast(e.message, true);
      return null;
    }
  }
  function summaryButton(job, { primary = false, text, onDone }) {
    const canAsk = state.me.ai_enabled && state.me.quota.remaining > 0;
    const btn = h('button', { class: 'btn small' + (primary ? ' primary' : ''), type: 'button', 'data-summarise': '', disabled: !canAsk, title: canAsk ? null : quotaText(),
      onclick: async (e) => {
        e.stopPropagation();
        btn.disabled = true; btn.setAttribute('data-busy', ''); btn.replaceChildren(h('span', { class: 'spinner', 'aria-hidden': 'true' }), ' Summarising…');
        const j = await requestSummary(job);
        btn.removeAttribute('data-busy');
        if (j) { if (onDone) onDone(j); }
        else { btn.disabled = state.me.quota.remaining <= 0; btn.replaceChildren(text); }
      } }, text);
    return btn;
  }
  function summarySection(j) {
    const ai = j.summary_status === 'ai';
    const sec = h('section', null);
    const done = (u) => sec.replaceWith(summarySection(u));
    sec.append(
      h('h3', null, ai ? 'AI summary' : 'Excerpt'),
      h('div', { class: 'callout' + (ai ? '' : ' excerpt') },
        ai ? j.summary : (j.excerpt || 'This posting has no description.'),
        !ai && h('div', { class: 'warn-text' }, 'This is only the start of the posting. Ask for an AI summary if you want one.'),
        ai && h('div', { class: 'muted-text', style: 'margin-top:8px' }, 'Saved permanently for this role and reused for every posting of it.')),
      !ai && h('div', { class: 'summary-actions' },
        state.me.ai_enabled && summaryButton(j, { primary: true, text: 'Summarise with AI', onDone: done }),
        h('span', { class: 'quota quota-live' }, quotaText())));
    return sec;
  }

  /* ------------------------------------------------------------ LinkedIn / WhatsApp post composer */
  const store = {
    get(k) { try { return localStorage.getItem(k) || ''; } catch (_) { return ''; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch (_) { /* storage unavailable */ } },
  };
  function postLocation(j) {
    const c = (j.cities || []).filter((x) => x !== 'Remote');
    if ((j.cities || []).includes('Remote')) c.push('Remote');
    return c.length ? c.join(', ') : (j.location || '');
  }
  function typeSuffix(j) {
    if (j.employment_type === 'Contract') return ' - Contractual Role';
    if (j.employment_type === 'Part-time') return ' - Part-time Role';
    if (j.employment_type === 'Internship' && !/\bintern/i.test(j.title)) return ' - Internship';
    return '';
  }
  // Government notice titles read "Recruitment of 25 Junior Engineers on contract basis at Noida":
  // keep just the role for "Looking For ...", since the type and location have their own lines.
  function postRole(j) {
    if (!j.is_notice) return j.title;
    let t = j.title.replace(/^(notification\s+for\s+)?(recruitment|engagement|appointment|filling\s+up|walk[- ]?in(\s+interview)?)(\s+of|\s+for)?\s+/i, '');
    t = t.replace(/\s+on\s+(a\s+)?contract(ual)?\s+basis/i, '').replace(/\s+(at|in)\s+[A-Z][\w\s.,-]*$/, '');
    return t.trim() || j.title;
  }
  // The standard LinkedIn/WhatsApp format: one block per role, blocks separated by blank lines.
  function postBlock(j, o, edits) {
    const e = edits || {};
    const lines = [
      `Looking For ${(e.title ?? postRole(j)).trim()}${typeSuffix(j)} For ${(o.company || '').trim() || j.company}`,
      '',
      `Experience - ${(e.exp ?? j.experience) || 'Not specified'}`,
      `Location - ${(e.loc ?? postLocation(j)) || 'Not specified'}`,
      `Qualification - ${(e.qual ?? j.qualification) || 'Not specified'}`,
    ];
    const tail = [];
    if ((o.email || '').trim()) tail.push(`Please share resumes to ${o.email.trim()}`);
    if (o.link && safeHref(j.job_url)) tail.push(`Apply here: ${j.job_url}`);
    if (tail.length) lines.push('', ...tail);
    return lines.join('\n');
  }

  function openComposer(jobs) {
    if (!jobs.length) return;
    const dlg = $('#post-dialog'), single = jobs.length === 1, j0 = jobs[0];
    const text = $('#post-text'), company = $('#post-company'), email = $('#post-email'), link = $('#post-link');
    $('#post-title').textContent = single ? 'Create post' : `Create post for ${jobs.length} roles`;
    company.value = store.get('jobline.companyLine');
    email.value = store.get('jobline.resumeEmail') || state.me.email || '';
    link.checked = store.get('jobline.addLink') === '1';
    $('#post-single-fields').hidden = !single;
    if (single) {
      $('#post-role').value = postRole(j0); $('#post-exp').value = j0.experience || '';
      $('#post-loc').value = postLocation(j0); $('#post-qual').value = j0.qualification || '';
    }
    const missing = () => {
      const m = new Set();
      jobs.forEach((j) => {
        if (single ? !$('#post-exp').value.trim() : !j.experience) m.add('experience');
        if (single ? !$('#post-qual').value.trim() : !j.qualification) m.add('qualification');
      });
      return [...m];
    };
    const syncWa = () => { $('#post-wa').href = 'https://wa.me/?text=' + encodeURIComponent(text.value); };
    const build = () => {
      const o = { company: company.value, email: email.value, link: link.checked };
      const edits = single ? { title: $('#post-role').value, exp: $('#post-exp').value, loc: $('#post-loc').value, qual: $('#post-qual').value } : null;
      text.value = jobs.map((j) => postBlock(j, o, edits)).join('\n\n\n');
      const m = missing(), warn = $('#post-warn');
      warn.hidden = !m.length;
      warn.textContent = m.length ? `${single ? 'The posting' : 'Some postings'} didn’t state ${m.join(' or ')}, so the post says “Not specified”. ${single ? 'Fill it in above' : 'Edit it in the text'} before sharing.` : '';
      $('#post-email-hint').hidden = !email.value.trim() || /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.value.trim());
      syncWa();
      store.set('jobline.companyLine', company.value); store.set('jobline.resumeEmail', email.value); store.set('jobline.addLink', link.checked ? '1' : '0');
    };
    dlg.querySelectorAll('input').forEach((el) => { el.oninput = build; el.onchange = build; });
    text.oninput = syncWa;
    $('#post-copy').onclick = () => copyText(text.value, 'Post copied. Paste it into LinkedIn or WhatsApp.');
    $('#post-linkedin').onclick = async () => { await copyText(text.value, 'Post copied. Paste it into the LinkedIn post box.'); window.open('https://www.linkedin.com/feed/', '_blank', 'noopener'); };
    $('#post-close').onclick = () => dlg.close();
    build();
    dlg.showModal();
  }

  async function copyText(value, msg) {
    try { await navigator.clipboard.writeText(value); toast(msg); return; } catch (_) { /* fall back below */ }
    const t = $('#post-text'); t.focus(); t.select();
    try { document.execCommand('copy'); toast(msg); } catch (_) { toast('Select the text and copy it with Ctrl+C.', true); }
  }

  function renderSelectionBar() {
    const bar = $('#select-bar'), n = state.selected.size;
    document.body.classList.toggle('has-selection', n > 0);
    bar.hidden = n === 0;
    if (!n) return;
    bar.replaceChildren(
      h('span', null, `${n} role${n === 1 ? '' : 's'} selected`),
      h('button', { class: 'btn signal small', type: 'button', onclick: () => openComposer([...state.selected.values()]) }, icon('send'), n > 1 ? 'Create one post' : 'Create post'),
      h('button', { class: 'btn small', type: 'button', onclick: () => {
        state.selected.clear(); document.querySelectorAll('input.pick').forEach((c) => { c.checked = false; });
        document.querySelectorAll('.job.is-selected').forEach((el) => el.classList.remove('is-selected')); renderSelectionBar();
      } }, 'Clear selection'));
  }

  /* ------------------------------------------------------------ drawer */
  let lastFocus = null;
  async function openDrawer(id) {
    lastFocus = document.activeElement;
    const root = $('#drawer-root');
    const close = () => { root.replaceChildren(); document.removeEventListener('keydown', onKey); lastFocus && lastFocus.focus && lastFocus.focus(); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    const closeBtn = h('button', { class: 'btn small ghost', type: 'button', onclick: close, 'aria-label': 'Close job details' }, icon('x'), 'Close');
    const body = h('div', { class: 'drawer-body' }, h('div', { class: 'skeleton' }));
    const titleEl = h('h2', { id: 'drawer-title' }, 'Job details');
    const headMain = h('div', null, titleEl);
    const head = h('div', { class: 'drawer-head' }, h('span'), headMain, closeBtn);
    root.replaceChildren(
      h('div', { class: 'scrim', onclick: close }),
      h('aside', { class: 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-labelledby': 'drawer-title' }, head, body),
    );
    closeBtn.focus();
    try {
      const j = await api(`/api/jobs/${id}`);
      titleEl.textContent = j.title;
      head.firstChild.replaceWith(logo(j.company));
      headMain.append(h('div', { class: 'job-sub' },
        h('span', { class: 'co' }, j.company),
        j.location && h('span', null, icon('pin'), j.location),
        j.department && h('span', null, j.department)));
      const href = safeHref(j.job_url);
      const intern = j.employment_type === 'Internship';
      const fact = (k, v) => v && h('div', { class: 'fact' }, h('dt', null, k), h('dd', null, v));
      body.replaceChildren(
        h('div', { class: 'chips' },
          j.experience && h('span', { class: 'tag exp' }, icon('briefcase'), j.experience),
          j.employment_type && h('span', { class: 'tag' + (intern ? ' intern' : '') }, j.employment_type),
          j.workplace_type && h('span', { class: 'tag' }, label(j.workplace_type)),
          j.is_notice && h('span', { class: 'tag gov' }, icon('building'), 'Government notice'),
          j.status === 'possibly_closed' && h('span', { class: 'tag closed' }, 'Possibly closed'),
          j.status === 'archived' && h('span', { class: 'tag closed' }, 'Over the per-company limit')),
        h('div', { class: 'drawer-actions' },
          h('button', { class: 'btn primary', type: 'button', onclick: () => openComposer([j]) }, icon('send'), 'Create post'),
          href && h('a', { class: 'btn', href, target: '_blank', rel: 'noopener noreferrer' }, icon('external'),
            j.is_notice ? 'Open official notice' : 'View original posting', h('span', { class: 'visually-hidden' }, ' (opens in a new tab)'))),
        j.is_notice
          ? h('section', null, h('h3', null, 'Government notice'),
              h('div', { class: 'callout' }, `Official recruitment notice from ${j.company}. Eligibility, age limit, fees and the last date are in the notice itself, so open it before applying or sharing.`))
          : summarySection(j),
        h('section', null, h('h3', null, 'At a glance'),
          h('dl', { class: 'facts-grid' },
            fact('Experience', j.experience || 'Not stated'),
            fact('Qualification', j.qualification || 'Not stated'),
            fact('Location', j.location || 'Not stated'),
            fact('Source', h('a', { href: safeHref(j.source.careers_url) || '#', target: '_blank', rel: 'noopener noreferrer' }, j.source.name)),
            fact('First seen', full(j.first_seen_at)),
            fact('Last seen', full(j.last_seen_at)),
            j.posted_at && fact('Posted', full(j.posted_at)),
            j.external_job_id && fact('Job ID', j.external_job_id),
            j.summary_model && j.summary_status === 'ai' && fact('Summary by', `${j.summary_model}, ${full(j.summarised_at)}`))),
        h('section', null, h('h3', null, 'Full description'),
          h('div', { class: 'description' }, j.description || 'The source did not provide a description.')),
      );
    } catch (e) {
      body.replaceChildren(h('p', { class: 'err-text' }, e.message));
    }
  }

  /* ------------------------------------------------------------ jobs view */
  const DEFAULT_QUERY = { q: '', sector: '', source: '', employment_type: '', workplace_type: '', city: '', experience: '', include_unspecified: '1', discovered: '', status: 'active' };
  const QUICK = [
    { label: 'Internships', icon: 'cap', on: (q) => q.employment_type === 'Internship', set: (q, on) => { q.employment_type = on ? 'Internship' : ''; } },
    { label: 'Freshers (0–1 yrs)', icon: 'sprout', on: (q) => q.experience === '0' && q.include_unspecified === '0',
      set: (q, on) => { q.experience = on ? '0' : ''; q.include_unspecified = on ? '0' : '1'; } },
    { label: 'Remote', icon: 'globe', on: (q) => q.city === 'Remote', set: (q, on) => { q.city = on ? 'Remote' : ''; } },
    { label: 'Government', icon: 'building', on: (q) => q.sector === 'government', set: (q, on) => { q.sector = on ? 'government' : ''; } },
    { label: 'New this week', icon: 'calendar', on: (q) => q.discovered === '7', set: (q, on) => { q.discovered = on ? '7' : ''; } },
  ];
  const DISCOVERED = { 1: 'Found in the last 24 hours', 7: 'Found in the last 7 days', 30: 'Found in the last 30 days' };
  const STATUS_LABEL = { possibly_closed: 'Possibly closed', archived: 'Over the per-company limit', all: 'All statuses' };

  function plainSelect(id, labelText, options, value, onChange, cls) {
    const sel = h('select', { id, class: cls || null, 'aria-label': labelText, onchange: (e) => onChange(e.target.value) },
      ...options.map(([v, t]) => h('option', { value: v }, t)));
    sel.value = value;
    return sel;
  }
  function fieldWrap(labelText, control, forId) {
    return h('div', { class: 'fgroup' }, h('label', { class: 'fgroup-label', for: forId }, labelText), control);
  }

  async function viewJobs() {
    const root = $('#view');
    const q = state.query;
    let timer, seq = 0;
    if (!state.filters) state.filters = await api('/api/filters');
    const f = state.filters;
    const changed = () => { q.page = 1; sync(); load(); };

    // ---- search band
    const search = h('input', { type: 'search', id: 'f-q', value: q.q, placeholder: 'Job title, skill or company', 'aria-label': 'Search jobs by title, skill, company or location',
      oninput: (e) => { q.q = e.target.value; clearTimeout(timer); timer = setTimeout(changed, 300); } });
    const city = plainSelect('f-city', 'City', [['', 'Any city'], ...(f.cities || []).map((c) => [c.name, `${c.name} (${num(c.count)})`])], q.city, (v) => { q.city = v; changed(); });
    const expOptions = [['', 'Any experience'], ['0', 'Fresher (0 years)'], ...[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 15, 20].map((n) => [String(n), `${n} year${n === 1 ? '' : 's'} experience`])];
    const exp = plainSelect('f-experience', 'Candidate experience', expOptions, q.experience, (v) => { q.experience = v; if (!v) q.include_unspecified = '1'; changed(); });
    const quickRow = h('div', { class: 'quick', role: 'group', 'aria-label': 'Quick filters' });
    const hero = h('section', { class: 'hero', 'aria-labelledby': 'hero-title' },
      h('h1', { id: 'hero-title' }, 'Find roles to share'),
      h('p', { class: 'hero-stats', id: 'status-line' }, ...statusLine()),
      h('div', { class: 'searchbar', role: 'search' },
        h('label', { class: 'sb-cell' }, icon('search'), search),
        h('label', { class: 'sb-cell' }, icon('pin'), city),
        h('label', { class: 'sb-cell' }, icon('briefcase'), exp)),
      quickRow);

    // ---- sidebar filters
    const seg = h('div', { class: 'seg', role: 'group', 'aria-label': 'Sector' });
    const sectorCounts = f.sectors || {};
    const segButtons = [['', 'All'], ['private', 'Private'], ['government', 'Govt']].map(([v, t]) =>
      h('button', { type: 'button', 'data-v': v, title: v ? `${t === 'Govt' ? 'Government' : t}${sectorCounts[v] ? `: ${num(sectorCounts[v])} jobs` : ''}` : 'All sectors',
        onclick: () => { q.sector = v; changed(); } }, t));
    seg.append(...segButtons);
    const company = plainSelect('f-source', 'Company', [['', 'All companies'], ...f.companies.map((c) => [String(c.id), `${c.name} (${num(c.count)})`])], q.source, (v) => { q.source = v; changed(); });
    const jobType = plainSelect('f-employment_type', 'Job type', [['', 'Any type'], ...f.employment_types.map((t) => [t, t])], q.employment_type, (v) => { q.employment_type = v; changed(); });
    const workplace = plainSelect('f-workplace_type', 'Workplace', [['', 'Any workplace'], ...f.workplace_types.map((t) => [t, label(t)])], q.workplace_type, (v) => { q.workplace_type = v; changed(); });
    const discovered = plainSelect('f-discovered', 'Found', [['', 'Any time'], ['1', 'Last 24 hours'], ['7', 'Last 7 days'], ['30', 'Last 30 days']], q.discovered, (v) => { q.discovered = v; changed(); });
    const status = plainSelect('f-status', 'Status', [['active', 'Open'], ['possibly_closed', 'Possibly closed'], ['archived', 'Over the per-company limit'], ['all', 'All']], q.status, (v) => { q.status = v; changed(); });
    const unspecified = h('input', { type: 'checkbox', id: 'f-unspec', onchange: (e) => { q.include_unspecified = e.target.checked ? '1' : '0'; changed(); } });
    const resetBtn = h('button', { type: 'button', class: 'clear-all', onclick: () => { Object.assign(q, DEFAULT_QUERY); search.value = ''; changed(); } }, 'Reset');
    const sideCount = h('span', { class: 'muted-text' });
    const sidebar = h('details', { class: 'panel sidebar', open: window.matchMedia('(min-width: 1081px)').matches },
      h('summary', null, h('span', { style: 'display:inline-flex;gap:8px;align-items:center' }, icon('sliders'), 'Filters ', sideCount), h('span', { class: 'muted-text' }, 'Show / hide')),
      h('div', { class: 'filter-body' },
        h('div', { class: 'filter-title' }, h('h2', null, 'Filters'), resetBtn),
        h('div', { class: 'fgroup' }, h('span', { class: 'fgroup-label' }, 'Sector'), seg),
        fieldWrap('Company', company, 'f-source'),
        fieldWrap('Job type', jobType, 'f-employment_type'),
        fieldWrap('Workplace', workplace, 'f-workplace_type'),
        fieldWrap('Found', discovered, 'f-discovered'),
        fieldWrap('Status', status, 'f-status'),
        h('label', { class: 'check filter-check' }, unspecified, 'When filtering by experience, include jobs that don’t state it')));

    // ---- results column
    const countEl = h('h2', { class: 'results-count', id: 'results-count', tabindex: '-1' }, 'Loading jobs…');
    const sort = plainSelect('f-ordering', 'Sort by', [['newest', 'Newest first'], ['company', 'Company A–Z'], ['title', 'Job title A–Z']], q.ordering, (v) => { q.ordering = v; q.page = 1; load(); });
    const quotaPill = h('span', { class: 'quota-pill' }, icon('sparkle'), h('span', { class: 'quota-live' }, quotaText()));
    const activeRow = h('div', { class: 'active-filters', 'aria-label': 'Active filters' });
    const results = h('div', null, h('div', { class: 'skeleton' }), h('div', { class: 'skeleton', style: 'margin-top:12px' }));
    root.replaceChildren(hero,
      h('div', { class: 'jobs-layout' }, sidebar,
        h('section', { 'aria-labelledby': 'results-count' },
          h('div', { class: 'results-bar' }, countEl,
            h('div', { class: 'results-tools' }, state.me.ai_enabled && quotaPill, h('label', { class: 'muted-text', for: 'f-ordering' }, 'Sort'), sort)),
          activeRow, results)));

    function activeFilters() {
      const list = [];
      const add = (text, clear) => list.push([text, clear]);
      if (q.q) add(`“${q.q}”`, () => { q.q = ''; search.value = ''; });
      if (q.sector) add(q.sector === 'government' ? 'Government' : 'Private companies', () => { q.sector = ''; });
      if (q.city) add(q.city, () => { q.city = ''; });
      if (q.experience) add((q.experience === '0' ? 'Fresher' : `${q.experience} yrs experience`) + (q.include_unspecified === '0' ? ' (stated only)' : ''),
        () => { q.experience = ''; q.include_unspecified = '1'; });
      if (q.source) { const c = f.companies.find((x) => String(x.id) === String(q.source)); add(c ? c.name : 'Company', () => { q.source = ''; }); }
      if (q.employment_type) add(q.employment_type, () => { q.employment_type = ''; });
      if (q.workplace_type) add(label(q.workplace_type), () => { q.workplace_type = ''; });
      if (q.discovered) add(DISCOVERED[q.discovered] || 'Recent', () => { q.discovered = ''; });
      if (q.status !== 'active') add(STATUS_LABEL[q.status] || label(q.status), () => { q.status = 'active'; });
      return list;
    }

    function sync() {
      if (search.value !== q.q) search.value = q.q;
      city.value = q.city; exp.value = q.experience; company.value = String(q.source || '');
      jobType.value = q.employment_type; workplace.value = q.workplace_type; discovered.value = q.discovered; status.value = q.status;
      unspecified.checked = q.include_unspecified === '1'; unspecified.disabled = !q.experience;
      segButtons.forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.v === (q.sector || ''))));
      quickRow.replaceChildren(h('span', { class: 'quick-label' }, 'Quick filters'), ...QUICK.map((c) => h('button', {
        type: 'button', class: 'qchip', 'aria-pressed': String(c.on(q)),
        onclick: () => { c.set(q, !c.on(q)); changed(); } }, icon(c.icon), c.label)));
      const act = activeFilters();
      sideCount.textContent = act.length ? `(${act.length})` : '';
      activeRow.hidden = !act.length;
      activeRow.replaceChildren(...act.map(([text, clear]) => h('button', { type: 'button', class: 'afchip', 'aria-label': `Remove filter: ${text}`,
        onclick: () => { clear(); changed(); countEl.focus(); } }, text, icon('x'))),
        act.length > 1 && h('button', { type: 'button', class: 'clear-all', onclick: () => { Object.assign(q, DEFAULT_QUERY); changed(); countEl.focus(); } }, 'Clear all'));
    }

    async function load() {
      const mine = ++seq;
      const params = new URLSearchParams();
      Object.entries(q).forEach(([k, v]) => { if (v !== '' && v != null) params.set(k, v); });
      try {
        const d = await api('/api/jobs?' + params);
        if (mine !== seq) return;
        q.page = d.page;
        state.rows.clear(); state.rowJobs.clear();
        const filtered = activeFilters().length > 0;
        countEl.textContent = `${num(d.count)} ${d.count === 1 ? 'role' : 'roles'}${filtered ? (d.count === 1 ? ' matches your filters' : ' match your filters') : ''}`;
        if (!d.results.length) {
          results.replaceChildren(h('div', { class: 'empty' },
            h('strong', null, filtered ? 'No roles match these filters' : 'No jobs collected yet'),
            filtered ? 'Remove a filter or try a different search.' : (state.me.is_admin ? 'Add a company on the Sources page, then fetch jobs.' : 'An administrator needs to run the first fetch.'),
            filtered && h('div', null, h('button', { type: 'button', class: 'btn', onclick: () => { Object.assign(q, DEFAULT_QUERY); changed(); } }, 'Clear all filters'))));
          return;
        }
        const first = (d.page - 1) * d.page_size + 1, last = first + d.results.length - 1;
        results.replaceChildren(
          h('ul', { class: 'jobs' }, d.results.map(jobRow)),
          h('nav', { class: 'pager', 'aria-label': 'Pages' },
            h('button', { class: 'btn small', type: 'button', disabled: d.page <= 1, onclick: () => { q.page = d.page - 1; load(); countEl.focus(); window.scrollTo({ top: 0 }); } }, 'Previous'),
            h('span', null, `${num(first)}–${num(last)} of ${num(d.count)}`),
            h('button', { class: 'btn small', type: 'button', disabled: d.page >= d.num_pages, onclick: () => { q.page = d.page + 1; load(); countEl.focus(); window.scrollTo({ top: 0 }); } }, 'Next')),
        );
      } catch (e) { results.replaceChildren(h('div', { class: 'empty' }, h('strong', null, 'Could not load jobs'), e.message)); }
    }
    state.refreshView = ({ quiet }) => { if (!quiet) { state.filters = null; viewJobs(); } };
    sync();
    load();
  }

  function jobRow(j) {
    const href = safeHref(j.job_url);
    const open = () => openDrawer(j.id);
    const ai = j.summary_status === 'ai';
    state.rowJobs.set(j.id, j);
    let li;
    const pick = h('input', { type: 'checkbox', class: 'pick', checked: state.selected.has(j.id), 'aria-label': `Select ${j.title} at ${j.company} for a combined post`,
      onclick: (e) => e.stopPropagation(),
      onkeydown: (e) => e.stopPropagation(),
      onchange: (e) => {
        if (e.target.checked) state.selected.set(j.id, j); else state.selected.delete(j.id);
        li.classList.toggle('is-selected', e.target.checked); renderSelectionBar();
      } });
    const intern = j.employment_type === 'Internship';
    li = h('li', { class: 'job' + (state.selected.has(j.id) ? ' is-selected' : ''), tabindex: '0', 'aria-label': `${j.title} at ${j.company}. Press Enter for details`, onclick: open,
      onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(); } },
      pick,
      logo(j.company),
      h('div', { class: 'job-main' },
        h('h3', null, j.title),
        h('div', { class: 'job-sub' },
          h('span', { class: 'co' }, j.company),
          j.location && h('span', null, icon('pin'), j.location)),
        h('div', { class: 'chips' },
          j.experience && h('span', { class: 'tag exp' }, icon('briefcase'), j.experience),
          j.employment_type && h('span', { class: 'tag' + (intern ? ' intern' : '') }, intern && icon('cap'), j.employment_type),
          j.workplace_type && h('span', { class: 'tag' }, label(j.workplace_type)),
          j.is_notice && h('span', { class: 'tag gov' }, icon('building'), 'Government notice'),
          ai && h('span', { class: 'tag ai' }, icon('sparkle'), 'AI summary'),
          j.status === 'possibly_closed' && h('span', { class: 'tag closed' }, 'Possibly closed'),
          j.status === 'archived' && h('span', { class: 'tag closed' }, 'Over the per-company limit')),
        h('p', { class: 'summary' + (ai ? '' : ' excerpt') }, ai ? j.summary : (j.excerpt || (j.is_notice ? 'Official recruitment notice. Open it for eligibility, age limit and the last date.' : 'No description provided.'))),
        !j.is_notice && !ai && state.me.ai_enabled && h('div', { class: 'summary-actions' }, summaryButton(j, { text: 'Summarise with AI' }))),
      h('div', { class: 'job-side' },
        h('time', { datetime: j.first_seen_at, title: `First seen ${full(j.first_seen_at)}` }, icon('clock'), `Found ${ago(j.first_seen_at)}`),
        h('button', { class: 'btn small primary', type: 'button', onclick: (e) => { e.stopPropagation(); openComposer([j]); } }, icon('send'), 'Create post'),
        href && h('a', { class: 'btn small', href, target: '_blank', rel: 'noopener noreferrer', onclick: (e) => e.stopPropagation() },
          icon('external'), j.is_notice ? 'Official notice' : 'View posting', h('span', { class: 'visually-hidden' }, ' (opens in a new tab)'))));
    state.rows.set(j.id, li);
    return li;
  }

  /* ------------------------------------------------------------ runs view */
  async function viewRuns({ quiet } = {}) {
    const root = $('#view');
    const d = await api('/api/fetch-runs');
    const expanded = new Set([...root.querySelectorAll('tr.detail')].map((r) => r.dataset.run));
    const tbody = h('tbody');
    d.results.forEach((r) => {
      const tr = h('tr', { class: 'clickable', tabindex: '0', 'aria-expanded': 'false', onclick: () => toggle(r.id, tr),
        onkeydown: (e) => { if (e.key === 'Enter') toggle(r.id, tr); } },
        h('td', null, h('strong', null, `#${r.id}`), h('span', { class: 'cell-sub' }, `${label(r.trigger)}${r.triggered_by ? ' by ' + r.triggered_by : ''}`)),
        h('td', { title: full(r.started_at || r.created_at) }, ago(r.started_at || r.created_at)),
        h('td', null, r.started_at ? duration(r.started_at, r.completed_at) : ''),
        h('td', null, h('span', { class: 'chip ' + r.status }, label(r.status)), r.is_active && r.current_step && h('span', { class: 'cell-sub' }, r.current_step)),
        h('td', { class: 'num' }, `${r.successful_sources} / ${r.failed_sources} / ${r.skipped_sources}`),
        h('td', { class: 'num' }, `${num(r.jobs_discovered)} / ${num(r.jobs_created)} / ${num(r.jobs_updated)}`));
      tbody.append(tr);
      if (expanded.has(String(r.id))) toggle(r.id, tr, true);
    });
    const table = h('table', null,
      h('thead', null, h('tr', null,
        h('th', null, 'Run'), h('th', null, 'Started'), h('th', null, 'Duration'), h('th', null, 'Status'),
        h('th', { class: 'num' }, 'Sources ok / failed / skipped'), h('th', { class: 'num' }, 'Jobs found / new / updated'))),
      tbody);
    root.replaceChildren(
      h('div', { class: 'page-head' }, h('div', null, h('h1', null, 'Fetch runs'),
        h('p', { class: 'lead' }, 'Each run collects the latest postings from every switched-on source. Select a run to see what happened for each company.'))),
      h('div', { class: 'panel table-wrap' }, d.results.length ? table : h('div', { class: 'empty' }, h('strong', null, 'No runs yet'),
        state.me.is_admin ? 'Choose Fetch jobs now to collect jobs.' : 'An administrator needs to start the first run.')));
    state.refreshView = viewRuns;

    async function toggle(id, tr, forceOpen) {
      const next = tr.nextElementSibling;
      if (next && next.classList.contains('detail') && !forceOpen) { next.remove(); tr.setAttribute('aria-expanded', 'false'); return; }
      if (next && next.classList.contains('detail')) next.remove();
      const cell = h('td', { colspan: '6' }, 'Loading…');
      const row = h('tr', { class: 'detail', 'data-run': String(id) }, cell);
      tr.after(row); tr.setAttribute('aria-expanded', 'true');
      try {
        const r = await api(`/api/fetch-runs/${id}`);
        cell.replaceChildren(
          r.error_summary && h('p', { class: 'err-text', style: 'white-space:pre-wrap' }, r.error_summary),
          r.results.length ? h('table', null,
            h('thead', null, h('tr', null, ['Source', 'Result', 'Found', state.me.country_filter === 'IN' ? 'Outside India' : 'Filtered out', state.me.max_jobs_per_company ? `Over the ${state.me.max_jobs_per_company} limit` : 'Over limit', 'New', 'Updated', 'Closed', 'Message'].map((t, i) => h('th', { class: i > 1 && i < 8 ? 'num' : '' }, t)))),
            h('tbody', null, r.results.map((x) => h('tr', null,
              h('td', null, x.company), h('td', null, h('span', { class: 'chip ' + x.status }, label(x.status))),
              h('td', { class: 'num' }, num(x.discovered)), h('td', { class: 'num' }, num(x.outside_country)), h('td', { class: 'num' }, num(x.over_cap)), h('td', { class: 'num' }, num(x.created)), h('td', { class: 'num' }, num(x.updated)), h('td', { class: 'num' }, num(x.closed)),
              h('td', null, x.error && h('div', { class: 'err-text' }, x.error), x.warnings && h('div', { class: 'warn-text' }, x.warnings)))))) : 'No per-source results yet.');
      } catch (e) { cell.textContent = e.message; }
    }
  }

  /* ------------------------------------------------------------ sources view */
  async function viewSources({ quiet } = {}) {
    const root = $('#view');
    if (!quiet) { const s = await api('/api/sources'); state.sources = s.results; state.adapters = s.adapters; }
    const admin = state.me.is_admin;
    const counts = { all: state.sources.length };
    state.sources.forEach((s) => { const k = sourceState(s).chip || 'never'; counts[k] = (counts[k] || 0) + 1; });
    const match = (s) => {
      const st = sourceState(s);
      // "Needs an adapter" and "Failing" include paused sources, so they can be found again and switched back on.
      return { all: true, collecting: st.cls === 'ok', failing: s.last_status === 'failed', adapter: s.adapter === 'unsupported',
        paused: !s.active }[state.sourceFilter];
    };
    const filter = h('select', { id: 'src-filter', 'aria-label': 'Which sources to show', onchange: (e) => { state.sourceFilter = e.target.value; viewSources({ quiet: true }); } },
      [['all', 'All sources'], ['collecting', 'Collecting'], ['failing', 'Failing'], ['adapter', 'Needs an adapter'], ['paused', 'Paused']].map(([v, t]) => h('option', { value: v, selected: state.sourceFilter === v }, t)));
    const shown = state.sources.filter(match);
    const onCount = shown.filter((s) => s.active).length;
    const allSwitch = h('input', { type: 'checkbox', checked: shown.length > 0 && onCount === shown.length, disabled: !shown.length,
      'aria-label': `Collect from all ${shown.length} sources shown`,
      onchange: (e) => setAllActive(shown, e.target.checked) });
    allSwitch.indeterminate = onCount > 0 && onCount < shown.length;
    const collectHead = h('th', null, h('div', { class: 'collect-head' }, 'Collect',
      h('label', { class: 'switch', title: onCount === shown.length ? 'Turn off all sources shown' : 'Turn on all sources shown' }, allSwitch, h('i')),
      h('span', { class: 'collect-count' }, `${onCount}/${shown.length}`)));
    const rows = shown.map((s) => {
      const st = sourceState(s);
      return h('tr', { 'data-source-row': String(s.id) },
        h('td', null, h('a', { href: safeHref(s.careers_url) || '#', target: '_blank', rel: 'noopener noreferrer' }, s.company),
          s.sector === 'government' && h('span', { class: 'cell-sub' }, 'Government')),
        h('td', null, s.adapter === 'unsupported' ? 'None' : (s.adapter === 'notice_board' ? 'Government notice page' : label(s.adapter)),
          admin && s.board && h('span', { class: 'cell-sub' }, s.board + (s.region === 'eu' ? ' (EU)' : '')),
          admin && s.notice_url && h('span', { class: 'cell-sub' }, (() => { try { return new URL(s.notice_url).host; } catch (_) { return s.notice_url; } })())),
        h('td', { class: 'num' }, s.job_count == null ? '' : num(s.job_count)),
        h('td', { title: full(s.last_success_at) }, s.last_success_at ? ago(s.last_success_at) : 'Never'),
        h('td', null, h('span', { class: 'chip ' + st.chip }, st.text),
          admin && s.last_error && s.last_status === 'failed' && h('div', { class: 'err-text' }, s.last_error),
          admin && s.consecutive_failures > 1 && h('div', { class: 'warn-text' }, `Failed ${s.consecutive_failures} runs in a row`)),
        admin && h('td', null,
          h('label', { class: 'switch', title: s.active ? 'Pause this source' : 'Resume this source' },
            h('input', { type: 'checkbox', checked: s.active, 'aria-label': `Collect from ${s.company}`, onchange: (e) => toggleActive(s, e.target.checked) }), h('i')),),
        admin && h('td', null, h('div', { style: 'display:flex;gap:.4rem' },
          h('button', { class: 'btn small', type: 'button', onclick: () => editSource(s) }, 'Edit'),
          s.adapter !== 'unsupported' && s.active && h('button', { class: 'btn small', type: 'button', disabled: !!state.overview.active_run, onclick: () => startFetch([s.id]) }, 'Fetch'))));
    });
    root.replaceChildren(
      h('div', { class: 'page-head' },
        h('div', null, h('h1', null, 'Sources'),
          h('p', { class: 'lead' }, 'Company job boards and official government pages that Jobline collects from.')),
        h('div', { class: 'page-actions' },
          admin && h('button', { class: 'btn primary', type: 'button', onclick: addCompany }, icon('plus'), 'Add source'))),
      h('section', { class: 'panel health', 'aria-label': 'Source health' },
        h('div', { class: 'health-stats', id: 'health-stats' }),
        h('div', { class: 'grid51', id: 'grid' }),
        h('div', { class: 'legend' },
          h('span', null, h('i', { class: 'ok' }), 'Collecting'), h('span', null, h('i', { class: 'failed' }), 'Last fetch failed'),
          h('span', null, h('i', { class: 'skipped' }), 'Needs an adapter'), h('span', null, h('i'), 'Not fetched yet or paused'))),
      h('div', { class: 'panel' },
        h('div', { class: 'toolbar' },
          h('label', { class: 'muted-text', style: 'display:flex;gap:10px;align-items:center' }, 'Show', filter),
          h('span', { class: 'muted-text' }, `${num(shown.length)} source${shown.length === 1 ? '' : 's'}`)),
        h('div', { class: 'table-wrap' }, h('table', null,
          h('thead', null, h('tr', null, h('th', null, 'Company'), h('th', null, 'Adapter'), h('th', { class: 'num' }, 'Open jobs'), h('th', null, 'Last success'), h('th', null, 'Status'),
            admin && collectHead, admin && h('th', null, h('span', { class: 'visually-hidden' }, 'Actions')))),
          h('tbody', null, rows)))),
      !admin && h('p', { class: 'muted-text', style: 'margin-top:12px' }, 'Only administrators can change sources.'));
    renderHealth();
    state.refreshView = viewSources;
  }

  async function setAllActive(list, active) {
    const where = state.sourceFilter === 'all' ? '' : ' shown';
    try {
      const r = await api('/api/sources/bulk-active', { method: 'POST', body: { active, ids: list.map((s) => s.id) } });
      toast(`Collection turned ${active ? 'on' : 'off'} for all ${num(r.matched)}${where} sources${r.changed !== r.matched ? ` (${num(r.changed)} changed)` : ''}.`);
    } catch (e) { toast(e.message, true); }
    await refreshStatus();
    viewSources({});
  }
  async function toggleActive(s, active) {
    try { await api(`/api/sources/${s.id}`, { method: 'PATCH', body: { active } }); s.active = active; await refreshStatus(); viewSources({ quiet: true }); }
    catch (e) { toast(e.message, true); viewSources({}); }
  }

  /* ------------------------------------------------------------ add company */
  function addCompany() {
    const dlg = $('#add-dialog'), name = $('#add-name'), link = $('#add-link'), box = $('#add-result'), save = $('#add-save');
    const kind = $('#add-kind'), gurl = $('#add-gov-url'), pdf = $('#add-pdf-only');
    name.value = ''; link.value = ''; gurl.value = ''; pdf.checked = true; kind.value = 'company';
    box.hidden = true; save.disabled = false;
    const sync = () => {
      const gov = kind.value === 'government';
      $('#add-company-fields').hidden = gov; $('#add-gov-fields').hidden = !gov;
      $('#add-name-label').textContent = gov ? 'Organisation name' : 'Company name';
      link.required = !gov; gurl.required = gov;
    };
    kind.onchange = sync; sync();
    $('#add-cancel').onclick = () => dlg.close();
    $('#add-form').onsubmit = async (ev) => {
      ev.preventDefault();
      const gov = kind.value === 'government';
      save.disabled = true; box.hidden = false; box.className = 'test-result';
      box.textContent = gov ? 'Reading the page and looking for recruitment notices…' : 'Checking the job board…';
      const body = gov ? { kind: 'government', company_name: name.value.trim(), url: gurl.value.trim(), pdf_only: pdf.checked }
        : { company_name: name.value.trim(), board_url: link.value.trim() };
      try {
        const r = await api('/api/sources', { method: 'POST', body });
        dlg.close();
        toast(gov ? `${r.company} added: ${num(r.found)} recruitment notice${r.found === 1 ? '' : 's'} found. Fetching now.`
          : `${r.company} added: ${num(r.matching)} of ${num(r.found)} jobs match the location filter${r.kept < r.matching ? ` (the latest ${num(r.kept)} will be kept)` : ''}. Fetching now.`);
        await refreshStatus({ withSources: true });
        if (!state.overview.active_run) await startFetch([r.id]);
        viewSources({ quiet: true });
      } catch (e) { save.disabled = false; box.className = 'test-result bad'; box.textContent = e.message; }
    };
    dlg.showModal(); name.focus();
  }

  /* ------------------------------------------------------------ source editor */
  function editSource(s) {
    const dlg = $('#source-dialog');
    const adapter = $('#src-adapter'), board = $('#src-board'), region = $('#src-region'), testBox = $('#src-test');
    const nurl = $('#src-url'), npdf = $('#src-pdf-only');
    $('#source-title').textContent = `Edit ${s.company}`;
    adapter.replaceChildren(h('option', { value: 'unsupported' }, 'No adapter yet'), ...state.adapters.map((a) => h('option', { value: a.key }, a.label)));
    adapter.value = s.adapter; board.value = s.board || ''; region.value = s.region || 'global'; testBox.hidden = true;
    nurl.value = s.notice_url || ''; npdf.checked = s.pdf_only !== false;
    const sync = () => {
      const none = adapter.value === 'unsupported';
      const notice = adapter.value === 'notice_board';
      $('#src-board-field').hidden = none || notice;
      $('#src-notice-fields').hidden = !notice;
      $('#src-region-field').hidden = adapter.value !== 'lever';
      $('#src-board-label').textContent = adapter.value === 'lever' ? 'Lever site name (jobs.lever.co/NAME)' : 'Greenhouse board token (boards.greenhouse.io/TOKEN)';
      $('#src-test-btn').disabled = none;
    };
    adapter.onchange = sync; sync();
    const payload = () => (adapter.value === 'notice_board'
      ? { adapter: adapter.value, url: nurl.value.trim(), pdf_only: npdf.checked }
      : { adapter: adapter.value, board: board.value.trim(), region: region.value });
    $('#src-test-btn').onclick = async () => {
      testBox.hidden = false; testBox.className = 'test-result'; testBox.textContent = 'Testing…';
      try {
        const r = await api(`/api/sources/${s.id}/test`, { method: 'POST', body: payload() });
        testBox.className = 'test-result' + (r.ok ? '' : ' bad');
        const what = adapter.value === 'notice_board' ? 'recruitment notice' : 'open job';
        testBox.textContent = r.ok ? `Found ${num(r.count)} ${what}${r.count === 1 ? '' : 's'}${r.sample.length ? `, for example: ${r.sample.slice(0, 3).join('; ')}` : ''}.` : r.error;
      } catch (e) { testBox.className = 'test-result bad'; testBox.textContent = e.message; }
    };
    $('#src-cancel').onclick = () => dlg.close();
    $('#source-form').onsubmit = async (ev) => {
      ev.preventDefault();
      try {
        await api(`/api/sources/${s.id}`, { method: 'PATCH', body: payload() });
        dlg.close(); toast(`${s.company} saved.`);
        await refreshStatus(); viewSources({ quiet: true });
      } catch (e) { testBox.hidden = false; testBox.className = 'test-result bad'; testBox.textContent = e.message; }
    };
    dlg.showModal();
  }

  /* ------------------------------------------------------------ router + boot */
  const routes = { jobs: viewJobs, runs: viewRuns, sources: viewSources };
  async function route() {
    const name = (location.hash.match(/^#\/(\w+)/) || [])[1] || 'jobs';
    const key = routes[name] ? name : 'jobs';
    document.querySelectorAll('[data-route]').forEach((a) => (a.dataset.route === key ? a.setAttribute('aria-current', 'page') : a.removeAttribute('aria-current')));
    state.refreshView = null;
    try { await routes[key](); } catch (e) { $('#view').replaceChildren(h('div', { class: 'empty' }, h('strong', null, 'Something went wrong'), e.message)); }
  }

  async function boot() {
    try {
      state.me = await api('/api/me');
      $('#who-name').textContent = state.me.username;
      $('#who-role').textContent = state.me.is_admin ? 'Administrator' : 'Recruiter';
      $('#who-avatar').textContent = initials(state.me.username);
      await refreshStatus();
    } catch (e) { $('#view').replaceChildren(h('div', { class: 'empty' }, h('strong', null, 'Could not load the dashboard'), e.message)); return; }
    $('#fetch-btn').addEventListener('click', confirmFetch);
    $('#confirm-cancel').addEventListener('click', () => $('#confirm-dialog').close());
    $('#confirm-ok').addEventListener('click', async () => { $('#confirm-dialog').close(); await startFetch(); });
    window.addEventListener('hashchange', route);
    route();
  }
  boot();
})();
