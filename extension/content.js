// KPX Content Script — fills credentials when instructed by popup/background

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
  // Prefer visible fields
  const visible = candidates.filter(isVisible);
  return visible[0] ?? candidates[0] ?? null;
}

function dispatchEvents(el) {
  for (const type of ["input", "change"]) {
    el.dispatchEvent(new Event(type, { bubbles: true, composed: true }));
  }
  // Also fire for React's synthetic event system
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
