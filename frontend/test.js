/* global APP_CONFIG, JSZip */
'use strict';

const cfg = window.APP_CONFIG || {};
const COGNITO_DOMAIN = cfg.cognitoHostedUiDomain || '';
const CLIENT_ID = cfg.cognitoClientId || '';
const API_URL = (cfg.apiUrl || '').replace(/\/$/, '');
// Always use the root as the redirect URI so Cognito callback URLs don't need updating for /test.html.
// startSignIn() stores auth_return in localStorage and app.js redirects back here after the callback.
const REDIRECT_URI = window.location.origin + '/';

let idToken = null;
let isRunning = false;
let currentFile = null;

// ── PKCE helpers ──────────────────────────────────────────────────────────────

function base64urlEncode(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function generatePKCE() {
  const verifier = base64urlEncode(crypto.getRandomValues(new Uint8Array(48)));
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return { verifier, challenge: base64urlEncode(digest) };
}

// ── Auth (shares localStorage tokens with the main app) ───────────────────────

function getTokenExpiry(token) {
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return payload.exp * 1000;
  } catch { return 0; }
}

function isTokenExpired(token) {
  return !token || Date.now() >= getTokenExpiry(token);
}

function storeTokens(tokens) {
  localStorage.setItem('id_token', tokens.id_token);
  localStorage.setItem('access_token', tokens.access_token);
  if (tokens.refresh_token) localStorage.setItem('refresh_token', tokens.refresh_token);
}

function clearTokens() {
  localStorage.removeItem('id_token');
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  sessionStorage.removeItem('pkce_verifier');
}

async function tryRefresh() {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) return false;
  try {
    const res = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: new URLSearchParams({
        grant_type: 'refresh_token',
        client_id: CLIENT_ID,
        refresh_token: refreshToken,
      }).toString(),
    });
    if (!res.ok) return false;
    const tokens = await res.json();
    storeTokens(tokens);
    idToken = tokens.id_token;
    return true;
  } catch { return false; }
}

async function ensureValidToken() {
  if (!isTokenExpired(idToken)) return true;
  if (await tryRefresh()) return true;
  handleSessionExpired();
  return false;
}

function handleSessionExpired() {
  clearTokens();
  idToken = null;
  showAuth();
}

async function startSignIn() {
  localStorage.setItem('auth_return', window.location.pathname);
  const { verifier, challenge } = await generatePKCE();
  sessionStorage.setItem('pkce_verifier', verifier);
  const params = new URLSearchParams({
    response_type: 'code',
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    scope: 'email openid profile',
    code_challenge: challenge,
    code_challenge_method: 'S256',
  });
  window.location.href = `${COGNITO_DOMAIN}/oauth2/authorize?${params}`;
}

function signOut() {
  clearTokens();
  window.location.href = `${COGNITO_DOMAIN}/logout?${new URLSearchParams({
    client_id: CLIENT_ID,
    logout_uri: REDIRECT_URI,
  })}`;
}

// ── UI ────────────────────────────────────────────────────────────────────────

function showAuth() {
  document.getElementById('auth-section').classList.remove('hidden');
  document.getElementById('test-section').classList.add('hidden');
}

function showTest() {
  document.getElementById('auth-section').classList.add('hidden');
  document.getElementById('test-section').classList.remove('hidden');
}

function setRunBtnEnabled() {
  const n = parseInt(document.getElementById('run-count').value, 10);
  document.getElementById('run-btn').disabled = !currentFile || !(n >= 1 && n <= 200) || isRunning;
}

function buildRunGrid(n) {
  const grid = document.getElementById('run-grid');
  grid.innerHTML = '';
  for (let i = 1; i <= n; i++) {
    const tile = document.createElement('div');
    tile.className = 'run-tile queued';
    tile.id = `run-tile-${i}`;
    tile.innerHTML = `<span class="run-num">Run ${i}</span><span class="run-status">queued</span>`;
    grid.appendChild(tile);
  }
  const log = document.getElementById('error-log');
  log.innerHTML = '';
  log.classList.add('hidden');
  document.getElementById('progress-panel').classList.remove('hidden');
}

