from __future__ import annotations

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "static_cockpit" / "vol12_static_mvp"
HTML = STATIC / "twos_command_center.html"
SCRIPT = STATIC / "twos_command_center.js"
STYLES = STATIC / "styles.css"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _slice(source: str, start: str, end: str) -> str:
    return start + source.split(start, 1)[1].split(end, 1)[0]


def _controller_source() -> str:
    source = _source(SCRIPT)
    eligibility = _slice(
        source,
        "function ownerPushConfirmationProjectionRelevant",
        "function canonicalPushState",
    )
    presentation = _slice(
        source,
        "function ownerPushConfirmationBusy",
        "function openOwnerPushConfirmation",
    )
    confirmation = _slice(
        source,
        "async function confirmApprovedPush",
        "async function decideAcceptance",
    )
    opening = _slice(
        source,
        "function openOwnerPushConfirmation",
        "async function reviewCommitPlan",
    )
    dialog_cancel = _slice(
        source,
        'elements.ownerPushConfirmationDialog.addEventListener("cancel"',
        "elements.cancelCodex.addEventListener",
    )
    return (
        eligibility
        + "\n"
        + presentation
        + "\n"
        + opening
        + "\n"
        + confirmation
        + "\n"
        + dialog_cancel
    )


def _run_node_scenario(scenario: str) -> dict[str, object]:
    controller = _controller_source()
    harness = f"""
const assert = require("node:assert/strict");

class ApiError extends Error {{
  constructor(status, code, message, fields, category, details) {{
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields || {{}};
    this.category = category || "api";
    this.details = details || {{}};
  }}
}}

class FakeButton {{
  constructor(text) {{
    this.textContent = text;
    this.disabled = false;
    this.attributes = {{}};
    this.listeners = {{}};
  }}
  addEventListener(name, listener) {{ this.listeners[name] = listener; }}
  setAttribute(name, value) {{ this.attributes[name] = value; }}
  removeAttribute(name) {{ delete this.attributes[name]; }}
  focus() {{ this.focused = true; }}
  click() {{
    if (this.disabled) return undefined;
    return this.listeners.click();
  }}
}}

class FakeDialog {{
  constructor() {{
    this.open = true;
    this.listeners = {{}};
  }}
  addEventListener(name, listener) {{ this.listeners[name] = listener; }}
  showModal() {{ this.open = true; }}
  close() {{ this.open = false; }}
  cancel() {{
    let defaultPrevented = false;
    const event = {{ preventDefault() {{ defaultPrevented = true; }} }};
    assert.equal(typeof this.listeners.cancel, "function");
    this.listeners.cancel(event);
    if (!defaultPrevented) this.close();
    return defaultPrevented;
  }}
}}

const OWNER_PUSH_CONFIRMATION_LABELS = Object.freeze({{
  ready_for_confirmation: "Ready for confirmation",
  submitting: "Submitting Push request",
  running: "Push in progress",
  succeeded: "Push delivered",
  already_delivered: "Already delivered",
  blocked: "Push blocked",
  failed: "Push failed",
  timed_out: "Push timed out",
  needs_review: "Push needs review"
}});
const OWNER_PUSH_RESPONSE_TIMEOUT_MS = 45000;
const OWNER_PUSH_REFRESH_WAIT_MS = 15000;
const OWNER_PUSH_RECONCILIATION_POLL_MS = 0;
const OWNER_PUSH_RECONCILIATION_MAX_POLLS = 4;
const AUTH_STATES = {{ SIGNED_IN: "signed_in" }};
const window = {{
  setTimeout,
  clearTimeout
}};
const elements = {{
  ownerPushConfirmationStatus: {{ dataset: {{}} }},
  ownerPushConfirmationStatusLabel: {{ textContent: "" }},
  ownerPushConfirmationStatusMessage: {{ textContent: "" }},
  confirmApprovedPush: new FakeButton("Confirm Push"),
  cancelApprovedPush: new FakeButton("Cancel"),
  confirmOwnerPush: new FakeButton("Confirm Push"),
  ownerPushConfirmationPlan: {{ textContent: "" }},
  ownerPushConfirmationRemote: {{ textContent: "" }},
  ownerPushConfirmationBranch: {{ textContent: "" }},
  ownerPushConfirmationOldSha: {{ textContent: "" }},
  ownerPushConfirmationNewSha: {{ textContent: "" }},
  ownerPushConfirmationFastForward: {{ textContent: "" }},
  ownerPushConfirmationDialog: new FakeDialog()
}};
const context = {{
  run_id: "1",
  plan_id: "pushplan_test",
  plan_digest: "a".repeat(64),
  approval_digest: "b".repeat(64),
  request_identity: "c".repeat(64),
  task_selection_epoch: 7
}};
const state = {{
  pending: new Set(),
  refreshing: false,
  auth: AUTH_STATES.SIGNED_IN,
  taskSelectionEpoch: 7,
  ownerPushConfirmationContext: context,
  ownerPushConfirmationState: {{
    phase: "ready_for_confirmation",
    message: "Ready",
    request_identity: context.request_identity
  }},
  ownerPushConfirmationUncertainty: null,
  ownerDeliveryRequestSequences: {{ "1": 4 }},
  ownerDeliveryProjections: {{}}
}};
let feedback = [];
let renderCount = 0;
let refreshCount = 0;
let postCount = 0;
let getCount = 0;
let canonicalState = "PUSH_CONFIRMATION_REQUIRED";
const reconciledParts = {{
  projection: {{ next_action: {{ message: "Confirm the approved Push." }} }},
  pushDelivery: {{}},
  pushPlan: {{
    id: context.plan_id,
    plan_digest: context.plan_digest,
    version: 1,
    remote_name: "origin",
    target_ref: "refs/heads/main",
    expected_remote_old_sha: "d".repeat(40),
    expected_new_sha: "e".repeat(40),
    fast_forward: true
  }},
  pushApproval: {{ approval_digest: context.approval_digest }},
  pushExecution: {{}},
  pushConfirmation: {{
    state: "ready_for_confirmation",
    can_confirm: true,
    plan_id: context.plan_id,
    request_identity: context.request_identity,
    progress: "Ready for explicit Owner confirmation."
  }},
  pushActions: {{ can_confirm_push: true }}
}};

function sanitizedApplyPlanText(value, fallback) {{ return value ? String(value) : fallback; }}
function objectRecord(value) {{ return value && typeof value === "object" ? value : {{}}; }}
function ownerDeliveryRecordId(value) {{
  const record = objectRecord(value);
  return record.id || record.plan_id || record.execution_id || record.push_execution_id || null;
}}
function ownerDeliveryDigest(value) {{
  const record = objectRecord(value);
  return record.digest || record.plan_digest || record.approval_digest || "";
}}
function currentCodexRun() {{ return {{ id: 1 }}; }}
function canonicalPushState() {{ return canonicalState; }}
function ownerDeliveryParts() {{ return reconciledParts; }}
function applyPlanTextList(value) {{ return Array.isArray(value) ? value : []; }}
function productActionMessage(error) {{ return error && error.message ? error.message : "Request failed."; }}
function setFeedback(message, kind) {{ feedback.push({{ message, kind }}); }}
function renderWorkspace() {{
  renderCount += 1;
  const parts = ownerDeliveryParts(currentCodexRun());
  if (state.ownerPushConfirmationContext) {{
    const phase = ownerPushConfirmationPhaseFor(parts);
    setOwnerPushConfirmationPhase(
      phase,
      ownerPushConfirmationReason(parts, "Review persisted Push evidence."),
      {{ request_identity: state.ownerPushConfirmationContext.request_identity }}
    );
  }}
  elements.confirmOwnerPush.disabled = !ownerPushConfirmationCanConfirm(parts)
    || state.pending.has("confirm-owner-push");
}}
async function refreshWorkspace() {{ refreshCount += 1; }}
function handleExpiredSession() {{ throw new Error("unexpected expired session"); }}
function ownerDeliveryActionContext() {{
  return {{
    run: currentCodexRun(),
    parts: reconciledParts,
    epoch: state.taskSelectionEpoch
  }};
}}
function boundedText(value, fallback) {{ return value ? String(value) : fallback; }}
function humanStatus(value) {{ return String(value); }}

{controller}

elements.confirmApprovedPush.addEventListener("click", confirmApprovedPush);
elements.cancelApprovedPush.addEventListener("click", closeOrHideOwnerPushConfirmation);

async function run() {{
  if ({json.dumps(scenario)} === "success_double_click") {{
    let release;
    const response = new Promise((resolve) => {{ release = resolve; }});
    api = async function(path, options) {{
      assert.match(path, /push-attempts$/);
      assert.equal(options.body.request_identity, context.request_identity);
      postCount += 1;
      return response;
    }};
    const first = elements.confirmApprovedPush.click();
    const second = elements.confirmApprovedPush.click();
    assert.equal(second, undefined);
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(postCount, 1);
    assert.equal(state.ownerPushConfirmationState.phase, "running");
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.equal(elements.confirmApprovedPush.textContent, "Pushing…");
    assert.equal(elements.cancelApprovedPush.textContent, "Hide");
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /continues|processing/i);
    elements.cancelApprovedPush.click();
    assert.equal(elements.ownerPushConfirmationDialog.open, false);
    assert.equal(state.ownerPushConfirmationContext, context);
    assert.equal(postCount, 1);
    renderWorkspace();
    assert.equal(state.ownerPushConfirmationState.phase, "running");
    assert.equal(elements.confirmOwnerPush.disabled, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /awaiting canonical/i);
    release({{
      push_execution: {{ state: "PUSHED" }},
      delivery_result: {{ status: "DELIVERED" }}
    }});
    await first;
    assert.equal(state.pending.size, 0);
    assert.equal(state.ownerPushConfirmationState.phase, "succeeded");
    assert.equal(elements.ownerPushConfirmationDialog.open, false);
    assert.equal(refreshCount, 1);
  }} else if ({json.dumps(scenario)} === "safe_pre_effect_409") {{
    api = async function(path) {{
      if (/push-attempts$/.test(path)) {{
        postCount += 1;
        throw new ApiError(
          409,
          "REPOSITORY_MUTATION_ACTIVE",
          "Repository evidence is being refreshed. No Push was started.",
          {{}},
          "twos",
          {{ request_accepted: false, remote_effect: "none", retry_safe: true }}
        );
      }}
      getCount += 1;
      reconciledParts.pushConfirmation = {{
        state: "ready_for_confirmation",
        can_confirm: true,
        plan_id: context.plan_id,
        request_identity: context.request_identity,
        progress: "Ready for explicit Owner confirmation."
      }};
      return {{
        run_id: "1",
        push_delivery: {{ confirmation: reconciledParts.pushConfirmation }}
      }};
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 1);
    assert.equal(getCount, 1);
    assert.equal(state.pending.size, 0);
    assert.equal(state.ownerPushConfirmationState.phase, "ready_for_confirmation");
    assert.equal(elements.confirmApprovedPush.disabled, false);
    assert.equal(elements.confirmApprovedPush.textContent, "Confirm Push");
    assert.equal(elements.cancelApprovedPush.textContent, "Cancel");
    assert.equal(elements.ownerPushConfirmationDialog.open, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /No Push was started/);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /did not retry automatically/i);
  }} else if ({json.dumps(scenario)} === "response_loss_reconciles_delivery") {{
    api = async function(path) {{
      if (/push-attempts$/.test(path)) {{
        postCount += 1;
        throw new ApiError(0, "NETWORK_ERROR", "Connection was lost.", {{}}, "network");
      }}
      getCount += 1;
      canonicalState = "DELIVERED";
      reconciledParts.pushActions = {{ can_confirm_push: false }};
      reconciledParts.pushConfirmation = {{
        state: "succeeded",
        can_confirm: false,
        plan_id: context.plan_id,
        execution_id: "push_test",
        request_accepted: true,
        request_identity: context.request_identity,
        progress: "Push completed and the exact remote SHA was verified."
      }};
      return {{
        run_id: "1",
        push_delivery: {{ confirmation: reconciledParts.pushConfirmation }}
      }};
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 1);
    assert.equal(getCount, 1);
    assert.equal(state.ownerPushConfirmationState.phase, "succeeded");
    assert.equal(elements.ownerPushConfirmationDialog.open, false);
    assert.equal(state.ownerPushConfirmationContext, null);
  }} else if ({json.dumps(scenario)} === "running_projection_polls_until_terminal") {{
    api = async function(path) {{
      if (/push-attempts$/.test(path)) {{
        postCount += 1;
        throw new ApiError(0, "REQUEST_TIMEOUT", "Connection was lost.", {{}}, "network");
      }}
      getCount += 1;
      reconciledParts.pushActions = {{ can_confirm_push: false }};
      reconciledParts.pushConfirmation = getCount === 1 ? {{
        state: "running",
        can_confirm: false,
        plan_id: context.plan_id,
        execution_id: "push_test",
        request_accepted: true,
        request_identity: context.request_identity,
        progress: "Push execution is running independently of this dialog."
      }} : {{
        state: "succeeded",
        can_confirm: false,
        plan_id: context.plan_id,
        execution_id: "push_test",
        request_accepted: true,
        request_identity: context.request_identity,
        progress: "Push completed and the exact remote SHA was verified."
      }};
      return {{
        run_id: "1",
        push_delivery: {{ confirmation: reconciledParts.pushConfirmation }}
      }};
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 1);
    assert.equal(getCount, 2);
    assert.equal(state.ownerPushConfirmationState.phase, "succeeded");
    assert.equal(state.ownerPushConfirmationContext, null);
  }} else if ({json.dumps(scenario)} === "definitive_pre_effect_block_keeps_reason") {{
    api = async function(path) {{
      if (/push-attempts$/.test(path)) {{
        postCount += 1;
        throw new ApiError(
          409,
          "PUSH_PLAN_EXPIRED",
          "The approved Push Plan expired. Review a new Plan.",
          {{}},
          "twos",
          {{ request_accepted: false, remote_effect: "none", retry_safe: false }}
        );
      }}
      getCount += 1;
      reconciledParts.pushActions = {{ can_confirm_push: false }};
      reconciledParts.pushConfirmation = {{
        state: "blocked",
        can_confirm: false,
        plan_id: context.plan_id,
        request_identity: context.request_identity,
        request_accepted: false,
        reason: "The approved Push Plan expired. Review a new Plan."
      }};
      return {{
        run_id: "1",
        push_delivery: {{ confirmation: reconciledParts.pushConfirmation }}
      }};
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 1);
    assert.equal(getCount, 1);
    assert.equal(state.ownerPushConfirmationState.phase, "blocked");
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /expired/);
  }} else if ({json.dumps(scenario)} === "refresh_wait_blocks_before_request") {{
    waitForOwnerPushRefresh = async function() {{
      throw new ApiError(
        409,
        "WORKSPACE_REFRESH_ACTIVE",
        "Read-only evidence refresh is still active. No Push request was sent.",
        {{}},
        "product"
      );
    }};
    api = async function() {{
      postCount += 1;
      throw new Error("request must not be sent");
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 0);
    assert.equal(state.ownerPushConfirmationState.phase, "ready_for_confirmation");
    assert.equal(elements.confirmApprovedPush.disabled, false);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /No Push request was sent/);
  }} else if ({json.dumps(scenario)} === "persisted_running_blocks_second_request") {{
    reconciledParts.pushConfirmation = {{
      state: "running",
      can_confirm: false,
      plan_id: context.plan_id,
      request_identity: context.request_identity,
      progress: "Push execution is running independently of this dialog."
    }};
    api = async function() {{
      postCount += 1;
      throw new Error("a second request must not be sent");
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 0);
    assert.equal(state.ownerPushConfirmationState.phase, "running");
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.equal(elements.cancelApprovedPush.textContent, "Hide");
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /running independently/i);
  }} else if ({json.dumps(scenario)} === "unapproved_projection_blocks_with_reason") {{
    reconciledParts.pushConfirmation = {{
      state: "blocked",
      can_confirm: false,
      plan_id: context.plan_id,
      request_identity: context.request_identity,
      reason: "Approve this exact Push Plan before confirmation."
    }};
    api = async function() {{
      postCount += 1;
      throw new Error("an unapproved Plan must not submit");
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 0);
    assert.equal(state.ownerPushConfirmationState.phase, "blocked");
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /Approve this exact Push Plan/);
  }} else if ({json.dumps(scenario)} === "request_identity_drift_blocks_before_post") {{
    reconciledParts.pushConfirmation.request_identity = "f".repeat(64);
    api = async function() {{
      postCount += 1;
      throw new Error("a drifted request identity must not submit");
    }};
    await elements.confirmApprovedPush.click();
    assert.equal(postCount, 0);
    assert.equal(state.ownerPushConfirmationState.phase, "blocked");
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /request identity changed/i);
  }} else if ({json.dumps(scenario)} === "unknown_effect_survives_hide_render_reopen") {{
    reconciledParts.pushConfirmation = {{
      state: "ready_for_confirmation",
      can_confirm: true,
      plan_id: context.plan_id,
      request_identity: context.request_identity,
      progress: "Ready for explicit Owner confirmation."
    }};
    let rejectPost;
    const pendingPost = new Promise((resolve, reject) => {{ rejectPost = reject; }});
    api = async function(path) {{
      if (/push-attempts$/.test(path)) {{
        postCount += 1;
        return pendingPost;
      }}
      getCount += 1;
      throw new ApiError(0, "NETWORK_ERROR", "Connection was lost.", {{}}, "network");
    }};
    const submission = elements.confirmApprovedPush.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(state.ownerPushConfirmationState.phase, "running");
    elements.cancelApprovedPush.click();
    assert.equal(elements.ownerPushConfirmationDialog.open, false);
    assert.equal(state.ownerPushConfirmationContext, context);
    rejectPost(new ApiError(0, "REQUEST_TIMEOUT", "Connection was lost.", {{}}, "network"));
    await submission;
    assert.equal(postCount, 1);
    assert.equal(getCount, 1);
    assert.ok(renderCount >= 1);
    assert.equal(state.ownerPushConfirmationState.phase, "needs_review");
    assert.equal(elements.confirmOwnerPush.disabled, true);
    assert.equal(ownerPushConfirmationCanConfirm(reconciledParts), false);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /No automatic retry/i);
    openOwnerPushConfirmation();
    assert.equal(elements.ownerPushConfirmationDialog.open, true);
    assert.equal(state.ownerPushConfirmationState.phase, "needs_review");
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.equal(postCount, 1);
  }} else if ({json.dumps(scenario)} === "native_cancel_while_running_uses_truthful_hide") {{
    let releasePost;
    const pendingPost = new Promise((resolve) => {{ releasePost = resolve; }});
    api = async function(path) {{
      if (/push-attempts$/.test(path)) {{
        postCount += 1;
        return pendingPost;
      }}
      throw new Error("native cancel must not create a reconciliation request");
    }};
    const submission = elements.confirmApprovedPush.click();
    await new Promise((resolve) => setTimeout(resolve, 0));
    assert.equal(postCount, 1);
    assert.equal(state.ownerPushConfirmationState.phase, "running");
    assert.equal(elements.cancelApprovedPush.textContent, "Hide");
    const prevented = elements.ownerPushConfirmationDialog.cancel();
    assert.equal(prevented, true);
    assert.equal(elements.ownerPushConfirmationDialog.open, false);
    assert.equal(state.ownerPushConfirmationContext, context);
    assert.ok(renderCount >= 1);
    assert.equal(elements.confirmOwnerPush.disabled, true);
    assert.ok(feedback.some((item) => /does not cancel an accepted request/i.test(item.message)));
    releasePost({{
      push_execution: {{ state: "PUSHED" }},
      delivery_result: {{ status: "DELIVERED" }}
    }});
    await submission;
    assert.equal(postCount, 1);
    assert.equal(state.ownerPushConfirmationState.phase, "succeeded");
    assert.equal(state.ownerPushConfirmationContext, null);
  }} else if ({json.dumps(scenario)} === "ready_projection_missing_identity_is_blocked") {{
    reconciledParts.pushConfirmation = {{
      state: "ready_for_confirmation",
      can_confirm: true,
      plan_id: context.plan_id,
      request_identity: "",
      progress: "Ready for explicit Owner confirmation."
    }};
    renderWorkspace();
    assert.equal(state.ownerPushConfirmationState.phase, "blocked");
    assert.equal(elements.confirmOwnerPush.disabled, true);
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /request identity is unavailable or malformed/i);
    elements.ownerPushConfirmationDialog.close();
    state.ownerPushConfirmationContext = null;
    openOwnerPushConfirmation();
    assert.equal(elements.ownerPushConfirmationDialog.open, false);
    assert.equal(state.ownerPushConfirmationContext, null);
    assert.ok(feedback.some((item) => /request identity is unavailable or malformed/i.test(item.message)));
    assert.equal(postCount, 0);
  }} else if ({json.dumps(scenario)} === "ready_projection_without_eligibility_is_blocked") {{
    reconciledParts.pushConfirmation = {{
      state: "ready_for_confirmation",
      can_confirm: false,
      plan_id: context.plan_id,
      request_identity: context.request_identity,
      progress: "Ready for explicit Owner confirmation."
    }};
    renderWorkspace();
    assert.equal(state.ownerPushConfirmationState.phase, "blocked");
    assert.equal(elements.confirmOwnerPush.disabled, true);
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /does not admit final confirmation/i);
    elements.ownerPushConfirmationDialog.close();
    state.ownerPushConfirmationContext = null;
    openOwnerPushConfirmation();
    assert.equal(elements.ownerPushConfirmationDialog.open, true);
    assert.equal(state.ownerPushConfirmationState.phase, "blocked");
    assert.equal(elements.confirmApprovedPush.disabled, true);
    assert.match(elements.ownerPushConfirmationStatusMessage.textContent, /does not admit final confirmation/i);
    assert.equal(postCount, 0);
  }} else {{
    throw new Error("unknown scenario");
  }}
  console.log(JSON.stringify({{
    scenario: {json.dumps(scenario)},
    postCount,
    getCount,
    phase: state.ownerPushConfirmationState.phase,
    feedbackCount: feedback.length,
    renderCount
  }}));
}}

run().catch((error) => {{
  console.error(error.stack || String(error));
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _run_real_api_error_parser() -> dict[str, object]:
    source = _source(SCRIPT)
    api_error = _slice(source, "class ApiError", "const byId")
    api_function = _slice(source, "async function api", "function setVisible")
    product_message = _slice(
        source,
        "function productActionMessage",
        "function handleExpiredSession",
    )
    envelope = {
        "error": {
            "code": "http_error",
            "message": "Request failed.",
            "request_id": "request-test",
            "details": {
                "code": "REPOSITORY_MUTATION_ACTIVE",
                "message": "Repository evidence is being refreshed. No Push was started.",
                "request_accepted": False,
                "remote_effect": "none",
                "retry_safe": True,
            },
        }
    }
    harness = f"""
