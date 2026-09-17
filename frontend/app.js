/* global APP_CONFIG */
'use strict';

// APP_CONFIG is injected by deploy_frontend.sh into config.js:
// window.APP_CONFIG = { cognitoUserPoolId, cognitoClientId, cognitoHostedUiDomain, apiUrl }

const cfg = window.APP_CONFIG || {};
const COGNITO_DOMAIN = cfg.cognitoHostedUiDomain || '';
const CLIENT_ID = cfg.cognitoClientId || '';
const API_URL = (cfg.apiUrl || '').replace(/\/$/, '');
const REDIRECT_URI = window.location.origin + window.location.pathname;

let pollTimer = null;
let idToken = null;

// ── PKCE helpers ─────────────────────────────────────────────────────────────

function base64urlEncode(buf) {
  return btoa(String.fromCharCode(...new Uint8Array(buf)))
    .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function generatePKCE() {
  const verifier = base64urlEncode(crypto.getRandomValues(new Uint8Array(48)));
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  const challenge = base64urlEncode(digest);
  return { verifier, challenge };
}

// ── Auth ─────────────────────────────────────────────────────────────────────

function getStoredToken() {
  return sessionStorage.getItem('id_token');
}

function storeTokens(tokens) {
  sessionStorage.setItem('id_token', tokens.id_token);
  sessionStorage.setItem('access_token', tokens.access_token);
}

function clearTokens() {
  sessionStorage.removeItem('id_token');
  sessionStorage.removeItem('access_token');
  sessionStorage.removeItem('pkce_verifier');
}

async function startSignIn() {
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

async function handleCallback(code) {
  const verifier = sessionStorage.getItem('pkce_verifier');
  if (!verifier) { showAuth(); return; }

  const body = new URLSearchParams({
    grant_type: 'authorization_code',
    client_id: CLIENT_ID,
    redirect_uri: REDIRECT_URI,
    code,
    code_verifier: verifier,
  });

  const res = await fetch(`${COGNITO_DOMAIN}/oauth2/token`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body.toString(),
  });

  if (!res.ok) { showAuth(); return; }

  const tokens = await res.json();
  storeTokens(tokens);
  idToken = tokens.id_token;

  // Clean code from URL
  window.history.replaceState({}, '', window.location.pathname);
  showUpload();
}

function signOut() {
  clearTokens();
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    logout_uri: window.location.origin + window.location.pathname,
  });
  window.location.href = `${COGNITO_DOMAIN}/logout?${params}`;
}

// ── UI state ─────────────────────────────────────────────────────────────────

function showAuth() {
  document.getElementById('auth-section').classList.remove('hidden');
  document.getElementById('upload-section').classList.add('hidden');
}

function showUpload() {
  document.getElementById('auth-section').classList.add('hidden');
  document.getElementById('upload-section').classList.remove('hidden');
  resetUploadUI();
}

function resetUploadUI() {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  document.getElementById('drop-zone').classList.remove('hidden');
  document.getElementById('status-section').classList.add('hidden');
  document.getElementById('summary-section').classList.add('hidden');
  document.getElementById('error-section').classList.add('hidden');
  document.getElementById('file-input').value = '';
}

function showStatus(text) {
  document.getElementById('drop-zone').classList.add('hidden');
  document.getElementById('status-section').classList.remove('hidden');
  document.getElementById('status-text').textContent = text;
  document.getElementById('summary-section').classList.add('hidden');
  document.getElementById('error-section').classList.add('hidden');
}

function showSummary(text) {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  document.getElementById('status-section').classList.add('hidden');
  document.getElementById('summary-section').classList.remove('hidden');
  document.getElementById('summary-content').textContent = text;
}

function showError(message) {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  document.getElementById('status-section').classList.add('hidden');
  document.getElementById('error-section').classList.remove('hidden');
  document.getElementById('error-message').textContent = message || 'An unexpected error occurred.';
}

// ── Upload flow ───────────────────────────────────────────────────────────────

async function handleFile(file) {
  if (!file) return;

  showStatus('Requesting upload URL...');

  const presignRes = await fetch(`${API_URL}/presign`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${idToken}`,
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({ filename: file.name }),
  });

  if (!presignRes.ok) {
    showError('Failed to get upload URL. Please try again.');
    return;
  }

  const { job_id, presign_url, presign_fields } = await presignRes.json();

  showStatus('Uploading document...');

  // S3 presigned POST: fields first, file MUST be appended last
  const formData = new FormData();
  for (const [k, v] of Object.entries(presign_fields)) {
    formData.append(k, v);
  }
  formData.append('file', file);

  const uploadRes = await fetch(presign_url, { method: 'POST', body: formData });
  if (!uploadRes.ok && uploadRes.status !== 204) {
    showError('Upload failed. Please try again.');
    return;
  }

  showStatus('Classifying document...');
  startPolling(job_id);
}

function startPolling(jobId) {
  const POLL_INTERVAL_MS = 5000;
  const STATUS_LABELS = {
    PENDING:  'Waiting to process...',
    RUNNING:  'Processing document...',
    FAILED:   null,
    COMPLETED: null,
  };

  pollTimer = setInterval(async () => {
    const res = await fetch(`${API_URL}/jobs/${jobId}`, {
      headers: { 'Authorization': `Bearer ${idToken}` },
    });

    if (!res.ok) return;

    const data = await res.json();

    if (data.status === 'COMPLETED') {
      showStatus('Loading summary...');
      const sumRes = await fetch(`${API_URL}/summaries/${jobId}`, {
        headers: { 'Authorization': `Bearer ${idToken}` },
      });
      if (sumRes.ok) {
        const sumData = await sumRes.json();
        showSummary(sumData.summary);
      } else {
        showError('Summary is ready but could not be retrieved. Refresh and try again.');
      }
    } else if (data.status === 'FAILED') {
      showError(data.error_message || 'Processing failed. Please try again.');
    } else {
      const label = STATUS_LABELS[data.status] || 'Processing...';
      showStatus(label);
    }
  }, POLL_INTERVAL_MS);
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');

  if (code) {
    await handleCallback(code);
    return;
  }

  const stored = getStoredToken();
  if (stored) {
    idToken = stored;
    showUpload();
  } else {
    showAuth();
  }
}

// ── Event listeners ───────────────────────────────────────────────────────────

document.getElementById('signin-btn').addEventListener('click', startSignIn);
document.getElementById('signout-btn').addEventListener('click', signOut);
document.getElementById('new-upload-btn').addEventListener('click', resetUploadUI);
document.getElementById('retry-btn').addEventListener('click', resetUploadUI);

document.getElementById('file-input').addEventListener('change', e => {
  handleFile(e.target.files[0]);
});

const dropZone = document.getElementById('drop-zone');
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('active'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('active'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('active');
  handleFile(e.dataTransfer.files[0]);
});

init().catch(console.error);