function logRunError(num, message) {
  const log = document.getElementById('error-log');
  log.classList.remove('hidden');
  const entry = document.createElement('p');
  entry.className = 'run-error-entry';
  entry.textContent = `Run ${String(num).padStart(2, '0')} failed: ${message}`;
  log.appendChild(entry);
}

const STATUS_CLASS = {
  queued: 'queued', uploading: 'uploading',
  pending: 'pending', running: 'running', processing: 'processing',
  completed: 'done', done: 'done', failed: 'failed',
};

function updateRunTile(num, status) {
  const tile = document.getElementById(`run-tile-${num}`);
  if (!tile) return;
  const cls = STATUS_CLASS[status] || 'processing';
  tile.className = `run-tile ${cls}`;
  tile.querySelector('.run-status').textContent = cls;
}

function setHeader(text) {
  document.getElementById('progress-header').textContent = text;
}

// ── Job orchestration ─────────────────────────────────────────────────────────

async function submitJob(file, runNum) {
  updateRunTile(runNum, 'uploading');

  if (!await ensureValidToken()) throw new Error('auth');

  const presignRes = await fetch(`${API_URL}/presign`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name }),
  });
  if (presignRes.status === 401) throw new Error('auth');
  if (!presignRes.ok) {
    const detail = await presignRes.json().catch(() => ({}));
    throw new Error(`presign HTTP ${presignRes.status}: ${detail.error || 'unknown error'}`);
  }

  const { job_id, presign_url, presign_fields } = await presignRes.json();

  const formData = new FormData();
  for (const [k, v] of Object.entries(presign_fields)) formData.append(k, v);
  formData.append('file', file);

  const uploadRes = await fetch(presign_url, { method: 'POST', body: formData });
  if (!uploadRes.ok && uploadRes.status !== 204) throw new Error(`upload failed (run ${runNum})`);

  updateRunTile(runNum, 'pending');
  return job_id;
}

async function pollUntilDone(job_id, runNum) {
  for (let tick = 0; tick < 120; tick++) {
    await new Promise(r => setTimeout(r, 5000));

    if (!await ensureValidToken()) throw new Error('auth');

    let res;
    try {
      res = await fetch(`${API_URL}/jobs/${job_id}`, {
        headers: { 'Authorization': `Bearer ${idToken}` },
      });
    } catch { continue; }

    if (res.status === 401) throw new Error('auth');
    if (!res.ok) continue;

    const data = await res.json();

    if (data.status === 'COMPLETED') {
      if (!await ensureValidToken()) throw new Error('auth');
      const sumRes = await fetch(`${API_URL}/summaries/${job_id}`, {
        headers: { 'Authorization': `Bearer ${idToken}` },
      });
      if (!sumRes.ok) throw new Error(`summary unavailable (run ${runNum})`);
      const payload = await sumRes.json();
      return { summary: payload.summary, usage: payload.usage || {} };
    }

    if (data.status === 'FAILED') throw new Error(data.error_message || `pipeline failed (run ${runNum})`);

    updateRunTile(runNum, data.status.toLowerCase());
  }
  throw new Error(`timed out after 10 min (run ${runNum})`);
}

// ── Comparison ────────────────────────────────────────────────────────────────

async function runComparison(summaries) {
  if (!await ensureValidToken()) throw new Error('auth');
  const res = await fetch(`${API_URL}/compare`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ texts: summaries }),
  });
  if (res.status === 401) throw new Error('auth');
  if (!res.ok) throw new Error(`compare HTTP ${res.status}`);
  return res.json();
}

function _matrixCellClass(val, i, j) {
  if (i === j) return 'diag';
  if (val >= 0.9) return 'high';
  if (val >= 0.7) return 'mid';
  return 'low';
}

function _fmt(n) {
  return typeof n === 'number' ? n.toFixed(3) : '—';
}