const window = {{ setTimeout, clearTimeout }};
{api_error}
{api_function}
{product_message}
global.fetch = async function() {{
  return {{
    ok: false,
    status: 409,
    async text() {{ return {json.dumps(json.dumps(envelope))}; }}
  }};
}};
(async function() {{
  try {{
    await api("/api/push-plans/test/push-attempts", {{ method: "POST" }});
    throw new Error("expected API failure");
  }} catch (error) {{
    if (!(error instanceof ApiError)) throw error;
    console.log(JSON.stringify({{
      code: error.code,
      message: error.message,
      category: error.category,
      details: error.details,
      ownerMessage: productActionMessage(error)
    }}));
  }}
}})().catch(function(error) {{
  console.error(error.stack || String(error));
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _run_controlled_response_body_timeout() -> dict[str, object]:
    source = _source(SCRIPT)
    api_error = _slice(source, "class ApiError", "const byId")
    api_function = _slice(source, "async function api", "function setVisible")
    harness = f"""
const assert = require("node:assert/strict");
let timerCallback = null;
let timerActive = false;
let clearCount = 0;
let bodyStartedResolve;
const bodyStarted = new Promise(function(resolve) {{ bodyStartedResolve = resolve; }});
const window = {{
  setTimeout(callback, delay) {{
    assert.equal(delay, 37);
    assert.equal(timerCallback, null);
    timerCallback = callback;
    timerActive = true;
    return 91;
  }},
  clearTimeout(identity) {{
    assert.equal(identity, 91);
    assert.equal(timerActive, true);
    timerActive = false;
    clearCount += 1;
  }}
}};
{api_error}
{api_function}
global.fetch = async function(path, request) {{
  assert.equal(path, "/api/controlled-body-timeout");
  assert.ok(request.signal);
  return {{
    ok: true,
    status: 200,
    text() {{
      bodyStartedResolve();
      return new Promise(function(resolve, reject) {{
        request.signal.addEventListener("abort", function() {{
          reject(new Error("controlled response body aborted"));
        }}, {{ once: true }});
      }});
    }}
  }};
}};
(async function() {{
  const pending = api("/api/controlled-body-timeout", {{ timeoutMs: 37 }});
  await bodyStarted;
  assert.equal(timerActive, true);
  assert.equal(clearCount, 0);
  assert.equal(typeof timerCallback, "function");
  timerCallback();
  let caught = null;
  try {{
    await pending;
  }} catch (error) {{
    caught = error;
  }}
  assert.ok(caught instanceof ApiError);
  assert.equal(caught.code, "REQUEST_TIMEOUT");
  assert.equal(caught.category, "network");
  assert.equal(timerActive, false);
  assert.equal(clearCount, 1);
  console.log(JSON.stringify({{
    code: caught.code,
    category: caught.category,
    timer_active_while_body_pending: true,
    clear_count: clearCount
  }}));
}})().catch(function(error) {{
  console.error(error.stack || String(error));
  process.exitCode = 1;
}});
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_owner_push_confirmation_has_modal_local_truth_and_responsive_copy() -> None:
    page = _source(HTML)
    styles = _source(STYLES)

    for selector in (
        "owner-push-confirmation-status",
        "owner-push-confirmation-status-label",
        "owner-push-confirmation-status-message",
    ):
        assert f'id="{selector}"' in page
    assert 'role="status"' in page
    assert 'aria-live="polite"' in page
    assert "owner-push-confirmation-status[data-state=\"submitting\"]" in styles
    assert "owner-push-confirmation-status[data-state=\"needs_review\"]" in styles
    assert "box-sizing: border-box" in styles
    assert "#owner-push-confirmation-dialog dd" in styles
    assert "overflow-wrap: anywhere" in styles
    assert "width: min(46rem, calc(100vw - 2rem))" in styles
    assert "max-height: calc(100dvh - 2rem)" in styles
    assert "overflow: auto" in styles
    assert "@media (max-width: 420px)" in styles
    assert "width: calc(100vw - 1rem)" in styles
    assert ".confirmation-actions {\n    align-items: stretch;\n    flex-direction: column;" in styles
    assert ".confirmation-actions .button," in styles

    root_font_px = 16
    desktop_viewport_px = 1280
    mobile_viewport_px = 390
    desktop_dialog_px = min(46 * root_font_px, desktop_viewport_px - 2 * root_font_px)
    mobile_dialog_px = mobile_viewport_px - root_font_px
    assert desktop_dialog_px == 736
    assert desktop_dialog_px < desktop_viewport_px
    assert mobile_dialog_px == 374
    assert mobile_dialog_px < mobile_viewport_px


def test_delivered_owner_card_resolves_exact_verified_remote_sha() -> None:
    script = _source(SCRIPT)
    helper = _slice(
        script,
        "function ownerVerifiedRemoteSha",
        "function canonicalCommitState",
    )
    rendering = _slice(
        script,
        "function renderOwnerCommitPushDelivery",
        "function confirmationListText",
    )
    assert "receipt.verified_remote_sha" in helper
    assert "receipt.reconciliation" not in helper
    assert "pushExecution.post_push" not in helper
    assert "pushExecution.advanced" not in helper
    assert "ownerVerifiedRemoteSha(parts)" in rendering
    assert '"Receipt unavailable"' not in rendering
    assert "Verified receipt requires review" in rendering
    styles = _source(STYLES)
    assert "overflow-wrap: anywhere" in styles


def test_owner_push_confirmation_waits_for_refresh_and_has_bounded_reconciliation() -> None:
    script = _source(SCRIPT)
    confirmation = _slice(
        script,
        "async function confirmApprovedPush",
        "async function decideAcceptance",
    )
    opening = _slice(
        script,
        "function openOwnerPushConfirmation",
        "async function reviewCommitPlan",
    )
    action_render = _slice(
        script,
        "function renderActionAvailability",
        "function renderHeaderStatus",
    )
    dialog_cancel = _slice(
        script,
        'elements.ownerPushConfirmationDialog.addEventListener("cancel"',
        "elements.cancelCodex.addEventListener",
    )

    assert "await waitForOwnerPushRefresh()" in confirmation
    assert "state.pending.has(\"confirm-owner-push\")" in confirmation
    assert "state.pending.add(\"confirm-owner-push\")" in confirmation
    assert "timeoutMs: OWNER_PUSH_RESPONSE_TIMEOUT_MS" in confirmation
    assert "await reconcileOwnerPushConfirmation" in confirmation
    assert "state.pending.delete(\"confirm-owner-push\")" in confirmation
    assert "performAction(" not in confirmation
    assert "context.parts.pushConfirmation.request_identity" in opening
    assert "request_identity: context.request_identity" in confirmation
    assert "beginOwnerPushConfirmationReconciliation(context)" in confirmation
    assert "markOwnerPushConfirmationUncertain" in script
    assert 'if (ownerPushConfirmationRequestInFlight(parts)) return "PUSHING";' in script
    assert "!ownerPushConfirmationCanConfirm(ownerDelivery)" in action_render
    assert "canonicalPushActions.can_confirm_push === true" not in action_render
    assert '"ready_for_confirmation"' in opening
    assert 'typeof legacyDetails.code === "string"' in script
    assert 'typeof legacyDetails.message === "string"' in script
    assert "pushConfirmation: pushConfirmation" in script
    assert "ownerPushConfirmationCanConfirm(parts)" in script
    assert "persistedPhase !== \"ready_for_confirmation\"" in script
    assert "event.preventDefault()" in dialog_cancel
    assert "closeOrHideOwnerPushConfirmation()" in dialog_cancel


def test_real_api_parser_preserves_nested_fastapi_push_rejection_truth() -> None:
    parsed = _run_real_api_error_parser()
    assert parsed["code"] == "REPOSITORY_MUTATION_ACTIVE"
    assert parsed["message"] == "Repository evidence is being refreshed. No Push was started."
    assert parsed["ownerMessage"] == parsed["message"]
    assert parsed["category"] == "twos"
    assert parsed["details"] == {
        "code": "REPOSITORY_MUTATION_ACTIVE",
        "message": "Repository evidence is being refreshed. No Push was started.",
        "request_accepted": False,
        "remote_effect": "none",
        "retry_safe": True,
    }


def test_api_timeout_remains_active_through_response_body_consumption() -> None:
    result = _run_controlled_response_body_timeout()
    assert result == {
        "code": "REQUEST_TIMEOUT",
        "category": "network",
        "timer_active_while_body_pending": True,
        "clear_count": 1,
    }


def test_actual_final_confirmation_click_path_is_single_flight_and_visible() -> None:
    result = _run_node_scenario("success_double_click")
    assert result["postCount"] == 1
    assert result["phase"] == "succeeded"


def test_actual_final_confirmation_click_path_recovers_safe_409_in_modal() -> None:
    result = _run_node_scenario("safe_pre_effect_409")
    assert result["postCount"] == 1
    assert result["getCount"] == 1
    assert result["phase"] == "ready_for_confirmation"


def test_actual_final_confirmation_response_loss_reconciles_without_replay() -> None:
    result = _run_node_scenario("response_loss_reconciles_delivery")
    assert result["postCount"] == 1
    assert result["getCount"] == 1
    assert result["phase"] == "succeeded"


def test_running_projection_is_polled_to_terminal_without_transport_replay() -> None:
    result = _run_node_scenario("running_projection_polls_until_terminal")
    assert result["postCount"] == 1
    assert result["getCount"] == 2
    assert result["phase"] == "succeeded"


def test_definitive_pre_effect_block_preserves_exact_reason_without_retry() -> None:
    result = _run_node_scenario("definitive_pre_effect_block_keeps_reason")
    assert result["postCount"] == 1
    assert result["getCount"] == 1
    assert result["phase"] == "blocked"


def test_refresh_collision_is_blocked_before_any_push_request() -> None:
    result = _run_node_scenario("refresh_wait_blocks_before_request")
    assert result["postCount"] == 0
    assert result["phase"] == "ready_for_confirmation"


def test_persisted_running_confirmation_cannot_emit_a_second_request() -> None:
    result = _run_node_scenario("persisted_running_blocks_second_request")
    assert result["postCount"] == 0
    assert result["phase"] == "running"


def test_unapproved_projection_blocks_with_exact_owner_reason() -> None:
    result = _run_node_scenario("unapproved_projection_blocks_with_reason")
    assert result["postCount"] == 0
    assert result["phase"] == "blocked"


def test_request_identity_drift_blocks_before_any_post() -> None:
    result = _run_node_scenario("request_identity_drift_blocks_before_post")
    assert result["postCount"] == 0
    assert result["phase"] == "blocked"


def test_unknown_effect_latch_survives_hide_full_render_and_reopen() -> None:
    result = _run_node_scenario("unknown_effect_survives_hide_render_reopen")
    assert result["postCount"] == 1
    assert result["getCount"] == 1
    assert result["phase"] == "needs_review"


def test_native_dialog_cancel_while_running_uses_truthful_hide_path() -> None:
    result = _run_node_scenario("native_cancel_while_running_uses_truthful_hide")
    assert result["postCount"] == 1
    assert result["phase"] == "succeeded"


def test_ready_projection_missing_request_identity_is_visibly_blocked() -> None:
    result = _run_node_scenario("ready_projection_missing_identity_is_blocked")
    assert result["postCount"] == 0
    assert result["phase"] == "blocked"


def test_ready_projection_without_canonical_eligibility_is_visibly_blocked() -> None:
    result = _run_node_scenario("ready_projection_without_eligibility_is_blocked")
    assert result["postCount"] == 0
    assert result["phase"] == "blocked"
