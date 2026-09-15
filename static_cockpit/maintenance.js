"use strict";
(() => {
  const el = id => document.getElementById(id);
  let status = null, stage = "backup", plan = null, busy = false;
  async function api(path, body) {
    const response = await fetch(path, {method: body === undefined ? "GET" : "POST", credentials: "same-origin",
      headers: body === undefined ? {} : {"Content-Type": "application/json"}, body: body === undefined ? undefined : JSON.stringify(body)});
    const result = await response.json();
    if (!response.ok) { const error = new Error(result.error?.message || result.detail || "Maintenance request failed."); error.status = response.status; throw error; }
    return result;
  }
  function fields(id, data) {
    el(id).replaceChildren();
    for (const [name, value] of Object.entries(data)) {
      const dt = document.createElement("dt"), dd = document.createElement("dd");
      dt.textContent = name; dd.textContent = String(value ?? "Not available"); el(id).append(dt, dd);
    }
  }
  function showEvidence(value) { el("advanced").textContent = JSON.stringify(value, null, 2); }
  function render() {
    const labels = {backup: "Create Backup", restore: "Inspect Backup", inspected: "Review Restore Plan", migration: "Review Migration Plan", review: "Approve Maintenance Plan", approved: `Confirm ${plan?.kind === "MIGRATION" ? "Migration" : "Restore"}`, workspace: "Reauthorize Workspace", complete: "Refresh Installation"};
    el("primary").textContent = busy ? "Working…" : labels[stage];
    el("primary").disabled = busy || status?.recovery_only || (stage === "backup" && !status?.backup_ready) || (stage === "approved" && el("confirmation").value !== plan?.confirmation);
    el("operation").disabled = busy || status?.recovery_only;
    el("backup-source").hidden = !["restore", "inspected", "review", "approved"].includes(stage) || (plan?.kind === "MIGRATION" && ["review", "approved"].includes(stage));
    el("workspace-source").hidden = stage !== "workspace";
    el("plan").hidden = !["review", "approved"].includes(stage);
    el("confirmation-area").hidden = stage !== "approved";
    if (stage === "approved") el("confirmation-label").textContent = plan.confirmation;
    el("next").textContent = status?.recovery_only ? status.next_action : busy ? "Local maintenance is in progress. Wait for its receipt; do not submit again." : stage === "backup" && status?.blocker ? status.blocker : `Next action: ${labels[stage]}.`;
  }
  async function refresh() {
    status = await api("/api/maintenance/status");
    el("login").hidden = true; el("maintenance").hidden = false;
    fields("installation", {"App version": status.app_version, Schema: status.schema, "Backup readiness": status.backup_ready ? "Ready" : "Blocked", "Recovery status": status.recovery.state, Workspace: status.authority.workspace_status || "Current authorization"});
    el("warning").textContent = status.sensitive_content_warning;
    if (status.schema !== status.target_schema) stage = "migration";
    else if (status.authority.workspace_status === "REAUTHORIZATION_REQUIRED") stage = "workspace";
    else if (!["restore", "inspected", "review", "approved"].includes(stage)) stage = "backup";
    el("operation").value = ["backup", "migration", "workspace"].includes(stage) ? stage : "restore";
    if (status.recovery.backup && !el("backup-path").value) el("backup-path").value = status.recovery.backup;
    if (!el("workspace-path").value) el("workspace-path").value = status.authority.workspace || status.workspace_candidate || "";
    showEvidence(status);
    const data = await api("/api/maintenance/data");
    el("tasks").replaceChildren();
    for (const task of data.tasks) { const li = document.createElement("li"); li.textContent = `${task.title} — ${task.status}`; el("tasks").append(li); }
    render();
  }
  async function guard(action) {
    if (busy) return;
    busy = true; el("error").textContent = ""; render();
    try { await action(); }
    catch (error) { el("error").textContent = error.message; if (error.status === 401) { el("login").hidden = false; el("maintenance").hidden = true; } }
    finally { busy = false; render(); }
  }
  el("login-form").addEventListener("submit", event => { event.preventDefault(); guard(async () => {
    await api("/api/auth/login", {username: el("username").value, password: el("password").value}); el("password").value = ""; await refresh();
  }); });
  el("operation").addEventListener("change", () => { stage = el("operation").value; plan = null; el("confirmation").value = ""; render(); });
  el("backup-path").addEventListener("input", () => { stage = "restore"; plan = null; fields("backup-summary", {}); render(); });
  el("confirmation").addEventListener("input", render);
  el("refresh").addEventListener("click", () => guard(refresh));
  el("primary").addEventListener("click", () => guard(async () => {
    let result;
    if (stage === "backup") {
      result = await api("/api/maintenance/backups", {confirmation: "CREATE_BACKUP"});
      el("backup-path").value = result.backup; stage = "restore"; el("operation").value = "restore";
    } else if (stage === "restore") {
      result = await api("/api/maintenance/inspect", {backup: el("backup-path").value}); stage = "inspected";
    } else if (stage === "inspected" || stage === "migration") {
      plan = await api(stage === "migration" ? "/api/maintenance/migration-plan" : "/api/maintenance/restore-plan", stage === "migration" ? {} : {backup: el("backup-path").value});
      result = plan; el("consequences").textContent = plan.consequences;
      fields("plan-summary", {From: plan.from_schema, To: plan.to_schema, "Recovery point": plan.recovery_point, "Tasks after activation": plan.counts.tasks}); stage = "review";
    } else if (stage === "review") {
      result = await api("/api/maintenance/approve-plan", {plan_id: plan.plan_id, confirmation: "APPROVE_MAINTENANCE_PLAN"}); stage = "approved"; el("confirmation").value = "";
    } else if (stage === "approved") {
      result = await api("/api/maintenance/confirm", {plan_id: plan.plan_id, confirmation: el("confirmation").value}); stage = "complete";
      el("confirmation").value = "";
      if (plan.kind === "RESTORE") { el("login").hidden = false; el("maintenance").hidden = true; el("error").textContent = "Restore completed. Log in again with the recovered Owner account."; }
    } else if (stage === "workspace") {
      result = await api("/api/maintenance/workspace", {path: el("workspace-path").value, confirmation: "REAUTHORIZE_WORKSPACE"}); stage = "complete";
    } else { await refresh(); return; }
    if (result.integrity_status === "VERIFIED") {
      fields("backup-summary", {"Backup format": result.manifest?.format || result.format,
        "Created": result.manifest?.created_at || result.started_at,
        "Integrity": "Verified"});
    }
    showEvidence(result); render();
  }));
  // Only passive local status/data reads occur on page load.
  refresh().catch(error => { if (error.status !== 401) el("error").textContent = error.message; });
})();
