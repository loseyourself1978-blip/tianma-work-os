"use strict";
(() => {
  const el = id => document.getElementById(id);
  let review = null, busy = false, confirmed = false;
  async function api(path, body) {
    const abort = new AbortController(), timer = setTimeout(() => abort.abort(), 20000);
    try {
      const response = await fetch(path, {method: body === undefined ? "GET" : "POST", credentials: "same-origin", signal: abort.signal,
        headers: body === undefined ? {} : {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
      const data = await response.json();
      if (!response.ok) { const error = new Error(data.error?.message || "The review could not complete."); error.status = response.status; throw error; }
      return data;
    } finally { clearTimeout(timer); }
  }
  function render() {
    el("confirm").disabled = busy || confirmed || !review?.can_confirm;
    el("reload").disabled = busy;
  }
  async function load() {
    const data = await api("/api/startup-recovery/review"); review = data.review;
    el("login").hidden = true; el("review").hidden = false; el("history").hidden = false;
    el("binding").textContent = `Project: ${review.project}\nWorkspace: ${review.path}\nSaved device: ${review.before_device}\nCurrent device: ${review.current_device}\nDirectory identity: ${review.inode}\nAPFS volume: ${review.volume_uuid || "Not established — remount recovery will require another explicit review"}`;
    el("records").replaceChildren();
    for (const record of data.history) {
      const heading = document.createElement("h3"), content = document.createElement("pre");
      heading.textContent = `${record.project} / ${record.task}`; content.textContent = JSON.stringify(record, null, 2);
      el("records").append(heading, content);
    }
    if (review.already_authorized) el("result").textContent = "Workspace confirmed. Quit Tianma Work OS normally, then launch it again to enter the workbench. Do not rerun the old delivery.";
    else if (!review.can_confirm) el("error").textContent = "The directory itself changed. Confirmation is blocked; keep the saved data and review recovery diagnostics.";
    render();
  }
  async function guard(action) {
    if (busy) return; busy = true; el("error").textContent = ""; render();
    try { await action(); }
    catch (error) { el("error").textContent = error.name === "AbortError" ? "The response timed out. Reload the review to inspect the saved state before confirming again." : error.message;
      if (error.status === 401) { el("login").hidden = false; el("review").hidden = true; el("history").hidden = true; }
    } finally { busy = false; render(); }
  }
  el("login-form").addEventListener("submit", event => { event.preventDefault(); guard(async () => {
    await api("/api/auth/login", {username: el("username").value, password: el("password").value}); el("password").value = ""; await load();
  }); });
  el("reload").addEventListener("click", () => guard(load));
  el("confirm").addEventListener("click", () => guard(async () => {
    const result = await api("/api/startup-recovery/confirm", {confirmation: "CONFIRM_CURRENT_WORKSPACE", review_digest: review.review_digest});
    confirmed = ["CONFIRMED", "ALREADY_CONFIRMED"].includes(result.status);
    el("result").textContent = "Workspace confirmed. Quit Tianma Work OS normally, then launch it again. Your previous delivery remains saved; do not repeat it.";
  }));
  guard(load);
})();