function showComparisonPanel(comparison, succeededCount) {
  const panel = document.getElementById('comparison-panel');
  panel.classList.remove('hidden');

  document.getElementById('comparison-run-count').textContent =
    `${succeededCount} run${succeededCount !== 1 ? 's' : ''} compared`;

  const metricsEl = document.getElementById('comparison-metrics');
  metricsEl.innerHTML = '';

  const metrics = [
    { key: 'embedding_cosine', title: 'Titan Embedding Cosine' },
    { key: 'tfidf_cosine',     title: 'TF-IDF Cosine (baseline)' },
  ];

  for (const { key, title } of metrics) {
    const s = comparison[key];
    const card = document.createElement('div');
    card.className = 'metric-card';
    card.innerHTML = `
      <div class="metric-card-title">${title}</div>
      <div class="metric-row">
        <div class="metric-stat">
          <span class="metric-stat-label">Mean</span>
          <span class="metric-stat-value">${_fmt(s.mean)}</span>
        </div>
        <div class="metric-stat">
          <span class="metric-stat-label">Min</span>
          <span class="metric-stat-value">${_fmt(s.min)}</span>
        </div>
        <div class="metric-stat">
          <span class="metric-stat-label">Max</span>
          <span class="metric-stat-value">${_fmt(s.max)}</span>
        </div>
        <div class="metric-stat">
          <span class="metric-stat-label">Std</span>
          <span class="metric-stat-value">${_fmt(s.std)}</span>
        </div>
      </div>`;
    metricsEl.appendChild(card);
  }

  const matrixEl = document.getElementById('similarity-matrix');
  matrixEl.innerHTML = '';
  const matrix = comparison.embedding_cosine.matrix;
  const n = matrix.length;
  const table = document.createElement('table');
  table.className = 'sim-matrix';

  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  headerRow.appendChild(document.createElement('th'));
  for (let j = 0; j < n; j++) {
    const th = document.createElement('th');
    th.textContent = `R${String(j + 1).padStart(2, '0')}`;
    headerRow.appendChild(th);
  }
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (let i = 0; i < n; i++) {
    const tr = document.createElement('tr');
    const rowHead = document.createElement('th');
    rowHead.textContent = `R${String(i + 1).padStart(2, '0')}`;
    tr.appendChild(rowHead);
    for (let j = 0; j < n; j++) {
      const td = document.createElement('td');
      const val = matrix[i][j];
      td.className = _matrixCellClass(val, i, j);
      td.textContent = val.toFixed(3);
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  matrixEl.appendChild(table);
}

function buildComparisonReport(docName, timestamp, succeededCount, comparison) {
  const s = comparison.embedding_cosine;
  const t = comparison.tfidf_cosine;
  const cv = v => (v != null ? v.toFixed(4) : 'N/A');
  const f = v => (typeof v === 'number' ? v.toFixed(4) : '—');

  const matrix = comparison.embedding_cosine.matrix;
  const n = matrix.length;
  const colW = 7;
  const header = ['       '].concat(
    Array.from({ length: n }, (_, i) => `R${String(i + 1).padStart(2, '0')}`.padStart(colW))
  ).join('  ');

  const rows = matrix.map((row, i) => {
    const cells = row.map(v => v.toFixed(3).padStart(colW)).join('  ');
    return `R${String(i + 1).padStart(2, '0')}     ${cells}`;
  });

  return [
    'Consistency Comparison Report',
    '==============================',
    `Document : ${docName}`,
    `Timestamp: ${timestamp}`,
    `Runs     : ${succeededCount}`,
    '',
    '── Titan Embedding Cosine ──',
    `  Mean   : ${f(s.mean)}    Min : ${f(s.min)}    Max : ${f(s.max)}`,
    `  Std Dev: ${f(s.std)}    CV  : ${cv(s.cv)}`,
    '',
    '── TF-IDF Cosine (baseline) ──',
    `  Mean   : ${f(t.mean)}    Min : ${f(t.min)}    Max : ${f(t.max)}`,
    `  Std Dev: ${f(t.std)}    CV  : ${cv(t.cv)}`,
    '',
    '── Pairwise Matrix (Embedding Cosine) ──',
    header,
    ...rows,
    '',
  ].join('\n');
}

// ── Zip builder ───────────────────────────────────────────────────────────────

function buildUsageReport(docName, timestamp, results) {
  const pad = (s, n) => String(s).padStart(n);
  const fmt = n => String(n).replace(/\B(?=(\d{3})+(?!\d))/g, ',');

  const lines = [
    'Model & Token Usage Report',
    '==========================',
    `Document : ${docName}`,
    `Timestamp: ${timestamp}`,
    `Runs     : ${results.length}`,
    '',
    `${'Run'.padEnd(4)}  ${'Stage'.padEnd(11)}  ${'Model'.padEnd(50)}  ${'Input'.padStart(7)}  ${'Output'.padStart(7)}  ${'Total'.padStart(7)}`,
    `${'---'.padEnd(4)}  ${'----------'.padEnd(11)}  ${'--------------------------------------------------'.padEnd(50)}  ${'-------'.padStart(7)}  ${'-------'.padStart(7)}  ${'-------'.padStart(7)}`,
  ];

  const stageTotals = {};

  results.forEach((r, i) => {
    const num = String(i + 1).padStart(2, '0');
    if (!r.usage || Object.keys(r.usage).length === 0) {
      lines.push(`${num.padEnd(4)}  ${'(failed)'.padEnd(64)}  ${'—'.padStart(7)}  ${'—'.padStart(7)}  ${'—'.padStart(7)}`);
      return;
    }
    for (const [stage, s] of Object.entries(r.usage)) {
      const total = (s.input_tokens || 0) + (s.output_tokens || 0);
      lines.push(`${num.padEnd(4)}  ${stage.padEnd(11)}  ${(s.model || '').padEnd(50)}  ${pad(fmt(s.input_tokens || 0), 7)}  ${pad(fmt(s.output_tokens || 0), 7)}  ${pad(fmt(total), 7)}`);
      if (!stageTotals[stage]) stageTotals[stage] = { input: 0, output: 0 };
      stageTotals[stage].input += s.input_tokens || 0;
      stageTotals[stage].output += s.output_tokens || 0;
    }
  });

  lines.push('', 'Totals', '------');
  let grandInput = 0, grandOutput = 0;
  for (const [stage, t] of Object.entries(stageTotals)) {
    const total = t.input + t.output;
    lines.push(`${stage.padEnd(11)}  input ${fmt(t.input).padStart(8)}  output ${fmt(t.output).padStart(8)}  total ${fmt(total).padStart(8)}`);
    grandInput += t.input;
    grandOutput += t.output;
  }
  lines.push(`${'Grand total'.padEnd(11)}  input ${fmt(grandInput).padStart(8)}  output ${fmt(grandOutput).padStart(8)}  total ${fmt(grandInput + grandOutput).padStart(8)}`);

  return lines.join('\n');
}

async function buildAndDownloadZip(docName, timestamp, results, comparison) {
  const zip = new JSZip();
  const folder = zip.folder(`consistency_${timestamp}`);
  const succeeded = results.filter(r => r.summary !== null).length;

  const manifest = [
    'Consistency Test',
    `Document : ${docName}`,
    `Timestamp: ${timestamp}`,
    `Runs     : ${results.length}`,
    `Succeeded: ${succeeded}`,
    '',
  ];

  results.forEach((r, i) => {
    const num = String(i + 1).padStart(2, '0');
    if (r.summary !== null) {
      folder.file(`summary_${num}.txt`, r.summary);
      manifest.push(`Run ${num}: OK`);
    } else {
      manifest.push(`Run ${num}: FAILED — ${r.error || 'unknown'}`);
    }
  });

  folder.file('manifest.txt', manifest.join('\n'));
  folder.file('usage_report.txt', buildUsageReport(docName, timestamp, results));

  if (comparison) {
    folder.file('comparison.json', JSON.stringify(comparison, null, 2));
    folder.file('comparison_report.txt', buildComparisonReport(docName, timestamp, succeeded, comparison));
  }

  const blob = await zip.generateAsync({ type: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: `consistency_${timestamp}.zip` });
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

// ── Test runner ───────────────────────────────────────────────────────────────

function formatTimestamp() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

async function runConsistencyTest() {
  if (isRunning || !currentFile) return;

  const n = parseInt(document.getElementById('run-count').value, 10);
  if (!(n >= 1 && n <= 200)) return;

  isRunning = true;
  document.getElementById('run-btn').disabled = true;

  const file = currentFile;
  const timestamp = formatTimestamp();
  const results = Array.from({ length: n }, () => ({ summary: null, usage: null, error: null }));
  let doneCount = 0;

  buildRunGrid(n);
  setHeader(`Submitting ${n} upload${n > 1 ? 's' : ''}…`);

  // Stagger submissions by 200 ms to avoid concurrent writes to the same DynamoDB quota item.
  // Jobs still poll in parallel — the stagger only affects the presign step.
  let jobIds;
  try {
    jobIds = await Promise.all(
      results.map((r, i) =>
        new Promise(resolve => setTimeout(resolve, i * 200))
          .then(() => submitJob(file, i + 1))
          .catch(err => {
            if (err.message === 'auth') throw err;
            r.error = err.message;
            updateRunTile(i + 1, 'failed');
            logRunError(i + 1, err.message);
            return null;
          })
      )
    );
  } catch (err) {
    if (err.message === 'auth') handleSessionExpired();
    else setHeader(`Submission error: ${err.message}`);
    isRunning = false;
    setRunBtnEnabled();
    return;
  }

  setHeader(`Processing — 0 / ${n} complete`);

  // Poll all submitted jobs in parallel
  await Promise.all(
    jobIds.map((job_id, i) => {
      if (!job_id) return Promise.resolve();
      return pollUntilDone(job_id, i + 1)
        .then(({ summary, usage }) => {
          results[i].summary = summary;
          results[i].usage = usage;
          updateRunTile(i + 1, 'done');
          doneCount++;
          setHeader(`Processing — ${doneCount} / ${n} complete`);
        })
        .catch(err => {
          if (err.message !== 'auth') {
            results[i].error = err.message;
            updateRunTile(i + 1, 'failed');
            logRunError(i + 1, err.message);
          }
        });
    })
  );

  const succeeded = results.filter(r => r.summary !== null).length;
  if (succeeded === 0) {
    setHeader('All runs failed — nothing to download.');
    isRunning = false;
    setRunBtnEnabled();
    return;
  }

  // Run comparison if at least 2 summaries succeeded
  let comparison = null;
  if (succeeded >= 2) {
    setHeader(`Complete — ${succeeded}/${n} succeeded. Comparing summaries…`);
    const summaries = results.filter(r => r.summary !== null).map(r => r.summary);
    try {
      comparison = await runComparison(summaries);
    } catch (err) {
      if (err.message === 'auth') { handleSessionExpired(); return; }
      // comparison failed — continue with zip download, just omit comparison files
    }
  }

  setHeader(`Building zip…`);
  await buildAndDownloadZip(file.name, timestamp, results, comparison);

  if (comparison) {
    showComparisonPanel(comparison, succeeded);
    setHeader(`Done — consistency_${timestamp}.zip downloaded (${succeeded} summar${succeeded !== 1 ? 'ies' : 'y'} + comparison).`);
  } else {
    setHeader(`Done — consistency_${timestamp}.zip downloaded (${succeeded} summary file${succeeded !== 1 ? 's' : ''}).`);
  }

  isRunning = false;
  setRunBtnEnabled();
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const stored = localStorage.getItem('id_token');
  if (stored && !isTokenExpired(stored)) {
    idToken = stored;
    showTest();
  } else if (await tryRefresh()) {
    showTest();
  } else {
    clearTokens();
    showAuth();
  }
}

document.getElementById('signin-btn').addEventListener('click', startSignIn);
document.getElementById('signout-btn').addEventListener('click', signOut);
document.getElementById('run-count').addEventListener('input', setRunBtnEnabled);
document.getElementById('run-btn').addEventListener('click', runConsistencyTest);
document.getElementById('file-input').addEventListener('change', e => {
  currentFile = e.target.files[0] || null;
  document.getElementById('file-name').textContent = currentFile ? currentFile.name : 'No file selected';
  setRunBtnEnabled();
});

init().catch(console.error);
