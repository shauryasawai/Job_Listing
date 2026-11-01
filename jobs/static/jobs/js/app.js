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

  function toast(msg, bad = false) {
    const t = h('div', { class: 'toast' + (bad ? ' bad' : '') }, msg);
    $('#toasts').append(t);
    setTimeout(() => t.remove(), bad ? 7000 : 4000);
  }

  /* ------------------------------------------------------------ state */
  const state = {
    me: null, sources: [], adapters: [], overview: null, filters: null,
    query: { q: '', source: '', employment_type: '', workplace_type: '', location: '', discovered: '', status: 'active', ordering: 'newest', page: 1 },
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

  function renderStatus() {
    const o = state.overview, src = state.sources;
    const collecting = src.filter((s) => sourceState(s).cls === 'ok').length;
    $('#headline').textContent = o.jobs_active
      ? `${num(o.jobs_active)} open jobs${state.me.country_filter === 'IN' ? ' in India' : ''} from ${collecting} of ${src.length} sources`
      : 'No jobs collected yet';

    const parts = [];
    if (o.active_run) parts.push(`Fetch #${o.active_run.id} is running.`);
    else if (o.last_run) {
      const r = o.last_run;
      let t = `Last fetch finished ${ago(r.completed_at)}`;
      const bits = [];
      if (r.failed_sources) bits.push(`${r.failed_sources} failed`);
      if (r.skipped_sources) bits.push(`${r.skipped_sources} without an adapter`);
      t += bits.length ? `: ${bits.join(', ')}.` : '.';
      parts.push(t);
    } else parts.push(state.me.is_admin ? 'Nothing has been fetched yet. Use Fetch jobs now to start the first run.' : 'Nothing has been fetched yet.');
    if (o.jobs_new_24h) parts.push(`${num(o.jobs_new_24h)} new in the last 24 hours.`);
    parts.push(`Scheduled daily at ${state.me.daily_fetch_time} ${state.me.time_zone}.`);
    $('#subline').textContent = parts.join(' ');

    $('#grid').replaceChildren(...src.map((s) => {
      const st = sourceState(s);
      return h('button', {
        class: 'cell ' + st.cls, type: 'button', title: `${s.company}: ${st.text}`,
        'aria-label': `${s.company}: ${st.text}`, onclick: () => { location.hash = '#/sources'; },
      });
    }));

    // run progress + fetch button
    const run = o.active_run, btn = $('#fetch-btn'), box = $('#run-progress');
    btn.hidden = !state.me.is_admin;
    btn.disabled = !!run;
    btn.replaceChildren(...(run ? [h('span', { class: 'spinner', 'aria-hidden': 'true' }), ' Fetching…'] : ['Fetch jobs now']));
    if (run) {
      const done = run.successful_sources + run.failed_sources + run.skipped_sources;
      const summarising = /^Summarising/.test(run.current_step);
      const pct = run.total_sources ? Math.round((done / run.total_sources) * 100) : 0;
      box.hidden = false;
      box.className = 'progress' + (!run.total_sources || summarising ? ' indeterminate' : '');
      box.replaceChildren(
        h('strong', null, run.status === 'queued' ? 'Waiting for the worker to pick up the run' : run.current_step || 'Working'),
        h('div', null, `${num(run.jobs_created)} new jobs, ${num(run.jobs_updated)} updated so far`),
        h('div', { class: 'bar' }, h('i', { style: `width:${summarising ? 100 : pct}%` })),
      );
    } else { box.hidden = true; box.replaceChildren(); }
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
    if (r) toast(`Fetch #${r.id} ${label(r.status).toLowerCase()}: ${num(r.jobs_created)} new, ${num(r.jobs_updated)} updated, ${r.failed_sources} failed.`, r.status === 'failed');
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
  async function requestSummary(job, regenerate) {
    try {
      const j = await api(`/api/jobs/${job.id}/summary`, { method: 'POST', body: regenerate ? { regenerate: true } : {} });
      state.me.quota = j.quota; updateQuotaLabel(); updateRowFor(j);
      return j;
    } catch (e) {
      if (e.data && e.data.quota) { state.me.quota = e.data.quota; updateQuotaLabel(); }
      toast(e.message, true);
      return null;
    }
  }
  function summaryButton(job, { regenerate = false, primary = false, text, onDone }) {
    const canAsk = state.me.ai_enabled && state.me.quota.remaining > 0;
    const btn = h('button', { class: 'btn small' + (primary ? ' primary' : ''), type: 'button', 'data-summarise': '', disabled: !canAsk, title: canAsk ? null : quotaText(),
      onclick: async (e) => {
        e.stopPropagation();
        btn.disabled = true; btn.setAttribute('data-busy', ''); btn.replaceChildren(h('span', { class: 'spinner', 'aria-hidden': 'true' }), ' Summarising…');
        const j = await requestSummary(job, regenerate);
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
        ai && j.summary_stale && h('div', { class: 'warn-text' }, 'The posting changed after this summary was written.')),
      h('div', { class: 'summary-actions' },
        state.me.ai_enabled && summaryButton(j, { primary: !ai, regenerate: ai, text: ai ? 'Regenerate' : 'Summarise with AI', onDone: done }),
        h('span', { class: 'quota quota-live' }, quotaText())));
    return sec;
  }

  /* ------------------------------------------------------------ drawer */
  let lastFocus = null;
  async function openDrawer(id) {
    lastFocus = document.activeElement;
    const root = $('#drawer-root');
    const close = () => { root.replaceChildren(); document.removeEventListener('keydown', onKey); lastFocus && lastFocus.focus && lastFocus.focus(); };
    const onKey = (e) => { if (e.key === 'Escape') close(); };
    document.addEventListener('keydown', onKey);
    const closeBtn = h('button', { class: 'btn small', type: 'button', onclick: close }, 'Close');
    const body = h('div', { class: 'drawer-body' }, h('p', null, 'Loading…'));
    const head = h('div', { class: 'drawer-head' }, h('h2', null, 'Job details'), closeBtn);
    root.replaceChildren(
      h('div', { class: 'scrim', onclick: close }),
      h('aside', { class: 'drawer', role: 'dialog', 'aria-modal': 'true', 'aria-label': 'Job details' }, head, body),
    );
    closeBtn.focus();
    try {
      const j = await api(`/api/jobs/${id}`);
      head.firstChild.textContent = j.title;
      const href = safeHref(j.job_url);
      body.replaceChildren(
        h('div', { class: 'meta' },
          h('span', { class: 'co' }, j.company),
          j.location && h('span', null, j.location),
          j.department && h('span', null, j.department),
          j.employment_type && h('span', { class: 'tag' }, j.employment_type),
          j.workplace_type && h('span', { class: 'tag' }, label(j.workplace_type)),
          j.status === 'possibly_closed' && h('span', { class: 'tag closed' }, 'Possibly closed'),
        ),
        href && h('div', null, h('a', { class: 'btn primary', href, target: '_blank', rel: 'noopener noreferrer' }, 'Open original posting')),
        summarySection(j),
        h('section', null, h('h3', null, 'Full description'),
          h('div', { class: 'description' }, j.description || 'The source did not provide a description.')),
        h('section', null, h('h3', null, 'Record'),
          h('dl', { class: 'facts' },
            h('dt', null, 'Source'), h('dd', null, h('a', { href: safeHref(j.source.careers_url) || '#', target: '_blank', rel: 'noopener noreferrer' }, j.source.name)),
            h('dt', null, 'First seen'), h('dd', null, full(j.first_seen_at)),
            h('dt', null, 'Last seen'), h('dd', null, full(j.last_seen_at)),
            j.posted_at && [h('dt', null, 'Posted'), h('dd', null, full(j.posted_at))],
            h('dt', null, 'Last updated'), h('dd', null, full(j.updated_at)),
            j.external_job_id && [h('dt', null, 'Job ID'), h('dd', null, j.external_job_id)],
            j.summary_model && j.summary_status === 'ai' && [h('dt', null, 'Summary by'), h('dd', null, `${j.summary_model}, ${full(j.summarised_at)}`)],
          )),
      );
    } catch (e) {
      body.replaceChildren(h('p', { class: 'err-text' }, e.message));
    }
  }

  /* ------------------------------------------------------------ jobs view */
  function selectField(labelText, key, options, onChange) {
    const sel = h('select', { id: `f-${key}`, onchange: (e) => onChange(e.target.value) },
      ...options.map(([v, t]) => h('option', { value: v, selected: String(state.query[key]) === String(v) }, t)));
    return h('label', { class: 'field' }, h('span', null, labelText), sel);
  }

  async function viewJobs() {
    const root = $('#view');
    const results = h('div', { class: 'panel' });
    const bar = h('div', { class: 'results-bar' });
    let timer;
    const reload = (resetPage = true) => { if (resetPage) state.query.page = 1; load(); };

    if (!state.filters) state.filters = await api('/api/filters');
    const f = state.filters;
    const search = h('label', { class: 'field search' }, h('span', null, 'Search title, company, location or summary'),
      h('input', { type: 'search', id: 'f-q', value: state.query.q, placeholder: 'For example: data engineer remote',
        oninput: (e) => { state.query.q = e.target.value; clearTimeout(timer); timer = setTimeout(reload, 300); } }));
    const location = h('label', { class: 'field' }, h('span', null, 'Location contains'),
      h('input', { type: 'text', value: state.query.location, oninput: (e) => { state.query.location = e.target.value; clearTimeout(timer); timer = setTimeout(reload, 300); } }));
    const filters = h('div', { class: 'panel filters' }, search,
      selectField('Company', 'source', [['', 'All companies'], ...f.companies.map((c) => [c.id, `${c.name} (${c.count})`])], (v) => { state.query.source = v; reload(); }),
      selectField('Job type', 'employment_type', [['', 'Any type'], ...f.employment_types.map((t) => [t, t])], (v) => { state.query.employment_type = v; reload(); }),
      selectField('Workplace', 'workplace_type', [['', 'Any workplace'], ...f.workplace_types.map((t) => [t, label(t)])], (v) => { state.query.workplace_type = v; reload(); }),
      location,
      selectField('Discovered', 'discovered', [['', 'Any time'], ['1', 'Last 24 hours'], ['7', 'Last 7 days'], ['30', 'Last 30 days']], (v) => { state.query.discovered = v; reload(); }),
      selectField('Status', 'status', [['active', 'Active'], ['possibly_closed', 'Possibly closed'], ['all', 'All']], (v) => { state.query.status = v; reload(); }),
      selectField('Sort by', 'ordering', [['newest', 'Newest first'], ['company', 'Company'], ['title', 'Title']], (v) => { state.query.ordering = v; reload(); }),
    );
    root.replaceChildren(filters, bar, results);

    let seq = 0;
    async function load() {
      const mine = ++seq;
      const params = new URLSearchParams();
      Object.entries(state.query).forEach(([k, v]) => { if (v !== '' && v != null) params.set(k, v); });
      try {
        const d = await api('/api/jobs?' + params);
        if (mine !== seq) return;
        state.query.page = d.page;
        state.rows.clear();
        bar.replaceChildren(h('span', null, `${num(d.count)} job${d.count === 1 ? '' : 's'}`), h('span', { class: 'quota quota-live' }, quotaText()));
        if (!d.results.length) {
          const any = Object.entries(state.query).some(([k, v]) => v && !['status', 'ordering', 'page'].includes(k));
          results.replaceChildren(h('div', { class: 'empty' },
            h('strong', null, any ? 'No jobs match these filters' : 'No jobs collected yet'),
            any ? 'Clear a filter or try a different search.' : (state.me.is_admin ? 'Add a Greenhouse or Lever board on the Sources page, then choose Fetch jobs now.' : 'An administrator needs to run the first fetch.')));
          return;
        }
        results.replaceChildren(
          h('ul', { class: 'jobs' }, d.results.map(jobRow)),
          d.num_pages > 1 && h('div', { class: 'pager' },
            h('button', { class: 'btn small', type: 'button', disabled: d.page <= 1, onclick: () => { state.query.page = d.page - 1; load(); window.scrollTo({ top: 0 }); } }, 'Previous'),
            h('span', null, `Page ${d.page} of ${d.num_pages}`),
            h('button', { class: 'btn small', type: 'button', disabled: d.page >= d.num_pages, onclick: () => { state.query.page = d.page + 1; load(); window.scrollTo({ top: 0 }); } }, 'Next')),
        );
      } catch (e) { results.replaceChildren(h('div', { class: 'empty' }, h('strong', null, 'Could not load jobs'), e.message)); }
    }
    state.refreshView = ({ quiet }) => { if (!quiet) { state.filters = null; viewJobs(); } };
    load();
  }

  function jobRow(j) {
    const href = safeHref(j.job_url);
    const open = () => openDrawer(j.id);
    const ai = j.summary_status === 'ai';
    const li = h('li', { class: 'job', tabindex: '0', role: 'button', 'aria-label': `${j.title} at ${j.company}. Open details`, onclick: open,
      onkeydown: (e) => { if (e.key === 'Enter' && e.target === e.currentTarget) open(); } },
      h('div', null,
        h('h3', null, j.title),
        h('div', { class: 'meta' },
          h('span', { class: 'co' }, j.company),
          j.location && h('span', null, j.location),
          j.employment_type && h('span', { class: 'tag' }, j.employment_type),
          j.workplace_type && h('span', { class: 'tag' }, label(j.workplace_type)),
          j.status === 'possibly_closed' && h('span', { class: 'tag closed' }, 'Possibly closed')),
        h('p', { class: 'summary' + (ai ? '' : ' excerpt') }, ai ? j.summary : (j.excerpt || 'No description provided.')),
        state.me.ai_enabled && h('div', { class: 'summary-actions' },
          !ai && summaryButton(j, { text: 'Summarise with AI' }),
          ai && j.summary_stale && summaryButton(j, { regenerate: true, text: 'Regenerate (posting changed)' }),
          ai && h('span', { class: 'tag' }, 'AI summary'))),
      h('div', { class: 'job-side' },
        h('time', { datetime: j.first_seen_at, title: full(j.first_seen_at) }, `First seen ${ago(j.first_seen_at)}`),
        href && h('a', { class: 'btn small', href, target: '_blank', rel: 'noopener noreferrer', onclick: (e) => e.stopPropagation() }, 'Open original posting')));
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
        h('td', null, h('strong', null, `#${r.id}`), h('div', { class: 'warn-text', style: 'color:var(--muted)' }, `${label(r.trigger)}${r.triggered_by ? ' by ' + r.triggered_by : ''}`)),
        h('td', { title: full(r.started_at || r.created_at) }, ago(r.started_at || r.created_at)),
        h('td', null, r.started_at ? duration(r.started_at, r.completed_at) : ''),
        h('td', null, h('span', { class: 'chip ' + r.status }, label(r.status)), r.is_active && r.current_step && h('div', { class: 'warn-text', style: 'color:var(--muted)' }, r.current_step)),
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
      h('div', { class: 'page-head' }, h('h2', null, 'Fetch runs')),
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
            h('thead', null, h('tr', null, ['Source', 'Result', 'Found', state.me.country_filter === 'IN' ? 'Outside India' : 'Filtered out', 'New', 'Updated', 'Closed', 'Message'].map((t, i) => h('th', { class: i > 1 && i < 7 ? 'num' : '' }, t)))),
            h('tbody', null, r.results.map((x) => h('tr', null,
              h('td', null, x.company), h('td', null, h('span', { class: 'chip ' + x.status }, label(x.status))),
              h('td', { class: 'num' }, num(x.discovered)), h('td', { class: 'num' }, num(x.outside_country)), h('td', { class: 'num' }, num(x.created)), h('td', { class: 'num' }, num(x.updated)), h('td', { class: 'num' }, num(x.closed)),
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
      return { all: true, collecting: st.cls === 'ok', failing: st.cls === 'failed', adapter: st.cls === 'skipped' }[state.sourceFilter];
    };
    const filter = h('select', { id: 'src-filter', onchange: (e) => { state.sourceFilter = e.target.value; viewSources({ quiet: true }); } },
      [['all', 'All sources'], ['collecting', 'Collecting'], ['failing', 'Failing'], ['adapter', 'Needs an adapter']].map(([v, t]) => h('option', { value: v, selected: state.sourceFilter === v }, t)));
    const rows = state.sources.filter(match).map((s) => {
      const st = sourceState(s);
      return h('tr', null,
        h('td', null, h('a', { href: safeHref(s.careers_url) || '#', target: '_blank', rel: 'noopener noreferrer' }, s.company)),
        h('td', null, s.adapter === 'unsupported' ? 'None' : label(s.adapter), admin && s.board && h('div', { class: 'warn-text', style: 'color:var(--muted)' }, s.board + (s.region === 'eu' ? ' (EU)' : ''))),
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
      h('div', { class: 'page-head' }, h('h2', null, 'Sources'),
        h('div', { style: 'display:flex;gap:.7rem;align-items:center' },
          admin && h('button', { class: 'btn primary', type: 'button', onclick: addCompany }, 'Add company'),
          h('label', { class: 'field', style: 'min-width:200px' }, h('span', { class: 'visually-hidden' }, 'Filter sources'), filter))),
      h('div', { class: 'panel table-wrap' }, h('table', null,
        h('thead', null, h('tr', null, h('th', null, 'Company'), h('th', null, 'Adapter'), h('th', { class: 'num' }, 'Open jobs'), h('th', null, 'Last success'), h('th', null, 'Status'),
          admin && h('th', null, 'Collect'), admin && h('th', null, ''))),
        h('tbody', null, rows))),
      !admin && h('p', { class: 'warn-text', style: 'color:var(--muted)' }, 'Only administrators can change sources.'));
    state.refreshView = viewSources;
  }

  async function toggleActive(s, active) {
    try { await api(`/api/sources/${s.id}`, { method: 'PATCH', body: { active } }); s.active = active; await refreshStatus(); viewSources({ quiet: true }); }
    catch (e) { toast(e.message, true); viewSources({}); }
  }

  /* ------------------------------------------------------------ add company */
  function addCompany() {
    const dlg = $('#add-dialog'), name = $('#add-name'), link = $('#add-link'), box = $('#add-result'), save = $('#add-save');
    name.value = ''; link.value = ''; box.hidden = true; save.disabled = false;
    $('#add-cancel').onclick = () => dlg.close();
    $('#add-form').onsubmit = async (ev) => {
      ev.preventDefault();
      save.disabled = true; box.hidden = false; box.className = 'test-result'; box.textContent = 'Checking the job board…';
      try {
        const r = await api('/api/sources', { method: 'POST', body: { company_name: name.value.trim(), board_url: link.value.trim() } });
        dlg.close();
        toast(`${r.company} added: ${num(r.matching)} of ${num(r.found)} jobs match the location filter. Fetching now.`);
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
    $('#source-title').textContent = `Edit ${s.company}`;
    adapter.replaceChildren(h('option', { value: 'unsupported' }, 'No adapter yet'), ...state.adapters.map((a) => h('option', { value: a.key }, a.label)));
    adapter.value = s.adapter; board.value = s.board || ''; region.value = s.region || 'global'; testBox.hidden = true;
    const sync = () => {
      const none = adapter.value === 'unsupported';
      $('#src-board-field').hidden = none;
      $('#src-region-field').hidden = adapter.value !== 'lever';
      $('#src-board-label').textContent = adapter.value === 'lever' ? 'Lever site name (jobs.lever.co/NAME)' : 'Greenhouse board token (boards.greenhouse.io/TOKEN)';
      $('#src-test-btn').disabled = none;
    };
    adapter.onchange = sync; sync();
    const payload = () => ({ adapter: adapter.value, board: board.value.trim(), region: region.value });
    $('#src-test-btn').onclick = async () => {
      testBox.hidden = false; testBox.className = 'test-result'; testBox.textContent = 'Testing…';
      try {
        const r = await api(`/api/sources/${s.id}/test`, { method: 'POST', body: payload() });
        testBox.className = 'test-result' + (r.ok ? '' : ' bad');
        testBox.textContent = r.ok ? `Found ${num(r.count)} open job${r.count === 1 ? '' : 's'}${r.sample.length ? `, for example: ${r.sample.slice(0, 3).join('; ')}` : ''}.` : r.error;
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
      $('#who-name').textContent = state.me.username + (state.me.is_admin ? ' (admin)' : '');
      await refreshStatus();
    } catch (e) { $('#headline').textContent = 'Could not load the dashboard'; $('#subline').textContent = e.message; return; }
    $('#fetch-btn').addEventListener('click', confirmFetch);
    $('#confirm-cancel').addEventListener('click', () => $('#confirm-dialog').close());
    $('#confirm-ok').addEventListener('click', async () => { $('#confirm-dialog').close(); await startFetch(); });
    window.addEventListener('hashchange', route);
    route();
  }
  boot();
})();
