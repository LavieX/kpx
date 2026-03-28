// KPX Content Script — fills credentials and shows inline suggestions

const USERNAME_SELECTORS = [
  'input[autocomplete="username"]',
  'input[autocomplete="email"]',
  'input[type="email"]',
  'input[type="text"][name*="user" i]',
  'input[type="text"][name*="login" i]',
  'input[type="text"][name*="email" i]',
  'input[type="text"][id*="user" i]',
  'input[type="text"][id*="login" i]',
  'input[type="text"][id*="email" i]',
  'input[type="text"][placeholder*="user" i]',
  'input[type="text"][placeholder*="email" i]',
];

const PASSWORD_SELECTORS = [
  'input[type="password"]',
  'input[autocomplete="current-password"]',
  'input[autocomplete="new-password"]',
];

function isVisible(el) {
  if (!el) return false;
  const style = getComputedStyle(el);
  if (style.display === "none" || style.visibility === "hidden" || style.opacity === "0") return false;
  const rect = el.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
}

function findBestField(selectors) {
  const candidates = [];
  for (const sel of selectors) {
    for (const el of document.querySelectorAll(sel)) {
      if (!el.disabled && !el.readOnly) candidates.push(el);
    }
  }
  const visible = candidates.filter(isVisible);
  return visible[0] ?? candidates[0] ?? null;
}

function dispatchEvents(el) {
  for (const type of ["input", "change"]) {
    el.dispatchEvent(new Event(type, { bubbles: true, composed: true }));
  }
  const nativeInputValueSetter = Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype, "value"
  )?.set;
  if (nativeInputValueSetter) {
    nativeInputValueSetter.call(el, el.value);
    el.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

function flashField(el) {
  const prev = el.style.transition;
  const prevBg = el.style.backgroundColor;
  const prevOutline = el.style.outline;
  el.style.transition = "background-color 0.15s, outline 0.15s";
  el.style.backgroundColor = "rgba(76, 175, 80, 0.25)";
  el.style.outline = "2px solid #4caf50";
  setTimeout(() => {
    el.style.backgroundColor = prevBg;
    el.style.outline = prevOutline;
    setTimeout(() => { el.style.transition = prev; }, 200);
  }, 600);
}

function fillField(el, value) {
  if (!el) return false;
  el.focus();
  el.value = value;
  dispatchEvents(el);
  flashField(el);
  return true;
}

// --- Fill credentials handler ---

chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.action !== "fillCredentials") return;

  const usernameField = findBestField(USERNAME_SELECTORS);
  const passwordField = findBestField(PASSWORD_SELECTORS);

  let filledUser = false;
  let filledPass = false;

  if (msg.username && usernameField) {
    filledUser = fillField(usernameField, msg.username);
  }
  if (msg.password && passwordField) {
    filledPass = fillField(passwordField, msg.password);
  }

  sendResponse({ filledUser, filledPass });
});

// --- Inline suggestion badge on login fields ---

let kpxBadge = null;
let kpxDropdown = null;
let cachedMatches = null;

function createBadge() {
  const badge = document.createElement("div");
  badge.id = "kpx-badge";
  badge.innerHTML = `<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#89b4fa" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>`;
  badge.style.cssText = `
    position: absolute; z-index: 2147483647; cursor: pointer;
    width: 26px; height: 26px; display: flex; align-items: center;
    justify-content: center; background: #1e1e2e; border: 1px solid #45475a;
    border-radius: 4px; opacity: 0.85; transition: opacity 0.15s;
  `;
  badge.addEventListener("mouseenter", () => badge.style.opacity = "1");
  badge.addEventListener("mouseleave", () => badge.style.opacity = "0.85");
  badge.addEventListener("click", (e) => {
    e.stopPropagation();
    toggleDropdown();
  });
  return badge;
}

function createDropdown(entries) {
  const dd = document.createElement("div");
  dd.id = "kpx-dropdown";
  dd.style.cssText = `
    position: absolute; z-index: 2147483647; background: #1e1e2e;
    border: 1px solid #45475a; border-radius: 6px; padding: 4px 0;
    min-width: 260px; max-width: 350px; box-shadow: 0 4px 16px rgba(0,0,0,0.4);
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    font-size: 13px; color: #cdd6f4;
  `;

  for (const entry of entries) {
    const item = document.createElement("div");
    item.style.cssText = `
      padding: 8px 12px; cursor: pointer; display: flex; flex-direction: column;
      gap: 2px; border-bottom: 1px solid #313244;
    `;
    item.innerHTML = `
      <span style="font-weight:600;color:#89b4fa">${esc(entry.title || "Untitled")}</span>
      <span style="color:#a6adc8;font-size:12px">${esc(entry.username || "")}</span>
    `;
    item.addEventListener("mouseenter", () => item.style.background = "#313244");
    item.addEventListener("mouseleave", () => item.style.background = "none");
    // Use mousedown to fire before the document click handler can close the dropdown
    item.addEventListener("mousedown", (e) => {
      e.preventDefault();
      e.stopPropagation();
      fillFromEntry(entry);
    });
    dd.appendChild(item);
  }

  return dd;
}

