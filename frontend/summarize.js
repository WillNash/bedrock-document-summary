/* global APP_CONFIG */
'use strict';

const cfg = window.APP_CONFIG || {};
const COGNITO_DOMAIN = cfg.cognitoHostedUiDomain || '';
const CLIENT_ID = cfg.cognitoClientId || '';
const API_URL = (cfg.apiUrl || '').replace(/\/$/, '');
const REDIRECT_URI = window.location.origin + '/';

let idToken = null;
let pollTimer = null;

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
  showError('Your session has expired. Please sign in again.');
  setTimeout(showAuth, 2000);
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
  document.getElementById('upload-section').classList.add('hidden');
}

function showUpload() {
  document.getElementById('auth-section').classList.add('hidden');
  document.getElementById('upload-section').classList.remove('hidden');
  resetUI();
}

function resetUI() {
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

// ── Upload and poll ───────────────────────────────────────────────────────────

async function handleFile(file) {
  if (!file) return;
  if (!await ensureValidToken()) return;

  showStatus('Requesting upload URL...');

  const presignRes = await fetch(`${API_URL}/presign`, {
    method: 'POST',
    headers: { 'Authorization': `Bearer ${idToken}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename: file.name }),
  });

  if (presignRes.status === 401) { handleSessionExpired(); return; }
  if (!presignRes.ok) {
    const data = await presignRes.json().catch(() => ({}));
    showError(data.error || 'Failed to get upload URL. Please try again.');
    return;
  }

  const { job_id, presign_url, presign_fields } = await presignRes.json();

  showStatus('Uploading document...');

  const formData = new FormData();
  for (const [k, v] of Object.entries(presign_fields)) formData.append(k, v);
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
  const STATUS_LABELS = {
    PENDING: 'Waiting to process...',
    RUNNING: 'Processing document...',
  };

  let tick = 0;
  pollTimer = setInterval(async () => {
    tick++;
    if (tick > 120) {
      showError('Processing timed out. Please try again.');
      return;
    }

    if (!await ensureValidToken()) return;

    let res;
    try {
      res = await fetch(`${API_URL}/jobs/${jobId}`, {
        headers: { 'Authorization': `Bearer ${idToken}` },
      });
    } catch { return; }

    if (res.status === 401) { handleSessionExpired(); return; }
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
      showStatus(STATUS_LABELS[data.status] || 'Processing...');
    }
  }, 5000);
}

// ── Init ──────────────────────────────────────────────────────────────────────

async function init() {
  const stored = localStorage.getItem('id_token');
  if (stored && !isTokenExpired(stored)) {
    idToken = stored;
    showUpload();
  } else if (await tryRefresh()) {
    showUpload();
  } else {
    clearTokens();
    showAuth();
  }
}

document.getElementById('signin-btn').addEventListener('click', startSignIn);
document.getElementById('signout-btn').addEventListener('click', signOut);
document.getElementById('new-upload-btn').addEventListener('click', resetUI);
document.getElementById('retry-btn').addEventListener('click', resetUI);

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
