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
    !currentDocFile || !currentRefFile || !(n >= 2 && n <= 100) || isRunning;
}

function setHeader(text) {
  document.getElementById('progress-header').textContent = text;
  document.getElementById('progress-panel').classList.remove('hidden');
}

// ── Upload ────────────────────────────────────────────────────────────────────

async function uploadDocument(file) {
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
  if (!uploadRes.ok && uploadRes.status !== 204) throw new Error('Document upload failed');

  // The S3 key the experiment_starter will copy N times.
  // Note: this upload also fires pipeline_starter and runs one extra pipeline
  // pass (the "seed" run). That job has no experiment context and its output
  // is not included in the experiment results.
  return `uploads/${job_id}/${file.name}`;
}

// ── Experiment ────────────────────────────────────────────────────────────────

async function startExperiment(sourceDocumentKey, expectedN, goldText, config) {
  if (!await ensureValidToken()) throw new Error('auth');

  const experimentId = crypto.randomUUID();

  const res = await fetch(`${API_URL}/experiments`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({
      experiment_id: experimentId,
      expected_n: expectedN,
      source_document_key: sourceDocumentKey,
      gold_text: goldText,
      config,
    }),
  });
  if (res.status === 401) throw new Error('auth');
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(`experiments HTTP ${res.status}: ${detail.error || 'unknown error'}`);
  }

  return experimentId;
}

async function pollExperiment(experimentId, expectedN) {
  // 180 ticks × 10s = 30 minutes max (covers N pipeline runs + comparison SM)
  for (let tick = 0; tick < 180; tick++) {
    await new Promise(r => setTimeout(r, 10000));

    if (!await ensureValidToken()) throw new Error('auth');

    let res;
    try {
      res = await fetch(`${API_URL}/experiments/${experimentId}`, {
        headers: { 'Authorization': `Bearer ${idToken}` },
      });
    } catch { continue; }

    if (res.status === 401) throw new Error('auth');
    if (!res.ok) continue;

    const data = await res.json();
    const completedN = data.completed_n ?? 0;
    setHeader(`Runs complete: ${completedN} / ${expectedN} — comparing…`);

    if (data.status === 'COMPLETED') return data;
    if (data.status === 'COMPARISON_FAILED') {
      throw new Error(data.error_message || 'Comparison pipeline failed');
    }
  }
  throw new Error('Timed out after 30 minutes');
}

// ── Results display ───────────────────────────────────────────────────────────

function _scoreCellClass(val) {
  if (val >= 0.8) return 'high';
  if (val >= 0.6) return 'mid';
  return 'low';
}

function _fmt(n) {
  return typeof n === 'number' ? n.toFixed(3) : '—';
}

