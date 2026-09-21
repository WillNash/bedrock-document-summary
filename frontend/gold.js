/* global APP_CONFIG, JSZip */
'use strict';

const cfg = window.APP_CONFIG || {};
const COGNITO_DOMAIN = cfg.cognitoHostedUiDomain || '';
const CLIENT_ID = cfg.cognitoClientId || '';
const API_URL = (cfg.apiUrl || '').replace(/\/$/, '');
const REDIRECT_URI = window.location.origin + '/';

let idToken = null;
let isRunning = false;
let currentDocFile = null;
let currentRefFile = null;

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

// ── Auth ──────────────────────────────────────────────────────────────────────

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

function showGold() {
  document.getElementById('auth-section').classList.add('hidden');
  document.getElementById('test-section').classList.remove('hidden');
}

function setRunBtnEnabled() {
  const n = parseInt(document.getElementById('run-count').value, 10);
  document.getElementById('run-btn').disabled =
    !currentDocFile || !currentRefFile || !(n >= 1 && n <= 200) || isRunning;
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

// ── Gold comparison ───────────────────────────────────────────────────────────

async function runGoldComparison(summaries, referenceText) {
  if (!await ensureValidToken()) throw new Error('auth');
  const res = await fetch(`${API_URL}/gold-compare`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ texts: summaries, reference: referenceText }),
  });
  if (res.status === 401) throw new Error('auth');
  if (!res.ok) throw new Error(`gold-compare HTTP ${res.status}`);
  return res.json();
}

function _scoreCellClass(val) {
  if (val >= 0.8) return 'high';
  if (val >= 0.6) return 'mid';
  return 'low';
}

function _fmt(n) {
  return typeof n === 'number' ? n.toFixed(3) : '—';
}

