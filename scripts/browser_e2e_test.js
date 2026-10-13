#!/usr/bin/env node
// Browser E2E test for the ETERNIX platform.
//
// Drives the real system Chrome over the Chrome DevTools Protocol.
// Playwright is unusable in this environment: its bundled Chromium
// cannot be downloaded (disk quota) and the system Chrome fatals on
// GPU-process launch unless the crash limit is disabled, which kills
// every Playwright session within seconds. CDP with
// --disable-gpu-process-crash-limit keeps a real browser alive.
//
// Flow: sign-in -> dev registration -> verification -> payment ->
// simple workspace (brand, new chat, previous chats, workspaces,
// ask-anything input) -> add workspace folder -> objective
// submission -> answer display -> sign out -> sign back in.
// Reports any page console errors.
const { spawn } = require("child_process");
const http = require("http");
const fs = require("fs");
const path = require("path");
const BASE = process.env.ETERNIX_BASE_URL || "http://127.0.0.1:8080";
const PORT = 9333;
const UNIQUE = String(Date.now()).slice(-9);
const USERNAME = `e2e${UNIQUE}`;
const PASSWORD = "Sup3rSecret!";
const EMAIL = `e2e${UNIQUE}@example.com`;
// A folder that really exists on this machine, used for workspace registration.
// Unique per run so the listing checks prove the new registration.
const WORKSPACE_PATH = process.env.ETERNIX_TEST_WORKSPACE || (() => {
  const dir = path.join(__dirname, "..", ".tmp", `e2e-workspace-${UNIQUE}`);
  fs.mkdirSync(dir, { recursive: true });
  return dir;
})();

let failed = 0;

function check(name, ok, detail = "") {
  if (!ok) failed += 1;
  console.log(`[${ok ? "PASS" : "FAIL"}] ${name}${detail ? ` — ${detail}` : ""}`);
}

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function getJson(url) {
  return new Promise((resolve, reject) => {
    http
      .get(url, (res) => {
        let data = "";
        res.on("data", (c) => (data += c));
        res.on("end", () => {
          try {
            resolve(JSON.parse(data));
          } catch (e) {
            reject(e);
          }
        });
      })
      .on("error", reject);
  });
}