function esc(str) {
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function positionBadge(field) {
  const rect = field.getBoundingClientRect();
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  kpxBadge.style.top = `${rect.top + scrollY + (rect.height - 26) / 2}px`;
  kpxBadge.style.left = `${rect.right + scrollX - 30}px`;
}

function positionDropdown(field) {
  const rect = field.getBoundingClientRect();
  const scrollX = window.scrollX;
  const scrollY = window.scrollY;
  kpxDropdown.style.top = `${rect.bottom + scrollY + 4}px`;
  kpxDropdown.style.left = `${rect.left + scrollX}px`;
}

function toggleDropdown() {
  if (kpxDropdown) {
    kpxDropdown.remove();
    kpxDropdown = null;
    return;
  }
  if (!cachedMatches || cachedMatches.length === 0) return;

  const field = findBestField(USERNAME_SELECTORS);
  kpxDropdown = createDropdown(cachedMatches);
  document.body.appendChild(kpxDropdown);
  if (field) positionDropdown(field);
}

async function fillFromEntry(entry) {
  // Close dropdown immediately so it doesn't interfere
  if (kpxDropdown) { kpxDropdown.remove(); kpxDropdown = null; }

  try {
    // Fetch full entry (need password — not in cached data)
    const resp = await chrome.runtime.sendMessage({
      action: "getEntry",
      data: { uuid: entry.uuid, db_path: entry.db_path },
    });

    let username = entry.username;
    let password = "";

    if (resp?.error) {
      console.error("KPX getEntry error:", resp.error);
      // Fall back: fill username only
    } else {
      const full = resp.result ?? resp;
      username = full.username ?? entry.username;
      password = full.password ?? "";
    }

    const usernameField = findBestField(USERNAME_SELECTORS);
    const passwordField = findBestField(PASSWORD_SELECTORS);
    if (usernameField) fillField(usernameField, username);
    if (passwordField && password) fillField(passwordField, password);

    if (!usernameField && !passwordField) {
      console.warn("KPX: no username or password fields found on page");
    }
  } catch (err) {
    console.error("KPX fill error:", err);
  }
}

// Close dropdown on outside click
document.addEventListener("click", () => {
  if (kpxDropdown) { kpxDropdown.remove(); kpxDropdown = null; }
});

// --- Auto-detect login fields and show badge ---

async function checkForLoginFields() {
  // Look for either a username or password field — password-only pages (e.g. Amazon step 2)
  const usernameField = findBestField(USERNAME_SELECTORS);
  const passwordField = findBestField(PASSWORD_SELECTORS);
  const targetField = (usernameField && isVisible(usernameField)) ? usernameField
    : (passwordField && isVisible(passwordField)) ? passwordField
    : null;
  if (!targetField) return;

  // Ask background for autofill match
  try {
    const resp = await chrome.runtime.sendMessage({
      action: "autofill",
      data: { url: window.location.href },
    });
    if (resp?.error) return;
    const result = resp.result ?? resp;
    const entries = Array.isArray(result) ? result
      : result?.entries ? result.entries
      : result?.title ? [result]
      : [];

    if (entries.length === 0) return;

    cachedMatches = entries;

    // Show badge on whichever field we found
    if (kpxBadge) kpxBadge.remove();
    kpxBadge = createBadge();
    document.body.appendChild(kpxBadge);
    positionBadge(targetField);

    // Reposition on scroll/resize
    const reposition = () => { if (kpxBadge) positionBadge(targetField); };
    window.addEventListener("scroll", reposition, { passive: true });
    window.addEventListener("resize", reposition, { passive: true });
  } catch {
    // Server not available or not paired — silently skip
  }
}

// Run after page settles
setTimeout(checkForLoginFields, 1000);

// Also watch for dynamically added login forms (SPAs)
const observer = new MutationObserver(() => {
  if (!kpxBadge || !document.body.contains(kpxBadge)) {
    setTimeout(checkForLoginFields, 500);
  }
});
observer.observe(document.body, { childList: true, subtree: true });