function showGoldPanel(comparison, succeededCount) {
  const panel = document.getElementById('comparison-panel');
  panel.classList.remove('hidden');

  document.getElementById('comparison-run-count').textContent =
    `${succeededCount} run${succeededCount !== 1 ? 's' : ''} scored`;

  const metricsEl = document.getElementById('comparison-metrics');
  metricsEl.innerHTML = '';

  const metrics = [
    { key: 'embedding_cosine', title: 'Titan Embedding Cosine vs Reference' },
    { key: 'bertscore_f1',     title: 'BERTScore F1 vs Reference (typical range ~0.84–0.97)' },
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

  const tableEl = document.getElementById('score-table');
  tableEl.innerHTML = '';

  const embScores = comparison.embedding_cosine.scores;
  const bertScores = comparison.bertscore_f1.scores;
  const n = embScores.length;

  const table = document.createElement('table');
  table.className = 'sim-matrix';

  const thead = document.createElement('thead');
  const headerRow = document.createElement('tr');
  ['Run', 'Emb Cosine', 'BERTScore F1'].forEach(text => {
    const th = document.createElement('th');
    th.textContent = text;
    headerRow.appendChild(th);
  });
  thead.appendChild(headerRow);
  table.appendChild(thead);

  const tbody = document.createElement('tbody');
  for (let i = 0; i < n; i++) {
    const tr = document.createElement('tr');

    const runTh = document.createElement('th');
    runTh.textContent = `R${String(i + 1).padStart(2, '0')}`;
    tr.appendChild(runTh);

    const embTd = document.createElement('td');
    embTd.className = _scoreCellClass(embScores[i]);
    embTd.textContent = embScores[i].toFixed(3);
    tr.appendChild(embTd);

    const bertTd = document.createElement('td');
    bertTd.className = _scoreCellClass(bertScores[i]);
    bertTd.textContent = bertScores[i].toFixed(3);
    tr.appendChild(bertTd);

    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableEl.appendChild(table);
}

// ── Report builders ───────────────────────────────────────────────────────────

function buildGoldReport(docName, timestamp, succeededCount, comparison, referenceText) {
  const e = comparison.embedding_cosine;
  const r = comparison.bertscore_f1;
  const f = v => (typeof v === 'number' ? v.toFixed(4) : '—');

  const refPreview = referenceText.length > 80
    ? referenceText.slice(0, 80) + '...'
    : referenceText;

  const header = [
    'Gold Standard Accuracy Report',
    '==============================',
    `Document : ${docName}`,
    `Reference: ${refPreview}`,
    `Timestamp: ${timestamp}`,
    `Runs     : ${succeededCount}`,
    '',
    '── Titan Embedding Cosine vs Reference ──',
    `  Mean   : ${f(e.mean)}    Min : ${f(e.min)}    Max : ${f(e.max)}`,
    `  Std Dev: ${f(e.std)}`,
    '',
    '── BERTScore F1 vs Reference (typical range ~0.84–0.97) ──',
    `  Mean   : ${f(r.mean)}    Min : ${f(r.min)}    Max : ${f(r.max)}`,
    `  Std Dev: ${f(r.std)}`,
    '',
    '── Per-Run Scores ──',
    `${'Run'.padEnd(5)} ${'Emb Cosine'.padEnd(12)} ${'BERTScore F1'}`,
    `${'---'.padEnd(5)} ${'----------'.padEnd(12)} ${'------------'}`,
  ];

  const embScores = comparison.embedding_cosine.scores;
  const bertScores = comparison.bertscore_f1.scores;
  const rows = embScores.map((emb, i) =>
    `R${String(i + 1).padStart(2, '0')}   ${emb.toFixed(4).padEnd(12)} ${bertScores[i].toFixed(4)}`
  );

  return [...header, ...rows, ''].join('\n');
}

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

// ── Zip builder ───────────────────────────────────────────────────────────────

async function buildAndDownloadZip(docName, timestamp, results, comparison, referenceText) {
  const zip = new JSZip();
  const folder = zip.folder(`gold_${timestamp}`);
  const succeeded = results.filter(r => r.summary !== null).length;

  const manifest = [
    'Gold Standard Test',
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
  folder.file('reference.txt', referenceText);

  if (comparison) {
    folder.file('gold_comparison.json', JSON.stringify(comparison, null, 2));
    folder.file('gold_comparison_report.txt', buildGoldReport(docName, timestamp, succeeded, comparison, referenceText));
  }

  const blob = await zip.generateAsync({ type: 'blob' });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement('a'), { href: url, download: `gold_${timestamp}.zip` });
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

async function runGoldTest() {
  if (isRunning || !currentDocFile || !currentRefFile) return;

  const n = parseInt(document.getElementById('run-count').value, 10);
  if (!(n >= 1 && n <= 200)) return;

  let referenceText;
  try {
    referenceText = await currentRefFile.text();
  } catch (err) {
    setHeader(`Could not read reference file: ${err.message}`);
    return;
  }

  isRunning = true;
  document.getElementById('run-btn').disabled = true;

  const file = currentDocFile;
  const timestamp = formatTimestamp();
  const results = Array.from({ length: n }, () => ({ summary: null, usage: null, error: null }));
  let doneCount = 0;

  buildRunGrid(n);
  setHeader(`Submitting ${n} upload${n > 1 ? 's' : ''}…`);

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

  let comparison = null;
  let scoringError = null;
  if (succeeded >= 1) {
    setHeader(`Complete — ${succeeded}/${n} succeeded. Scoring against reference…`);
    const summaries = results.filter(r => r.summary !== null).map(r => r.summary);
    try {
      comparison = await runGoldComparison(summaries, referenceText);
    } catch (err) {
      if (err.message === 'auth') { handleSessionExpired(); return; }
      scoringError = err.message;
      console.error('gold-compare failed:', err.message);
    }
  }

  setHeader('Building zip…');
  await buildAndDownloadZip(file.name, timestamp, results, comparison, referenceText);

  if (comparison) {
    showGoldPanel(comparison, succeeded);
    setHeader(`Done — gold_${timestamp}.zip downloaded (${succeeded} summar${succeeded !== 1 ? 'ies' : 'y'} + accuracy scores).`);
  } else {
    const errSuffix = scoringError ? ` Scoring error: ${scoringError}.` : '';
    setHeader(`Done — gold_${timestamp}.zip downloaded (${succeeded} summary file${succeeded !== 1 ? 's' : ''}, no accuracy metrics).${errSuffix}`);
  }

  isRunning = false;
  setRunBtnEnabled();
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const stored = localStorage.getItem('id_token');
  if (stored && !isTokenExpired(stored)) {
    idToken = stored;
    showGold();
  } else if (await tryRefresh()) {
    showGold();
  } else {
    clearTokens();
    showAuth();
  }
}

document.getElementById('signin-btn').addEventListener('click', startSignIn);
document.getElementById('signout-btn').addEventListener('click', signOut);
document.getElementById('run-count').addEventListener('input', setRunBtnEnabled);
document.getElementById('run-btn').addEventListener('click', runGoldTest);
document.getElementById('file-input').addEventListener('change', e => {
  currentDocFile = e.target.files[0] || null;
  document.getElementById('file-name').textContent = currentDocFile ? currentDocFile.name : 'No file selected';
  setRunBtnEnabled();
});
document.getElementById('ref-input').addEventListener('change', e => {
  currentRefFile = e.target.files[0] || null;
  document.getElementById('ref-name').textContent = currentRefFile ? currentRefFile.name : 'No reference selected';
  setRunBtnEnabled();
});

init().catch(console.error);