function showGoldPanel(goldResults, successfulN) {
  const panel = document.getElementById('comparison-panel');
  panel.classList.remove('hidden');

  document.getElementById('comparison-run-count').textContent =
    `${successfulN} run${successfulN !== 1 ? 's' : ''} scored`;

  const metricsEl = document.getElementById('comparison-metrics');
  metricsEl.innerHTML = '';

  const metrics = [
    { key: 'embedding_cosine', title: 'Titan Embedding Cosine vs Reference' },
    { key: 'bertscore_f1',     title: 'BERTScore F1 vs Reference (typical range ~0.84–0.97)' },
  ];

  for (const { key, title } of metrics) {
    const s = goldResults[key];
    if (!s) continue;
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

  const embData = goldResults.embedding_cosine;
  const bertData = goldResults.bertscore_f1;
  if (!embData || !bertData) return;

  const runNumbers = embData.run_numbers || embData.scores.map((_, i) => i + 1);
  const n = runNumbers.length;

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
    runTh.textContent = `R${String(runNumbers[i]).padStart(2, '0')}`;
    tr.appendChild(runTh);

    const embTd = document.createElement('td');
    embTd.className = _scoreCellClass(embData.scores[i]);
    embTd.textContent = embData.scores[i].toFixed(3);
    tr.appendChild(embTd);

    const bertTd = document.createElement('td');
    bertTd.className = _scoreCellClass(bertData.scores[i]);
    bertTd.textContent = bertData.scores[i].toFixed(3);
    tr.appendChild(bertTd);

    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
  tableEl.appendChild(table);
}

// ── Report builders ───────────────────────────────────────────────────────────

function buildTextReport(docName, timestamp, experimentResult) {
  const report = experimentResult.report || {};
  const gold = report.gold_results || {};
  const variance = report.variance_results || {};
  const f = v => (typeof v === 'number' ? v.toFixed(4) : '—');

  const lines = [
    'Gold Standard Accuracy Report',
    '==============================',
    `Document    : ${docName}`,
    `Experiment  : ${experimentResult.experiment_id}`,
    `Timestamp   : ${timestamp}`,
    `Runs scored : ${experimentResult.successful_n}`,
    `Doc type    : ${report.doc_type || 'unknown'}`,
    '',
  ];

  if (gold.embedding_cosine) {
    const e = gold.embedding_cosine;
    lines.push(
      '── Titan Embedding Cosine vs Reference ──',
      `  Mean: ${f(e.mean)}   Min: ${f(e.min)}   Max: ${f(e.max)}   Std: ${f(e.std)}`,
      '',
    );
  }

  if (gold.bertscore_f1) {
    const b = gold.bertscore_f1;
    lines.push(
      '── BERTScore F1 vs Reference (typical range ~0.84–0.97) ──',
      `  Mean: ${f(b.mean)}   Min: ${f(b.min)}   Max: ${f(b.max)}   Std: ${f(b.std)}`,
      '',
    );
  }

  if (variance.embedding_cosine) {
    const v = variance.embedding_cosine;
    lines.push(
      '── Inter-run Variance (Embedding Cosine) ──',
      `  Mean: ${f(v.mean)}   Std: ${f(v.std)}   Min: ${f(v.min)}   Max: ${f(v.max)}`,
      '',
    );
  }

  if (gold.embedding_cosine && gold.bertscore_f1) {
    const runNumbers = gold.embedding_cosine.run_numbers ||
      gold.embedding_cosine.scores.map((_, i) => i + 1);
    lines.push(
      '── Per-Run Scores ──',
      `${'Run'.padEnd(5)} ${'Emb Cosine'.padEnd(12)} ${'BERTScore F1'}`,
      `${'---'.padEnd(5)} ${'----------'.padEnd(12)} ${'------------'}`,
      ...gold.embedding_cosine.scores.map((emb, i) =>
        `R${String(runNumbers[i]).padStart(2, '0')}   ${emb.toFixed(4).padEnd(12)} ${gold.bertscore_f1.scores[i].toFixed(4)}`
      ),
      '',
    );
  }

  return lines.join('\n');
}

// ── Zip builder ───────────────────────────────────────────────────────────────

function formatTimestamp() {
  const d = new Date();
  const p = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}_${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`;
}

async function buildAndDownloadZip(docName, timestamp, experimentResult, referenceText) {
  const zip = new JSZip();
  const folder = zip.folder(`gold_${timestamp}`);

  folder.file('reference.txt', referenceText);
  folder.file('gold_report.txt', buildTextReport(docName, timestamp, experimentResult));

  if (experimentResult.report) {
    folder.file('comparison.json', JSON.stringify(experimentResult.report, null, 2));
  }

  if (experimentResult.narrative) {
    folder.file('narrative.md', experimentResult.narrative);
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

async function runGoldTest() {
  if (isRunning || !currentDocFile || !currentRefFile) return;

  const n = parseInt(document.getElementById('run-count').value, 10);
  if (!(n >= 2 && n <= 100)) return;

  let referenceText;
  try {
    referenceText = await currentRefFile.text();
  } catch (err) {
    setHeader(`Could not read reference file: ${err.message}`);
    return;
  }

  isRunning = true;
  document.getElementById('run-btn').disabled = true;
  document.getElementById('run-grid').innerHTML = '';

  const file = currentDocFile;
  const timestamp = formatTimestamp();

  try {
    setHeader('Uploading document…');
    const sourceDocumentKey = await uploadDocument(file);

    const modelInput = document.getElementById('model-input').value.trim();
    const temperatureInput = parseFloat(document.getElementById('temperature-input').value);
    const config = {};
    if (modelInput) config.extractor_model_id = modelInput;
    config.temperature = Number.isFinite(temperatureInput) ? temperatureInput : 0;

    setHeader(`Starting ${n} pipeline runs…`);
    const experimentId = await startExperiment(sourceDocumentKey, n, referenceText, config);

    setHeader(`Runs complete: 0 / ${n} — waiting…`);
    const experimentResult = await pollExperiment(experimentId, n);

    setHeader('Building download…');
    await buildAndDownloadZip(file.name, timestamp, experimentResult, referenceText);

    const successfulN = experimentResult.successful_n ?? n;
    const goldResults = experimentResult.report?.gold_results;
    if (goldResults) {
      showGoldPanel(goldResults, successfulN);
    }

    setHeader(`Done — gold_${timestamp}.zip downloaded (${successfulN} run${successfulN !== 1 ? 's' : ''} scored).`);
  } catch (err) {
    if (err.message === 'auth') {
      handleSessionExpired();
    } else {
      setHeader(`Error: ${err.message}`);
    }
  } finally {
    isRunning = false;
    setRunBtnEnabled();
  }
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
