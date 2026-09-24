/* global APP_CONFIG, JSZip */
'use strict';

// ── Embedded schemas and prompts ──────────────────────────────────────────────

const DOC_TYPES = {
  lab_result: {
    prompt: `You are a clinical data extraction assistant specializing in laboratory results. Your task is to extract all relevant information from the provided lab result document and populate the provided tool schema precisely.

Guidelines:
- Extract values exactly as they appear in the document. Do not interpret, normalize, or convert values.
- Use null for any field that is genuinely absent from the document. Do not invent or infer missing values.
- For test results, capture all panels and individual results present in the document.
- Preserve the original units as written (e.g., "mg/dL", "mmol/L", "g/dL").
- For reference ranges, extract the full range string as written (e.g., "3.5-5.0", ">60").
- For flags, use the flag annotation from the document (e.g., "H", "L", "HIGH", "LOW", "CRITICAL", or null if not flagged).
- The interpretation field should capture the overall lab interpretation or pathologist comment if present.
- Do not include information that is not present in the source document.`,
    schema: `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "LabResult",
  "type": "object",
  "required": ["patient_id", "test_date", "ordering_provider", "test_panels"],
  "properties": {
    "patient_id": { "type": "string" },
    "test_date": { "type": "string", "format": "date" },
    "ordering_provider": { "type": "string" },
    "test_panels": {
      "type": "array",
      "minItems": 1,
      "items": {
        "type": "object",
        "required": ["panel_name", "results"],
        "properties": {
          "panel_name": { "type": "string" },
          "results": {
            "type": "array",
            "minItems": 1,
            "items": {
              "type": "object",
              "required": ["name", "value", "unit"],
              "properties": {
                "name": { "type": "string" },
                "value": { "type": "string" },
                "unit": { "type": ["string", "null"] },
                "reference_range": { "type": ["string", "null"] },
                "flag": { "type": ["string", "null"] }
              }
            }
          }
        }
      }
    },
    "interpretation": { "type": ["string", "null"] },
    "notes": { "type": ["string", "null"] }
  },
  "additionalProperties": false
}`,
  },
  doctors_notes: {
    prompt: `You are a clinical data extraction assistant specializing in physician notes. Your task is to extract all relevant information from the provided clinical note and populate the provided tool schema precisely.

Guidelines:
- Extract information as it appears in the source document. Do not paraphrase or interpret beyond what is written.
- Use null for any field genuinely absent from the note. Do not infer or fabricate missing clinical information.
- chief_complaint: the patient's primary reason for the visit, in their words or as documented.
- history_of_present_illness: the narrative description of the current illness or complaint.
- physical_exam_findings: objective findings from the physical examination.
- assessment: the clinician's diagnostic impressions or diagnoses.
- plan: the treatment plan, including orders, referrals, and instructions.
- medications_changed: only medications explicitly added, changed, or discontinued during this visit. Use null if no changes were made.
- follow_up: the documented follow-up instructions or return visit timeline. Use null if not specified.
- Do not include information not present in the source document.`,
    schema: `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "DoctorsNotes",
  "type": "object",
  "required": ["patient_id", "visit_date", "provider", "chief_complaint", "history_of_present_illness", "physical_exam_findings", "assessment", "plan"],
  "properties": {
    "patient_id": { "type": "string" },
    "visit_date": { "type": "string", "format": "date" },
    "provider": { "type": "string" },
    "chief_complaint": { "type": "string" },
    "history_of_present_illness": { "type": "string" },
    "physical_exam_findings": { "type": "string" },
    "assessment": { "type": "string" },
    "plan": { "type": "string" },
    "medications_changed": { "type": ["array", "null"], "items": { "type": "string" } },
    "follow_up": { "type": ["string", "null"] }
  },
  "additionalProperties": false
}`,
  },
  injury_doc: {
    prompt: `You are a clinical data extraction assistant specializing in injury documentation. Your task is to extract all relevant information from the provided injury document and populate the provided tool schema precisely.

Guidelines:
- Extract information as it appears in the source document. Do not interpret or embellish.
- Use null for any field genuinely absent from the document.
- incident_date: the date the injury occurred, in ISO 8601 format (YYYY-MM-DD) if determinable, otherwise as written.
- body_regions_affected: list all anatomical regions mentioned as injured or affected.
- mechanism_of_injury: how the injury occurred (e.g., "fall from height", "motor vehicle accident", "repetitive strain").
- severity: must be exactly one of: "minor", "moderate", or "severe". Infer from clinical language if not explicitly stated.
- imaging_findings: any radiological or imaging results described. Use null if no imaging was performed or documented.
- treatment_plan: the documented treatment approach, interventions, or management plan.
- work_status: any documentation of the patient's work capacity or restrictions. Use null if not addressed.
- Do not include information not present in the source document.`,
    schema: `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "InjuryDoc",
  "type": "object",
  "required": ["patient_id", "incident_date", "body_regions_affected", "mechanism_of_injury", "severity", "treatment_plan"],
  "properties": {
    "patient_id": { "type": "string" },
    "incident_date": { "type": "string", "format": "date" },
    "body_regions_affected": { "type": "array", "items": { "type": "string" }, "minItems": 1 },
    "mechanism_of_injury": { "type": "string" },
    "severity": { "type": "string", "enum": ["minor", "moderate", "severe"] },
    "imaging_findings": { "type": ["string", "null"] },
    "treatment_plan": { "type": "string" },
    "work_status": { "type": ["string", "null"] },
    "notes": { "type": ["string", "null"] }
  },
  "additionalProperties": false
}`,
  },
  visit_assessment: {
    prompt: `You are a clinical data extraction assistant specializing in visit assessments and therapy notes. Your task is to extract all relevant information from the provided assessment document and populate the provided tool schema precisely.

Guidelines:
- Extract information as it appears in the source document. Do not interpret or add clinical judgment.
- Use null for any field genuinely absent from the document.
- visit_type: classify as one of "initial", "follow_up", "discharge", or "telehealth". Infer from context if not explicitly stated.
- functional_status: the patient's documented functional abilities, limitations, or activity level.
- pain_score: the numeric pain rating (0-10) if documented. Use null if no pain score is recorded.
- goals_progress: the documented progress toward established treatment goals.
- barriers: any documented barriers to recovery, treatment compliance, or goal achievement. Use null if none documented.
- plan_updates: any modifications to the treatment plan, goals, or next steps documented in this visit.
- Do not include information not present in the source document.`,
    schema: `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "VisitAssessment",
  "type": "object",
  "required": ["patient_id", "visit_date", "visit_type", "functional_status", "goals_progress", "plan_updates"],
  "properties": {
    "patient_id": { "type": "string" },
    "visit_date": { "type": "string", "format": "date" },
    "visit_type": { "type": "string", "enum": ["initial", "follow_up", "discharge", "telehealth"] },
    "functional_status": { "type": "string" },
    "pain_score": { "type": ["integer", "null"], "minimum": 0, "maximum": 10 },
    "goals_progress": { "type": "string" },
    "barriers": { "type": ["string", "null"] },
    "plan_updates": { "type": "string" }
  },
  "additionalProperties": false
}`,
  },
  psych_eval: {
    prompt: `You are a clinical data extraction assistant specializing in psychiatric and psychological evaluations. Your task is to extract information from the provided evaluation document and populate the provided tool schema.

Guidelines:
- Extract structured fields (patient_id, eval_date, evaluator) exactly as they appear.
- Use null for structured fields genuinely absent from the document.
- For narrative fields (mental_status_summary, diagnostic_impressions, recommendations), synthesize the relevant content from the document into coherent clinical prose. These fields should read as professional clinical narrative, not bullet points.
- presenting_concerns: a concise clinical statement of the primary reasons for the evaluation.
- mental_status_summary: a synthesized narrative of the mental status examination findings, including affect, mood, thought process, insight, and judgment as documented.
- diagnostic_impressions: the evaluator's diagnostic conclusions or differential diagnoses, in clinical language.
- risk_assessment: the documented assessment of suicidal ideation, homicidal ideation, self-harm risk, or any safety concerns. If explicitly documented as absent, state that clearly. Use null only if the evaluation contains no risk assessment section at all.
- recommendations: the evaluator's recommendations for treatment, follow-up, referrals, or further assessment, synthesized as clinical prose.
- Preserve clinical accuracy and professional tone throughout all narrative fields.`,
    schema: `{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "PsychEval",
  "type": "object",
  "required": ["patient_id", "eval_date", "evaluator", "presenting_concerns", "mental_status_summary", "diagnostic_impressions", "risk_assessment", "recommendations"],
  "properties": {
    "patient_id": { "type": "string" },
    "eval_date": { "type": "string", "format": "date" },
    "evaluator": { "type": "string" },
    "presenting_concerns": { "type": "string" },
    "mental_status_summary": { "type": "string" },
    "diagnostic_impressions": { "type": "string" },
    "risk_assessment": { "type": ["string", "null"] },
    "recommendations": { "type": "string" }
  },
  "additionalProperties": false
}`,
  },
};

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

    const docTypeVal = document.getElementById('doc-type-select').value;
    if (docTypeVal) {
      config.doc_type = docTypeVal;
      const promptText = document.getElementById('prompt-textarea').value.trim();
      if (promptText) config.custom_prompt = promptText;
      if (document.getElementById('no-schema-checkbox').checked) {
        config.custom_schema = '';
      } else {
        const schemaText = document.getElementById('schema-textarea').value.trim();
        if (schemaText) config.custom_schema = schemaText;
      }
    }

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

// ── Doc type / custom extraction controls ─────────────────────────────────────

function onDocTypeChange() {
  const val = document.getElementById('doc-type-select').value;
  const section = document.getElementById('custom-extraction-section');
  if (!val) {
    section.classList.add('hidden');
    return;
  }
  section.classList.remove('hidden');
  const dt = DOC_TYPES[val];
  if (dt) {
    document.getElementById('prompt-textarea').value = dt.prompt;
    document.getElementById('schema-textarea').value = dt.schema;
    document.getElementById('no-schema-checkbox').checked = false;
    document.getElementById('schema-textarea').disabled = false;
  }
}

function onNoSchemaChange() {
  const noSchema = document.getElementById('no-schema-checkbox').checked;
  const schemaArea = document.getElementById('schema-textarea');
  schemaArea.disabled = noSchema;
  if (noSchema) schemaArea.value = '';
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
document.getElementById('doc-type-select').addEventListener('change', onDocTypeChange);
document.getElementById('no-schema-checkbox').addEventListener('change', onNoSchemaChange);
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
