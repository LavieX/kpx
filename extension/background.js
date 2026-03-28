const API_BASE = "http://127.0.0.1:19455";
const HEALTH_INTERVAL_MS = 30_000;

let serverOnline = false;
let healthTimer = null;

// --- Storage helpers ---

async function getToken() {
  const { kpxToken } = await chrome.storage.local.get("kpxToken");
  return kpxToken ?? null;
}

async function setToken(token) {
  await chrome.storage.local.set({ kpxToken: token });
}

// --- HTTP helpers ---

async function apiFetch(path, options = {}) {
  const token = await getToken();
  const headers = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;

  const url = path.startsWith("http") ? path : `${API_BASE}${path}`;
  const resp = await fetch(url, { ...options, headers: { ...headers, ...options.headers } });

  if (!resp.ok) {
    const text = await resp.text().catch(() => "");
    throw new Error(`HTTP ${resp.status}: ${text || resp.statusText}`);
  }
  return resp.json();
}

// --- Health check ---

async function checkHealth() {
  try {
    await fetch(`${API_BASE}/health`, { method: "GET" });
    serverOnline = true;
  } catch {
    serverOnline = false;
  }
  return serverOnline;
}

function startHealthPolling() {
  if (healthTimer) clearInterval(healthTimer);
  checkHealth();
  healthTimer = setInterval(checkHealth, HEALTH_INTERVAL_MS);
}

// --- Message handlers ---

async function handleGetStatus() {
  const online = await checkHealth();
  const token = await getToken();
  return { online, paired: online && !!token };
}

async function handlePair(data) {
  if (data?.code) {
    const result = await apiFetch("/pair", {
      method: "POST",
      body: JSON.stringify({ code: data.code }),
    });
    if (result.token) {
      await setToken(result.token);
      return { success: true };
    }
    throw new Error("No token returned from server");
  }
  // Initiate pairing (no code yet)
  await apiFetch("/pair", { method: "POST", body: JSON.stringify({}) });
  return { initiated: true };
}

async function handleAutofill(data) {
  const url = encodeURIComponent(data.url);
  return apiFetch(`/autofill?url=${url}`);
}

async function handleSearch(data) {
  const q = encodeURIComponent(data.query);
  return apiFetch(`/search?q=${q}`);
}

async function handleGetEntry(data) {
  const db = encodeURIComponent(data.db_path);
  return apiFetch(`/entry/${data.uuid}?db=${db}`);
}

async function handleGetDatabases() {
  return apiFetch("/databases");
}

async function handleFillCredentials(data) {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab?.id) throw new Error("No active tab");

  await chrome.tabs.sendMessage(tab.id, {
    action: "fillCredentials",
    username: data.username,
    password: data.password,
  });
  return { success: true };
}

// --- Listener ---

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  const handlers = {
    getStatus: handleGetStatus,
    pair: handlePair,
    autofill: handleAutofill,
    search: handleSearch,
    getEntry: handleGetEntry,
    getDatabases: handleGetDatabases,
    fillCredentials: handleFillCredentials,
  };

  const handler = handlers[msg.action];
  if (!handler) {
    sendResponse({ error: `Unknown action: ${msg.action}` });
    return false;
  }

  handler(msg.data)
    .then((result) => sendResponse({ result }))
    .catch((err) => sendResponse({ error: err.message }));

  return true; // keep channel open for async response
});

// --- Init ---
startHealthPolling();
