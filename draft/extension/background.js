/* fflDraft background: the only place that talks to the Apps Script web app.
 *
 * Content scripts run inside espn.com and are bound by that page's CSP, so a
 * cross-origin POST from there can be blocked. The background script is not,
 * and with host_permissions it may call script.google.com directly. So the
 * content script only ever sends a message here; this does the network.
 *
 * Apps Script web apps answer a POST with a 302 to script.googleusercontent.com
 * (hence that host permission and redirect:'follow'), and they parse the body
 * themselves -- so we send text/plain to stay a "simple" request with no CORS
 * preflight, and JSON.parse it server-side. */

const api = (typeof browser !== 'undefined') ? browser : chrome;

async function callWebApp(payload) {
  const cfg = await api.storage.local.get(['webAppUrl', 'token']);
  if (!cfg.webAppUrl) {
    return { ok: false, error: 'No web app URL set — open the extension options.' };
  }
  try {
    const res = await fetch(cfg.webAppUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'text/plain;charset=utf-8' },
      body: JSON.stringify({ ...payload, token: cfg.token || '' }),
      redirect: 'follow'
    });
    const text = await res.text();
    try { return JSON.parse(text); }
    catch (e) { return { ok: false, error: 'Non-JSON reply (check the deployment)', raw: text.slice(0, 200) }; }
  } catch (e) {
    return { ok: false, error: String(e) };
  }
}

api.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || !msg.type) return;
  if (msg.type === 'PICK')  { callWebApp({ name: msg.name, info: msg.info || '' }).then(sendResponse); return true; }
  if (msg.type === 'RESET') { callWebApp({ action: 'reset' }).then(sendResponse); return true; }
  if (msg.type === 'PING')  { callWebApp({ action: 'ping' }).then(sendResponse);  return true; }
});
