from __future__ import annotations

import html as html_module
import json
import os
import re
import signal
import shutil
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


def _run_node(source: str) -> dict[str, object]:
    completed = subprocess.run(
        ["node", "-e", source],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout)


def _headless_browser() -> Path:
    candidates = [
        shutil.which("chromium"),
        shutil.which("chromium-browser"),
        shutil.which("google-chrome"),
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise AssertionError(
        "A local Chromium-compatible browser is required for the real 1280px/390px First Run geometry gate."
    )


def _geometry_fixture(surface: str) -> str:
    page = _source(HTML)
    styles = _source(STYLES)
    page = page.replace(
        '<link rel="stylesheet" href="/static_cockpit/vol12_static_mvp/styles.css?v=0.17.0">',
        "<style>" + styles + "</style>",
    )
    page = page.replace(
        '<script src="/static_cockpit/vol12_static_mvp/twos_command_center.js?v=0.17.0" defer></script>',
        "",
    )
    page = page.replace(
        '<div id="loading-view" class="loading-view" role="status" aria-live="polite">',
        '<div id="loading-view" class="loading-view" role="status" aria-live="polite" hidden>',
    )
    long_value = "local-boundary-" + ("0123456789abcdef" * 24)
    page = page.replace("Loading setup state", long_value)
    page = page.replace(
        '<dd id="first-run-data-root">Loading</dd>',
        f'<dd id="first-run-data-root">{long_value}</dd>',
    )
    page = page.replace(
        "Create and save the first task. Saving does not start a Run or contact a provider.",
        long_value,
    )
    if surface == "setup":
        page = page.replace(
            '<section id="first-run-view" class="first-run-shell" hidden',
            '<section id="first-run-view" class="first-run-shell"',
        )
        for identifier in (
            "first-run-installation",
            "first-run-owner",
            "first-run-workspace",
            "first-run-tools",
            "first-run-finish",
            "first-run-blocked",
        ):
            page = page.replace(
                f'<section id="{identifier}" class="first-run-step" hidden',
                f'<section id="{identifier}" class="first-run-step"',
            )
        root_selector = "#first-run-view"
    elif surface == "first_task":
        page = page.replace(
            '<div id="app-view" class="app-shell" hidden>',
            '<div id="app-view" class="app-shell">',
        )
        page = page.replace(
            '<aside id="first-run-first-task-banner" class="first-run-first-task-banner" aria-live="polite" hidden>',
            '<aside id="first-run-first-task-banner" class="first-run-first-task-banner" aria-live="polite">',
        )
        page = page.replace(
            '<div id="task-name-field" class="field-group task-name-field" hidden>',
            '<div id="task-name-field" class="field-group task-name-field">',
        )
        page = page.replace(
            "</head>",
            "<style>.workflow-grid > section:not(#task-card) { display: none !important; }</style></head>",
        )
        root_selector = "#task-card"
    else:
        raise AssertionError(f"Unsupported geometry surface: {surface}")

    measurement = r'''
<script>
(() => {
  const root = document.querySelector(ROOT_SELECTOR);
  const tolerance = 1;
  const clientWidth = document.documentElement.clientWidth;
  const visible = Array.from(root.querySelectorAll("*")).filter((element) => {
    const style = getComputedStyle(element);
    const rect = element.getBoundingClientRect();
    return style.display !== "none" && style.visibility !== "hidden" && rect.width > 0 && rect.height > 0;
  });
  const overflow = visible.map((element) => {
    const rect = element.getBoundingClientRect();
    return {
      id: element.id || "",
      tag: element.tagName.toLowerCase(),
      left: rect.left,
      right: rect.right,
      ownScrollWidth: element.scrollWidth,
      ownClientWidth: element.clientWidth
    };
  }).filter((item) => item.left < -tolerance || item.right > clientWidth + tolerance || item.ownScrollWidth > item.ownClientWidth + tolerance);
  const rootRect = root.getBoundingClientRect();
  const result = {
    innerWidth: window.innerWidth,
    clientWidth,
    documentScrollWidth: document.documentElement.scrollWidth,
    bodyScrollWidth: document.body.scrollWidth,
    rootLeft: rootRect.left,
    rootRight: rootRect.right,
    rootScrollWidth: root.scrollWidth,
    rootClientWidth: root.clientWidth,
    overflow
  };
  const output = document.createElement("pre");
  output.id = "twos-geometry-output";
  output.textContent = JSON.stringify(result);
  document.body.appendChild(output);
  if (window.parent !== window) {
    window.parent.postMessage({twosGeometry: result}, "*");
  }
})();
</script>
'''.replace("ROOT_SELECTOR", json.dumps(root_selector))
    return page.replace("</body>", measurement + "</body>")


def _browser_geometry(tmp_path: Path, *, surface: str, width: int) -> dict[str, object]:
    browser = _headless_browser()
    page = tmp_path / f"{surface}-{width}.html"
    # macOS headless Chrome clamps its outer window to >=500 CSS pixels.
    # A real fixed-width iframe establishes the requested CSS viewport without
    # scaling or weakening the innerWidth/media-query/overflow assertions.
    fixture = html_module.escape(_geometry_fixture(surface), quote=True)
    wrapper = (
        '<!doctype html><html><head><meta charset="utf-8">'
        '<script>window.addEventListener("message", (event) => {'
        'if (event.source !== document.querySelector("iframe").contentWindow || '
        '!event.data.twosGeometry) return;'
        'const output = document.createElement("pre");'
        'output.id = "twos-geometry-output";'
        'output.textContent = JSON.stringify(event.data.twosGeometry);'
        'document.body.appendChild(output);});</script></head><body>'
        f'<iframe style="display:block;border:0;width:{width}px;height:20000px" '
        f'srcdoc="{fixture}"></iframe></body></html>'
    )
    page.write_text(wrapper, encoding="utf-8")
    profile = tmp_path / f"browser-profile-{surface}-{width}"
    command = [
        str(browser),
        "--headless=new",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-gpu",
        "--disable-sync",
        "--hide-scrollbars",
        "--metrics-recording-only",
        "--no-default-browser-check",
        "--no-first-run",
        "--force-device-scale-factor=1",
        f"--user-data-dir={profile}",
        f"--window-size={width},1400",
        "--dump-dom",
        page.as_uri(),
    ]
    process = subprocess.Popen(
        command,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=10)
    except subprocess.TimeoutExpired:
        # The macOS Chrome wrapper can keep its browser process alive after
        # --dump-dom has emitted the complete document. Terminate the isolated
        # process group and use only the DOM it already rendered.
        os.killpg(process.pid, signal.SIGTERM)
        try:
            stdout, stderr = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            stdout, stderr = process.communicate(timeout=5)
    match = re.search(
        r'<pre id="twos-geometry-output">(.*?)</pre>',
        stdout,
        re.DOTALL,
    )
    assert match is not None, stderr[-2000:]
    return json.loads(html_module.unescape(match.group(1)))


def _auth_render_result() -> dict[str, object]:
    script = _source(SCRIPT)
    controller = _slice(script, "function firstRunIsIncomplete", "function authFields")
    harness = r'''
const assert = require("node:assert/strict");
const AUTH_STATES = {
  LOADING: "loading",
  SIGNED_OUT: "signed_out",
  SIGNING_UP: "signing_up",
  LOGGING_IN: "logging_in",
  SIGNED_IN: "signed_in",
  ERROR: "error"
};
function element(text) {
  return {
    hidden: false,
    disabled: false,
    textContent: text || "",
    dataset: {},
    classList: { add() {}, remove() {} }
  };
}
const elements = {
  body: element(), loadingView: element(), sessionErrorView: element(),
  firstRunView: element(), publicView: element(), appView: element(),
  landingView: element(), signupView: element(), loginView: element(),
  headerSignup: element(), landingSignup: element(), loginToSignup: element(),
  loginFormError: element("Incorrect username or password."),
  signupSubmit: element(), loginSubmit: element(), accountUsername: element()
};
elements.loginFormError.hidden = false;
const state = {
  auth: AUTH_STATES.ERROR,
  errorScope: "form",
  authView: "login",
  user: null,
  firstRun: {
    enabled: true,
    state: "workspace_pending",
    owner_exists: true
  },
  tasks: [],
  pending: new Set()
};
function setVisible(target, visible) { target.hidden = !visible; }
function setAuthFormError(mode, message) {
  assert.equal(mode, "login");
  elements.loginFormError.textContent = message || "";
  elements.loginFormError.hidden = !message;
}
function humanStatus(value) { return String(value || ""); }
function setStatusLabel() {}
function replaceText() {}
''' + controller + r'''
renderAuthShell();
const preserved = elements.loginFormError.textContent;
elements.loginFormError.textContent = "";
elements.loginFormError.hidden = true;
state.auth = AUTH_STATES.SIGNED_OUT;
renderAuthShell();
console.log(JSON.stringify({
  preserved,
  initialGuidance: elements.loginFormError.textContent,
  loginVisible: !elements.loginView.hidden,
  signupHidden: elements.signupView.hidden && elements.headerSignup.hidden
}));
'''
    return _run_node(harness)


def _signed_in_failure_result() -> dict[str, object]:
    script = _source(SCRIPT)
    controller = _slice(
        script,
        "async function completeSignedInTransition",
        "function renderAuthSubmissionFailure",
    )
    harness = r'''
const assert = require("node:assert/strict");
const AUTH_STATES = { SIGNED_IN: "signed_in" };
const SETUP_ROUTES = { STATUS: "/api/setup/status" };
const FIRST_RUN_RECONCILE_TIMEOUT_MS = 5000;
const state = {
  auth: "signed_out",
  errorScope: null,
  user: null,
  firstRun: { enabled: true, state: "workspace_pending" }
};
const elements = {
  workbenchMain: { focus() { throw new Error("workbench must remain unavailable"); } }
};
let renders = 0;
let refreshes = 0;
let visibleSurface = "login";
let setupMessage = "";
let setupTone = "";
function firstRunIsIncomplete() {
  return Boolean(state.firstRun && state.firstRun.enabled === true && state.firstRun.state !== "ready");
}
function hidePassword() {}
function resetProtectedState() {}
function renderAuthShell() {
  renders += 1;
  visibleSurface = state.auth === AUTH_STATES.SIGNED_IN && firstRunIsIncomplete()
    ? "first-run"
    : "workbench";
}
function setFirstRunMessage(message, tone) { setupMessage = message; setupTone = tone; }
function setFeedback() {}
async function refreshWorkspace() { refreshes += 1; }
async function api(path, options) {
  assert.equal(path, SETUP_ROUTES.STATUS);
  assert.equal(options.timeoutMs, FIRST_RUN_RECONCILE_TIMEOUT_MS);
  throw new Error("status unavailable");
}
''' + controller + r'''
async function run() {
  await completeSignedInTransition(
    { username: "owner" },
    { password: { value: "temporary" } },
    "login"
  );
  console.log(JSON.stringify({
    auth: state.auth,
    renders,
    refreshes,
    visibleSurface,
    setupMessage,
    setupTone
  }));
}
run().catch((error) => { console.error(error); process.exit(1); });
'''
    return _run_node(harness)


def _owner_request_result(scenario: str) -> dict[str, object]:
    script = _source(SCRIPT)
    identity = _slice(
        script,
        "function secureRequestIdentity",
        "function openCodexRunConfirmation",
    )
    controller = _slice(
        script,
        "function setupStepCompleted",
        "async function authorizeFirstRunWorkspace",
    )
    crypto = {
        "secure_unavailable": "const window = {};",
        "secure_throws": (
            "const window = { crypto: { randomUUID() { "
            'throw new Error("secure random failed"); } } };'
        ),
    }.get(
        scenario,
        (
            "const window = { crypto: { randomUUID() { "
            'uuidCalls += 1; return "owner-request-fixed-0001"; } } };'
        ),
    )
    harness = r'''
const assert = require("node:assert/strict");
class ApiError extends Error {
  constructor(status, code, message, fields, category) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields || {};
    this.category = category || "api";
  }
}
const AUTH_STATES = { SIGNED_IN: "signed_in", SIGNED_OUT: "signed_out" };
const AUTH_ROUTES = { SESSION: "/api/auth/session" };
const SETUP_ROUTES = {
  STATUS: "/api/setup/status",
  START: "/api/setup/start",
  OWNER: "/api/setup/owner"
};
const FIRST_RUN_ACTION_TIMEOUT_MS = 15000;
const FIRST_RUN_RECONCILE_TIMEOUT_MS = 5000;
let uuidCalls = 0;
''' + crypto + r'''
function input(value) {
  return { value, focus() {}, setAttribute() {}, removeAttribute() {} };
}
function button(text) {
  return { textContent: text, disabled: false, setAttribute() {}, removeAttribute() {} };
}
const elements = {
  firstRunOwnerForm: { checkValidity() { return true; }, reportValidity() {} },
  firstRunOwnerUsername: input("owner"),
  firstRunOwnerPassword: input("correct-password"),
  firstRunOwnerPasswordConfirmation: input("correct-password"),
  firstRunSetupAuthorization: input("setup-authorization-value"),
  firstRunCreateOwner: button("Create First Owner"),
  firstRunStart: button("Start Setup"),
  loginFormError: { textContent: "", hidden: true }
};
const state = {
  pending: new Set(),
  firstOwnerRequestId: null,
  firstRun: {
    enabled: true,
    state: "owner_creation_pending",
    owner_exists: false,
    completed_steps: ["welcome", "installation"]
  },
  auth: AUTH_STATES.SIGNED_OUT,
  errorScope: null,
  authView: "landing",
  user: null,
  tasks: []
};
let posts = [];
let statusReads = 0;
let releaseOwner;
let firstAttempt = true;
let firstRunMessage = "";
let firstRunMessageTone = "";
const scenario = ''' + json.dumps(scenario) + r''';
function renderFirstRun() {}
function renderAuthShell() {}
function firstRunIsIncomplete() { return state.firstRun.state !== "ready"; }
function setFirstRunMessage(message, tone) {
  firstRunMessage = message || "";
  firstRunMessageTone = tone || "";
}
function clearAuthErrors() {}
function setAuthFormError(mode, message) {
  assert.equal(mode, "login");
  elements.loginFormError.textContent = message;
  elements.loginFormError.hidden = !message;
}
function authenticatedUserFromPayload(value) {
  return value && value.authenticated === true && value.user
    ? { username: value.user.username }
    : null;
}
async function api(path, options) {
  if (path === SETUP_ROUTES.OWNER) {
    assert.equal(options.timeoutMs, FIRST_RUN_ACTION_TIMEOUT_MS);
    posts.push(options.body.request_id);
    if (scenario === "double_click") {
      return new Promise((resolve) => { releaseOwner = resolve; });
    }
    if (scenario === "timeout_retry" && firstAttempt) {
      firstAttempt = false;
      throw new ApiError(0, "REQUEST_TIMEOUT", "Request timed out.", {}, "network");
    }
    return {
      enabled: true,
      state: "workspace_pending",
      owner_exists: true,
      authenticated: true,
      user: { username: "owner" },
      completed_steps: ["welcome", "installation", "owner"]
    };
  }
  if (path === SETUP_ROUTES.STATUS) {
    assert.equal(options.timeoutMs, FIRST_RUN_RECONCILE_TIMEOUT_MS);
    statusReads += 1;
    return {
      enabled: true,
      state: "owner_creation_pending",
      owner_exists: false,
      authenticated: false,
      completed_steps: ["welcome", "installation"]
    };
  }
  throw new Error("unexpected API path " + path);
}
''' + identity + controller + r'''
async function run() {
  if (scenario === "double_click") {
    const first = createFirstRunOwner();
    const stableWhilePending = state.firstOwnerRequestId;
    const second = createFirstRunOwner();
    await Promise.resolve();
    assert.equal(posts.length, 1);
    releaseOwner({
      enabled: true,
      state: "workspace_pending",
      owner_exists: true,
      authenticated: true,
      user: { username: "owner" },
      completed_steps: ["welcome", "installation", "owner"]
    });
    await Promise.all([first, second]);
    console.log(JSON.stringify({ posts, stableWhilePending, finalRequestId: state.firstOwnerRequestId, uuidCalls }));
    return;
  }
  if (scenario === "secure_unavailable" || scenario === "secure_throws") {
    await createFirstRunOwner();
    console.log(JSON.stringify({
      posts,
      finalRequestId: state.firstOwnerRequestId,
      firstRunMessage,
      firstRunMessageTone,
      uuidCalls,
      setupState: state.firstRun.state,
      ownerExists: state.firstRun.owner_exists,
      pendingCount: state.pending.size,
      statusReads
    }));
    return;
  }
  await createFirstRunOwner();
  const retainedAfterTimeout = state.firstOwnerRequestId;
  await createFirstRunOwner();
  console.log(JSON.stringify({ posts, statusReads, retainedAfterTimeout, finalRequestId: state.firstOwnerRequestId, uuidCalls }));
}
run().catch((error) => { console.error(error); process.exit(1); });
'''
    return _run_node(harness)


def _secure_request_identity_result() -> dict[str, object]:
    script = _source(SCRIPT)
    identity = _slice(
        script,
        "function secureRequestIdentity",
        "function openCodexRunConfirmation",
    )
    harness = r'''
const assert = require("node:assert/strict");
const window = { crypto: {} };
let uuidCalls = 0;
let byteCalls = 0;
window.crypto.randomUUID = function () {
  uuidCalls += 1;
  return "12345678-1234-4234-8234-123456789abc";
};
window.crypto.getRandomValues = function () {
  byteCalls += 1;
  throw new Error("UUID preference must not invoke the byte fallback");
};
''' + identity + r'''
const uuidIdentity = secureRequestIdentity("owner-");
delete window.crypto.randomUUID;
let byteLength = 0;
window.crypto.getRandomValues = function (bytes) {
  byteCalls += 1;
  byteLength = bytes.length;
  bytes.forEach(function (_value, index) { bytes[index] = index; });
  return bytes;
};
const byteIdentity = secureRequestIdentity("run-");
console.log(JSON.stringify({
  uuidIdentity,
  byteIdentity,
  uuidCalls,
  byteCalls,
  byteLength
}));
'''
    return _run_node(harness)


def _first_task_save_event_result() -> dict[str, object]:
    script = _source(SCRIPT)
    pending = _slice(
        script,
        "function firstRunFirstTaskPending",
        "function firstRunToolStatus",
    )
    action = _slice(script, "async function performAction", "function selectedTask")
    selected = _slice(script, "function selectedTask", "function resetTaskDetails")
    save = _slice(script, "function taskPayload", "async function recomposeTeam")
    submit = _slice(
        script,
        'elements.taskForm.addEventListener("submit", function (event) {',
        "TASK_DETAIL_FIELDS.forEach",
    )
    harness = r'''
const assert = require("node:assert/strict");
class ApiError extends Error {
  constructor(status, code, message, fields, category) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields || {};
    this.category = category || "api";
  }
}
const AUTH_STATES = { SIGNED_IN: "signed_in" };
function input(value) { return { value, required: false }; }
function button(text) {
  return {
    textContent: text,
    disabled: false,
    attributes: {},
    setAttribute(name, value) { this.attributes[name] = value; },
    removeAttribute(name) { delete this.attributes[name]; }
  };
}
let submitHandler = null;
const elements = {
  taskForm: {
    checkValidity() { return true; },
    reportValidity() { throw new Error("valid first task must not report validity"); },
    addEventListener(name, handler) {
      assert.equal(name, "submit");
      submitHandler = handler;
    }
  },
  saveTask: button("Save Task"),
  taskProject: input("7"),
  taskName: input("First owner task"),
  taskTitle: input("Prove the first Owner delivery path"),
  taskAction: input("Analyze"),
  taskWorkflow: input("general"),
  taskForbiddenScope: input("Keep every action local and Owner-controlled."),
  capabilityFocus: input(""),
  riskLevel: input("medium"),
  aiUrgency: input("normal")
};
const TASK_DETAIL_FIELDS = [];
const DEFAULT_BOUNDARY = "Keep every action local and Owner-controlled.";
const state = {
  firstRun: {
    enabled: true,
    state: "ready",
    current_step: "first_task",
    first_task_created: false,
    task_count: 0
  },
  tasks: [],
  creatingTask: true,
  newTaskInitialized: true,
  selectedTaskId: null,
  selectedActivityRunId: "old-run",
  taskSelectionEpoch: 3,
  taskLoadState: "empty",
  taskLoadMessage: "Create the first task.",
  renderedTaskId: null,
  renderedPlanId: "old-plan",
  taskDetailProvenance: {},
  pending: new Set(),
  auth: "signed_in"
};
const serverTasks = [];
const apiCalls = [];
let refreshCount = 0;
let renderCount = 0;
let feedback = null;
let settleFeedback;
const feedbackSettled = new Promise((resolve) => { settleFeedback = resolve; });
function syncTaskRequirements() {}
function renderWorkspace() { renderCount += 1; }
function productActionMessage(error) { return error.message; }
function handleExpiredSession() { throw new Error("session must remain valid"); }
function currentPassedPostApplyVerification() { return null; }
function currentCodexRun() { return null; }
function objectRecord(value) { return value && typeof value === "object" ? value : {}; }
function storePushDeliveryReview() {}
function setFeedback(message, tone) {
  feedback = { message, tone };
  settleFeedback();
}
async function refreshWorkspace(options) {
  assert.deepEqual(options, { force: true });
  refreshCount += 1;
  // This models the server-backed task-list refresh. It deliberately does
  // not assign selectedTaskId; only the production save path may do that.
  state.tasks = serverTasks.map((task) => ({ ...task }));
}
async function api(path, options) {
  apiCalls.push({ path, method: options && options.method, body: options && options.body });
  if (path === "/api/tasks") {
    assert.equal(options.method, "POST");
    const created = {
      id: 41,
      project_id: options.body.project_id,
      title: options.body.title,
      development_task: options.body.development_task,
      objective: options.body.objective
    };
    serverTasks.push(created);
    return { ...created };
  }
  if (path === "/api/ai/team-compose") {
    assert.equal(options.method, "POST");
    assert.equal(options.body.task_id, 41);
    return { task_id: 41, status: "composed" };
  }
  throw new Error("unexpected API path " + path);
}
''' + pending + action + selected + save + submit + r'''
async function run() {
  assert.equal(typeof submitHandler, "function");
  assert.equal(selectedTask(), null);
  let prevented = 0;
  const eventReturn = submitHandler({ preventDefault() { prevented += 1; } });
  assert.equal(eventReturn, undefined);
  await feedbackSettled;
  await new Promise((resolve) => setImmediate(resolve));
  const selectedAfterSave = selectedTask();
  console.log(JSON.stringify({
    prevented,
    selectedTaskId: state.selectedTaskId,
    selectedAfterSaveId: selectedAfterSave && selectedAfterSave.id,
    creatingTask: state.creatingTask,
    newTaskInitialized: state.newTaskInitialized,
    taskSelectionEpoch: state.taskSelectionEpoch,
    refreshCount,
    renderCount,
    feedback,
    apiCalls
  }));
}
run().catch((error) => { console.error(error); process.exit(1); });
'''
    return _run_node(harness)


def test_first_run_markup_shows_seven_truthful_owner_steps_and_passive_tools() -> None:
    page = _source(HTML)
    script = _source(SCRIPT)
    steps = re.findall(r'data-setup-step="([^"]+)"', page)
    assert steps == [
        "welcome",
        "installation",
        "owner",
        "workspace",
        "optional_tools",
        "finish",
        "first_task",
    ]
    assert "Step 07 of 07" in page
    assert "Create First Task" in page
    for selector in (
        "first-run-current-step",
        "first-run-next-action",
        "first-run-blocking-reason",
        "first-run-authorization-state",
        "first-run-refresh-status",
    ):
        assert f'id="{selector}"' in page
    assert "Record Codex Needs Setup" in page
    assert "TWOS does not inspect Codex, contact a provider, or start a Run here" in page
    renderer = _slice(script, "function firstRunAuthorizationSummary", "function renderAuthShell")
    assert "authorization.expired === true" in renderer
    assert "setup.next_action" in renderer
    assert "setup.blocking_reason" in renderer
    assert "elements.firstRunCurrentStep.textContent" in renderer
    advanced = re.search(r"<details class=\"first-run-advanced\"([^>]*)>", page)
    assert advanced is not None
    assert "open" not in advanced.group(1)


def test_existing_login_failure_copy_is_not_replaced_by_resume_guidance() -> None:
    result = _auth_render_result()
    assert result == {
        "preserved": "Incorrect username or password.",
        "initialGuidance": "Log in as the first Owner to resume First Run.",
        "loginVisible": True,
        "signupHidden": True,
    }


def test_signed_in_setup_status_failure_renders_truth_without_opening_workbench() -> None:
    result = _signed_in_failure_result()
    assert result["auth"] == "signed_in"
    assert result["renders"] >= 2
    assert result["refreshes"] == 0
    assert result["visibleSurface"] == "first-run"
    assert result["setupTone"] == "error"
    assert "No setup action was started" in str(result["setupMessage"])


def test_owner_double_click_has_one_post_and_one_stable_request_identity() -> None:
    result = _owner_request_result("double_click")
    assert result["posts"] == ["owner-request-fixed-0001"]
    assert result["stableWhilePending"] == "owner-request-fixed-0001"
    assert result["finalRequestId"] is None
    assert result["uuidCalls"] == 1


def test_uncertain_owner_request_reconciles_and_reuses_identity_on_explicit_retry() -> None:
    result = _owner_request_result("timeout_retry")
    assert result["posts"] == ["owner-request-fixed-0001", "owner-request-fixed-0001"]
    assert result["statusReads"] == 1
    assert result["retainedAfterTimeout"] == "owner-request-fixed-0001"
    assert result["finalRequestId"] is None
    assert result["uuidCalls"] == 1


def test_secure_request_identity_prefers_uuid_then_uses_16_random_bytes() -> None:
    result = _secure_request_identity_result()
    assert result == {
        "uuidIdentity": "owner-12345678-1234-4234-8234-123456789abc",
        "byteIdentity": "run-000102030405060708090a0b0c0d0e0f",
        "uuidCalls": 1,
        "byteCalls": 1,
        "byteLength": 16,
    }


def test_first_owner_blocks_without_post_when_secure_identity_is_unavailable() -> None:
    for scenario in ("secure_unavailable", "secure_throws"):
        result = _owner_request_result(scenario)
        assert result["posts"] == []
        assert result["finalRequestId"] is None
        assert result["firstRunMessageTone"] == "error"
        assert "secure First Owner request identity" in result["firstRunMessage"]
        assert "No Owner request was sent" in result["firstRunMessage"]
        assert result["setupState"] == "owner_creation_pending"
        assert result["ownerExists"] is False
        assert result["pendingCount"] == 0
        assert result["statusReads"] == 0
        for secret in ("correct-password", "setup-authorization-value"):
            assert secret not in json.dumps(result)


def test_action_identities_never_use_time_math_random_or_owner_input_entropy() -> None:
    script = _source(SCRIPT)
    identity = _slice(
        script,
        "function secureRequestIdentity",
        "function openCodexRunConfirmation",
    )
    owner = _slice(
        script,
        "async function createFirstRunOwner",
        "async function authorizeFirstRunWorkspace",
    )
    assert "Date.now()" not in script
    assert "Math.random()" not in script
    assert "performance.now()" not in script
    for clock_or_weak_source in ("Date", "getTime", "performance", "timestamp", "Math.random"):
        assert clock_or_weak_source not in identity
    assert "window.crypto.randomUUID" in identity
    assert "new Uint8Array(16)" in identity
    assert "window.crypto.getRandomValues(bytes)" in identity
    assert 'secureRequestIdentity("")' in owner
    for owner_input in (
        "firstRunOwnerUsername",
        "firstRunOwnerPassword",
        "firstRunOwnerPasswordConfirmation",
        "firstRunSetupAuthorization",
    ):
        assert owner_input not in identity


def test_setup_mutations_are_bounded_reconciled_and_never_start_codex() -> None:
    script = _source(SCRIPT)
    setup = _slice(script, "function setupStepCompleted", "async function logout")
    assert "FIRST_RUN_ACTION_TIMEOUT_MS = 15000" in script
    assert "FIRST_RUN_RECONCILE_TIMEOUT_MS = 5000" in script
    assert setup.count("timeoutMs: FIRST_RUN_ACTION_TIMEOUT_MS") == 6
    assert "await reconcileFirstRunStatus" in setup
    assert "No automatic retry occurred" in setup
    assert "config.settled(reconciled)" in setup
    assert "state.pending.has(\"first-run-action\")" in setup
    assert "state.pending.add(\"first-run-action\")" in setup
    assert "state.pending.delete(\"first-run-action\")" in setup
    for forbidden in (
        "/codex-runs",
        "/codex-packs",
        "/api/providers",
        "startCodexRun(",
        "generatePack(",
        "adapter.detect",
    ):
        assert forbidden not in setup


def test_first_task_defaults_and_requirements_are_scoped_to_ready_zero_task_state() -> None:
    script = _source(SCRIPT)
    pending = _slice(script, "function firstRunFirstTaskPending", "function firstRunToolStatus")
    form = _slice(script, "function initializeNewTaskForm", "async function refreshWorkspace")
    payload = _slice(script, "function taskPayload", "async function persistTask")
    save = _slice(script, "async function saveTask", "async function recomposeTeam")
    assert 'state.firstRun.state === "ready"' in pending
    assert "state.firstRun.first_task_created !== true" in pending
    assert "state.tasks.length === 0" in pending
    assert 'firstRunFirstTaskPending()\n      ? "general"\n      : "product_development"' in form
    assert "const firstTask = firstRunFirstTaskPending() && state.creatingTask" in form
    assert "elements.taskName.required = firstTask" in form
    assert "setVisible(elements.taskNameField, firstTask)" in form
    assert "setVisible(elements.firstRunFirstTaskBanner, firstTask)" in form
    assert 'firstTask ? "Goal or objective" : "Development task"' in form
    assert "if (firstTask) payload.objective = elements.taskTitle.value" in payload
    assert "const savingFirstRunFirstTask = firstRunFirstTaskPending() && state.creatingTask" in save
    assert "await composeTeam(task)" in save
    assert "/codex-packs" not in save
    assert "/codex-runs" not in save


def test_first_task_submit_event_keeps_the_created_task_selected_after_save() -> None:
    result = _first_task_save_event_result()
    assert result["prevented"] == 1
    assert result["selectedTaskId"] == 41
    assert result["selectedAfterSaveId"] == 41
    assert result["creatingTask"] is False
    assert result["newTaskInitialized"] is False
    assert result["taskSelectionEpoch"] == 4
    assert result["refreshCount"] == 1
    assert result["renderCount"] == 1
    assert result["feedback"] == {
        "message": "Task saved. No Run, Pack, or provider action started.",
        "tone": "success",
    }
    calls = result["apiCalls"]
    assert [call["path"] for call in calls] == [
        "/api/tasks",
        "/api/ai/team-compose",
    ]
    created = calls[0]["body"]
    assert created["project_id"] == 7
    assert created["title"] == "First owner task"
    assert created["development_task"] == "Prove the first Owner delivery path"
    assert created["objective"] == "Prove the first Owner delivery path"


def test_first_run_layout_contract_fits_real_1280_and_390_browser_geometry(
    tmp_path: Path,
) -> None:
    styles = _source(STYLES)
    assert "box-sizing: border-box" in styles
    assert ".first-run-card {" in styles
    assert "width: min(100%, 880px);" in styles
    assert "grid-template-columns: repeat(7, minmax(0, 1fr));" in styles
    assert ".first-run-status-summary dd" in styles
    assert "#first-run-message" in styles
    assert ".first-run-first-task-banner p" in styles
    assert styles.count("overflow-wrap: anywhere;") >= 10
    assert "@media (max-width: 760px)" in styles
    assert ".first-run-progress li:nth-child(7)::before" in styles
    assert "@media (max-width: 420px)" in styles
    assert ".first-run-status-actions .button" in styles
    for surface in ("setup", "first_task"):
        for width in (1280, 390):
            geometry = _browser_geometry(tmp_path, surface=surface, width=width)
            assert geometry["innerWidth"] == width
            assert geometry["clientWidth"] == width
            assert geometry["documentScrollWidth"] <= width
            assert geometry["bodyScrollWidth"] <= width
            assert geometry["rootLeft"] >= -1
            assert geometry["rootRight"] <= width + 1
            assert geometry["rootScrollWidth"] <= geometry["rootClientWidth"] + 1
            assert geometry["overflow"] == []
