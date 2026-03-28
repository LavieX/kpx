// KPX Popup — UI controller

const $ = (sel) => document.querySelector(sel);
const show = (el) => el.classList.remove("hidden");
const hide = (el) => el.classList.add("hidden");

const views = {
  disconnected: $("#view-disconnected"),
  pair: $("#view-pair"),
  connected: $("#view-connected"),
};

const dot = $("#status-dot");
const footer = $("#footer");
const dbCount = $("#db-count");

// --- Messaging ---

function send(action, data = {}) {
  return new Promise((resolve, reject) => {
    chrome.runtime.sendMessage({ action, data }, (resp) => {
      if (chrome.runtime.lastError) {
        reject(new Error(chrome.runtime.lastError.message));
        return;
      }
      if (resp?.error) {
        reject(new Error(resp.error));
        return;
      }
      resolve(resp?.result);
    });
  });
}

// --- View switching ---

function showView(name) {
  for (const [key, el] of Object.entries(views)) {
    if (key === name) show(el);
    else hide(el);
  }
}

function setDot(color) {
  dot.className = `dot ${color}`;
}

// --- Init ---

async function init() {
  try {
    const status = await send("getStatus");
    if (!status.online) {
      setDot("red");
      showView("disconnected");
      hide(footer);
      return;
    }
    if (!status.paired) {
      setDot("yellow");
      showView("pair");
      hide(footer);
      return;
    }
    setDot("green");
    showView("connected");
    await loadAutofill();
    await loadDatabases();
  } catch {
    setDot("red");
    showView("disconnected");
    hide(footer);
  }
}

// --- Autofill ---

async function loadAutofill() {
  const list = $("#autofill-list");
  const noMatches = $("#no-matches");
  list.innerHTML = "";
  hide(noMatches);

  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (!tab?.url) { show(noMatches); return; }

    const result = await send("autofill", { url: tab.url });
    // Result may be a single entry or have entries array
    const entries = Array.isArray(result) ? result
      : result?.entries ? result.entries
      : result?.title ? [result]
      : [];

    if (entries.length === 0) {
      show(noMatches);
      return;
    }

    for (const entry of entries) {
      list.appendChild(createEntryItem(entry));
    }
  } catch {
    show(noMatches);
  }
}

// --- Databases ---

async function loadDatabases() {
  try {
    const result = await send("getDatabases");
    const dbs = Array.isArray(result) ? result : result?.databases ?? [];
    if (dbs.length > 0) {
      dbCount.textContent = `${dbs.length} database${dbs.length !== 1 ? "s" : ""} open`;
      show(footer);
    } else {
      hide(footer);
    }
  } catch {
    hide(footer);
  }
}

// --- Entry rendering ---

function createEntryItem(entry) {
  const el = document.createElement("div");
  el.className = "entry-item";
  el.innerHTML = `
    <span class="entry-title">${esc(entry.title || "Untitled")}</span>
    <span class="entry-user">${esc(entry.username || "")}</span>
    ${entry.url ? `<span class="entry-url">${esc(entry.url)}</span>` : ""}
  `;
  el.addEventListener("click", () => fillEntry(entry));
  return el;
}

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

// --- Fill ---

async function fillEntry(entry) {
  try {
    // Fetch full entry to get password
    const full = await send("getEntry", { uuid: entry.uuid, db_path: entry.db_path });
    // Send fill directly to content script via tabs API (avoids popup close race)
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    if (tab?.id) {
      await chrome.tabs.sendMessage(tab.id, {
        action: "fillCredentials",
        username: full.username ?? entry.username,
        password: full.password,
      });
    }
    window.close();
  } catch (err) {
    console.error("Fill failed:", err);
  }
}

// --- Search ---

let searchTimeout = null;

$("#search-input").addEventListener("input", (e) => {
  clearTimeout(searchTimeout);
  const query = e.target.value.trim();
  if (query.length < 2) {
    $("#search-results").innerHTML = "";
    return;
  }
  searchTimeout = setTimeout(() => doSearch(query), 250);
});

async function doSearch(query) {
  const results = $("#search-results");
  results.innerHTML = "";
  try {
    const data = await send("search", { query });
    const entries = data?.entries ?? [];
    for (const entry of entries) {
      results.appendChild(createEntryItem(entry));
    }
    if (entries.length === 0) {
      results.innerHTML = '<p class="hint">No results.</p>';
    }
  } catch (err) {
    results.innerHTML = `<p class="error">${esc(err.message)}</p>`;
  }
}

// --- Pairing ---

$("#btn-pair").addEventListener("click", async () => {
  const code = $("#pair-code").value.trim();
  const errEl = $("#pair-error");
  hide(errEl);

  if (!code) {
    errEl.textContent = "Enter the code shown on the server console.";
    show(errEl);
    return;
  }

  try {
    await send("pair", { code });
    init(); // re-init to switch to connected state
  } catch (err) {
    errEl.textContent = err.message;
    show(errEl);
  }
});

$("#btn-init-pair").addEventListener("click", async () => {
  const errEl = $("#pair-error");
  hide(errEl);
  try {
    await send("pair", {});
    errEl.textContent = "";
    $("#pair-code").focus();
  } catch (err) {
    errEl.textContent = err.message;
    show(errEl);
  }
});

// --- Retry ---

$("#btn-retry").addEventListener("click", () => init());

// --- Enter key on pair code ---

$("#pair-code").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#btn-pair").click();
});

// --- Boot ---
init();
