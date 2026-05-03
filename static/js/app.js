/* ── Nx-Citadel Frontend ── */

// ── Theme toggle ──
function initTheme() {
  if (localStorage.getItem('citadel-theme') === 'light')
    document.documentElement.classList.add('light-theme');
  _syncThemeBtn();
}
function toggleTheme() {
  const light = document.documentElement.classList.toggle('light-theme');
  localStorage.setItem('citadel-theme', light ? 'light' : 'dark');
  _syncThemeBtn();
}
function _syncThemeBtn() {
  const btn = document.getElementById('theme-toggle');
  if (!btn) return;
  const light = document.documentElement.classList.contains('light-theme');
  btn.textContent = light ? '🌙' : '☀';
  btn.title = light ? 'Switch to dark theme' : 'Switch to light theme';
}

// Redirect to login on any 401
function _handle401() { window.location.href = '/login'; }

const API = {
  async get(path) {
    const r = await fetch('/api' + path);
    if (r.status === 401) { _handle401(); return null; }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async post(path, body) {
    const r = await fetch('/api' + path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (r.status === 401) { _handle401(); return null; }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async put(path, body) {
    const r = await fetch('/api' + path, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
    if (r.status === 401) { _handle401(); return null; }
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  },
  async delete(path) {
    const r = await fetch('/api' + path, { method: 'DELETE' });
    if (r.status === 401) { _handle401(); return null; }
    if (!r.ok && r.status !== 204) throw new Error(await r.text());
    return true;
  },
};

/* ── Current user / auth bootstrap ── */
let currentUser = null;

async function loadCurrentUser() {
  try {
    const me = await API.get('/auth/me');
    if (!me) return;
    currentUser = me;
    applyRoleVisibility(me.role);
    document.getElementById('user-display-name').textContent = me.username;
    document.getElementById('user-display-role').textContent = roleLabel(me.role);
    document.getElementById('user-avatar').textContent = me.username[0].toUpperCase();
    if (me.mfa_setup_required) {
      document.getElementById('mfa-setup-banner').classList.remove('hidden');
    }
  } catch(e) { /* middleware handles redirect */ }
}

function roleLabel(role) {
  return { user: 'User', manager: 'Citadel Manager', admin: 'Citadel Admin' }[role] || role;
}

function applyRoleVisibility(role) {
  const rank = { user: 1, manager: 2, admin: 3 };
  const r = rank[role] || 1;
  document.body.classList.add(`role-${role}`);
  // manager-only: hide for users
  document.querySelectorAll('.manager-only').forEach(el => {
    el.style.display = r >= 2 ? '' : 'none';
  });
  // admin-only: hide for non-admins
  document.querySelectorAll('.admin-only').forEach(el => {
    el.style.display = r >= 3 ? '' : 'none';
  });
  // nav items with data-role-min: show grayed/disabled if rank is insufficient
  document.querySelectorAll('.nav-item[data-role-min]').forEach(el => {
    const required = rank[el.dataset.roleMin] || 1;
    el.classList.toggle('nav-disabled', r < required);
  });
}

async function doLogout() {
  await fetch('/api/auth/logout', { method: 'POST' });
  window.location.href = '/login';
}

/* ── Toast ── */
function toast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  el.textContent = msg;
  document.getElementById('toast-container').appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

/* ── Navigation ── */
const PAGES = ['dashboard', 'interests', 'resources', 'summary-reports', 'settings', 'logs', 'admin', 'users',
               'ioc-ips', 'ioc-hashes', 'ioc-urls', 'ioc-domains', 'ioc-config'];
let currentPage = 'dashboard';

function navigate(page) {
  const navEl = document.querySelector(`.nav-item[data-page="${page}"]`);
  if (navEl && navEl.classList.contains('nav-disabled')) return;
  currentPage = page;
  PAGES.forEach(p => {
    document.getElementById(`page-${p}`).classList.toggle('hidden', p !== page);
    document.querySelector(`.nav-item[data-page="${p}"]`)?.classList.toggle('active', p === page);
  });
  if (page === 'dashboard') loadDashboard();
  else if (page === 'interests') loadInterests();
  else if (page === 'resources') loadResources();
  else if (page === 'summary-reports') loadSummaryReports();
  else if (page === 'settings') loadSettings();
  else if (page === 'logs') loadLogs();
  else if (page === 'admin') loadAdmin();
  else if (page === 'users') loadUsers();
  else if (page === 'ioc-ips') loadIocPage('ip');
  else if (page === 'ioc-hashes') loadIocPage('hash');
  else if (page === 'ioc-urls') loadIocPage('url');
  else if (page === 'ioc-domains') loadIocPage('domain');
  else if (page === 'ioc-config') loadIocConfig();
}

document.querySelectorAll('.nav-item[data-page]').forEach(el => {
  el.addEventListener('click', () => navigate(el.dataset.page));
});

/* ══════════════════════════════════════════
   DASHBOARD
══════════════════════════════════════════ */
async function loadDashboard() {
  try {
    const [interests, resources, jobs, activity, reports24h, iocCounts] = await Promise.all([
      API.get('/interests/'),
      API.get('/resources/'),
      API.get('/settings/schedules'),
      API.get('/interests/activity/recent?limit=50'),
      API.get('/interests/reports/count-24h'),
      API.get('/iocs/counts'),
    ]);

    const _set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    _set('stat-resources', resources.length);
    _set('stat-active', interests.filter(i => i.active).length);
    _set('stat-scheduled', jobs.length);
    _set('stat-reports-24h', reports24h.count);

    const iocTotal = (iocCounts.ip || 0) + (iocCounts.hash || 0) + (iocCounts.url || 0) + (iocCounts.domain || 0);
    _set('stat-iocs-total', iocTotal.toLocaleString());
    _set('stat-ioc-ips', (iocCounts.ip || 0).toLocaleString());
    _set('stat-ioc-hashes', (iocCounts.hash || 0).toLocaleString());
    _set('stat-ioc-urls', (iocCounts.url || 0).toLocaleString());
    _set('stat-ioc-domains', (iocCounts.domain || 0).toLocaleString());

    // Upcoming runs table
    const tbody = document.getElementById('upcoming-runs');
    if (jobs.length === 0) {
      tbody.innerHTML = '<tr><td colspan="2" class="dash-empty">No scheduled jobs</td></tr>';
    } else {
      tbody.innerHTML = jobs.slice(0, 50).map(j => `
        <tr>
          <td class="dash-name">${escHtml(j.name)}</td>
          <td class="dash-time">${j.next_run ? relTime(j.next_run) : '—'}</td>
        </tr>`).join('');
    }

    // Activity feed
    const feed = document.getElementById('activity-feed');
    if (!activity.length) {
      feed.innerHTML = '<div class="dash-empty">No reports yet — run an interest to populate</div>';
    } else {
      const interestMap = Object.fromEntries(interests.map(i => [i.id, i]));
      feed.innerHTML = activity.map(a => {
        const interest = interestMap[a.interest_id];
        return `
        <div class="activity-row" onclick="viewReportContent('${a.interest_id}','${escHtml(a.filename)}')" title="View report">
          <div class="activity-dot"></div>
          <div class="activity-info">
            <span class="activity-name">${escHtml(a.interest_name)}</span>
            <span class="activity-meta">${relTime(a.ran_at)} · ${formatBytes(a.size)}</span>
          </div>
          ${interest ? outputIcons(interest.output) : ''}
          <span class="activity-arrow">›</span>
        </div>`;
      }).join('');
    }
  } catch(e) { toast('Failed to load dashboard: ' + e.message, 'error'); }
}

function relTime(iso) {
  const diff = Date.now() - new Date(iso).getTime();
  const future = diff < 0;
  const abs = Math.abs(diff);
  const m = Math.floor(abs / 60000);
  const h = Math.floor(m / 60);
  const d = Math.floor(h / 24);
  if (future) {
    if (m < 1)  return 'in <1m';
    if (m < 60) return `in ${m}m`;
    if (h < 24) return `in ${h}h ${m % 60}m`;
    return `in ${d}d`;
  }
  if (m < 1)  return 'just now';
  if (m < 60) return `${m}m ago`;
  if (h < 24) return `${h}h ago`;
  return `${d}d ago`;
}

/* ══════════════════════════════════════════
   INTERESTS
══════════════════════════════════════════ */
let interestEditId = null;

async function loadInterests() {
  const container = document.getElementById('interests-list');
  container.innerHTML = '<div style="color:var(--citadel-muted);padding:20px">Loading…</div>';
  try {
    const items = await API.get('/interests/');
    renderInterests(items);
  } catch(e) { toast('Failed to load interests: ' + e.message, 'error'); }
}

function renderInterests(items) {
  const container = document.getElementById('interests-list');
  if (!items.length) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-icon">🎯</div>
      <p>No interests yet. Add one to start tracking topics.</p>
      <button class="btn btn-primary" onclick="openInterestModal()">+ Add Interest</button>
    </div>`;
    return;
  }
  container.innerHTML = '<div class="item-list">' + items.map(item => `
    <div class="item-card">
      <div class="item-info">
        <div class="item-name">${escHtml(item.name)}</div>
        <div class="item-meta">
          <span>${escHtml(item.type || 'term')}</span>
          <span>Schedule: ${scheduleLabel(item.schedule)}</span>
          ${outputIcons(item.output)}
          ${item.last_run ? `<span>Last run: ${new Date(item.last_run).toLocaleString()}</span>` : ''}
          ${item.next_run ? `<span>Next: ${new Date(item.next_run).toLocaleString()}</span>` : ''}
          ${(item.tags||[]).map(t=>`<span class="badge badge-accent">${escHtml(t)}</span>`).join('')}
        </div>
      </div>
      <div class="item-actions">
        <span class="badge ${item.active ? 'badge-success' : 'badge-muted'}">${item.active ? 'Active' : 'Paused'}</span>
        <button class="btn btn-ghost btn-sm" onclick="viewReports('${item.id}', '${escHtml(item.name)}')">Reports</button>
        <button class="btn btn-ghost btn-sm manager-only" onclick="runNow('${item.id}', '${escHtml(item.name)}')">▶ Run</button>
        <button class="btn btn-ghost btn-sm" onclick="openInterestModal('${item.id}')">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteInterest('${item.id}', '${escHtml(item.name)}')">Delete</button>
      </div>
    </div>`).join('') + '</div>';
}

function scheduleLabel(s) {
  if (!s) return 'Manual';
  if (s.type === 'manual') return 'Manual';
  if (s.type === 'weekly') {
    const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
    const d = (s.days_of_week || []).map(i => days[i]).join(', ');
    return `Weekly (${d || 'no days'}) @ ${s.run_time || '09:00'}`;
  }
  if (s.type === 'cron') return `Cron: ${s.cron_expression}`;
  return `Every ${s.interval_value} ${s.interval_unit}`;
}

function outputLabel(o) {
  if (!o || !o.types) return 'report';
  return o.types.join(', ');
}

function outputIcons(output) {
  const selected = new Set(output?.types || []);
  const defs = [
    {
      key: 'email', label: 'Email', color: '#4A9EFF',
      paths: `<rect x="1.5" y="3.5" width="13" height="9" rx="1.5"/><polyline points="1.5,3.5 8,8.5 14.5,3.5"/>`
    },
    {
      key: 'slack', label: 'Slack', color: '#E01E5A',
      paths: `<line x1="5.5" y1="3" x2="5.5" y2="13"/><line x1="10.5" y1="3" x2="10.5" y2="13"/><line x1="2.5" y1="6" x2="13.5" y2="6"/><line x1="2.5" y1="10" x2="13.5" y2="10"/>`
    },
    {
      key: 'sms', label: 'SMS', color: '#2DD4A0',
      paths: `<rect x="4.5" y="1.5" width="7" height="13" rx="1.5"/><line x1="6.5" y1="12" x2="9.5" y2="12"/>`
    },
    {
      key: 'discord', label: 'Discord', color: '#7289DA',
      paths: `<path d="M3 9.5C3 5.91 5.24 3 8 3s5 2.91 5 6.5"/><rect x="1.5" y="8.5" width="3" height="5" rx="1.5"/><rect x="11.5" y="8.5" width="3" height="5" rx="1.5"/>`
    }
  ];
  return `<span class="output-icons">${defs.map(({key, label, color, paths}) => {
    const on = selected.has(key);
    return `<svg class="output-icon" viewBox="0 0 16 16" width="15" height="15" fill="none" stroke-linecap="round" stroke-linejoin="round" stroke-width="1.5" stroke="${on ? color : 'var(--citadel-muted)'}" style="opacity:${on ? '1' : '0.28'}" title="${label}${on ? '' : ' (off)'}">${paths}</svg>`;
  }).join('')}</span>`;
}

async function openInterestModal(id = null) {
  interestEditId = id;
  const modal = document.getElementById('interest-modal');
  const title = document.getElementById('interest-modal-title');
  title.textContent = id ? 'Edit Interest' : 'New Interest';

  // Reset form
  document.getElementById('interest-form').reset();
  setTagsValue('interest-keywords', []);
  setTagsValue('interest-tags', []);
  setTagsValue('interest-email-recipients', []);
  setTagsValue('interest-sms-numbers', []);
  setTagsValue('interest-topics', []);
  document.querySelectorAll('.day-btn').forEach(b => b.classList.remove('selected'));
  document.getElementById('schedule-type').dispatchEvent(new Event('change'));

  if (id) {
    try {
      const item = await API.get(`/interests/${id}`);
      document.getElementById('interest-name').value = item.name || '';
      document.getElementById('interest-body').value = item.body || '';
      document.getElementById('interest-type').value = item.type || 'term';
      document.getElementById('interest-active').checked = item.active !== false;
      setTagsValue('interest-keywords', item.keywords || []);
      setTagsValue('interest-tags', item.tags || []);

      const s = item.schedule || {};
      document.getElementById('schedule-type').value = s.type || 'interval';
      document.getElementById('schedule-type').dispatchEvent(new Event('change'));
      document.getElementById('interval-value').value = s.interval_value || 1;
      document.getElementById('interval-unit').value = s.interval_unit || 'days';
      document.getElementById('run-time').value = s.run_time || '09:00';
      document.getElementById('cron-expression').value = s.cron_expression || '';
      (s.days_of_week || []).forEach(d => {
        document.querySelector(`.day-btn[data-day="${d}"]`)?.classList.add('selected');
      });

      const o = item.output || {};
      ['email','sms','slack','discord'].forEach(t => {
        const cb = document.getElementById(`out-${t}`);
        if (cb) cb.checked = (o.types || []).includes(t);
      });
      setTagsValue('interest-email-recipients', o.email_recipients || []);
      setTagsValue('interest-sms-numbers', o.sms_numbers || []);
      document.getElementById('slack-webhook').value = o.slack_webhook || '';
      document.getElementById('discord-webhook').value = o.discord_webhook || '';
      document.getElementById('report-format').value = o.report_format || 'markdown';
    } catch(e) { toast('Failed to load interest: ' + e.message, 'error'); return; }
  }

  modal.classList.remove('hidden');
}

function closeInterestModal() {
  document.getElementById('interest-modal').classList.add('hidden');
  interestEditId = null;
}

document.getElementById('schedule-type').addEventListener('change', function() {
  document.getElementById('interval-fields').classList.toggle('hidden', this.value !== 'interval');
  document.getElementById('weekly-fields').classList.toggle('hidden', this.value !== 'weekly');
  document.getElementById('cron-fields').classList.toggle('hidden', this.value !== 'cron');
});

document.querySelectorAll('.day-btn').forEach(btn => {
  btn.addEventListener('click', () => btn.classList.toggle('selected'));
});

async function saveInterest() {
  const scheduleType = document.getElementById('schedule-type').value;
  const payload = {
    name: document.getElementById('interest-name').value.trim(),
    description: document.getElementById('interest-body').value.trim(),
    type: document.getElementById('interest-type').value,
    keywords: getTagsValue('interest-keywords'),
    tags: getTagsValue('interest-tags'),
    active: document.getElementById('interest-active').checked,
    schedule: {
      type: scheduleType,
      interval_value: parseInt(document.getElementById('interval-value').value) || 1,
      interval_unit: document.getElementById('interval-unit').value,
      run_time: document.getElementById('run-time').value,
      cron_expression: document.getElementById('cron-expression').value,
      days_of_week: [...document.querySelectorAll('.day-btn.selected')].map(b => parseInt(b.dataset.day)),
    },
    output: {
      types: ['email','sms','slack','discord'].filter(t => document.getElementById(`out-${t}`)?.checked),
      email_recipients: getTagsValue('interest-email-recipients'),
      sms_numbers: getTagsValue('interest-sms-numbers'),
      slack_webhook: document.getElementById('slack-webhook').value.trim() || null,
      discord_webhook: document.getElementById('discord-webhook').value.trim() || null,
      report_format: document.getElementById('report-format').value,
    },
  };

  if (!payload.name) { toast('Name is required', 'error'); return; }

  const btn = document.getElementById('save-interest-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Saving…';
  try {
    if (interestEditId) {
      await API.put(`/interests/${interestEditId}`, payload);
      toast('Interest updated', 'success');
    } else {
      await API.post('/interests/', payload);
      toast('Interest created', 'success');
    }
    closeInterestModal();
    loadInterests();
  } catch(e) {
    toast('Save failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save';
  }
}

async function deleteInterest(id, name) {
  if (!confirm(`Delete interest "${name}"? This cannot be undone.`)) return;
  try {
    await API.delete(`/interests/${id}`);
    toast('Interest deleted', 'success');
    loadInterests();
  } catch(e) { toast('Delete failed: ' + e.message, 'error'); }
}

async function runNow(id, name) {
  toast(`Running "${name}"…`, 'info');
  try {
    const result = await API.post(`/interests/${id}/run`, {});
    if (result.error) {
      toast('Run failed: ' + result.error, 'error');
    } else {
      toast(`"${name}" completed. Outputs: ${result.output_sent.join(', ') || 'none'}`, 'success');
    }
    loadInterests();
  } catch(e) { toast('Run failed: ' + e.message, 'error'); }
}

async function viewReports(id, name) {
  try {
    const reports = await API.get(`/interests/${id}/reports`);
    const container = document.getElementById('reports-list');
    document.getElementById('reports-title').textContent = `Reports: ${name}`;
    if (!reports.length) {
      container.innerHTML = '<p style="color:var(--citadel-muted)">No reports yet. Run this interest to generate a report.</p>';
    } else {
      container.innerHTML = reports.map(r => `
        <div class="item-card" style="cursor:pointer" onclick="viewReportContent('${id}', '${r.filename}')">
          <div class="item-info">
            <div class="item-name">${r.filename}</div>
            <div class="item-meta"><span>${new Date(r.modified).toLocaleString()}</span><span>${formatBytes(r.size)}</span></div>
          </div>
          <div class="item-actions"><button class="btn btn-ghost btn-sm">View</button></div>
        </div>`).join('');
    }
    document.getElementById('reports-modal').classList.remove('hidden');
  } catch(e) { toast('Failed to load reports: ' + e.message, 'error'); }
}

async function viewReportContent(interestId, filename) {
  try {
    const data = await API.get(`/interests/${interestId}/reports/${filename}`);
    const el = document.getElementById('report-content');
    el.innerHTML = typeof marked !== 'undefined'
      ? marked.parse(data.content)
      : `<pre style="white-space:pre-wrap">${escHtml(data.content)}</pre>`;
    const dateEl = document.getElementById('report-generated-date');
    if (data.generated_at) {
      dateEl.textContent = 'generated on: ' + new Date(data.generated_at).toLocaleString();
      dateEl.style.display = 'inline';
    } else {
      dateEl.style.display = 'none';
    }
    _setReportCtx('interest', interestId, filename);
    document.getElementById('report-content-modal').classList.remove('hidden');
  } catch(e) { toast('Failed to load report', 'error'); }
}

/* ══════════════════════════════════════════
   RESOURCES
══════════════════════════════════════════ */
let resourceEditId = null;

const DEFAULT_RESOURCE_PROMPT = `NEVER start with a Data Coverage Notice
ALWAYS put the Stories Extractable from Provided Results at the very top.
If there are Data Coverage Concerns or Notices, put those after-underneath the stories

Your source is [ SOURCE ]
Parse the full source provided (It may be a web page, RSS feed, XML file, Twitter or X account). Extract every item published in the last 48 hours (use any available date field and filter strictly to items from the past 48 hours as of right now). Ignore older items. For each significant/recent story, output in this exact format:

Title
[Exact title from the Source]

Executive Summary
[Concise overview based on the full article content]

Technical Details (as applicable)
[Any vulnerabilities, malware, attack techniques, tools, code snippets, or technical specifics mentioned in the full article]

Known IOCs (as applicable)
[List any Indicators of Compromise (IPs, domains, hashes, filenames, C2 servers, etc.). If none are mentioned, write "None disclosed." If this is a cyber security matter include this section; if not, omit it entirely]

Impact / Conclusion
[Clear assessment of affected sectors, organizations, potential damage, risk level, or broader implications]

Instructions for best results:
- If the Source is only a short teaser, automatically follow the <link> URL to the full article and read the complete page content before summarizing.
- Prioritize the most important/recent stories (aim for 8–15 top stories max; skip minor or repetitive ones).
- Focus especially on technical depth, IOCs, exploits, and real-world business/security impact.
- Use today's date and time as the cutoff for the 48-hour window.

Link
[HTML link direct to story details]

ALWAYS put the Stories Extractable from Provided Results at the very top.
If there are Data Coverage Concerns or Notices, put those after the stories — place a horizontal divider, then a heading "Data Coverage Notice" with a caution icon and articulate the data coverage issues.`;

async function loadResources() {
  const container = document.getElementById('resources-list');
  container.innerHTML = '<div style="color:var(--citadel-muted);padding:20px">Loading…</div>';
  try {
    const items = await API.get('/resources/');
    renderResources(items);
  } catch(e) { toast('Failed to load resources: ' + e.message, 'error'); }
}

function renderResources(items) {
  const container = document.getElementById('resources-list');
  if (!items.length) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-icon">🔒</div>
      <p>No trusted resources yet. Add sources to monitor independently.</p>
      <button class="btn btn-primary" onclick="openResourceModal()">+ Add Resource</button>
    </div>`;
    return;
  }
  container.innerHTML = '<div class="item-list">' + items.map(item => `
    <div class="item-card">
      <div class="item-info">
        <div class="item-name">${escHtml(item.name)}</div>
        <div class="item-meta">
          <span>${escHtml(item.type || 'website')}</span>
          ${item.source ? `<span style="color:var(--citadel-accent)">${escHtml(item.source)}</span>` : ''}
          <span>Schedule: ${scheduleLabel(item.schedule)}</span>
          ${item.last_run ? `<span>Last run: ${new Date(item.last_run).toLocaleString()}</span>` : ''}
          ${item.next_run ? `<span>Next: ${new Date(item.next_run).toLocaleString()}</span>` : ''}
          ${(item.tags||[]).map(t=>`<span class="badge badge-accent">${escHtml(t)}</span>`).join('')}
        </div>
      </div>
      <div class="item-actions">
        <span class="badge ${item.active ? 'badge-success' : 'badge-muted'}">${item.active ? 'Active' : 'Paused'}</span>
        <button class="btn btn-ghost btn-sm" onclick="viewResourceReports('${item.id}', '${escHtml(item.name)}')">Reports</button>
        <button class="btn btn-ghost btn-sm manager-only" onclick="runResource('${item.id}', '${escHtml(item.name)}')">▶ Run</button>
        <button class="btn btn-ghost btn-sm" onclick="openResourceModal('${item.id}')">Edit</button>
        <button class="btn btn-danger btn-sm" onclick="deleteResource('${item.id}', '${escHtml(item.name)}')">Delete</button>
      </div>
    </div>`).join('') + '</div>';
}

async function openResourceModal(id = null) {
  resourceEditId = id;
  document.getElementById('resource-modal-title').textContent = id ? 'Edit Resource' : 'New Trusted Resource';
  document.getElementById('resource-form').reset();
  setTagsValue('resource-tags', []);
  setTagsValue('res-email-recipients', []);
  setTagsValue('res-sms-numbers', []);
  document.querySelectorAll('.res-day-btn').forEach(b => b.classList.remove('selected'));
  document.getElementById('res-schedule-type').dispatchEvent(new Event('change'));

  if (id) {
    try {
      const item = await API.get(`/resources/${id}`);
      document.getElementById('resource-name').value = item.name || '';
      document.getElementById('resource-source').value = item.source || '';
      document.getElementById('resource-type').value = item.type || 'website';
      const resPromptEl = document.getElementById('resource-prompt');
      resPromptEl.value = item.body || item.prompt || DEFAULT_RESOURCE_PROMPT;
      resPromptEl.dataset.tpl = resPromptEl.value;
      document.getElementById('resource-active').checked = item.active !== false;
      setTagsValue('resource-tags', item.tags || []);

      const s = item.schedule || {};
      document.getElementById('res-schedule-type').value = s.type || 'interval';
      document.getElementById('res-schedule-type').dispatchEvent(new Event('change'));
      document.getElementById('res-interval-value').value = s.interval_value || 1;
      document.getElementById('res-interval-unit').value = s.interval_unit || 'days';
      document.getElementById('res-run-time').value = s.run_time || '09:00';
      document.getElementById('res-cron-expression').value = s.cron_expression || '';
      (s.days_of_week || []).forEach(d => {
        document.querySelector(`.res-day-btn[data-day="${d}"]`)?.classList.add('selected');
      });

      const o = item.output || {};
      ['email','sms','slack','discord'].forEach(t => {
        const cb = document.getElementById(`res-out-${t}`);
        if (cb) cb.checked = (o.types || []).includes(t);
      });
      setTagsValue('res-email-recipients', o.email_recipients || []);
      setTagsValue('res-sms-numbers', o.sms_numbers || []);
      document.getElementById('res-slack-webhook').value = o.slack_webhook || '';
      document.getElementById('res-discord-webhook').value = o.discord_webhook || '';
      document.getElementById('res-report-format').value = o.report_format || 'markdown';
    } catch(e) { toast('Failed to load resource', 'error'); return; }
  } else {
    const promptEl = document.getElementById('resource-prompt');
    const effectiveDefault = (_defaultResourcePrompt && _defaultResourcePrompt.trim()) ? _defaultResourcePrompt : DEFAULT_RESOURCE_PROMPT;
    promptEl.value = effectiveDefault;
    promptEl.dataset.tpl = effectiveDefault;
  }

  // Reset to first tab
  switchTab(document.querySelector('#resource-modal .tab-btn'), 'res-tab-basic');
  document.getElementById('resource-modal').classList.remove('hidden');
}

function closeResourceModal() {
  document.getElementById('resource-modal').classList.add('hidden');
  resourceEditId = null;
}

document.getElementById('res-schedule-type').addEventListener('change', function() {
  document.getElementById('res-interval-fields').classList.toggle('hidden', this.value !== 'interval');
  document.getElementById('res-weekly-fields').classList.toggle('hidden', this.value !== 'weekly');
  document.getElementById('res-cron-fields').classList.toggle('hidden', this.value !== 'cron');
});

document.querySelectorAll('.res-day-btn').forEach(btn => {
  btn.addEventListener('click', () => btn.classList.toggle('selected'));
});

// Source → Prompt live sync
// Store the template (prompt with [ SOURCE ] tokens) separately so incremental typing works
document.getElementById('resource-source').addEventListener('input', function() {
  const promptEl = document.getElementById('resource-prompt');
  const tpl = promptEl.dataset.tpl;
  if (tpl && tpl.includes('[ SOURCE ]')) {
    promptEl.value = tpl.replace(/\[ SOURCE \]/g, this.value || '[ SOURCE ]');
  }
});
// When the user manually edits the prompt, update the stored template
document.getElementById('resource-prompt').addEventListener('input', function() {
  this.dataset.tpl = this.value;
});

async function saveResource() {
  const scheduleType = document.getElementById('res-schedule-type').value;
  const payload = {
    name: document.getElementById('resource-name').value.trim(),
    source: document.getElementById('resource-source').value.trim(),
    type: document.getElementById('resource-type').value,
    prompt: document.getElementById('resource-prompt').value.trim(),
    tags: getTagsValue('resource-tags'),
    active: document.getElementById('resource-active').checked,
    schedule: {
      type: scheduleType,
      interval_value: parseInt(document.getElementById('res-interval-value').value) || 1,
      interval_unit: document.getElementById('res-interval-unit').value,
      run_time: document.getElementById('res-run-time').value,
      cron_expression: document.getElementById('res-cron-expression').value,
      days_of_week: [...document.querySelectorAll('.res-day-btn.selected')].map(b => parseInt(b.dataset.day)),
    },
    output: {
      types: ['email','sms','slack','discord'].filter(t => document.getElementById(`res-out-${t}`)?.checked),
      email_recipients: getTagsValue('res-email-recipients'),
      sms_numbers: getTagsValue('res-sms-numbers'),
      slack_webhook: document.getElementById('res-slack-webhook').value.trim() || null,
      discord_webhook: document.getElementById('res-discord-webhook').value.trim() || null,
      report_format: document.getElementById('res-report-format').value,
    },
  };
  if (!payload.name) { toast('Name is required', 'error'); return; }

  const btn = document.getElementById('save-resource-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Saving…';
  try {
    if (resourceEditId) {
      await API.put(`/resources/${resourceEditId}`, payload);
      toast('Resource updated', 'success');
    } else {
      await API.post('/resources/', payload);
      toast('Resource added', 'success');
    }
    closeResourceModal();
    loadResources();
  } catch(e) {
    toast('Save failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save';
  }
}

async function runResource(id, name) {
  if (!confirm(`Run resource "${name}" now?`)) return;
  try {
    toast(`Running "${name}"…`, 'info');
    await API.post(`/resources/${id}/run`, {});
    toast(`"${name}" complete`, 'success');
    loadResources();
  } catch(e) { toast('Run failed: ' + e.message, 'error'); }
}

async function viewResourceReports(id, name) {
  try {
    const reports = await API.get(`/resources/${id}/reports`);
    const container = document.getElementById('reports-list');
    document.getElementById('reports-title').textContent = `Reports: ${name}`;
    if (!reports.length) {
      container.innerHTML = '<p style="color:var(--citadel-muted)">No reports yet. Run this resource to generate a report.</p>';
    } else {
      container.innerHTML = reports.map(r => `
        <div class="item-card" style="cursor:pointer" onclick="viewResourceReportContent('${id}', '${r.filename}')">
          <div class="item-info">
            <div class="item-name">${r.filename}</div>
            <div class="item-meta"><span>${new Date(r.modified).toLocaleString()}</span><span>${formatBytes(r.size)}</span></div>
          </div>
          <div class="item-actions"><button class="btn btn-ghost btn-sm">View</button></div>
        </div>`).join('');
    }
    document.getElementById('reports-modal').classList.remove('hidden');
  } catch(e) { toast('Failed to load reports: ' + e.message, 'error'); }
}

async function viewResourceReportContent(resourceId, filename) {
  try {
    const data = await API.get(`/resources/${resourceId}/reports/${filename}`);
    const el = document.getElementById('report-content');
    el.innerHTML = typeof marked !== 'undefined'
      ? marked.parse(data.content)
      : `<pre style="white-space:pre-wrap">${escHtml(data.content)}</pre>`;
    const dateEl = document.getElementById('report-generated-date');
    if (data.generated_at) {
      dateEl.textContent = 'generated on: ' + new Date(data.generated_at).toLocaleString();
      dateEl.style.display = 'inline';
    } else {
      dateEl.style.display = 'none';
    }
    _setReportCtx('resource', resourceId, filename);
    document.getElementById('report-content-modal').classList.remove('hidden');
  } catch(e) { toast('Failed to load report', 'error'); }
}

async function deleteResource(id, name) {
  if (!confirm(`Delete trusted resource "${name}"?`)) return;
  try {
    await API.delete(`/resources/${id}`);
    toast('Resource deleted', 'success');
    loadResources();
  } catch(e) { toast('Delete failed: ' + e.message, 'error'); }
}

/* ══════════════════════════════════════════
   SETTINGS
══════════════════════════════════════════ */
let currentSettings = null;

async function loadSettings() {
  try {
    currentSettings = await API.get('/settings/');
    const llm = currentSettings.llm || {};
    const email = currentSettings.email || {};
    const sms = currentSettings.sms || {};
    const slack = currentSettings.slack || {};
    const search = currentSettings.search || {};

    document.getElementById('llm-provider').value = llm.provider || 'anthropic';
    document.getElementById('llm-api-key').value = llm.api_key || '';
    document.getElementById('llm-model').value = llm.model || 'claude-sonnet-4-6';

    document.getElementById('smtp-host').value = email.smtp_host || '';
    document.getElementById('smtp-port').value = email.smtp_port || 587;
    document.getElementById('smtp-user').value = email.smtp_user || '';
    document.getElementById('smtp-password').value = email.smtp_password || '';
    document.getElementById('smtp-from').value = email.from_address || '';
    document.getElementById('smtp-tls').checked = email.use_tls !== false;

    document.getElementById('twilio-sid').value = sms.account_sid || '';
    document.getElementById('twilio-token').value = sms.auth_token || '';
    document.getElementById('twilio-from').value = sms.from_number || '';

    document.getElementById('slack-default-webhook').value = slack.default_webhook || '';

    const discord = currentSettings.discord || {};
    document.getElementById('discord-default-webhook').value = discord.default_webhook || '';

    document.getElementById('search-provider').value = search.provider || 'duckduckgo';
    document.getElementById('search-max-results').value = search.max_results || 10;
    document.getElementById('serpapi-key').value = search.serpapi_key || '';
    document.getElementById('brave-api-key').value = search.brave_api_key || '';
    toggleSearchKeyFields();

    updateLLMStatus(llm.api_key && llm.api_key !== '***' ? 'configured' : 'unconfigured');
  } catch(e) { toast('Failed to load settings: ' + e.message, 'error'); }
}

function toggleSearchKeyFields() {
  const p = document.getElementById('search-provider').value;
  document.getElementById('brave-key-group').classList.toggle('hidden', p !== 'brave');
  document.getElementById('serpapi-key-group').classList.toggle('hidden', p !== 'serpapi');
}
// keep old name as alias for any inline callers
const toggleSerpAPIKey = toggleSearchKeyFields;

function updateLLMStatus(status) {
  const el = document.getElementById('llm-status');
  if (status === 'configured') {
    el.innerHTML = '<span class="badge badge-success">API Key Configured</span>';
  } else if (status === 'ok') {
    el.innerHTML = '<span class="badge badge-success">Connected ✓</span>';
  } else if (status === 'error') {
    el.innerHTML = '<span class="badge badge-danger">Connection Failed</span>';
  } else {
    el.innerHTML = '<span class="badge badge-muted">Not Configured</span>';
  }
}

async function testLLMConnection() {
  await saveSettings(true);
  const btn = document.getElementById('test-llm-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Testing…';
  try {
    const result = await API.post('/settings/test-llm', {});
    if (result.ok) {
      updateLLMStatus('ok');
      toast('LLM connection successful! Response: ' + result.response, 'success');
    } else {
      updateLLMStatus('error');
      toast('LLM test failed: ' + result.error, 'error');
    }
  } catch(e) {
    updateLLMStatus('error');
    toast('Test failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Connection';
  }
}

async function testEmailConnection() {
  await saveSettings(true);
  const btn = document.getElementById('test-email-btn');
  const result_el = document.getElementById('test-email-result');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Testing…';
  result_el.textContent = '';
  try {
    const result = await API.post('/settings/test-email', {});
    if (result.ok) {
      result_el.style.color = 'var(--citadel-success)';
      result_el.textContent = '✓ ' + result.message;
      toast('Email test succeeded!', 'success');
    } else {
      result_el.style.color = 'var(--citadel-danger)';
      result_el.textContent = '✗ ' + result.error;
      toast('Email test failed: ' + result.error, 'error');
    }
  } catch(e) {
    result_el.style.color = 'var(--citadel-danger)';
    result_el.textContent = '✗ ' + e.message;
    toast('Email test failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Email';
  }
}

async function testSMSConnection() {
  await saveSettings(true);
  const toNumber = document.getElementById('sms-test-number').value.trim();
  if (!toNumber) { toast('Enter a test number first', 'error'); return; }
  const btn = document.getElementById('test-sms-btn');
  const result_el = document.getElementById('test-sms-result');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Sending…';
  result_el.textContent = '';
  try {
    const result = await API.post('/settings/test-sms', { to_number: toNumber });
    if (result.ok) {
      result_el.style.color = 'var(--citadel-success)';
      result_el.textContent = '✓ ' + result.message;
      toast('SMS test succeeded!', 'success');
    } else {
      result_el.style.color = 'var(--citadel-danger)';
      result_el.textContent = '✗ ' + result.error;
      toast('SMS test failed: ' + result.error, 'error');
    }
  } catch(e) {
    result_el.style.color = 'var(--citadel-danger)';
    result_el.textContent = '✗ ' + e.message;
    toast('SMS test failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test SMS';
  }
}

async function testDiscordConnection() {
  await saveSettings(true);
  const btn = document.getElementById('test-discord-btn');
  const result_el = document.getElementById('test-discord-result');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Sending…';
  result_el.textContent = '';
  try {
    const result = await API.post('/settings/test-discord', {});
    if (result.ok) {
      result_el.style.color = 'var(--citadel-success)';
      result_el.textContent = '✓ ' + result.message;
      toast('Discord test succeeded!', 'success');
    } else {
      result_el.style.color = 'var(--citadel-danger)';
      result_el.textContent = '✗ ' + result.error;
      toast('Discord test failed: ' + result.error, 'error');
    }
  } catch(e) {
    result_el.style.color = 'var(--citadel-danger)';
    result_el.textContent = '✗ ' + e.message;
    toast('Discord test failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Test Discord';
  }
}

async function saveSettings(silent = false) {
  const payload = {
    llm: {
      provider: document.getElementById('llm-provider').value,
      api_key: document.getElementById('llm-api-key').value,
      model: document.getElementById('llm-model').value,
    },
    email: {
      smtp_host: document.getElementById('smtp-host').value,
      smtp_port: parseInt(document.getElementById('smtp-port').value) || 587,
      smtp_user: document.getElementById('smtp-user').value,
      smtp_password: document.getElementById('smtp-password').value,
      from_address: document.getElementById('smtp-from').value,
      use_tls: document.getElementById('smtp-tls').checked,
    },
    sms: {
      provider: 'twilio',
      account_sid: document.getElementById('twilio-sid').value,
      auth_token: document.getElementById('twilio-token').value,
      from_number: document.getElementById('twilio-from').value,
    },
    slack: {
      default_webhook: document.getElementById('slack-default-webhook').value,
    },
    discord: {
      default_webhook: document.getElementById('discord-default-webhook').value,
    },
    search: {
      provider: document.getElementById('search-provider').value,
      max_results: parseInt(document.getElementById('search-max-results').value) || 10,
      serpapi_key: document.getElementById('serpapi-key').value,
      brave_api_key: document.getElementById('brave-api-key').value,
    },
  };
  try {
    await API.put('/settings/', payload);
    if (!silent) toast('Settings saved', 'success');
  } catch(e) {
    toast('Save failed: ' + e.message, 'error');
    throw e;
  }
}

/* ══════════════════════════════════════════
   LOGS
══════════════════════════════════════════ */
async function loadLogs() {
  const viewer = document.getElementById('log-viewer');
  viewer.innerHTML = '<div style="color:var(--citadel-muted)">Loading logs…</div>';
  try {
    const data = await API.get('/logs/?lines=300');
    if (!data.lines.length) {
      viewer.innerHTML = '<div style="color:var(--citadel-muted)">No log entries yet.</div>';
      return;
    }
    viewer.innerHTML = data.lines.map(line => {
      const level = /\|\s+(INFO USER|INFO|WARNING|ERROR|DEBUG)\s+\|/.exec(line)?.[1] || 'INFO';
      const cssLevel = level.replace(' ', '-');
      const completed = line.includes("Completed interest") ? ' log-completed' : '';
      return `<div class="log-line log-${cssLevel}${completed}">${escHtml(line)}</div>`;
    }).join('');
    viewer.scrollTop = viewer.scrollHeight;

    const archives = await API.get('/logs/archives');
    const archList = document.getElementById('archive-list');
    if (!archives.length) {
      archList.innerHTML = '<span style="color:var(--citadel-muted)">No archives yet</span>';
    } else {
      archList.innerHTML = archives.map(a => `<div class="log-line">${escHtml(a.path)} (${formatBytes(a.size)})</div>`).join('');
    }
  } catch(e) { toast('Failed to load logs: ' + e.message, 'error'); }
}

/* ══════════════════════════════════════════
   SUMMARY REPORTS
══════════════════════════════════════════ */
let summaryEditId = null;

async function loadSummaryReports() {
  const container = document.getElementById('summary-reports-list');
  container.innerHTML = '<div style="color:var(--citadel-muted);padding:20px">Loading…</div>';
  try {
    const items = await API.get('/summary-reports/');
    renderSummaryReports(items);
  } catch(e) { toast('Failed to load summary reports: ' + e.message, 'error'); }
}

function renderSummaryReports(items) {
  const container = document.getElementById('summary-reports-list');
  if (!items.length) {
    container.innerHTML = `<div class="empty-state">
      <div class="empty-icon">📊</div>
      <p>No summary reports yet. Create one to synthesize intelligence across tagged interests.</p>
      <button class="btn btn-primary manager-only" onclick="openSummaryModal()">+ New Summary Report</button>
    </div>`;
    return;
  }
  container.innerHTML = '<div class="item-list">' + items.map(item => `
    <div class="item-card">
      <div class="item-info">
        <div class="item-name">${escHtml(item.name)}</div>
        <div class="item-meta">
          <span>Schedule: ${scheduleLabel(item.schedule)}</span>
          ${outputIcons(item.output)}
          ${item.last_run ? `<span>Last run: ${new Date(item.last_run).toLocaleString()}</span>` : ''}
          ${item.next_run ? `<span>Next: ${new Date(item.next_run).toLocaleString()}</span>` : ''}
          ${(item.tags||[]).map(t=>`<span class="badge badge-accent">${escHtml(t)}</span>`).join('')}
        </div>
      </div>
      <div class="item-actions">
        <span class="badge ${item.active ? 'badge-success' : 'badge-muted'}">${item.active ? 'Active' : 'Paused'}</span>
        <button class="btn btn-ghost btn-sm" onclick="viewSummaryReports('${item.id}', '${escHtml(item.name)}')">Reports</button>
        <button class="btn btn-ghost btn-sm manager-only" onclick="runSummaryNow('${item.id}', '${escHtml(item.name)}')">▶ Run</button>
        <button class="btn btn-ghost btn-sm manager-only" onclick="openSummaryModal('${item.id}')">Edit</button>
        <button class="btn btn-danger btn-sm manager-only" onclick="deleteSummaryReport('${item.id}', '${escHtml(item.name)}')">Delete</button>
      </div>
    </div>`).join('') + '</div>';
}

async function openSummaryModal(id = null) {
  summaryEditId = id;
  document.getElementById('summary-modal-title').textContent = id ? 'Edit Summary Report' : 'New Summary Report';
  document.getElementById('summary-form').reset();
  setTagsValue('sr-tags', []);
  setTagsValue('sr-email-recipients', []);
  setTagsValue('sr-sms-numbers', []);
  document.querySelectorAll('.sr-day-btn').forEach(b => b.classList.remove('selected'));
  document.getElementById('sr-schedule-type').dispatchEvent(new Event('change'));

  if (id) {
    try {
      const item = await API.get(`/summary-reports/${id}`);
      document.getElementById('sr-name').value = item.name || '';
      document.getElementById('sr-body').value = item.body || '';
      document.getElementById('sr-active').checked = item.active !== false;
      setTagsValue('sr-tags', item.tags || []);

      const s = item.schedule || {};
      document.getElementById('sr-schedule-type').value = s.type || 'interval';
      document.getElementById('sr-schedule-type').dispatchEvent(new Event('change'));
      document.getElementById('sr-interval-value').value = s.interval_value || 1;
      document.getElementById('sr-interval-unit').value = s.interval_unit || 'days';
      document.getElementById('sr-run-time').value = s.run_time || '09:00';
      document.getElementById('sr-cron-expression').value = s.cron_expression || '';
      (s.days_of_week || []).forEach(d => {
        document.querySelector(`.sr-day-btn[data-day="${d}"]`)?.classList.add('selected');
      });

      const o = item.output || {};
      ['email','sms','slack','discord'].forEach(t => {
        const cb = document.getElementById(`sr-out-${t}`);
        if (cb) cb.checked = (o.types || []).includes(t);
      });
      setTagsValue('sr-email-recipients', o.email_recipients || []);
      setTagsValue('sr-sms-numbers', o.sms_numbers || []);
      document.getElementById('sr-slack-webhook').value = o.slack_webhook || '';
      document.getElementById('sr-discord-webhook').value = o.discord_webhook || '';
      document.getElementById('sr-report-format').value = o.report_format || 'markdown';
    } catch(e) { toast('Failed to load summary report: ' + e.message, 'error'); return; }
  }

  document.getElementById('summary-modal').classList.remove('hidden');
}

function closeSummaryModal() {
  document.getElementById('summary-modal').classList.add('hidden');
  summaryEditId = null;
}

document.getElementById('sr-schedule-type').addEventListener('change', function() {
  document.getElementById('sr-interval-fields').classList.toggle('hidden', this.value !== 'interval');
  document.getElementById('sr-weekly-fields').classList.toggle('hidden', this.value !== 'weekly');
  document.getElementById('sr-cron-fields').classList.toggle('hidden', this.value !== 'cron');
});

document.querySelectorAll('.sr-day-btn').forEach(btn => {
  btn.addEventListener('click', () => btn.classList.toggle('selected'));
});

async function saveSummaryReport() {
  const scheduleType = document.getElementById('sr-schedule-type').value;
  const payload = {
    name: document.getElementById('sr-name').value.trim(),
    description: document.getElementById('sr-body').value.trim(),
    tags: getTagsValue('sr-tags'),
    active: document.getElementById('sr-active').checked,
    schedule: {
      type: scheduleType,
      interval_value: parseInt(document.getElementById('sr-interval-value').value) || 1,
      interval_unit: document.getElementById('sr-interval-unit').value,
      run_time: document.getElementById('sr-run-time').value,
      cron_expression: document.getElementById('sr-cron-expression').value,
      days_of_week: [...document.querySelectorAll('.sr-day-btn.selected')].map(b => parseInt(b.dataset.day)),
    },
    output: {
      types: ['email','sms','slack','discord'].filter(t => document.getElementById(`sr-out-${t}`)?.checked),
      email_recipients: getTagsValue('sr-email-recipients'),
      sms_numbers: getTagsValue('sr-sms-numbers'),
      slack_webhook: document.getElementById('sr-slack-webhook').value.trim() || null,
      discord_webhook: document.getElementById('sr-discord-webhook').value.trim() || null,
      report_format: document.getElementById('sr-report-format').value,
    },
  };

  if (!payload.name) { toast('Name is required', 'error'); return; }

  const btn = document.getElementById('save-summary-btn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Saving…';
  try {
    if (summaryEditId) {
      await API.put(`/summary-reports/${summaryEditId}`, payload);
      toast('Summary report updated', 'success');
    } else {
      await API.post('/summary-reports/', payload);
      toast('Summary report created', 'success');
    }
    closeSummaryModal();
    loadSummaryReports();
  } catch(e) {
    toast('Save failed: ' + e.message, 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = 'Save';
  }
}

async function deleteSummaryReport(id, name) {
  if (!confirm(`Delete summary report "${name}"? This cannot be undone.`)) return;
  try {
    await API.delete(`/summary-reports/${id}`);
    toast('Summary report deleted', 'success');
    loadSummaryReports();
  } catch(e) { toast('Delete failed: ' + e.message, 'error'); }
}

async function runSummaryNow(id, name) {
  toast(`Running "${name}"…`, 'info');
  try {
    const result = await API.post(`/summary-reports/${id}/run`, {});
    if (result.error) {
      toast('Run failed: ' + result.error, 'error');
    } else {
      const n = result.reports_collected || 0;
      toast(`"${name}" completed. ${n} source report${n !== 1 ? 's' : ''} collected. Outputs: ${result.output_sent.join(', ') || 'none'}`, 'success');
    }
    loadSummaryReports();
  } catch(e) { toast('Run failed: ' + e.message, 'error'); }
}

async function viewSummaryReports(id, name) {
  try {
    const reports = await API.get(`/summary-reports/${id}/reports`);
    const container = document.getElementById('reports-list');
    document.getElementById('reports-title').textContent = `Summary Reports: ${name}`;
    if (!reports.length) {
      container.innerHTML = '<p style="color:var(--citadel-muted)">No reports yet. Run this summary to generate a report.</p>';
    } else {
      container.innerHTML = reports.map(r => `
        <div class="item-card" style="cursor:pointer" onclick="viewSummaryReportContent('${id}', '${r.filename}')">
          <div class="item-info">
            <div class="item-name">${r.filename}</div>
            <div class="item-meta"><span>${new Date(r.modified).toLocaleString()}</span><span>${formatBytes(r.size)}</span></div>
          </div>
        </div>`).join('');
    }
    document.getElementById('reports-modal').classList.remove('hidden');
  } catch(e) { toast('Failed to load reports', 'error'); }
}

async function viewSummaryReportContent(reportId, filename) {
  try {
    const data = await API.get(`/summary-reports/${reportId}/reports/${filename}`);
    const el = document.getElementById('report-content');
    el.innerHTML = typeof marked !== 'undefined'
      ? marked.parse(data.content)
      : `<pre style="white-space:pre-wrap">${escHtml(data.content)}</pre>`;
    const dateEl = document.getElementById('report-generated-date');
    if (data.generated_at) {
      dateEl.textContent = 'generated on: ' + new Date(data.generated_at).toLocaleString();
      dateEl.style.display = 'inline';
    } else {
      dateEl.style.display = 'none';
    }
    _setReportCtx('summary', reportId, filename);
    document.getElementById('report-content-modal').classList.remove('hidden');
  } catch(e) { toast('Failed to load report', 'error'); }
}

/* ══════════════════════════════════════════
   TAGS INPUT HELPER
══════════════════════════════════════════ */
function initTagsInput(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const input = container.querySelector('.tag-input-field');
  input.addEventListener('keydown', (e) => {
    if ((e.key === 'Enter' || e.key === ',') && input.value.trim()) {
      e.preventDefault();
      addTag(container, input.value.trim().replace(/,/g, ''));
      input.value = '';
    } else if (e.key === 'Backspace' && !input.value) {
      const tags = container.querySelectorAll('.tag');
      tags[tags.length - 1]?.remove();
    }
  });
  container.addEventListener('click', () => input.focus());
}

function addTag(container, value) {
  if (!value) return;
  const existing = [...container.querySelectorAll('.tag')].map(t => t.dataset.value);
  if (existing.includes(value)) return;
  const tag = document.createElement('span');
  tag.className = 'tag';
  tag.dataset.value = value;
  tag.innerHTML = `${escHtml(value)} <span class="remove" onclick="this.parentElement.remove()">×</span>`;
  container.insertBefore(tag, container.querySelector('.tag-input-field'));
}

function getTagsValue(containerId) {
  const container = document.getElementById(containerId);
  if (!container) return [];
  // Flush any text still typed but not confirmed with Enter
  const pending = container.querySelector('.tag-input-field');
  if (pending && pending.value.trim()) {
    addTag(container, pending.value.trim().replace(/,/g, ''));
    pending.value = '';
  }
  return [...container.querySelectorAll('.tag')].map(t => t.dataset.value);
}

function setTagsValue(containerId, values) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.querySelectorAll('.tag').forEach(t => t.remove());
  values.forEach(v => addTag(container, v));
}

/* ══════════════════════════════════════════
   UTILS
══════════════════════════════════════════ */
function escHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function formatBytes(b) {
  if (b < 1024) return b + ' B';
  if (b < 1048576) return (b/1024).toFixed(1) + ' KB';
  return (b/1048576).toFixed(1) + ' MB';
}

/* ══════════════════════════════════════════
   USERS PAGE
══════════════════════════════════════════ */
async function loadUsers() {
  const el = document.getElementById('users-list');
  el.innerHTML = '<div style="color:var(--citadel-muted);padding:16px">Loading users…</div>';
  try {
    const users = await API.get('/users/');
    if (!users) return;
    if (!users.length) { el.innerHTML = '<div style="color:var(--citadel-muted);padding:16px">No users found.</div>'; return; }
    el.innerHTML = `
      <table class="dash-table" style="width:100%">
        <thead><tr>
          <th>Username</th><th>Role</th><th>MFA</th><th>MFA Exempt</th><th>Created</th><th>Actions</th>
        </tr></thead>
        <tbody>
          ${users.map(u => `
            <tr>
              <td><strong>${escHtml(u.username)}</strong></td>
              <td><span class="role-badge role-${u.role}">${roleLabel(u.role)}</span></td>
              <td>${u.mfa_enabled ? '<span style="color:var(--citadel-success)">✔ Enabled</span>' : '<span style="color:var(--citadel-muted)">—</span>'}</td>
              <td>${u.mfa_exempt ? '<span style="color:var(--citadel-warn)">Exempt</span>' : '—'}</td>
              <td style="color:var(--citadel-muted);font-size:0.82rem">${u.created_at ? u.created_at.slice(0,10) : '—'}</td>
              <td>
                <button class="btn btn-ghost btn-sm" onclick="openUserModal('${u.id}')">Edit</button>
                <button class="btn btn-ghost btn-sm" onclick="resetUserMFA('${u.id}','${escHtml(u.username)}')">Reset MFA</button>
                ${u.id !== currentUser?.id ? `<button class="btn btn-danger btn-sm" onclick="deleteUser('${u.id}','${escHtml(u.username)}')">Delete</button>` : ''}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  } catch(e) { el.innerHTML = `<div style="color:var(--citadel-danger);padding:16px">Failed to load users: ${e.message}</div>`; }
}

let userEditId = null;

async function openUserModal(id = null) {
  userEditId = id;
  document.getElementById('user-modal-title').textContent = id ? 'Edit User' : 'Add User';
  document.getElementById('user-edit-id').value = id || '';
  document.getElementById('user-username').value = '';
  document.getElementById('user-username').disabled = !!id;
  document.getElementById('user-password').value = '';
  document.getElementById('user-role').value = 'user';
  document.getElementById('user-mfa-exempt').checked = false;
  document.getElementById('user-pw-label').textContent = id ? 'New Password (optional)' : 'Password';
  document.getElementById('user-pw-hint').style.display = id ? '' : 'none';

  if (id) {
    try {
      const users = await API.get('/users/');
      const u = users?.find(x => x.id === id);
      if (u) {
        document.getElementById('user-username').value = u.username;
        document.getElementById('user-role').value = u.role;
        document.getElementById('user-mfa-exempt').checked = u.mfa_exempt || false;
      }
    } catch(e) { toast('Failed to load user: ' + e.message, 'error'); return; }
  }
  document.getElementById('user-modal').classList.remove('hidden');
}

function closeUserModal() {
  document.getElementById('user-modal').classList.add('hidden');
  userEditId = null;
}

async function saveUser() {
  const id = document.getElementById('user-edit-id').value;
  const payload = {
    username: document.getElementById('user-username').value.trim(),
    password: document.getElementById('user-password').value,
    role: document.getElementById('user-role').value,
    mfa_exempt: document.getElementById('user-mfa-exempt').checked,
  };
  try {
    if (id) {
      await API.put(`/users/${id}`, payload);
      toast('User updated', 'success');
    } else {
      await API.post('/users/', payload);
      toast('User created', 'success');
    }
    closeUserModal();
    loadUsers();
  } catch(e) {
    let msg = e.message;
    try { msg = JSON.parse(msg).detail || msg; } catch(_) {}
    toast('Save failed: ' + msg, 'error');
  }
}

async function deleteUser(id, name) {
  if (!confirm(`Delete user "${name}"?\n\nThis cannot be undone.`)) return;
  try {
    await API.delete(`/users/${id}`);
    toast(`User "${name}" deleted`, 'success');
    loadUsers();
  } catch(e) { toast('Delete failed: ' + e.message, 'error'); }
}

async function resetUserMFA(id, name) {
  if (!confirm(`Reset MFA for "${name}"?\n\nThey will need to set up MFA again on next login.`)) return;
  try {
    const r = await API.post(`/users/${id}/reset-mfa`, {});
    toast(r?.message || 'MFA reset', 'success');
    loadUsers();
  } catch(e) { toast('Reset failed: ' + e.message, 'error'); }
}

/* ══════════════════════════════════════════
   PROFILE MODAL
══════════════════════════════════════════ */
async function openProfileModal(tab = 'pw') {
  const modal = document.getElementById('profile-modal');
  // Refresh user info to get current MFA state
  try {
    const me = await API.get('/auth/me');
    if (!me) return;
    currentUser = me;
    _refreshMFATab(me);
  } catch(e) {}

  // Switch to requested tab
  if (tab === 'mfa') {
    document.getElementById('profile-tab-mfa-btn').click();
  } else {
    document.getElementById('profile-tab-pw-btn').click();
  }
  // Clear password fields
  document.getElementById('pw-current').value = '';
  document.getElementById('pw-new').value = '';
  document.getElementById('pw-confirm').value = '';
  modal.classList.remove('hidden');
}

function _refreshMFATab(user) {
  const enabled = document.getElementById('mfa-status-enabled');
  const setup = document.getElementById('mfa-status-setup');
  if (user.mfa_enabled) {
    enabled.classList.remove('hidden');
    setup.classList.add('hidden');
  } else {
    enabled.classList.add('hidden');
    setup.classList.remove('hidden');
    document.getElementById('mfa-setup-step1').classList.remove('hidden');
    document.getElementById('mfa-setup-step2').classList.add('hidden');
  }
}

function closeProfileModal() {
  document.getElementById('profile-modal').classList.add('hidden');
}

async function changePassword() {
  const current = document.getElementById('pw-current').value;
  const newPw = document.getElementById('pw-new').value;
  const confirm = document.getElementById('pw-confirm').value;
  if (newPw !== confirm) { toast('New passwords do not match', 'error'); return; }
  if (newPw.length < 8) { toast('Password must be at least 8 characters', 'error'); return; }
  try {
    const r = await API.post('/auth/change-password', { current_password: current, new_password: newPw });
    toast(r?.message || 'Password updated', 'success');
    closeProfileModal();
  } catch(e) {
    let msg = e.message;
    try { msg = JSON.parse(msg).detail || msg; } catch(_) {}
    toast('Failed: ' + msg, 'error');
  }
}

async function beginMFASetup() {
  try {
    const data = await API.get('/auth/setup-mfa');
    if (!data) return;
    document.getElementById('mfa-qr-img').src = `data:image/png;base64,${data.qr_code}`;
    document.getElementById('mfa-secret-text').textContent = data.secret;
    document.getElementById('mfa-confirm-code').value = '';
    document.getElementById('mfa-setup-step1').classList.add('hidden');
    document.getElementById('mfa-setup-step2').classList.remove('hidden');
  } catch(e) { toast('Failed to start MFA setup: ' + e.message, 'error'); }
}

async function confirmMFASetup() {
  const code = document.getElementById('mfa-confirm-code').value.replace(/\s/g,'');
  if (code.length !== 6) { toast('Enter the 6-digit code from your authenticator app', 'error'); return; }
  try {
    const r = await API.post('/auth/confirm-mfa', { code });
    toast(r?.message || 'MFA enabled!', 'success');
    currentUser.mfa_enabled = true;
    currentUser.mfa_setup_required = false;
    document.getElementById('mfa-setup-banner').classList.add('hidden');
    _refreshMFATab(currentUser);
  } catch(e) {
    let msg = e.message;
    try { msg = JSON.parse(msg).detail || msg; } catch(_) {}
    toast('Failed: ' + msg, 'error');
  }
}

function cancelMFASetup() {
  document.getElementById('mfa-setup-step1').classList.remove('hidden');
  document.getElementById('mfa-setup-step2').classList.add('hidden');
}

async function disableMFA() {
  const code = document.getElementById('mfa-disable-code').value.replace(/\s/g,'');
  if (code.length !== 6) { toast('Enter your current 6-digit authenticator code', 'error'); return; }
  if (!confirm('Disable MFA on your account? This reduces your account security.')) return;
  try {
    const r = await API.post('/auth/disable-mfa', { code });
    toast(r?.message || 'MFA disabled', 'success');
    currentUser.mfa_enabled = false;
    _refreshMFATab(currentUser);
    document.getElementById('mfa-disable-code').value = '';
  } catch(e) {
    let msg = e.message;
    try { msg = JSON.parse(msg).detail || msg; } catch(_) {}
    toast('Failed: ' + msg, 'error');
  }
}

/* ══════════════════════════════════════════
   REPORT DELETE (dev mode + admin)
══════════════════════════════════════════ */
let _currentReportCtx = null; // { type: 'interest'|'resource'|'summary', parentId, filename }

function _setReportCtx(type, parentId, filename) {
  _currentReportCtx = { type, parentId, filename };
  const btn = document.getElementById('report-delete-btn');
  if (btn) {
    const canDelete = _devMode && currentUser && currentUser.role === 'admin';
    btn.classList.toggle('hidden', !canDelete);
  }
}

function deleteCurrentReport() {
  if (!_currentReportCtx) return;
  const { filename } = _currentReportCtx;
  document.getElementById('report-delete-filename').textContent = filename;
  document.getElementById('report-delete-confirm-modal').classList.remove('hidden');
}

async function confirmDeleteReport() {
  if (!_currentReportCtx) return;
  const { type, parentId, filename } = _currentReportCtx;
  const urlMap = {
    interest: `/interests/${parentId}/reports/${filename}`,
    resource:  `/resources/${parentId}/reports/${filename}`,
    summary:   `/summary-reports/${parentId}/reports/${filename}`,
  };
  try {
    await API.delete(urlMap[type]);
    document.getElementById('report-delete-confirm-modal').classList.add('hidden');
    document.getElementById('report-content-modal').classList.add('hidden');
    _currentReportCtx = null;
    toast('Report deleted', 'success');
  } catch(e) { toast('Delete failed: ' + e.message, 'error'); }
}

/* ══════════════════════════════════════════
   ADMIN
══════════════════════════════════════════ */
let _devMode = false;
let _defaultResourcePrompt = null;

async function loadAdmin() {
  try {
    const data = await API.get('/admin/system-state');
    const val = data.system_state || '';
    document.getElementById('system-state-input').value = val;
    _devMode = val.trim().toLowerCase() === 'dev';
    updateDevModeBadge();
  } catch(e) { /* non-fatal */ }
  try {
    const data = await API.get('/admin/default-resource-prompt');
    _defaultResourcePrompt = data.default_resource_prompt || '';
    const el = document.getElementById('default-resource-prompt-input');
    if (el) el.value = _defaultResourcePrompt;
  } catch(e) { /* non-fatal */ }
}

function updateDevModeBadge() {
  const val = (document.getElementById('system-state-input').value || '').trim().toLowerCase();
  const badge = document.getElementById('system-state-badge');
  if (!badge) return;
  if (val === 'dev') {
    badge.innerHTML = '<span class="badge badge-danger">Development Mode</span>';
  } else if (val) {
    badge.innerHTML = `<span class="badge badge-muted">${escHtml(val)}</span>`;
  } else {
    badge.innerHTML = '<span class="badge badge-success">Normal Operation</span>';
  }
}

async function saveSystemState() {
  const val = (document.getElementById('system-state-input').value || '').trim();
  try {
    const res = await API.put('/admin/system-state', { system_state: val });
    _devMode = (res.system_state || '').toLowerCase() === 'dev';
    updateDevModeBadge();
    toast('System state saved', 'success');
  } catch(e) { toast('Failed to save system state: ' + e.message, 'error'); }
}

async function saveDefaultResourcePrompt() {
  const val = (document.getElementById('default-resource-prompt-input').value || '').trim();
  try {
    const res = await API.put('/admin/default-resource-prompt', { default_resource_prompt: val });
    _defaultResourcePrompt = res.default_resource_prompt || '';
    toast('Default resource prompt saved', 'success');
  } catch(e) { toast('Failed to save prompt: ' + e.message, 'error'); }
}

function resetDefaultResourcePrompt() {
  if (!confirm('Reset to the built-in default prompt? This clears your custom prompt.')) return;
  const el = document.getElementById('default-resource-prompt-input');
  if (el) el.value = '';
  saveDefaultResourcePrompt();
}

function adminExport(type) {
  const a = document.createElement('a');
  a.href = `/api/admin/backup/${type}`;
  a.download = '';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  toast(`Preparing ${type} export…`, 'info');
}

function adminRestore(type, accept) {
  const label = type === 'full' ? 'ALL system data' : type;
  if (!confirm(`Restore ${label}?\n\nThis will overwrite existing files. Make sure you have a backup first.`)) return;
  const input = document.createElement('input');
  input.type = 'file';
  input.accept = accept;
  input.onchange = async () => {
    const file = input.files[0];
    if (!file) return;
    const formData = new FormData();
    formData.append('file', file);
    toast(`Uploading ${file.name}…`, 'info');
    try {
      const r = await fetch(`/api/admin/restore/${type}`, { method: 'POST', body: formData });
      const data = await r.json();
      if (r.ok && data.ok) {
        toast(data.message, 'success');
      } else {
        toast('Restore failed: ' + (data.detail || data.error || 'unknown error'), 'error');
      }
    } catch(e) {
      toast('Restore failed: ' + e.message, 'error');
    }
  };
  input.click();
}

async function adminBuildPackage() {
  const btn     = document.getElementById('build-pkg-btn');
  const dlBtn   = document.getElementById('download-pkg-btn');
  const result  = document.getElementById('build-pkg-result');
  const errBox  = document.getElementById('build-pkg-error');
  const missing = document.getElementById('build-pkg-missing');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Building…';
  result.textContent = '';
  result.style.color = 'var(--citadel-muted)';
  dlBtn.classList.add('hidden');
  errBox.classList.add('hidden');

  try {
    const data = await API.post('/admin/build-package', {});
    result.textContent = data.message || 'Package built successfully';
    result.style.color = 'var(--citadel-success)';
    dlBtn.classList.remove('hidden');
    toast('Package built — download it below to deploy to production', 'success');
  } catch(e) {
    let detail = e.message;
    let missingFiles = null;
    try {
      const parsed = JSON.parse(e.message);
      detail = parsed.detail?.error || parsed.detail || detail;
      missingFiles = parsed.detail?.missing || null;
    } catch(_) {}
    result.textContent = 'Build failed: ' + detail;
    result.style.color = 'var(--citadel-danger)';
    if (missingFiles && missingFiles.length) {
      missing.textContent = missingFiles.join('\n');
      errBox.classList.remove('hidden');
    }
    toast('Build failed — see details below', 'error');
  } finally {
    btn.disabled = false;
    btn.textContent = '⚙ Build Package Now';
  }
}

// ── Self-Update / Recovery ────────────────────────────────────────────────────

let _suEventSource = null;

function adminSelfUpdate() {
  const urlInput = document.getElementById('su-url');
  const url = (urlInput.value || '').trim();
  if (!url) { toast('Enter a package URL to proceed', 'error'); return; }

  if (!confirm(
    'This will perform the following steps automatically:\n\n' +
    '  1. Create a full data backup (saved to deploy/)\n' +
    '  2. Snapshot current code into a deployment package\n' +
    '  3. Download and install: ' + url + '\n' +
    '     (data and config are always preserved)\n' +
    '  4. Update Python dependencies and restart Citadel\n\n' +
    'Proceed?'
  )) return;

  const btn   = document.getElementById('su-start-btn');
  const panel = document.getElementById('su-panel');
  const log   = document.getElementById('su-log');

  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> Running…';
  panel.classList.remove('hidden');
  log.innerHTML = '';
  document.getElementById('su-reconnect').classList.add('hidden');

  const stepIds = { 1: 'su-step-1', 2: 'su-step-2', 3: 'su-step-3', 4: 'su-step-4' };
  Object.values(stepIds).forEach(id => {
    const el = document.getElementById(id);
    el.style.background   = '';
    el.style.borderColor  = 'var(--citadel-border)';
    el.style.color        = 'var(--citadel-text)';
  });

  let _completeSeen = false;

  function esc(s) {
    return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }

  function appendLog(status, msg) {
    const icon  = { running: '⟳', done: '✔', warn: '⚠', error: '✘' }[status] || '·';
    const color = {
      running: 'var(--citadel-accent)',
      done:    'var(--citadel-success)',
      warn:    'var(--citadel-warn)',
      error:   'var(--citadel-danger)',
    }[status] || 'inherit';
    const div = document.createElement('div');
    div.innerHTML = `<span style="color:${color};display:inline-block;width:1.4em">${icon}</span>${esc(msg)}`;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function markStep(step, status) {
    const el = document.getElementById(stepIds[step]);
    if (!el) return;
    const styles = {
      running: { bg: '#0e1f2e', border: 'var(--citadel-accent)',   color: 'var(--citadel-accent)'   },
      done:    { bg: '#0d2b1a', border: 'var(--citadel-success)',  color: 'var(--citadel-success)'  },
      warn:    { bg: '#2b200a', border: 'var(--citadel-warn)',     color: 'var(--citadel-warn)'     },
      error:   { bg: '#2b0a0a', border: 'var(--citadel-danger)',   color: 'var(--citadel-danger)'   },
    }[status] || {};
    el.style.background  = styles.bg    || '';
    el.style.borderColor = styles.border || '';
    el.style.color       = styles.color  || '';
  }

  if (_suEventSource) { _suEventSource.close(); _suEventSource = null; }

  const src = new EventSource('/api/admin/self-update/stream?url=' + encodeURIComponent(url));
  _suEventSource = src;

  src.onmessage = (e) => {
    let d;
    try { d = JSON.parse(e.data); } catch(_) { return; }

    if (typeof d.step === 'number') markStep(d.step, d.status);
    appendLog(d.status, d.msg);

    if (d.step === 'complete') {
      _completeSeen = true;
      src.close();
      _suEventSource = null;
      btn.disabled = false;
      btn.textContent = '🔄 Begin Update';

      const reconnect = document.getElementById('su-reconnect');
      reconnect.classList.remove('hidden');
      let t = 10;
      const iv = setInterval(() => {
        t--;
        const el = document.getElementById('su-countdown');
        if (el) el.textContent = t;
        if (t <= 0) { clearInterval(iv); location.reload(); }
      }, 1000);
    }
  };

  src.onerror = () => {
    src.close();
    _suEventSource = null;
    if (_completeSeen) return;
    appendLog('warn', 'Connection lost — the service may be restarting. Reload in 10–15 seconds.');
    btn.disabled = false;
    btn.textContent = '🔄 Begin Update';
    const reconnect = document.getElementById('su-reconnect');
    reconnect.classList.remove('hidden');
    let t = 12;
    document.getElementById('su-countdown').textContent = t;
    const iv = setInterval(() => {
      t--;
      const el = document.getElementById('su-countdown');
      if (el) el.textContent = t;
      if (t <= 0) { clearInterval(iv); location.reload(); }
    }, 1000);
  };
}

async function terminateSessions() {
  if (!confirm('Terminate all active sessions?\n\nEvery logged-in user (except you) will be immediately logged out and forced to reauthenticate. Your session will not be affected.')) return;
  try {
    const data = await API.post('/admin/terminate-sessions', {});
    toast(data.message || 'All sessions terminated', 'success');
  } catch (e) {
    toast('Failed to terminate sessions: ' + (e.message || e), 'error');
  }
}

async function factoryResetRequest() {
  if (!confirm('Are you sure you want to start the factory reset process?\n\nA validation code will be generated that you must re-enter to confirm.')) return;
  try {
    const data = await API.post('/admin/factory-reset/challenge', {});
    document.getElementById('reset-challenge-code').textContent = data.code;
    document.getElementById('reset-code-input').value = '';
    document.getElementById('factory-reset-idle').classList.add('hidden');
    document.getElementById('factory-reset-challenge').classList.remove('hidden');
    toast('Validation code generated — enter it below to confirm reset', 'info');
  } catch(e) { toast('Failed to generate code: ' + e.message, 'error'); }
}

async function factoryResetConfirm() {
  const code = document.getElementById('reset-code-input').value.trim().toUpperCase();
  if (code.length !== 8) { toast('Enter the full 8-character code', 'error'); return; }
  if (!confirm('FINAL WARNING: This will permanently delete all data.\n\nProceed?')) return;
  try {
    const data = await API.post('/admin/factory-reset/confirm', { code });
    toast(data.message, 'success');
    factoryResetCancel();
  } catch(e) {
    let msg = e.message;
    try { msg = JSON.parse(e.message).detail || msg; } catch(_) {}
    toast('Reset failed: ' + msg, 'error');
    document.getElementById('reset-code-input').value = '';
  }
}

function factoryResetCancel() {
  document.getElementById('factory-reset-idle').classList.remove('hidden');
  document.getElementById('factory-reset-challenge').classList.add('hidden');
  document.getElementById('reset-code-input').value = '';
}

/* ══════════════════════════════════════════
   IOC GRID
══════════════════════════════════════════ */

const IOC_PAGE_SIZE = 50;

function _iocSearch(iocType) {
  const inp = document.getElementById(`ioc-search-input-${iocType}`);
  _iocState[iocType].search = inp ? inp.value : '';
  _iocState[iocType].page = 0;
  renderIocGrid(iocType);
  const refocused = document.getElementById(`ioc-search-input-${iocType}`);
  if (refocused) { refocused.focus(); refocused.setSelectionRange(refocused.value.length, refocused.value.length); }
}

// Per-type UI state
const _iocState = {};
['ip','hash','url','domain'].forEach(t => {
  _iocState[t] = { data: [], sortCol: 'added_at', sortDir: 'desc', page: 0, search: '', filterStatus: '', filterFamily: '', filterPriority: '' };
});

// Column definitions per IOC type
const IOC_COLS = {
  ip: [
    { key:'value',           label:'IP Address',    sortable:true,  width:'130px' },
    { key:'port',            label:'Port',          sortable:true,  width:'60px'  },
    { key:'status',          label:'Status',        sortable:true,  width:'80px'  },
    { key:'threat_type',     label:'Threat',        sortable:true,  width:'120px' },
    { key:'malware_family',  label:'Malware',       sortable:true,  width:'120px' },
    { key:'country',         label:'Ctry',          sortable:true,  width:'50px'  },
    { key:'asn_name',        label:'ASN',           sortable:false, width:'160px' },
    { key:'sources',         label:'Sources',       sortable:false, width:'100px' },
    { key:'first_seen',      label:'First Seen',    sortable:true,  width:'100px' },
    { key:'added_at',        label:'Added',         sortable:true,  width:'100px' },
    { key:'priority_override',label:'Priority',     sortable:true,  width:'80px'  },
    { key:'expires_at',      label:'Expires',       sortable:true,  width:'100px' },
  ],
  hash: [
    { key:'value',           label:'SHA-256',       sortable:true,  width:'180px' },
    { key:'hash_md5',        label:'MD5',           sortable:false, width:'130px' },
    { key:'file_type',       label:'Type',          sortable:true,  width:'60px'  },
    { key:'malware_family',  label:'Malware',       sortable:true,  width:'130px' },
    { key:'reporter',        label:'Reporter',      sortable:true,  width:'110px' },
    { key:'first_seen',      label:'First Seen',    sortable:true,  width:'100px' },
    { key:'added_at',        label:'Added',         sortable:true,  width:'100px' },
    { key:'priority_override',label:'Priority',     sortable:true,  width:'80px'  },
    { key:'expires_at',      label:'Expires',       sortable:true,  width:'100px' },
  ],
  url: [
    { key:'value',           label:'URL',           sortable:true,  width:'280px' },
    { key:'status',          label:'Status',        sortable:true,  width:'80px'  },
    { key:'threat_type',     label:'Threat',        sortable:true,  width:'130px' },
    { key:'malware_family',  label:'Malware',       sortable:true,  width:'120px' },
    { key:'tags',            label:'Tags',          sortable:false, width:'120px' },
    { key:'reporter',        label:'Reporter',      sortable:true,  width:'110px' },
    { key:'added_at',        label:'Added',         sortable:true,  width:'100px' },
    { key:'priority_override',label:'Priority',     sortable:true,  width:'80px'  },
    { key:'expires_at',      label:'Expires',       sortable:true,  width:'100px' },
  ],
  domain: [
    { key:'value',           label:'Domain',        sortable:true,  width:'200px' },
    { key:'status',          label:'Status',        sortable:true,  width:'80px'  },
    { key:'threat_type',     label:'Threat',        sortable:true,  width:'120px' },
    { key:'malware_family',  label:'Malware',       sortable:true,  width:'120px' },
    { key:'tags',            label:'Tags',          sortable:false, width:'120px' },
    { key:'sources',         label:'Sources',       sortable:false, width:'100px' },
    { key:'first_seen',      label:'First Seen',    sortable:true,  width:'100px' },
    { key:'added_at',        label:'Added',         sortable:true,  width:'100px' },
    { key:'priority_override',label:'Priority',     sortable:true,  width:'80px'  },
    { key:'expires_at',      label:'Expires',       sortable:true,  width:'100px' },
  ],
};

const IOC_TYPE_LABEL = { ip:'IP Addresses', hash:'File Hashes', url:'Malicious URLs', domain:'Domains' };

async function loadIocPage(iocType) {
  const st = _iocState[iocType];
  try {
    st.data = await API.get(`/iocs/${iocType}`) || [];
  } catch(e) {
    st.data = [];
  }
  renderIocGrid(iocType);
}

function _iocFiltered(iocType) {
  const st = _iocState[iocType];
  const q = st.search.toLowerCase();
  return st.data.filter(r => {
    if (q && !JSON.stringify(r).toLowerCase().includes(q)) return false;
    if (st.filterStatus && r.status !== st.filterStatus) return false;
    if (st.filterFamily && (r.malware_family || '').toLowerCase() !== st.filterFamily.toLowerCase()) return false;
    if (st.filterPriority) {
      if (st.filterPriority === 'none' && r.priority_override) return false;
      if (st.filterPriority !== 'none' && r.priority_override !== st.filterPriority) return false;
    }
    return true;
  });
}

function _sortIoc(rows, col, dir) {
  return [...rows].sort((a, b) => {
    let av = a[col] ?? '', bv = b[col] ?? '';
    if (typeof av === 'number' && typeof bv === 'number') return dir === 'asc' ? av - bv : bv - av;
    av = String(av).toLowerCase(); bv = String(bv).toLowerCase();
    return dir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
  });
}

function _fmtDate(val) {
  if (!val) return '';
  try { return new Date(val).toLocaleDateString('en-CA'); } catch { return String(val).slice(0,10); }
}

function _iocStatusBadge(status) {
  if (!status) return '<span class="ioc-badge ioc-badge-unknown">?</span>';
  if (status === 'online') return '<span class="ioc-badge ioc-badge-online">online</span>';
  if (status === 'offline') return '<span class="ioc-badge ioc-badge-offline">offline</span>';
  return `<span class="ioc-badge ioc-badge-unknown">${escHtml(status)}</span>`;
}

function _iocPriorityBadge(p) {
  if (!p) return '';
  const cls = { low:'ioc-badge-pri-low', medium:'ioc-badge-pri-med', high:'ioc-badge-pri-high' }[p] || '';
  return `<span class="ioc-badge ${cls}">${p}</span>`;
}

function _iocCellValue(col, rec) {
  const v = rec[col.key];
  if (col.key === 'status') return _iocStatusBadge(v);
  if (col.key === 'priority_override') return _iocPriorityBadge(v);
  if (col.key === 'tags' || col.key === 'sources') {
    if (!v || !v.length) return '';
    const arr = Array.isArray(v) ? v : String(v).split(',');
    return arr.filter(Boolean).map(t => `<span class="ioc-tag">${escHtml(t.trim())}</span>`).join(' ');
  }
  if (col.key === 'first_seen' || col.key === 'added_at' || col.key === 'expires_at') return _fmtDate(v);
  if (col.key === 'value') {
    const s = String(v || '');
    const display = s.length > 40 ? s.slice(0,38) + '…' : s;
    return `<span title="${escHtml(s)}" style="font-family:monospace;font-size:0.78rem">${escHtml(display)}</span>`;
  }
  if (col.key === 'hash_md5') {
    const s = String(v || '');
    return s ? `<span style="font-family:monospace;font-size:0.75rem" title="${escHtml(s)}">${s.slice(0,8)}…</span>` : '';
  }
  return escHtml(String(v ?? ''));
}

function renderIocGrid(iocType) {
  const st = _iocState[iocType];
  const cols = IOC_COLS[iocType];
  const container = document.getElementById(`ioc-grid-${iocType}`);
  if (!container) return;

  const filtered = _iocFiltered(iocType);
  const sorted = _sortIoc(filtered, st.sortCol, st.sortDir);
  const totalPages = Math.max(1, Math.ceil(sorted.length / IOC_PAGE_SIZE));
  if (st.page >= totalPages) st.page = 0;
  const pageRows = sorted.slice(st.page * IOC_PAGE_SIZE, (st.page + 1) * IOC_PAGE_SIZE);

  // Unique malware families for filter dropdown
  const families = [...new Set(st.data.map(r => r.malware_family).filter(Boolean))].sort();

  const canEdit = currentUser && ['manager','admin'].includes(currentUser.role);

  container.innerHTML = `
    <div class="ioc-toolbar">
      <input class="form-control ioc-search" type="text" id="ioc-search-input-${iocType}" placeholder="Search all fields…"
        value="${escHtml(st.search)}"
        onkeydown="if(event.key==='Enter'){event.preventDefault();_iocSearch('${iocType}')}">
      <button class="btn ioc-search-btn" onclick="_iocSearch('${iocType}')">Search</button>
      <select class="form-control ioc-filter-select" onchange="_iocState['${iocType}'].filterStatus=this.value;_iocState['${iocType}'].page=0;renderIocGrid('${iocType}')">
        <option value="">All Statuses</option>
        <option value="online" ${st.filterStatus==='online'?'selected':''}>Online</option>
        <option value="offline" ${st.filterStatus==='offline'?'selected':''}>Offline</option>
      </select>
      <select class="form-control ioc-filter-select" onchange="_iocState['${iocType}'].filterFamily=this.value;_iocState['${iocType}'].page=0;renderIocGrid('${iocType}')">
        <option value="">All Families</option>
        ${families.map(f => `<option value="${escHtml(f)}" ${st.filterFamily===f?'selected':''}>${escHtml(f)}</option>`).join('')}
      </select>
      <select class="form-control ioc-filter-select" onchange="_iocState['${iocType}'].filterPriority=this.value;_iocState['${iocType}'].page=0;renderIocGrid('${iocType}')">
        <option value="">All Priorities</option>
        <option value="high" ${st.filterPriority==='high'?'selected':''}>High</option>
        <option value="medium" ${st.filterPriority==='medium'?'selected':''}>Medium</option>
        <option value="low" ${st.filterPriority==='low'?'selected':''}>Low</option>
        <option value="none" ${st.filterPriority==='none'?'selected':''}>None</option>
      </select>
      <span class="ioc-count">${filtered.length} record${filtered.length!==1?'s':''}</span>
    </div>

    <div class="ioc-table-wrap">
      <table class="ioc-table">
        <thead>
          <tr>
            ${cols.map(c => `
              <th class="${c.sortable?'sortable':''}" style="min-width:${c.width}" onclick="${c.sortable?`_iocSort('${iocType}','${c.key}')`:''}" >
                ${c.label}
                ${c.sortable && st.sortCol===c.key ? (st.sortDir==='asc'?'▲':'▼') : ''}
              </th>`).join('')}
            <th style="width:80px">Actions</th>
          </tr>
        </thead>
        <tbody>
          ${pageRows.length === 0
            ? `<tr><td colspan="${cols.length+1}" style="text-align:center;color:var(--citadel-muted);padding:24px">No IOCs found</td></tr>`
            : pageRows.map(rec => `
              <tr>
                ${cols.map(c => `<td>${_iocCellValue(c, rec)}</td>`).join('')}
                <td>
                  ${canEdit ? `
                    <button class="btn btn-ghost btn-sm" onclick="openIocModal('${iocType}','${rec.id}')" title="Edit">✏</button>
                    <button class="btn btn-ghost btn-sm" style="color:var(--citadel-danger)" onclick="deleteIoc('${iocType}','${rec.id}','${escHtml(String(rec.value||'').slice(0,20))}')" title="Delete">🗑</button>
                  ` : '—'}
                </td>
              </tr>`).join('')}
        </tbody>
      </table>
    </div>

    ${totalPages > 1 ? `
    <div class="ioc-pagination">
      <button class="btn btn-ghost btn-sm" onclick="_iocState['${iocType}'].page=${st.page-1};renderIocGrid('${iocType}')" ${st.page===0?'disabled':''}>‹ Prev</button>
      <span>Page ${st.page+1} of ${totalPages}</span>
      <button class="btn btn-ghost btn-sm" onclick="_iocState['${iocType}'].page=${st.page+1};renderIocGrid('${iocType}')" ${st.page>=totalPages-1?'disabled':''}>Next ›</button>
    </div>` : ''}
  `;
}

function _iocSort(iocType, col) {
  const st = _iocState[iocType];
  if (st.sortCol === col) {
    st.sortDir = st.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    st.sortCol = col;
    st.sortDir = 'asc';
  }
  renderIocGrid(iocType);
}

/* ── IOC Modal ── */

let _iocModalType = '';
let _iocModalId = '';

function openIocModal(iocType, iocId) {
  _iocModalType = iocType;
  _iocModalId = iocId || '';

  document.getElementById('ioc-modal-title').textContent = iocId ? 'Edit IOC' : `Add ${IOC_TYPE_LABEL[iocType] || 'IOC'}`;
  document.getElementById('ioc-ip-fields').style.display   = iocType === 'ip'   ? '' : 'none';
  document.getElementById('ioc-hash-fields').style.display = iocType === 'hash' ? '' : 'none';

  // Clear form
  ['ioc-value','ioc-threat-type','ioc-malware-family','ioc-reporter','ioc-tags',
   'ioc-sources','ioc-refs','ioc-notes','ioc-first-seen','ioc-expires-at',
   'ioc-port','ioc-country','ioc-asn','ioc-asn-name',
   'ioc-hash-md5','ioc-hash-sha1','ioc-file-type','ioc-file-name'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  document.getElementById('ioc-status').value = '';
  document.getElementById('ioc-priority').value = '';

  if (iocId) {
    const rec = _iocState[iocType].data.find(r => r.id === iocId);
    if (rec) _populateIocModal(rec);
  }

  document.getElementById('ioc-modal').classList.remove('hidden');
  document.getElementById('ioc-value').focus();
}

function _populateIocModal(rec) {
  const set = (id, val) => { const el = document.getElementById(id); if (el && val != null) el.value = String(val); };
  set('ioc-value', rec.value);
  set('ioc-status', rec.status || '');
  set('ioc-threat-type', rec.threat_type || '');
  set('ioc-malware-family', rec.malware_family || '');
  set('ioc-reporter', rec.reporter || '');
  set('ioc-tags', Array.isArray(rec.tags) ? rec.tags.join(', ') : (rec.tags || ''));
  set('ioc-sources', Array.isArray(rec.sources) ? rec.sources.join(', ') : (rec.sources || ''));
  set('ioc-refs', Array.isArray(rec.refs) ? rec.refs.join(', ') : (rec.refs || ''));
  set('ioc-notes', rec.notes || '');
  set('ioc-first-seen', rec.first_seen ? rec.first_seen.slice(0,10) : '');
  set('ioc-expires-at', rec.expires_at ? rec.expires_at.slice(0,10) : '');
  set('ioc-priority', rec.priority_override || '');
  // IP-specific
  set('ioc-port', rec.port);
  set('ioc-country', rec.country);
  set('ioc-asn', rec.asn);
  set('ioc-asn-name', rec.asn_name);
  // Hash-specific
  set('ioc-hash-md5', rec.hash_md5);
  set('ioc-hash-sha1', rec.hash_sha1);
  set('ioc-file-type', rec.file_type);
  set('ioc-file-name', rec.file_name);
}

function closeIocModal() {
  document.getElementById('ioc-modal').classList.add('hidden');
}

function _splitCsv(val) {
  return val.split(',').map(s => s.trim()).filter(Boolean);
}

async function saveIoc() {
  const value = document.getElementById('ioc-value').value.trim();
  if (!value) { toast('IOC value is required', 'error'); return; }

  const payload = {
    value,
    status: document.getElementById('ioc-status').value || null,
    threat_type: document.getElementById('ioc-threat-type').value.trim() || null,
    malware_family: document.getElementById('ioc-malware-family').value.trim() || null,
    reporter: document.getElementById('ioc-reporter').value.trim() || null,
    tags: _splitCsv(document.getElementById('ioc-tags').value),
    sources: _splitCsv(document.getElementById('ioc-sources').value),
    refs: _splitCsv(document.getElementById('ioc-refs').value),
    notes: document.getElementById('ioc-notes').value.trim() || null,
    first_seen: document.getElementById('ioc-first-seen').value || null,
    expires_at: document.getElementById('ioc-expires-at').value || null,
    priority_override: document.getElementById('ioc-priority').value || null,
  };

  if (_iocModalType === 'ip') {
    const port = document.getElementById('ioc-port').value;
    payload.port = port ? parseInt(port) : null;
    payload.country = document.getElementById('ioc-country').value.trim().toUpperCase() || null;
    const asn = document.getElementById('ioc-asn').value;
    payload.asn = asn ? parseInt(asn) : null;
    payload.asn_name = document.getElementById('ioc-asn-name').value.trim() || null;
  }
  if (_iocModalType === 'hash') {
    payload.hash_md5  = document.getElementById('ioc-hash-md5').value.trim().toLowerCase() || null;
    payload.hash_sha1 = document.getElementById('ioc-hash-sha1').value.trim().toLowerCase() || null;
    payload.file_type = document.getElementById('ioc-file-type').value.trim() || null;
    payload.file_name = document.getElementById('ioc-file-name').value.trim() || null;
  }

  try {
    if (_iocModalId) {
      await API.put(`/iocs/${_iocModalType}/${_iocModalId}`, payload);
      toast('IOC updated', 'success');
    } else {
      await API.post(`/iocs/${_iocModalType}`, payload);
      toast('IOC saved', 'success');
    }
    closeIocModal();
    loadIocPage(_iocModalType);
  } catch(e) {
    toast('Save failed: ' + (e.message || e), 'error');
  }
}

async function deleteIoc(iocType, iocId, label) {
  if (!confirm(`Delete IOC "${label}"?\n\nThis cannot be undone.`)) return;
  try {
    await API.delete(`/iocs/${iocType}/${iocId}`);
    toast('IOC deleted', 'success');
    loadIocPage(iocType);
  } catch(e) {
    toast('Delete failed: ' + (e.message || e), 'error');
  }
}

async function runIocMaintenance() {
  if (!confirm('Run IOC maintenance now?\n\nThis will remove expired IOCs and cap each type at 1000 records.')) return;
  try {
    const data = await API.post('/iocs/maintenance/run', {});
    const summary = Object.entries(data.results)
      .map(([t, r]) => `${t}: −${r.expired} expired, −${r.capped} capped, ${r.remaining} remaining`)
      .join('\n');
    toast('Maintenance complete', 'success');
    alert('IOC Maintenance Results:\n\n' + summary);
    // Reload whichever IOC page is currently visible
    ['ip','hash','url','domain'].forEach(t => {
      if (!document.getElementById(`page-ioc-${t}s`).classList.contains('hidden') ||
          !document.getElementById(`page-ioc-${t === 'ip' ? 'ips' : t === 'hash' ? 'hashes' : t + 's'}`).classList.contains('hidden')) {
        loadIocPage(t);
      }
    });
  } catch(e) {
    toast('Maintenance failed: ' + (e.message || e), 'error');
  }
}

/* ── IOC Bulk Upload ── */

let _iocBulkType = '';

function downloadIocTemplate(iocType) {
  const a = document.createElement('a');
  a.href = `/api/iocs/${iocType}/csv-template`;
  a.download = `ioc_${iocType}_template.csv`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
}

function openBulkUploadModal(iocType) {
  _iocBulkType = iocType;
  document.getElementById('ioc-bulk-modal-title').textContent =
    `Bulk Upload — ${IOC_TYPE_LABEL[iocType] || iocType}`;
  document.getElementById('ioc-bulk-file').value = '';
  document.getElementById('ioc-bulk-priority').value = '';
  document.getElementById('ioc-bulk-expires').value = '';
  document.getElementById('ioc-bulk-conflict').value = 'csv_wins';
  const resultsEl = document.getElementById('ioc-bulk-results');
  resultsEl.innerHTML = '';
  resultsEl.classList.add('hidden');
  const btn = document.getElementById('ioc-bulk-submit-btn');
  btn.disabled = false;
  btn.textContent = '⬆ Upload CSV';
  btn.onclick = submitBulkUpload;
  document.getElementById('ioc-bulk-modal').classList.remove('hidden');
}

function closeBulkUploadModal() {
  document.getElementById('ioc-bulk-modal').classList.add('hidden');
}

async function submitBulkUpload() {
  const fileInput = document.getElementById('ioc-bulk-file');
  if (!fileInput.files.length) {
    toast('Please select a CSV file to upload', 'error');
    return;
  }

  const priority = document.getElementById('ioc-bulk-priority').value;
  const expires  = document.getElementById('ioc-bulk-expires').value;
  const conflict = document.getElementById('ioc-bulk-conflict').value;

  const formData = new FormData();
  formData.append('file', fileInput.files[0]);
  if (priority) formData.append('priority_override', priority);
  if (expires)  formData.append('expires_at', expires);
  formData.append('conflict_resolution', conflict);

  const btn = document.getElementById('ioc-bulk-submit-btn');
  btn.disabled = true;
  btn.textContent = 'Uploading…';

  const resultsEl = document.getElementById('ioc-bulk-results');
  resultsEl.innerHTML = '';
  resultsEl.classList.add('hidden');

  try {
    const resp = await fetch(`/api/iocs/${_iocBulkType}/bulk-upload`, {
      method: 'POST',
      body: formData,
      credentials: 'include',
    });

    const data = await resp.json();

    if (!resp.ok) {
      const msg = data.detail || 'Upload failed';
      resultsEl.innerHTML = `<div class="bulk-result-error">${escHtml(String(msg))}</div>`;
      resultsEl.classList.remove('hidden');
      btn.disabled = false;
      btn.textContent = '⬆ Upload CSV';
      return;
    }

    let html = `<div class="bulk-result-summary">
      <div class="bulk-result-stat bulk-result-ok">✓ ${data.added} new record${data.added !== 1 ? 's' : ''} added</div>`;
    if (data.merged > 0) {
      html += `<div class="bulk-result-stat bulk-result-info">↗ ${data.merged} existing record${data.merged !== 1 ? 's' : ''} updated (merged sources/refs)</div>`;
    }
    if (data.warnings && data.warnings.length) {
      data.warnings.forEach(w => {
        html += `<div class="bulk-result-stat bulk-result-warn">⚠ ${escHtml(w)}</div>`;
      });
    }
    html += '</div>';

    // Row-level field corrections — imported successfully but some fields were cleared
    if (data.row_warnings && data.row_warnings.length) {
      html += `<div class="bulk-result-errors">
        <div class="bulk-result-errors-label bulk-result-warn-label">⚠ Field corrections applied to ${data.row_warnings.length} row${data.row_warnings.length !== 1 ? 's' : ''} — records were imported</div>
        <div class="bulk-result-errors-list">`;
      data.row_warnings.slice(0, 20).forEach(w => {
        html += `<div class="bulk-result-warn-row">${escHtml(w)}</div>`;
      });
      if (data.row_warnings.length > 20) {
        html += `<div class="bulk-result-warn-row" style="color:var(--citadel-muted);font-family:inherit">…and ${data.row_warnings.length - 20} more</div>`;
      }
      html += `</div></div>`;
    }

    // Truly skipped rows — not imported at all
    if (data.skipped && data.skipped.length) {
      html += `<div class="bulk-result-errors">
        <div class="bulk-result-errors-label">✗ Rows not imported (${data.skipped.length})</div>
        <div class="bulk-result-errors-list">`;
      data.skipped.slice(0, 20).forEach(e => {
        html += `<div class="bulk-result-error-row">${escHtml(e)}</div>`;
      });
      if (data.skipped.length > 20) {
        html += `<div class="bulk-result-error-row" style="color:var(--citadel-muted);font-family:inherit">…and ${data.skipped.length - 20} more</div>`;
      }
      html += `</div></div>`;
    }

    resultsEl.innerHTML = html;
    resultsEl.classList.remove('hidden');

    toast(`Bulk upload complete: ${data.added} added, ${data.merged} merged`, 'success');
    loadIocPage(_iocBulkType);

    btn.disabled = false;
    btn.textContent = 'Done';
    btn.onclick = closeBulkUploadModal;

  } catch(e) {
    resultsEl.innerHTML = `<div class="bulk-result-error">Network error: ${escHtml(e.message || String(e))}</div>`;
    resultsEl.classList.remove('hidden');
    btn.disabled = false;
    btn.textContent = '⬆ Upload CSV';
    toast('Upload failed: ' + (e.message || e), 'error');
  }
}

/* ── IOC Configuration ── */

let _iocConfigData = null;
let _iocSyncStatus = null;
let _iocPullInProgress = false;

const IOC_SOURCE_META = {
  feodo_tracker: { label: 'Feodo Tracker', desc: 'C2 IP blocklist (Emotet, QakBot, etc.) — no API key required', hasKey: false },
  urlhaus:        { label: 'URLhaus',        desc: 'Malicious URL feed — no API key required for CSV feed',         hasKey: false },
  malwarebazaar:  { label: 'MalwareBazaar',  desc: 'File hash feed — no API key required for CSV feed',             hasKey: false },
  openphish:      { label: 'OpenPhish',      desc: 'Phishing URL feed — no API key required',                       hasKey: false },
  threatfox:      { label: 'ThreatFox',      desc: 'Multi-type IOC feed — free API key required (threatfox.abuse.ch)', hasKey: true },
  otx:            { label: 'AlienVault OTX', desc: 'Open Threat Exchange — free API key required (otx.alienvault.com)', hasKey: true },
};

async function loadIocConfig() {
  try {
    const [cfg, status] = await Promise.all([
      API.get('/ioc-config/'),
      API.get('/ioc-config/status'),
    ]);
    _iocConfigData = cfg;
    _iocSyncStatus = status;
    renderIocConfig();
  } catch(e) {
    document.getElementById('ioc-config-content').innerHTML =
      `<div class="alert alert-error">Failed to load IOC configuration: ${escHtml(e.message)}</div>`;
  }
}

function _fmtRelTime(isoStr) {
  if (!isoStr) return null;
  try {
    const diff = Date.now() - new Date(isoStr).getTime();
    const abs = Math.abs(diff);
    const future = diff < 0;
    if (abs < 60000) return future ? 'in less than a minute' : 'just now';
    if (abs < 3600000) {
      const m = Math.round(abs / 60000);
      return future ? `in ${m}m` : `${m}m ago`;
    }
    if (abs < 86400000) {
      const h = Math.round(abs / 3600000);
      return future ? `in ${h}h` : `${h}h ago`;
    }
    const d = Math.round(abs / 86400000);
    return future ? `in ${d}d` : `${d}d ago`;
  } catch { return null; }
}

function renderIocConfig() {
  const cfg = _iocConfigData || {};
  const st  = _iocSyncStatus || {};
  const srcSt = st.sources || {};

  const lastRun  = st.last_run  ? _fmtRelTime(st.last_run)  : null;
  const nextRun  = st.next_run  ? _fmtRelTime(st.next_run)  : null;
  const lastFull = st.last_run  ? new Date(st.last_run).toLocaleString()  : '—';
  const nextFull = st.next_run  ? new Date(st.next_run).toLocaleString()  : '—';

  const statusBanner = `
    <div class="ioc-sync-banner">
      <div class="ioc-sync-meta">
        <div class="ioc-sync-stat">
          <span class="ioc-sync-label">Last Sync</span>
          <span class="ioc-sync-value" title="${escHtml(lastFull)}">${lastRun ? escHtml(lastRun) : 'Never'}</span>
        </div>
        <div class="ioc-sync-divider"></div>
        <div class="ioc-sync-stat">
          <span class="ioc-sync-label">Next Scheduled Sync</span>
          <span class="ioc-sync-value" title="${escHtml(nextFull)}">${nextRun ? escHtml(nextRun) : '—'}</span>
        </div>
      </div>
      <button id="ioc-pull-btn" class="btn btn-primary" onclick="triggerIocPull()">
        ⬇ Pull All Sources Now
      </button>
    </div>
  `;

  const sourceCards = Object.entries(IOC_SOURCE_META).map(([src, meta]) => {
    const srcCfg = cfg[src] || {};
    const ss = srcSt[src] || {};
    const skipped = ss.skipped;
    const hasRun = ss.last_run && !skipped;
    const errClass = ss.error ? 'ioc-src-error' : (hasRun ? 'ioc-src-ok' : '');
    const lastSyncStr = hasRun ? _fmtRelTime(ss.last_run) : null;
    const countStr = hasRun ? `${ss.count} IOC${ss.count !== 1 ? 's' : ''} collected` : '';

    return `
    <div class="card" style="margin-bottom:16px">
      <div class="card-header">
        <div>
          <div class="card-title">${escHtml(meta.label)}</div>
          <div class="card-subtitle">${escHtml(meta.desc)}</div>
        </div>
        <label class="toggle-label">
          <input type="checkbox" id="ioc-src-enabled-${src}" ${srcCfg.enabled ? 'checked' : ''}
            onchange="this.nextElementSibling.nextElementSibling.textContent=this.checked?'Enabled':'Disabled'">
          <span class="toggle-track"></span>
          <span style="margin-left:8px;font-size:0.85rem">${srcCfg.enabled ? 'Enabled' : 'Disabled'}</span>
        </label>
      </div>
      ${hasRun || ss.error ? `
      <div class="ioc-src-status ${errClass}">
        ${ss.error
          ? `<span>⚠ Last pull error: ${escHtml(ss.error)}</span>`
          : `<span>✓ Last pull: ${escHtml(lastSyncStr || '')} — ${escHtml(countStr)}</span>`}
      </div>` : (skipped ? `<div class="ioc-src-status">Skipped (disabled)</div>` : '')}
      ${meta.hasKey ? `
      <div class="form-group" style="margin-top:12px">
        <label class="form-label">API Key</label>
        <input id="ioc-src-key-${src}" type="password" class="form-control"
          style="font-family:monospace"
          value="${escHtml(srcCfg.api_key || '')}"
          placeholder="Paste your API key here">
      </div>` : ''}
    </div>`;
  }).join('');

  document.getElementById('ioc-config-content').innerHTML = statusBanner + sourceCards;
}

async function saveIocConfig() {
  const payload = {};
  for (const src of Object.keys(IOC_SOURCE_META)) {
    const enabledEl = document.getElementById(`ioc-src-enabled-${src}`);
    const keyEl = document.getElementById(`ioc-src-key-${src}`);
    payload[src] = {
      enabled: enabledEl ? enabledEl.checked : true,
      api_key: keyEl ? keyEl.value : '',
    };
  }
  try {
    await API.put('/ioc-config/', payload);
    toast('IOC configuration saved', 'success');
    _iocConfigData = payload;
  } catch(e) {
    toast('Save failed: ' + (e.message || e), 'error');
  }
}

async function triggerIocPull() {
  if (_iocPullInProgress) return;
  if (!confirm('Pull IOCs from all enabled sources now?\n\nThis may take up to a minute depending on which sources are enabled.')) return;

  _iocPullInProgress = true;
  const btn = document.getElementById('ioc-pull-btn');
  if (btn) { btn.disabled = true; btn.textContent = '⏳ Pulling…'; }

  try {
    const data = await API.post('/ioc-config/pull', {});
    toast(`Pull complete — ${data.total} IOC${data.total !== 1 ? 's' : ''} collected`, 'success');
    // Reload status and re-render
    _iocSyncStatus = await API.get('/ioc-config/status');
    renderIocConfig();
  } catch(e) {
    toast('Pull failed: ' + (e.message || e), 'error');
  } finally {
    _iocPullInProgress = false;
    const btn2 = document.getElementById('ioc-pull-btn');
    if (btn2) { btn2.disabled = false; btn2.textContent = '⬇ Pull All Sources Now'; }
  }
}

/* ══════════════════════════════════════════
   INIT
══════════════════════════════════════════ */
document.addEventListener('DOMContentLoaded', async () => {
  initTheme();
  await loadCurrentUser();
  ['interest-keywords','interest-tags','interest-email-recipients','interest-sms-numbers',
   'interest-topics','resource-tags','res-email-recipients','res-sms-numbers',
   'sr-tags','sr-email-recipients','sr-sms-numbers'].forEach(initTagsInput);
  navigate('dashboard');
});