async function main() {
    // /tmp is quota-exceeded in this environment; keep the profile local.
    // A fresh profile per run avoids stale tokens from earlier runs
    // triggering (correct) session-restore 401s on page load.
    const profileDir = path.join(
      __dirname, "..", ".tmp", `chrome-e2e-profile-${UNIQUE}`
    );
    fs.mkdirSync(profileDir, { recursive: true });
    const chrome = spawn("google-chrome", [
      "--headless",
      "--disable-gpu",
      "--no-sandbox",
      "--disable-dev-shm-usage",
      "--disable-extensions",
      "--disable-gpu-process-crash-limit",
      `--remote-debugging-port=${PORT}`,
      `--user-data-dir=${profileDir}`,
      "about:blank",
    ]);
  chrome.stderr.on("data", (d) => {
    const s = d.toString();
    if (s.includes("FATAL")) console.log("[chrome-fatal]", s.trim().slice(0, 200));
  });
  chrome.on("exit", (code) => {
    if (code && code !== 0) console.log("[chrome-exit]", code);
  });

  let version;
  for (let i = 0; i < 100 && !version; i++) {
    try {
      version = await getJson(`http://127.0.0.1:${PORT}/json/version`);
    } catch {
      await sleep(200);
    }
  }
  if (!version) throw new Error("CDP endpoint never appeared");

  const ws = new WebSocket(version.webSocketDebuggerUrl);
  await new Promise((res, rej) => {
    ws.onopen = res;
    ws.onerror = rej;
  });

  const consoleErrors = [];
  let id = 0;
  const pending = new Map();
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      pending.get(msg.id)(msg);
      pending.delete(msg.id);
      return;
    }
    if (msg.method === "Runtime.exceptionThrown") {
      const d = msg.params.exceptionDetails;
      consoleErrors.push(`exception: ${d.text} ${d.exception?.description || ""}`);
    } else if (msg.method === "Runtime.consoleAPICalled" && msg.params.type === "error") {
      consoleErrors.push(
        "console.error: " + msg.params.args.map((a) => a.value ?? a.description ?? "").join(" ")
      );
    } else if (msg.method === "Log.entryAdded" && msg.params.entry.level === "error") {
      const u = msg.params.entry.url || "";
      if (!u.includes("favicon")) {
        consoleErrors.push(`log: ${msg.params.entry.text} ${u}`);
      }
    } else if (msg.method === "Network.responseReceived") {
      const resp = msg.params.response;
      if (resp.status >= 400 && !resp.url.includes("favicon")) {
        consoleErrors.push(`http ${resp.status}: ${resp.url}`);
        send("Network.getResponseBody", { requestId: msg.params.requestId }).then(
          (body) => {
            if (body.result?.body) {
              consoleErrors.push(`   body: ${body.result.body.slice(0, 300)}`);
            }
          },
          () => {}
        );
      }
    }
  };

  const send = (method, params = {}, sessionId) =>
    new Promise((res) => {
      const myId = ++id;
      pending.set(myId, res);
      ws.send(
        JSON.stringify({ id: myId, method, params, ...(sessionId ? { sessionId } : {}) })
      );
    });

  const { result: target } = await send("Target.createTarget", { url: `${BASE}/` });
  const { result: attach } = await send("Target.attachToTarget", {
    targetId: target.targetId,
    flatten: true,
  });
  const sid = attach.sessionId;
  await send("Page.enable", {}, sid);
  await send("Runtime.enable", {}, sid);
  await send("Log.enable", {}, sid);
  await send("Network.enable", {}, sid);

  // Intercept fetch to capture response bodies of failing requests.
  await send(
    "Page.addScriptToEvaluateOnNewDocument",
    {
      source: `
        window.__fetchLog = [];
        const origFetch = window.fetch;
        window.fetch = async function (...args) {
          const resp = await origFetch.apply(this, args);
          const clone = resp.clone();
          try {
            const text = await clone.text();
            window.__fetchLog.push({
              url: String(args[0]),
              status: resp.status,
              body: text.slice(0, 300),
            });
          } catch {}
          return resp;
        };
      `,
    },
    sid
  );

  const evalInPage = async (expression) => {
    const r = await send("Runtime.evaluate", { expression, returnByValue: true }, sid);
    if (r.result?.exceptionDetails) {
      throw new Error("eval failed: " + JSON.stringify(r.result.exceptionDetails).slice(0, 300));
    }
    return r.result?.result?.value;
  };

  const bodyText = () => evalInPage("document.body.innerText");

  const clickText = (text) =>
    evalInPage(`(() => {
      const els = [...document.querySelectorAll('button, [role=menuitem], a')];
      const el = els.find(b => (b.textContent || '').trim().includes(${JSON.stringify(text)}));
      if (!el) return false;
      el.click();
      return true;
    })()`);

  const clickSelector = (selector) =>
    evalInPage(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      el.click();
      return true;
    })()`);

  const setInput = (id, value) =>
    evalInPage(`(() => {
      const el = document.getElementById(${JSON.stringify(id)});
      if (!el) return false;
      const proto = el.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, ${JSON.stringify(value)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);

  const setTextarea = (selector, value) =>
    evalInPage(`(() => {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (!el) return false;
      const setter = Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value').set;
      setter.call(el, ${JSON.stringify(value)});
      el.dispatchEvent(new Event('input', { bubbles: true }));
      return true;
    })()`);

  async function waitFor(expr, timeoutMs, what) {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      const v = await evalInPage(`(() => (${expr}))()`);
      if (v) return v;
      await sleep(300);
    }
    throw new Error("timeout waiting for " + (what || expr));
  }

  try {
    // 1. Sign-in screen
    await waitFor(`document.body.innerText.includes('Sign In')`, 15000, "sign-in screen");
    const devAvailable = await waitFor(
      `[...document.querySelectorAll('button')].some(b => b.textContent.includes('Create development identity'))`,
      15000,
      "dev registration"
    );
    check("sign-in screen renders", devAvailable);

    // 2. Dev registration -> credentials step
    await clickText("Create development identity");
    await waitFor(`!!document.getElementById('reg-username')`, 10000, "credentials step");
    check("dev identity created, credentials step shown", true);

    // 3. Complete registration
    check("username input", await setInput("reg-username", USERNAME));
    check("email input", await setInput("reg-email", EMAIL));
    check("password input", await setInput("reg-password", PASSWORD));
    await waitFor(
      `(() => {
        const b = [...document.querySelectorAll('button')].find(x => x.textContent.includes('Create account'));
        return b && !b.disabled;
      })()`,
      10000,
      "username available"
    );
    check("username availability check passed", true);
    await clickText("Create account");
    await waitFor(`document.body.innerText.includes('Send verification code')`, 15000, "verification step");
    check("registration complete, verification step shown", true);

    // 4. Verification
    await clickText("Send verification code");
    const code = await waitFor(
      `(() => { const p = document.querySelector('p.font-mono'); return p ? p.textContent.trim() : null; })()`,
      10000,
      "dev code"
    );
    check("dev verification code delivered", /^\d{6}$/.test(code), `code=${code}`);
    check("code input", await setInput("verify-code", code));
    await clickText("Verify contact");
    await waitFor(`document.body.innerText.includes('Register payment method')`, 15000, "payment step");
    check("contact verified, payment step shown", true);

    // 5. Payment (sandbox)
    const provider = await evalInPage(
      `document.body.innerText.includes('Sandbox') ? 'sandbox' : 'unknown'`
    );
    check("sandbox provider indicated", provider === "sandbox");
    await clickText("Register payment method");
    await waitFor(`document.body.innerText.includes('Confirm & activate account')`, 15000, "payment confirm");
    check("payment method registered", true);
    await clickText("Confirm & activate account");

    // 6. Simple workspace shell
    await waitFor(`!!document.querySelector('textarea[aria-label="Ask Anything"]')`, 20000, "workspace shell");
    check("account activated, workspace loaded", true);
    const brandOk = await evalInPage(
      `(() => { const h1 = document.querySelector('h1'); return h1 ? h1.textContent.trim() : null; })()`
    );
    check("brand is Eternix", brandOk === "Eternix", `h1=${brandOk}`);
    check("new chat button", await evalInPage(
      `[...document.querySelectorAll('button')].some(b => (b.textContent || '').trim() === 'New Chat')`
    ));
    check("previous chats section", await evalInPage(
      `document.body.textContent.includes('Previous Chats')`
    ));
    check("workspaces section", await evalInPage(
      `document.body.textContent.includes('Workspaces')`
    ));
    check("ask anything input present", await evalInPage(
      `!!document.querySelector('textarea[aria-label="Ask Anything"]')`
    ));
    // No raw model/capability inventory may be exposed to the UI.
    check("no model inventory exposed", !(await evalInPage(
      `document.body.innerText.includes('Models') && [...document.querySelectorAll('*')].some(e => e.textContent.includes('.gguf'))`
    )));

    // 7. Add a workspace folder from this machine
    check("add workspace button", await clickSelector('button[aria-label="Add workspace folder"]'));
    await waitFor(`!!document.querySelector('input[placeholder="/home/you/projects"]')`, 10000, "workspace dialog");
    check("add workspace dialog opened", true);
    check("workspace path input", await setInput("folder-path", WORKSPACE_PATH));
    await clickText("Add Workspace");
    const wsListed = await waitFor(
      `(() => {
        const items = [...document.querySelectorAll('[title]')];
        return items.some(el => el.title === ${JSON.stringify(WORKSPACE_PATH)});
      })()`
    , 15000, "workspace listed");
    check("workspace folder registered and listed", wsListed);
    check("workspace marked active", await waitFor(
      `(() => {
        const items = [...document.querySelectorAll('[title]')];
        return items.some(el => el.title === ${JSON.stringify(WORKSPACE_PATH)} && (el.textContent || '').includes('Active'));
      })()`,
      15000,
      "workspace active badge"
    ));

    // 8. Objective submission through the Ask Anything input
    check("question typed", await setTextarea('textarea[aria-label="Ask Anything"]', "List the files in the current workspace directory"));
    check("question sent", await clickSelector('button[aria-label="Send message"]'));
    // The user turn appears immediately...
    await waitFor(`document.body.innerText.includes('List the files in the current workspace directory')`, 20000, "user turn");
    check("user question shown", true);
    // ...and the agent's answer lands in the answer display area.
    const answerShown = await waitFor(
      `(() => {
        const answers = [...document.querySelectorAll('[data-message-id]')];
        return answers.some(el => (el.textContent || '').includes('List files in current directory'));
      })()`,
      90000,
      "agent answer"
    );
    check("agent answer displayed", answerShown);

    // 9. The conversation is saved under Previous Chats
    const chatListed = await waitFor(
      `(() => {
        const section = [...document.querySelectorAll('div')].find(d => (d.textContent || '').trim().startsWith('Previous Chats'));
        return section && section.textContent.includes('List the files in the current');
      })()`,
      15000,
      "conversation in sidebar"
    );
    check("conversation saved to previous chats", chatListed);

    // Let the post-run conversation save settle before tearing down.
    await sleep(1500);

    // 10. Sign out
    check("sign out clicked", await clickSelector('button[aria-label="Sign out"]'));
    await waitFor(`document.body.innerText.includes('Create development identity')`, 15000, "sign-in after logout");
    check("signed out, back at sign-in screen", true);

    // 11. Sign back in with the credentials created above
    check("login username", await setInput("signin-username", USERNAME));
    check("login password", await setInput("signin-password", PASSWORD));
    await clickText("Sign In");
    await waitFor(`!!document.querySelector('textarea[aria-label="Ask Anything"]')`, 20000, "workspace after login");
    check("signed back in via login form", true);

    // 12. Console errors
    const realErrors = consoleErrors.filter(
      (e) => !e.includes("favicon") && !e.includes("DevTools")
    );
    check("no page console errors", realErrors.length === 0, realErrors.slice(0, 3).join(" | "));

    if (failed) {
      console.log(`\n${failed} CHECK(S) FAILED`);
      process.exitCode = 1;
    } else {
      console.log("\nALL BROWSER E2E CHECKS PASSED");
    }
  } catch (err) {
    console.log(`[FAIL] aborted: ${err.message}`);
    const fetchLog = await evalInPage("JSON.stringify(window.__fetchLog || [])").catch(
      () => "[]"
    );
    for (const entry of JSON.parse(fetchLog)) {
      console.log(`[fetch ${entry.status}] ${entry.url} — ${entry.body.slice(0, 120)}`);
    }
    console.log("[network]");
    for (const e of consoleErrors) console.log("  ", e);
    const pageText = await bodyText().catch(() => "");
    console.log("[page]", JSON.stringify(pageText.slice(0, 400)));
    process.exitCode = 1;
  } finally {
    chrome.kill("SIGKILL");
  }
}

main().catch((e) => {
  console.error("[error]", e);
  process.exit(1);
});
