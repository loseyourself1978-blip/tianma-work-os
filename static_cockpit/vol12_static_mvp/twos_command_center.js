(function () {
  "use strict";

  const AUTH_STATES = Object.freeze({
    LOADING: "loading",
    SIGNED_OUT: "signed_out",
    SIGNING_UP: "signing_up",
    LOGGING_IN: "logging_in",
    SIGNED_IN: "signed_in",
    ERROR: "error"
  });

  const AUTH_ROUTES = Object.freeze({
    SESSION: "/api/auth/session",
    SIGNUP: "/api/auth/signup",
    LOGIN: "/api/auth/login",
    LOGOUT: "/api/auth/logout"
  });

  const DEFAULT_BOUNDARY = "No automatic merge, push, live trading, live betting, or unrestricted command execution.";
  const POLL_INTERVAL_MS = 3000;

  class ApiError extends Error {
    constructor(status, code, message, fields, category) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code || "UNEXPECTED_RESPONSE";
      this.fields = fields && typeof fields === "object" ? fields : {};
      this.category = category || "api";
    }
  }

  const byId = function (id) {
    const element = document.getElementById(id);
    if (!element) {
      throw new Error("Missing required interface element.");
    }
    return element;
  };

  const elements = {
    body: document.body,
    loadingView: byId("loading-view"),
    sessionErrorView: byId("session-error-view"),
    sessionErrorMessage: byId("session-error-message"),
    retrySession: byId("retry-session"),
    publicView: byId("public-view"),
    landingView: byId("landing-view"),
    signupView: byId("signup-view"),
    loginView: byId("login-view"),
    appView: byId("app-view"),
    headerLogin: byId("header-login"),
    headerSignup: byId("header-signup"),
    landingLogin: byId("landing-login"),
    landingSignup: byId("landing-signup"),
    signupBack: byId("signup-back"),
    loginBack: byId("login-back"),
    signupToLogin: byId("signup-to-login"),
    loginToSignup: byId("login-to-signup"),
    signupForm: byId("signup-form"),
    signupUsername: byId("signup-username"),
    signupPassword: byId("signup-password"),
    signupUsernameError: byId("signup-username-error"),
    signupPasswordError: byId("signup-password-error"),
    signupFormError: byId("signup-form-error"),
    signupSubmit: byId("signup-submit"),
    signupPasswordToggle: byId("signup-password-toggle"),
    loginForm: byId("login-form"),
    loginUsername: byId("login-username"),
    loginPassword: byId("login-password"),
    loginUsernameError: byId("login-username-error"),
    loginPasswordError: byId("login-password-error"),
    loginFormError: byId("login-form-error"),
    loginSubmit: byId("login-submit"),
    loginPasswordToggle: byId("login-password-toggle"),
    mobileMenuToggle: byId("mobile-menu-toggle"),
    sidebarClose: byId("sidebar-close"),
    sidebarBackdrop: byId("sidebar-backdrop"),
    taskSidebar: byId("task-sidebar"),
    accountMenuButton: byId("account-menu-button"),
    accountUsername: byId("account-username"),
    accountMenu: byId("account-menu"),
    logoutButton: byId("logout-button"),
    codexHeaderStatus: byId("codex-header-status"),
    workbenchMain: byId("workbench-main"),
    feedback: byId("workbench-feedback"),
    newTask: byId("new-task"),
    taskList: byId("task-list"),
    taskForm: byId("task-form"),
    taskProject: byId("task-project"),
    taskWorkflow: byId("task-workflow"),
    taskTitle: byId("task-title"),
    taskObjective: byId("task-objective"),
    taskSource: byId("task-source"),
    taskOutput: byId("task-output"),
    taskAcceptanceTarget: byId("task-acceptance-target"),
    taskImplementationScope: byId("task-implementation-scope"),
    taskForbiddenScope: byId("task-forbidden-scope"),
    taskAction: byId("task-action"),
    taskStatus: byId("task-status"),
    saveTask: byId("save-task"),
    recomposeTeam: byId("recompose-team"),
    repositoryIdentity: byId("repository-identity"),
    sourceBaseline: byId("source-baseline"),
    capabilityFocus: byId("capability-focus"),
    riskLevel: byId("risk-level"),
    aiUrgency: byId("ai-urgency"),
    aiTeamStatus: byId("ai-team-status"),
    aiCapabilities: byId("ai-capabilities"),
    aiMinimumCount: byId("ai-minimum-count"),
    aiPlanStatus: byId("ai-plan-status"),
    aiWhy: byId("ai-why"),
    aiReasons: byId("ai-reasons"),
    routingStatus: byId("routing-status"),
    routingNextAction: byId("routing-next-action"),
    routingProvider: byId("routing-provider"),
    routingModel: byId("routing-model"),
    routingFallback: byId("routing-fallback"),
    routingCost: byId("routing-cost"),
    routingLatency: byId("routing-latency"),
    routingRecords: byId("routing-records"),
    routingReason: byId("routing-reason"),
    routingDetails: byId("routing-details"),
    packStatus: byId("pack-status"),
    packVersion: byId("pack-version"),
    packApproval: byId("pack-approval"),
    packStages: byId("pack-stages"),
    packAcceptanceTarget: byId("pack-acceptance-target"),
    packBoundaries: byId("pack-boundaries"),
    generatePack: byId("generate-pack"),
    approvePack: byId("approve-pack"),
    packHistory: byId("pack-history"),
    packRaw: byId("pack-raw"),
    packId: byId("pack-id"),
    packBaseline: byId("pack-baseline"),
    runStatus: byId("run-status"),
    codexReadiness: byId("codex-readiness"),
    codexReason: byId("codex-reason"),
    codexNextAction: byId("codex-next-action"),
    runCodex: byId("run-codex"),
    cancelCodex: byId("cancel-codex"),
    codexRunId: byId("codex-run-id"),
    taskRunId: byId("task-run-id"),
    taskRunAction: byId("task-run-action"),
    worktreeBranch: byId("worktree-branch"),
    worktreePath: byId("worktree-path"),
    runExitCode: byId("run-exit-code"),
    runStarted: byId("run-started"),
    runFinished: byId("run-finished"),
    runError: byId("run-error"),
    codexStdout: byId("codex-stdout"),
    codexStderr: byId("codex-stderr"),
    resultStatus: byId("result-status"),
    resultTask: byId("result-task"),
    resultLifecycle: byId("result-lifecycle"),
    resultChangedFiles: byId("result-changed-files"),
    resultSummary: byId("result-summary"),
    resultTests: byId("result-tests"),
    resultBoundary: byId("result-boundary"),
    resultReview: byId("result-review"),
    resultCommit: byId("result-commit"),
    acceptanceStatus: byId("acceptance-status"),
    acceptanceItems: byId("acceptance-items"),
    acceptanceNote: byId("acceptance-note"),
    acceptResult: byId("accept-result"),
    rejectResult: byId("reject-result"),
    compactSyncStatus: byId("compact-sync-status"),
    compactSyncSummary: byId("compact-sync-summary"),
    compactSyncOutput: byId("compact-sync-output"),
    runCompactSync: byId("run-compact-sync"),
    workerDecision: byId("worker-decision"),
    workerReason: byId("worker-reason"),
    workerAudit: byId("worker-audit"),
    workerEngine: byId("worker-engine"),
    workerAcceptanceId: byId("worker-acceptance-id"),
    workerAcceptanceCount: byId("worker-acceptance-count"),
    workerCheckIds: byId("worker-check-ids"),
    workerChecks: byId("worker-checks"),
    workerAuditEvents: byId("worker-audit-events"),
    runtimeHealth: byId("runtime-health"),
    scheduleInterval: byId("schedule-interval"),
    createSchedule: byId("create-schedule"),
    pauseSchedule: byId("pause-schedule"),
    resumeSchedule: byId("resume-schedule"),
    scheduleStatus: byId("schedule-status"),
    scheduleLast: byId("schedule-last"),
    scheduleNext: byId("schedule-next"),
    scheduleCount: byId("schedule-count"),
    scheduleRuns: byId("schedule-runs"),
    providerList: byId("provider-list"),
    toolList: byId("tool-list"),
    auditList: byId("audit-list")
  };

  const state = {
    auth: AUTH_STATES.LOADING,
    authView: "landing",
    errorScope: null,
    user: null,
    pending: new Set(),
    refreshing: false,
    refreshQueued: false,
    workspaceLoaded: false,
    registryLoaded: false,
    projects: [],
    tasks: [],
    runs: [],
    schedules: [],
    audit: [],
    providers: [],
    tools: [],
    aiCapabilityRegistry: [],
    health: null,
    codexStatus: null,
    aiPlan: null,
    acceptance: null,
    packs: [],
    codexRuns: [],
    ownerAcceptance: null,
    selectedTaskId: null,
    selectedPackId: null,
    selectedScheduleId: null,
    creatingTask: false,
    newTaskInitialized: false,
    renderedTaskId: null,
    renderedPlanId: null,
    renderedAcceptanceId: null,
    renderedAcceptanceSignature: null
  };

  async function api(path, options) {
    const request = Object.assign({
      credentials: "same-origin",
      headers: { "Accept": "application/json" }
    }, options || {});
    if (request.body && typeof request.body !== "string") {
      request.headers = Object.assign({}, request.headers, { "Content-Type": "application/json" });
      request.body = JSON.stringify(request.body);
    }

    let response;
    try {
      response = await fetch(path, request);
    } catch (error) {
      throw new ApiError(0, "NETWORK_ERROR", "Unable to connect. Try again.", {}, "network");
    }

    const responseText = await response.text();
    let data = {};
    if (responseText) {
      try {
        data = JSON.parse(responseText);
      } catch (error) {
        throw new ApiError(response.status, "UNEXPECTED_RESPONSE", "Something went wrong. Try again.", {}, "payload");
      }
    }

    if (!response.ok) {
      const legacy = data && data.error && typeof data.error === "object" ? data.error : {};
      const trustedLegacyEnvelope = Boolean(
        data
        && Object.keys(data).length === 1
        && data.error
        && typeof legacy.code === "string"
        && typeof legacy.message === "string"
        && typeof legacy.request_id === "string"
        && Object.prototype.hasOwnProperty.call(legacy, "details")
      );
      const code = typeof data.code === "string" ? data.code : typeof legacy.code === "string" ? legacy.code : "HTTP_ERROR";
      const message = typeof data.message === "string"
        ? data.message
        : typeof legacy.message === "string"
          ? legacy.message
          : typeof data.detail === "string"
            ? data.detail
            : "Something went wrong. Try again.";
      const fields = data.fields && typeof data.fields === "object" ? data.fields : {};
      throw new ApiError(response.status, code, message, fields, trustedLegacyEnvelope ? "twos" : "api");
    }

    return data;
  }

  function setVisible(element, visible) {
    element.hidden = !visible;
  }

  function replaceText(element, value, fallback) {
    element.textContent = value === null || value === undefined || value === "" ? fallback : String(value);
  }

  function clearChildren(element) {
    while (element.firstChild) {
      element.removeChild(element.firstChild);
    }
  }

  function humanStatus(value) {
    return String(value || "waiting")
      .split("_")
      .map(function (part) { return part.charAt(0).toUpperCase() + part.slice(1); })
      .join(" ");
  }

  function formatTime(value) {
    if (!value) return "Not recorded";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? "Not recorded" : date.toLocaleString();
  }

  function setStatusLabel(element, value) {
    const normalized = String(value || "").toLowerCase();
    element.classList.remove("is-success", "is-warning", "is-error");
    if (/accepted|approved|complete|configured|healthy|pass|ready|saved/.test(normalized)) {
      element.classList.add("is-success");
    } else if (/fail|error|timed out|cancel/.test(normalized)) {
      element.classList.add("is-error");
    } else if (/waiting|review|required|setup|queued|running|draft|unavailable/.test(normalized)) {
      element.classList.add("is-warning");
    }
  }

  function renderAuthShell() {
    elements.body.dataset.authState = state.auth;
    const isLoading = state.auth === AUTH_STATES.LOADING;
    const sessionError = state.auth === AUTH_STATES.ERROR && state.errorScope === "session";
    const isSignedIn = state.auth === AUTH_STATES.SIGNED_IN;
    const showPublic = !isLoading && !sessionError && !isSignedIn;

    setVisible(elements.loadingView, isLoading);
    setVisible(elements.sessionErrorView, sessionError);
    setVisible(elements.publicView, showPublic);
    setVisible(elements.appView, isSignedIn);

    if (showPublic) {
      setVisible(elements.landingView, state.authView === "landing");
      setVisible(elements.signupView, state.authView === "signup");
      setVisible(elements.loginView, state.authView === "login");
    }

    const signingUp = state.auth === AUTH_STATES.SIGNING_UP;
    const loggingIn = state.auth === AUTH_STATES.LOGGING_IN;
    elements.signupSubmit.disabled = signingUp;
    elements.signupSubmit.textContent = signingUp ? "Signing up…" : "Sign up";
    elements.loginSubmit.disabled = loggingIn;
    elements.loginSubmit.textContent = loggingIn ? "Logging in…" : "Log in";

    if (isSignedIn && state.user) {
      elements.accountUsername.textContent = state.user.username;
    }
  }

  function authFields(mode) {
    return mode === "signup"
      ? {
          username: elements.signupUsername,
          password: elements.signupPassword,
          usernameError: elements.signupUsernameError,
          passwordError: elements.signupPasswordError,
          formError: elements.signupFormError
        }
      : {
          username: elements.loginUsername,
          password: elements.loginPassword,
          usernameError: elements.loginUsernameError,
          passwordError: elements.loginPasswordError,
          formError: elements.loginFormError
        };
  }

  function setFieldError(input, target, message) {
    const visible = Boolean(message);
    input.setAttribute("aria-invalid", visible ? "true" : "false");
    target.textContent = visible ? message : "";
    target.hidden = !visible;
  }

  function clearAuthErrors(mode) {
    const fields = authFields(mode);
    setFieldError(fields.username, fields.usernameError, "");
    setFieldError(fields.password, fields.passwordError, "");
    fields.formError.textContent = "";
    fields.formError.hidden = true;
  }

  function setAuthFormError(mode, message) {
    const target = authFields(mode).formError;
    target.textContent = message || "";
    target.hidden = !message;
  }

  function renderAuthFieldErrors(mode, fieldErrors) {
    const fields = authFields(mode);
    setFieldError(fields.username, fields.usernameError, fieldErrors.username || "");
    setFieldError(fields.password, fields.passwordError, fieldErrors.password || "");
  }

  function openAuthView(view, options) {
    const config = options || {};
    state.auth = AUTH_STATES.SIGNED_OUT;
    state.errorScope = null;
    state.authView = view;
    if (view === "signup") {
      clearAuthErrors("signup");
      if (!config.preservePassword) elements.signupPassword.value = "";
      hidePassword(elements.signupPassword, elements.signupPasswordToggle);
    } else if (view === "login") {
      clearAuthErrors("login");
      if (!config.preservePassword) elements.loginPassword.value = "";
      hidePassword(elements.loginPassword, elements.loginPasswordToggle);
    }
    renderAuthShell();
    window.requestAnimationFrame(function () {
      if (view === "signup") elements.signupUsername.focus();
      if (view === "login") elements.loginUsername.focus();
    });
  }

  function showLanding() {
    state.auth = AUTH_STATES.SIGNED_OUT;
    state.errorScope = null;
    state.authView = "landing";
    elements.signupPassword.value = "";
    elements.loginPassword.value = "";
    hidePassword(elements.signupPassword, elements.signupPasswordToggle);
    hidePassword(elements.loginPassword, elements.loginPasswordToggle);
    clearAuthErrors("signup");
    clearAuthErrors("login");
    renderAuthShell();
  }

  function validateAuthForm(mode) {
    const fields = authFields(mode);
    const errors = {};
    if (!fields.username.value.trim()) errors.username = "Enter a username.";
    if (!fields.password.value) {
      errors.password = "Enter a password.";
    } else if (mode === "signup" && fields.password.value.length < 8) {
      errors.password = "Use at least 8 characters.";
    }
    renderAuthFieldErrors(mode, errors);
    return Object.keys(errors).length === 0;
  }

  function safeAuthMessage(error, mode) {
    if (error.category === "network") return "Unable to connect. Try again.";
    if (error.code === "VALIDATION_ERROR") return "Check the highlighted fields.";
    if (mode === "signup" && error.code === "ACCOUNT_EXISTS") {
      return "An account already exists. Log in instead.";
    }
    if (mode === "login" && error.code === "INVALID_CREDENTIALS" && error.status === 401) {
      return "Incorrect username or password.";
    }
    if (error.code === "AUTH_SERVICE_ERROR") return "Something went wrong. Try again.";
    return "Something went wrong. Try again.";
  }

  async function submitAuth(mode) {
    const pendingState = mode === "signup" ? AUTH_STATES.SIGNING_UP : AUTH_STATES.LOGGING_IN;
    if (state.auth === AUTH_STATES.SIGNING_UP || state.auth === AUTH_STATES.LOGGING_IN) return;
    clearAuthErrors(mode);
    if (!validateAuthForm(mode)) {
      state.auth = AUTH_STATES.ERROR;
      state.errorScope = "form";
      state.authView = mode;
      setAuthFormError(mode, "Check the highlighted fields.");
      renderAuthShell();
      return;
    }

    const fields = authFields(mode);
    state.auth = pendingState;
    state.errorScope = null;
    state.authView = mode;
    renderAuthShell();

    try {
      const data = await api(mode === "signup" ? AUTH_ROUTES.SIGNUP : AUTH_ROUTES.LOGIN, {
        method: "POST",
        body: {
          username: fields.username.value.trim(),
          password: fields.password.value
        }
      });
      if (!data || data.authenticated !== true || !data.user || typeof data.user.username !== "string") {
        throw new ApiError(200, "UNEXPECTED_RESPONSE", "Something went wrong. Try again.", {}, "payload");
      }
      fields.password.value = "";
      hidePassword(fields.password, mode === "signup" ? elements.signupPasswordToggle : elements.loginPasswordToggle);
      state.user = { username: data.user.username };
      state.auth = AUTH_STATES.SIGNED_IN;
      state.errorScope = null;
      resetProtectedState();
      renderAuthShell();
      setFeedback("Loading your workbench…", "neutral");
      await refreshWorkspace({ force: true });
      elements.workbenchMain.focus();
    } catch (error) {
      if (!(error instanceof ApiError)) {
        error = new ApiError(0, "UNEXPECTED_RESPONSE", "Something went wrong. Try again.", {}, "payload");
      }
      if (mode === "signup" && error.code === "ACCOUNT_EXISTS") {
        const username = fields.username.value;
        elements.loginUsername.value = username;
        elements.signupPassword.value = "";
        hidePassword(elements.signupPassword, elements.signupPasswordToggle);
        hidePassword(elements.loginPassword, elements.loginPasswordToggle);
        state.auth = AUTH_STATES.ERROR;
        state.errorScope = "form";
        state.authView = "login";
        clearAuthErrors("login");
        setAuthFormError("login", "An account already exists. Log in instead.");
        renderAuthShell();
        elements.loginPassword.focus();
        return;
      }
      state.auth = AUTH_STATES.ERROR;
      state.errorScope = "form";
      state.authView = mode;
      renderAuthFieldErrors(mode, error.fields || {});
      setAuthFormError(mode, safeAuthMessage(error, mode));
      fields.password.value = "";
      hidePassword(fields.password, mode === "signup" ? elements.signupPasswordToggle : elements.loginPasswordToggle);
      renderAuthShell();
      if (error.fields && error.fields.username) fields.username.focus();
      else fields.password.focus();
    }
  }

  async function initializeSession() {
    state.auth = AUTH_STATES.LOADING;
    state.errorScope = null;
    renderAuthShell();
    try {
      const data = await api(AUTH_ROUTES.SESSION);
      if (!data || typeof data.authenticated !== "boolean") {
        throw new ApiError(200, "UNEXPECTED_RESPONSE", "Something went wrong. Try again.", {}, "payload");
      }
      if (data.authenticated) {
        if (!data.user || typeof data.user.username !== "string") {
          throw new ApiError(200, "UNEXPECTED_RESPONSE", "Something went wrong. Try again.", {}, "payload");
        }
        state.user = { username: data.user.username };
        state.auth = AUTH_STATES.SIGNED_IN;
        resetProtectedState();
        renderAuthShell();
        setFeedback("Loading your workbench…", "neutral");
        await refreshWorkspace({ force: true });
      } else {
        state.user = null;
        state.auth = AUTH_STATES.SIGNED_OUT;
        state.authView = "landing";
        renderAuthShell();
      }
    } catch (error) {
      state.auth = AUTH_STATES.ERROR;
      state.errorScope = "session";
      elements.sessionErrorMessage.textContent = error instanceof ApiError && error.category === "network"
        ? "Unable to connect. Try again."
        : "Something went wrong. Try again.";
      renderAuthShell();
    }
  }

  async function logout() {
    if (state.pending.has("logout")) return;
    state.pending.add("logout");
    elements.logoutButton.disabled = true;
    elements.logoutButton.textContent = "Logging out…";
    try {
      await api(AUTH_ROUTES.LOGOUT, { method: "POST" });
      closeAccountMenu();
      closeTaskDrawer();
      state.user = null;
      resetProtectedState();
      showLanding();
    } catch (error) {
      closeAccountMenu();
      setFeedback(error instanceof ApiError && error.category === "network"
        ? "Unable to connect. Try again."
        : "Something went wrong. Try again.", "error");
    } finally {
      state.pending.delete("logout");
      elements.logoutButton.disabled = false;
      elements.logoutButton.textContent = "Log out";
    }
  }

  function togglePassword(input, button) {
    const showing = input.type === "text";
    input.type = showing ? "password" : "text";
    button.textContent = showing ? "Show" : "Hide";
    button.setAttribute("aria-pressed", showing ? "false" : "true");
    input.focus();
    const end = input.value.length;
    input.setSelectionRange(end, end);
  }

  function hidePassword(input, button) {
    input.type = "password";
    button.textContent = "Show";
    button.setAttribute("aria-pressed", "false");
  }

  function resetProtectedState() {
    state.pending.clear();
    state.workspaceLoaded = false;
    state.registryLoaded = false;
    state.projects = [];
    state.tasks = [];
    state.runs = [];
    state.schedules = [];
    state.audit = [];
    state.providers = [];
    state.tools = [];
    state.aiCapabilityRegistry = [];
    state.health = null;
    state.codexStatus = null;
    state.aiPlan = null;
    state.acceptance = null;
    state.packs = [];
    state.codexRuns = [];
    state.ownerAcceptance = null;
    state.selectedTaskId = null;
    state.selectedPackId = null;
    state.selectedScheduleId = null;
    state.creatingTask = false;
    state.newTaskInitialized = false;
    state.renderedTaskId = null;
    state.renderedPlanId = null;
    state.renderedAcceptanceId = null;
    state.renderedAcceptanceSignature = null;
  }

  function setFeedback(message, kind) {
    elements.feedback.textContent = message;
    elements.feedback.classList.remove("is-error", "is-success");
    if (kind === "error") elements.feedback.classList.add("is-error");
    if (kind === "success") elements.feedback.classList.add("is-success");
  }

  function productActionMessage(error) {
    if (error instanceof ApiError && error.category === "network") return "Unable to connect. Try again.";
    if (!(error instanceof ApiError)) return "Something went wrong. Try again.";
    if (error.code === "validation_error" || error.code === "VALIDATION_ERROR") {
      return "Check the highlighted fields.";
    }
    if (error.category === "product") return error.message;
    const message = typeof error.message === "string" ? error.message : "";
    const looksInternal = /traceback|sqlalchemy|validationerror|\/users\/|\\users\\|\.sqlite|stack trace/i.test(message);
    if (error.category === "twos" && error.code === "http_error" && !looksInternal && message && message.length <= 220) {
      return message;
    }
    return "Something went wrong. Try again.";
  }

  function handleExpiredSession() {
    state.user = null;
    resetProtectedState();
    state.auth = AUTH_STATES.SIGNED_OUT;
    state.authView = "login";
    state.errorScope = null;
    clearAuthErrors("login");
    setAuthFormError("login", "Your session ended. Log in again.");
    renderAuthShell();
  }

  async function performAction(key, button, pendingText, action) {
    if (state.pending.has(key)) return;
    const originalText = button.textContent;
    state.pending.add(key);
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    if (pendingText) button.textContent = pendingText;
    try {
      const successMessage = await action();
      await refreshWorkspace({ force: true });
      if (successMessage) setFeedback(successMessage, "success");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleExpiredSession();
        return;
      }
      setFeedback(productActionMessage(error), "error");
    } finally {
      state.pending.delete(key);
      button.removeAttribute("aria-busy");
      button.textContent = originalText;
      if (state.auth === AUTH_STATES.SIGNED_IN) renderWorkspace();
    }
  }

  function selectedTask() {
    if (state.creatingTask) return null;
    return state.tasks.find(function (task) { return task.id === state.selectedTaskId; }) || null;
  }

  function currentPack() {
    return state.packs.length ? state.packs[0] : null;
  }

  function currentCodexRun() {
    return state.codexRuns.length ? state.codexRuns[0] : null;
  }

  function currentLegacyRun() {
    const task = selectedTask();
    if (!task) return null;
    return state.runs.find(function (run) { return run.task_id === task.id; }) || null;
  }

  function taskSchedules() {
    const task = selectedTask();
    return task ? state.schedules.filter(function (schedule) { return schedule.task_id === task.id; }) : [];
  }

  function currentSchedule() {
    const schedules = taskSchedules();
    let selected = schedules.find(function (schedule) { return schedule.id === state.selectedScheduleId; });
    if (!selected && schedules.length) {
      selected = schedules[schedules.length - 1];
      state.selectedScheduleId = selected.id;
    }
    return selected || null;
  }

  function resetTaskDetails() {
    state.aiPlan = null;
    state.acceptance = null;
    state.packs = [];
    state.codexRuns = [];
    state.ownerAcceptance = null;
    state.selectedPackId = null;
    state.selectedScheduleId = null;
    state.renderedPlanId = null;
    state.renderedAcceptanceId = null;
    state.renderedAcceptanceSignature = null;
  }

  function initializeNewTaskForm() {
    elements.taskWorkflow.value = "product_development";
    elements.taskTitle.value = "";
    elements.taskObjective.value = "";
    elements.taskSource.value = "";
    elements.taskOutput.value = "";
    elements.taskAcceptanceTarget.value = "";
    elements.taskImplementationScope.value = "";
    elements.taskForbiddenScope.value = DEFAULT_BOUNDARY;
    elements.taskAction.value = "Analyze";
    elements.repositoryIdentity.textContent = "Assigned on save";
    elements.sourceBaseline.textContent = "Assigned on save";
    elements.capabilityFocus.value = "";
    elements.riskLevel.value = "medium";
    elements.aiUrgency.value = "normal";
    if (state.projects.length) elements.taskProject.value = String(state.projects[0].id);
    state.newTaskInitialized = true;
    syncTaskRequirements();
  }

  function beginNewTask(shouldFocus) {
    state.creatingTask = true;
    state.selectedTaskId = null;
    state.renderedTaskId = null;
    resetTaskDetails();
    initializeNewTaskForm();
    renderWorkspace();
    closeTaskDrawer();
    setFeedback("New task ready. Complete the fields, then select Save Task.", "neutral");
    if (shouldFocus) elements.taskTitle.focus();
  }

  function syncTaskRequirements() {
    const productDevelopment = elements.taskWorkflow.value === "product_development";
    [
      elements.taskObjective,
      elements.taskAcceptanceTarget,
      elements.taskImplementationScope,
      elements.taskForbiddenScope
    ].forEach(function (input) {
      input.required = productDevelopment;
    });
  }

  async function refreshWorkspace(options) {
    const config = options || {};
    if (state.auth !== AUTH_STATES.SIGNED_IN) return;
    if (state.refreshing) {
      if (config.force) state.refreshQueued = true;
      return;
    }
    state.refreshing = true;
    try {
      const base = await Promise.all([
        api("/api/health"),
        api("/api/projects"),
        api("/api/tasks"),
        api("/api/runs"),
        api("/api/schedules"),
        api("/api/audit"),
        api("/api/codex/status")
      ]);
      state.health = base[0];
      state.projects = Array.isArray(base[1]) ? base[1] : [];
      state.tasks = Array.isArray(base[2]) ? base[2] : [];
      state.runs = Array.isArray(base[3]) ? base[3] : [];
      state.schedules = Array.isArray(base[4]) ? base[4] : [];
      state.audit = Array.isArray(base[5]) ? base[5] : [];
      state.codexStatus = base[6] || null;

      if (!state.registryLoaded) {
        const registry = await Promise.all([
          api("/api/providers"),
          api("/api/tools"),
          api("/api/ai/capabilities")
        ]);
        state.providers = Array.isArray(registry[0]) ? registry[0] : [];
        state.tools = Array.isArray(registry[1]) ? registry[1] : [];
        state.aiCapabilityRegistry = Array.isArray(registry[2]) ? registry[2] : [];
        state.registryLoaded = true;
      }

      if (!state.creatingTask) {
        const stillExists = state.tasks.some(function (task) { return task.id === state.selectedTaskId; });
        if (!stillExists) {
          state.selectedTaskId = state.tasks.length ? state.tasks[state.tasks.length - 1].id : null;
          state.renderedTaskId = null;
          resetTaskDetails();
        }
      }
      if (!state.tasks.length && !state.creatingTask) {
        state.creatingTask = true;
        initializeNewTaskForm();
      }

      const task = selectedTask();
      if (task) {
        const detail = await Promise.all([
          api("/api/tasks/" + task.id + "/acceptance"),
          api("/api/tasks/" + task.id + "/ai-plan"),
          api("/api/tasks/" + task.id + "/codex-packs"),
          api("/api/tasks/" + task.id + "/codex-runs"),
          api("/api/tasks/" + task.id + "/owner-acceptance")
        ]);
        state.acceptance = detail[0] || null;
        state.aiPlan = detail[1] || null;
        state.packs = Array.isArray(detail[2]) ? detail[2] : [];
        state.codexRuns = Array.isArray(detail[3]) ? detail[3] : [];
        state.ownerAcceptance = detail[4] && detail[4].acceptance ? detail[4].acceptance : null;
      } else {
        resetTaskDetails();
      }

      state.workspaceLoaded = true;
      renderWorkspace();
      if (elements.feedback.textContent === "Loading your workbench…") {
        setFeedback(state.tasks.length ? "Workbench ready." : "Create your first task to begin.", "neutral");
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleExpiredSession();
      } else {
        setFeedback(productActionMessage(error), "error");
      }
    } finally {
      state.refreshing = false;
      if (state.refreshQueued && state.auth === AUTH_STATES.SIGNED_IN) {
        state.refreshQueued = false;
        await refreshWorkspace();
      }
    }
  }

  function renderWorkspace() {
    if (state.auth !== AUTH_STATES.SIGNED_IN) return;
    renderProjectOptions();
    renderCapabilityOptions();
    renderTaskList();
    renderTaskForm();
    renderAIPlan();
    renderPack();
    renderCodex();
    renderResult();
    renderOwnerAcceptance();
    renderCompactSync();
    renderWorkerAcceptance();
    renderSchedules();
    renderRegistries();
    renderAudit();
    renderActionAvailability();
    renderHeaderStatus();
  }

  function renderHeaderStatus() {
    const detection = state.codexStatus;
    const ready = detection && detection.status === "configured";
    elements.codexHeaderStatus.textContent = ready ? "Codex: Ready" : "Codex: Needs setup";
    elements.codexHeaderStatus.dataset.status = ready ? "ready" : "setup";
    elements.accountUsername.textContent = state.user ? state.user.username : "Account";
    elements.runtimeHealth.textContent = state.health && state.health.status === "healthy" && state.health.database === "ok"
      ? "Healthy"
      : state.health ? humanStatus(state.health.status) : "Checking";
  }

  function renderProjectOptions() {
    const current = elements.taskProject.value;
    clearChildren(elements.taskProject);
    state.projects.forEach(function (project) {
      const option = document.createElement("option");
      option.value = String(project.id);
      option.textContent = project.name;
      elements.taskProject.appendChild(option);
    });
    if (state.projects.some(function (project) { return String(project.id) === current; })) {
      elements.taskProject.value = current;
    } else if (state.projects.length) {
      elements.taskProject.value = String(state.projects[0].id);
    }
  }

  function renderCapabilityOptions() {
    const current = elements.capabilityFocus.value;
    clearChildren(elements.capabilityFocus);
    const automatic = document.createElement("option");
    automatic.value = "";
    automatic.textContent = "Auto-select from task";
    elements.capabilityFocus.appendChild(automatic);
    state.aiCapabilityRegistry.filter(function (item) { return item.enabled; }).forEach(function (item) {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = humanStatus(item.name);
      elements.capabilityFocus.appendChild(option);
    });
    elements.capabilityFocus.value = Array.from(elements.capabilityFocus.options).some(function (option) { return option.value === current; }) ? current : "";
  }

  function renderTaskList() {
    clearChildren(elements.taskList);
    if (!state.tasks.length) {
      const empty = document.createElement("li");
      empty.className = "task-list-empty";
      empty.textContent = "No saved tasks yet.";
      elements.taskList.appendChild(empty);
      return;
    }
    state.tasks.slice().reverse().forEach(function (task) {
      const item = document.createElement("li");
      const button = document.createElement("button");
      const title = document.createElement("strong");
      const status = document.createElement("span");
      button.type = "button";
      button.className = "task-list-button";
      button.dataset.taskId = String(task.id);
      button.setAttribute("aria-current", !state.creatingTask && task.id === state.selectedTaskId ? "page" : "false");
      title.textContent = task.title;
      status.textContent = humanStatus(task.status);
      button.appendChild(title);
      button.appendChild(status);
      button.addEventListener("click", function () {
        state.creatingTask = false;
        state.newTaskInitialized = false;
        state.selectedTaskId = task.id;
        state.renderedTaskId = null;
        resetTaskDetails();
        renderTaskList();
        closeTaskDrawer();
        setFeedback("Loading task…", "neutral");
        refreshWorkspace({ force: true });
      });
      item.appendChild(button);
      elements.taskList.appendChild(item);
    });
  }

  function populateTaskForm(task) {
    if (!task || state.renderedTaskId === task.id) return;
    elements.taskProject.value = String(task.project_id);
    elements.taskWorkflow.value = task.workflow_type || "general";
    elements.taskTitle.value = task.title || "";
    elements.taskObjective.value = task.objective || task.title || "";
    elements.taskSource.value = task.source_sync_summary || "";
    elements.taskOutput.value = task.required_output || "";
    elements.taskAcceptanceTarget.value = task.acceptance_target || "";
    elements.taskImplementationScope.value = task.implementation_scope || "";
    elements.taskForbiddenScope.value = task.forbidden_scope || task.boundary_risk || "";
    elements.taskAction.value = task.action || "Analyze";
    elements.repositoryIdentity.textContent = task.repository_identity || "Not assigned";
    elements.sourceBaseline.textContent = task.source_baseline_commit || "Not assigned";
    state.renderedTaskId = task.id;
    state.newTaskInitialized = false;
    syncTaskRequirements();
  }

  function renderTaskForm() {
    const task = selectedTask();
    if (task) {
      populateTaskForm(task);
      elements.taskStatus.textContent = "Saved / " + humanStatus(task.status);
    } else {
      if (!state.newTaskInitialized) initializeNewTaskForm();
      elements.taskStatus.textContent = "New task";
    }
    setStatusLabel(elements.taskStatus, elements.taskStatus.textContent);
  }

  function appendTextList(target, values, emptyText) {
    clearChildren(target);
    if (!values.length) {
      const empty = document.createElement("li");
      empty.textContent = emptyText;
      target.appendChild(empty);
      return;
    }
    values.forEach(function (value) {
      const item = document.createElement("li");
      item.textContent = value;
      target.appendChild(item);
    });
  }

  function renderAIPlan() {
    const payload = state.aiPlan;
    const plan = payload && payload.plan ? payload.plan : null;
    const routes = payload && Array.isArray(payload.routes) ? payload.routes : [];
    const routing = payload && payload.routing_summary ? payload.routing_summary : null;
    if (!plan) {
      elements.aiTeamStatus.textContent = "Waiting";
      elements.aiCapabilities.textContent = "Save a task to compose its plan.";
      elements.aiMinimumCount.textContent = "Waiting";
      elements.aiPlanStatus.textContent = "Waiting";
      elements.aiWhy.textContent = "Task-specific reasoning will appear after composition.";
      appendTextList(elements.aiReasons, [], "Waiting for a saved task.");
      elements.routingStatus.textContent = "Waiting";
      elements.routingNextAction.textContent = selectedTask() ? "Recompose the AI Team." : "Save a task first.";
      elements.routingProvider.textContent = "Waiting";
      elements.routingModel.textContent = "Waiting";
      elements.routingFallback.textContent = "Waiting";
      elements.routingCost.textContent = "Unknown";
      elements.routingLatency.textContent = "Unknown";
      elements.routingRecords.textContent = "None";
      elements.routingReason.textContent = "No routing evidence yet.";
      appendTextList(elements.routingDetails, [], "No routing records loaded.");
      setStatusLabel(elements.aiTeamStatus, "waiting");
      return;
    }

    const required = Array.isArray(plan.required_capabilities) ? plan.required_capabilities : [];
    const primary = routes.length ? routes[0] : null;
    const selected = primary && primary.selected ? primary.selected : null;
    const fallback = primary && primary.fallback ? primary.fallback : null;
    const evaluated = Boolean(routing && routing.evaluation_completed);
    elements.aiTeamStatus.textContent = required.length + " capabilities";
    elements.aiCapabilities.textContent = required.length ? required.map(humanStatus).join(" + ") : "None selected";
    elements.aiMinimumCount.textContent = String(plan.minimum_role_count || required.length) + " capabilities";
    elements.aiPlanStatus.textContent = "Composed";
    elements.aiWhy.textContent = plan.explanation || "Team composed from the saved task.";
    appendTextList(elements.aiReasons, Array.isArray(plan.team) ? plan.team.map(function (item) {
      return humanStatus(item.capability) + ": " + item.selection_reason;
    }) : [], "No capability reasons reported.");
    elements.routingStatus.textContent = evaluated ? "Evaluated / " + humanStatus(routing.status) : "Evaluation pending";
    elements.routingNextAction.textContent = routing && routing.next_action ? routing.next_action : "Recompose the AI Team.";
    elements.routingProvider.textContent = routing && routing.selected_provider ? routing.selected_provider : evaluated ? "None" : "Waiting";
    elements.routingModel.textContent = routing && routing.selected_model ? routing.selected_model : evaluated ? "None" : "Waiting";
    elements.routingFallback.textContent = routing && routing.fallback_status === "available" && fallback
      ? fallback.provider + " / " + fallback.model_name
      : routing && routing.fallback_status === "unavailable"
        ? "Unavailable. " + routing.fallback_reason
        : "Waiting";
    elements.routingCost.textContent = selected && selected.cost_metadata ? selected.cost_metadata : "Unknown";
    elements.routingLatency.textContent = selected && selected.latency_metadata ? selected.latency_metadata : "Unknown";
    elements.routingRecords.textContent = routes.length ? routes.map(function (route) { return "#" + route.id; }).join(", ") : "None";
    elements.routingReason.textContent = routing && routing.reason ? routing.reason : "Routing evaluation pending.";
    appendTextList(elements.routingDetails, routes.map(function (route) {
      const target = route.selected ? route.selected.provider + " / " + route.selected.model_name : "No provider or model selected";
      return humanStatus(route.capability) + " / " + humanStatus(route.status) + " / " + target + ". " + (route.reason || "");
    }), "No routing records loaded.");
    setStatusLabel(elements.aiTeamStatus, "composed");
    if (state.renderedPlanId !== plan.id) {
      if (plan.risk_level) elements.riskLevel.value = plan.risk_level;
      if (plan.urgency) elements.aiUrgency.value = plan.urgency;
      state.renderedPlanId = plan.id;
    }
  }

  function renderPack() {
    const pack = currentPack();
    elements.packStatus.textContent = pack ? humanStatus(pack.status) : "Not generated";
    elements.packVersion.textContent = pack ? "v" + pack.version : "None";
    elements.packApproval.textContent = !pack
      ? "Required before execution"
      : pack.approved
        ? "Approved"
        : pack.status === "invalidated"
          ? "Invalidated"
          : "Approval required";
    elements.packStages.textContent = pack && pack.stage_summary ? pack.stage_summary : "Generate a pack after saving the task.";
    elements.packAcceptanceTarget.textContent = pack && pack.acceptance_target
      ? pack.acceptance_target
      : elements.taskAcceptanceTarget.value || "Waiting for task";
    elements.packBoundaries.textContent = pack && pack.key_boundaries
      ? pack.key_boundaries
      : "No merge, push, live trading, or live betting.";
    setStatusLabel(elements.packStatus, elements.packStatus.textContent);

    const previousSelection = String(state.selectedPackId || "");
    clearChildren(elements.packHistory);
    if (!state.packs.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No persisted versions";
      elements.packHistory.appendChild(option);
    } else {
      state.packs.forEach(function (item) {
        const option = document.createElement("option");
        option.value = String(item.id);
        option.textContent = "v" + item.version + " / " + humanStatus(item.status);
        elements.packHistory.appendChild(option);
      });
    }
    let selected = state.packs.find(function (item) { return String(item.id) === previousSelection; }) || pack;
    state.selectedPackId = selected ? selected.id : null;
    if (selected) elements.packHistory.value = String(selected.id);
    elements.packRaw.textContent = selected && selected.content ? selected.content : "No instruction pack generated.";
    elements.packId.textContent = selected ? "#" + selected.id : "None";
    elements.packBaseline.textContent = selected && selected.source_baseline_commit ? selected.source_baseline_commit : "None";
    elements.generatePack.textContent = pack ? "Regenerate Codex Pack" : "Generate Codex Pack";
  }

  function renderCodex() {
    const detection = state.codexStatus;
    const run = currentCodexRun();
    const ready = detection && detection.status === "configured";
    elements.codexReadiness.textContent = ready ? "Ready" : "Needs setup";
    elements.codexReason.textContent = detection && detection.reason ? detection.reason : "Checking the supported local command.";
    elements.runStatus.textContent = run ? humanStatus(run.status) : "Not started";
    const active = run && ["queued", "running"].indexOf(run.status) !== -1;
    elements.codexNextAction.textContent = active
      ? "Wait for completion or select Cancel Run."
      : detection && detection.next_action
        ? detection.next_action
        : "Save a task and generate a pack.";
    elements.codexRunId.textContent = run ? "#" + run.id : "None";
    elements.worktreeBranch.textContent = run && run.worktree_branch ? run.worktree_branch : "None";
    elements.worktreePath.textContent = run && run.worktree_path ? run.worktree_path : "None";
    elements.runExitCode.textContent = run && run.exit_code !== null && run.exit_code !== undefined ? String(run.exit_code) : "None";
    setStatusLabel(elements.runStatus, elements.runStatus.textContent);
  }

  function renderResult() {
    const task = selectedTask();
    const run = currentCodexRun();
    const legacyRun = currentLegacyRun();
    elements.resultTask.textContent = task ? task.title : "None";
    if (run) {
      const result = run.result || {};
      const changed = Array.isArray(result.changed_files) ? result.changed_files : [];
      const tests = Array.isArray(result.tests_reported) ? result.tests_reported : [];
      const commits = Array.isArray(result.commits) ? result.commits : [];
      elements.resultStatus.textContent = humanStatus(run.status);
      elements.resultLifecycle.textContent = humanStatus(run.status);
      elements.resultChangedFiles.textContent = changed.length ? changed.join(", ") : "None";
      elements.resultSummary.textContent = run.owner_summary || "Execution result persisted.";
      elements.resultTests.textContent = tests.length
        ? tests.join(" | ")
        : result.validation && result.validation.diff_check
          ? "Git diff check passed; no test output reported."
          : "Needs review";
      elements.resultCommit.textContent = commits.length
        ? commits.join(" | ")
        : result.post_run_commit
          ? "No new commit; worktree at " + String(result.post_run_commit).slice(0, 12)
          : "No commit evidence";
      elements.resultBoundary.textContent = result.boundary_confirmation
        ? "Isolated worktree used; no automatic merge or push."
        : "No merge or push performed.";
      elements.resultReview.textContent = state.ownerAcceptance
        ? "Complete the Owner Acceptance checklist."
        : "Inspect result evidence and execution status.";
      elements.taskRunId.textContent = "None";
      elements.taskRunAction.textContent = "Approved Codex Pack v" + (run.pack_version || "?");
      elements.runStarted.textContent = formatTime(run.started_at);
      elements.runFinished.textContent = formatTime(run.finished_at);
      elements.runError.textContent = run.status === "failed" ? run.owner_summary || "Execution failed." : "None";
      elements.codexStdout.textContent = run.stdout || "No standard output.";
      elements.codexStderr.textContent = run.stderr || "No standard error.";
    } else if (legacyRun) {
      elements.resultStatus.textContent = humanStatus(legacyRun.status);
      elements.resultLifecycle.textContent = humanStatus(legacyRun.status);
      elements.resultChangedFiles.textContent = "Internal worker only";
      elements.resultSummary.textContent = legacyRun.result ? "Generated Compact Sync." : legacyRun.error || "No result yet.";
      elements.resultTests.textContent = "Deterministic worker checks";
      elements.resultCommit.textContent = "No Git commit";
      elements.resultBoundary.textContent = "Internal worker only; no external call, merge, or push.";
      elements.resultReview.textContent = "Deterministic acceptance evidence is available in Advanced.";
      elements.taskRunId.textContent = "#" + legacyRun.id;
      elements.taskRunAction.textContent = legacyRun.action || "None";
      elements.runStarted.textContent = formatTime(legacyRun.started_at);
      elements.runFinished.textContent = formatTime(legacyRun.finished_at);
      elements.runError.textContent = legacyRun.error || "None";
      elements.codexStdout.textContent = "No process output for the internal worker.";
      elements.codexStderr.textContent = "No process errors for the internal worker.";
    } else {
      elements.resultStatus.textContent = "Not run";
      elements.resultLifecycle.textContent = task ? humanStatus(task.status) : "Waiting";
      elements.resultChangedFiles.textContent = "None";
      elements.resultSummary.textContent = "No result yet.";
      elements.resultTests.textContent = "Not run";
      elements.resultCommit.textContent = "No commit";
      elements.resultBoundary.textContent = "No merge or push performed.";
      elements.resultReview.textContent = "Run Codex to create review evidence.";
      elements.taskRunId.textContent = "None";
      elements.taskRunAction.textContent = "None";
      elements.runStarted.textContent = "Not started";
      elements.runFinished.textContent = "Not finished";
      elements.runError.textContent = "None";
      elements.codexStdout.textContent = "No output.";
      elements.codexStderr.textContent = "No errors.";
    }
    setStatusLabel(elements.resultStatus, elements.resultStatus.textContent);
  }

  function ownerAcceptanceSignature(acceptance) {
    if (!acceptance) return "none";
    return JSON.stringify({
      id: acceptance.id,
      status: acceptance.status,
      items: (acceptance.items || []).map(function (item) {
        return [item.id, item.status, item.note];
      })
    });
  }

  function renderOwnerAcceptance() {
    const acceptance = state.ownerAcceptance;
    elements.acceptanceStatus.textContent = acceptance ? humanStatus(acceptance.status) : "Waiting for result";
    setStatusLabel(elements.acceptanceStatus, elements.acceptanceStatus.textContent);
    const signature = ownerAcceptanceSignature(acceptance);
    if (signature !== state.renderedAcceptanceSignature) {
      clearChildren(elements.acceptanceItems);
      if (!acceptance) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = "No Codex result is ready for review.";
        elements.acceptanceItems.appendChild(empty);
      } else {
        (acceptance.items || []).forEach(function (item) {
          const row = document.createElement("section");
          const header = document.createElement("div");
          const title = document.createElement("strong");
          const status = document.createElement("span");
          const inspect = document.createElement("p");
          const standard = document.createElement("p");
          const note = document.createElement("input");
          const actions = document.createElement("div");
          row.className = "acceptance-item";
          row.dataset.status = item.status;
          header.className = "acceptance-item-header";
          title.textContent = item.label + (item.required ? " / Required" : "");
          status.className = "status-label";
          status.textContent = humanStatus(item.status);
          setStatusLabel(status, status.textContent);
          inspect.textContent = "Inspect: " + item.inspect_target + " · " + item.ui_path;
          standard.textContent = "Pass standard: " + item.pass_standard;
          note.type = "text";
          note.value = item.note || "";
          note.placeholder = "Short evidence note";
          note.setAttribute("aria-label", "Note for " + item.label);
          actions.className = "button-row";
          [
            { value: "pass", label: "Pass" },
            { value: "needs_review", label: "Needs Review" },
            { value: "fail", label: "Fail" }
          ].forEach(function (choice) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "button button-secondary" + (choice.value === item.status ? " is-active" : "");
            button.textContent = choice.label;
            button.disabled = acceptance.status !== "owner_review";
            button.addEventListener("click", function () {
              performAction("acceptance-item-" + item.id, button, "Saving…", async function () {
                await api("/api/owner-acceptance/" + acceptance.id + "/items/" + item.id, {
                  method: "PATCH",
                  body: { status: choice.value, note: note.value }
                });
                return "Acceptance item saved as " + choice.label + ".";
              });
            });
            actions.appendChild(button);
          });
          header.appendChild(title);
          header.appendChild(status);
          row.appendChild(header);
          row.appendChild(inspect);
          row.appendChild(standard);
          row.appendChild(note);
          row.appendChild(actions);
          elements.acceptanceItems.appendChild(row);
        });
      }
      state.renderedAcceptanceSignature = signature;
    }
    if (acceptance && state.renderedAcceptanceId !== acceptance.id) {
      elements.acceptanceNote.value = acceptance.owner_note || "";
      state.renderedAcceptanceId = acceptance.id;
    }
  }

  function renderCompactSync() {
    const task = selectedTask();
    const accepted = state.ownerAcceptance && state.ownerAcceptance.compact_sync_result;
    const content = accepted || (task && task.compact_sync_result) || "";
    elements.compactSyncSummary.textContent = content
      ? "Compact Sync is saved for this task and ready for handoff."
      : "No Compact Sync has been saved for this task.";
    elements.compactSyncOutput.textContent = content || "No persisted Compact Sync payload.";
    elements.compactSyncStatus.textContent = content ? "Saved" : "Not generated";
    setStatusLabel(elements.compactSyncStatus, elements.compactSyncStatus.textContent);
  }

  function renderWorkerAcceptance() {
    const acceptance = state.acceptance;
    const checks = acceptance && Array.isArray(acceptance.checks) ? acceptance.checks : [];
    elements.workerDecision.textContent = acceptance ? acceptance.display_decision : "Waiting";
    elements.workerReason.textContent = acceptance && acceptance.reason ? acceptance.reason : "No evidence yet.";
    elements.workerAudit.textContent = acceptance && acceptance.audit_created ? "Created" : "Waiting";
    elements.workerEngine.textContent = acceptance && acceptance.engine ? acceptance.engine : "None";
    elements.workerAcceptanceId.textContent = acceptance && acceptance.id ? "#" + acceptance.id : "None";
    elements.workerAcceptanceCount.textContent = acceptance ? String(acceptance.record_count || 0) : "0";
    elements.workerCheckIds.textContent = checks.length ? checks.map(function (check) { return check.id; }).join(", ") : "None";
    appendTextList(elements.workerChecks, checks.map(function (check) {
      return (check.passed === true ? "Pass" : check.passed === false ? "Fail" : "Pending") + ": " + check.label;
    }), "Waiting for execution.");
    const events = acceptance && Array.isArray(acceptance.audit_events) ? acceptance.audit_events : [];
    appendTextList(elements.workerAuditEvents, events.map(function (event) {
      return formatTime(event.created_at) + " / " + event.action + " / " + event.details;
    }), "No acceptance audit event yet.");
  }

  function scheduledRuns(schedule) {
    if (!schedule) return [];
    const runIds = state.audit.filter(function (event) {
      return event.action === "schedule_run_completed" && event.entity_id === schedule.id;
    }).map(function (event) {
      const match = /task_run=(\d+)/.exec(event.details || "");
      return match ? Number(match[1]) : null;
    }).filter(Boolean);
    return state.runs.filter(function (run) { return runIds.indexOf(run.id) !== -1; });
  }

  function renderSchedules() {
    const schedule = currentSchedule();
    const runs = scheduledRuns(schedule);
    elements.scheduleStatus.textContent = schedule ? schedule.paused ? "Paused" : "Active" : "Not created";
    elements.scheduleLast.textContent = schedule && schedule.last_run_at ? formatTime(schedule.last_run_at) : "Never";
    elements.scheduleNext.textContent = schedule && schedule.next_run_at
      ? formatTime(schedule.next_run_at)
      : schedule && schedule.paused ? "Paused" : "Not scheduled";
    elements.scheduleCount.textContent = schedule ? String(schedule.run_count || 0) : "0";
    appendTextList(elements.scheduleRuns, runs.map(function (run, index) {
      return "Run " + (index + 1) + " / " + humanStatus(run.status) + " / " + formatTime(run.finished_at);
    }), "No recurring executions yet.");
  }

  function renderRegistryList(target, list, emptyText) {
    appendTextList(target, list.map(function (item) {
      return item.name + " / " + item.kind + ": " + humanStatus(item.status) + " — " + (item.details || item.health_reason || "No details");
    }), emptyText);
  }

  function renderRegistries() {
    renderRegistryList(elements.providerList, state.providers, "No providers loaded.");
    renderRegistryList(elements.toolList, state.tools, "No tools loaded.");
  }

  function renderAudit() {
    appendTextList(elements.auditList, state.audit.map(function (event) {
      return formatTime(event.created_at) + " / " + event.action + " / " + event.details;
    }), "No audit events loaded.");
  }

  function renderActionAvailability() {
    const task = selectedTask();
    const plan = state.aiPlan && state.aiPlan.plan ? state.aiPlan.plan : null;
    const pack = currentPack();
    const codexRun = currentCodexRun();
    const activeRun = codexRun && ["queued", "running"].indexOf(codexRun.status) !== -1;
    const codexReady = state.codexStatus && state.codexStatus.status === "configured";
    const acceptance = state.ownerAcceptance;
    const schedule = currentSchedule();
    const authenticated = state.auth === AUTH_STATES.SIGNED_IN;

    elements.saveTask.disabled = !authenticated || state.pending.has("save-task");
    elements.recomposeTeam.disabled = !authenticated || !task || state.pending.has("recompose-team");
    elements.generatePack.disabled = !authenticated || !task || task.workflow_type !== "product_development" || !plan || state.pending.has("generate-pack");
    elements.approvePack.disabled = !pack || pack.status !== "approval_required" || state.pending.has("approve-pack");
    elements.runCodex.disabled = !authenticated || !pack || !pack.approved || !codexReady || activeRun || state.pending.has("run-codex");
    elements.cancelCodex.disabled = !activeRun || state.pending.has("cancel-codex");
    const decisionPending = state.pending.has("acceptance-decision");
    elements.acceptResult.disabled = !acceptance || !acceptance.can_accept || acceptance.status !== "owner_review" || decisionPending;
    elements.rejectResult.disabled = !acceptance || acceptance.status !== "owner_review" || decisionPending;
    elements.runCompactSync.disabled = !authenticated || !task || task.action !== "Compact Sync" || state.pending.has("run-compact-sync");
    elements.runCompactSync.title = task && task.action === "Compact Sync"
      ? "Run the safe internal Compact Sync worker."
      : "Choose Compact Sync in Advanced task execution settings and save the task first.";
    elements.createSchedule.disabled = !authenticated || !task || task.action !== "Compact Sync" || state.pending.has("create-schedule");
    elements.pauseSchedule.disabled = !schedule || schedule.paused || state.pending.has("pause-schedule");
    elements.resumeSchedule.disabled = !schedule || !schedule.paused || state.pending.has("resume-schedule");
  }

  function taskPayload() {
    return {
      project_id: Number(elements.taskProject.value),
      title: elements.taskTitle.value,
      action: elements.taskAction.value,
      workflow_type: elements.taskWorkflow.value,
      objective: elements.taskObjective.value,
      source_sync_summary: elements.taskSource.value,
      required_output: elements.taskOutput.value,
      implementation_scope: elements.taskImplementationScope.value,
      forbidden_scope: elements.taskForbiddenScope.value,
      acceptance_target: elements.taskAcceptanceTarget.value,
      boundary_risk: elements.taskForbiddenScope.value || DEFAULT_BOUNDARY
    };
  }

  async function persistTask(task) {
    return task
      ? api("/api/tasks/" + task.id, { method: "PATCH", body: taskPayload() })
      : api("/api/tasks", { method: "POST", body: taskPayload() });
  }

  async function composeTeam(task) {
    const override = elements.capabilityFocus.value ? [elements.capabilityFocus.value] : [];
    await api("/api/ai/team-compose", {
      method: "POST",
      body: {
        task_id: task.id,
        risk_level: elements.riskLevel.value,
        urgency: elements.aiUrgency.value,
        capability_override: override
      }
    });
    state.renderedPlanId = null;
  }

  async function saveTask() {
    syncTaskRequirements();
    if (!elements.taskForm.checkValidity()) {
      elements.taskForm.reportValidity();
      return;
    }
    await performAction("save-task", elements.saveTask, "Saving…", async function () {
      if (!elements.taskProject.value) throw new ApiError(400, "NO_PROJECT", "No project is available.", {}, "product");
      const task = await persistTask(selectedTask());
      state.creatingTask = false;
      state.newTaskInitialized = false;
      state.selectedTaskId = task.id;
      state.renderedTaskId = null;
      await composeTeam(task);
      return "Task saved. AI Team composed and routing evaluated.";
    });
  }

  async function recomposeTeam() {
    await performAction("recompose-team", elements.recomposeTeam, "Recomposing…", async function () {
      let task = selectedTask();
      if (!task) throw new ApiError(400, "NO_TASK", "Save or select a task first.", {}, "product");
      task = await persistTask(task);
      await composeTeam(task);
      return "AI Team recomposed. Any prior pack approval was invalidated.";
    });
  }

  async function generatePack() {
    await performAction("generate-pack", elements.generatePack, "Generating…", async function () {
      const task = selectedTask();
      if (!task) throw new ApiError(400, "NO_TASK", "Save the task before generating a Codex Pack.", {}, "product");
      const pack = await api("/api/tasks/" + task.id + "/codex-packs", { method: "POST" });
      state.selectedPackId = pack.id;
      return "Codex Pack v" + pack.version + " generated. Approval is required.";
    });
  }

  async function approvePack() {
    await performAction("approve-pack", elements.approvePack, "Approving…", async function () {
      const task = selectedTask();
      const pack = currentPack();
      if (!task || !pack) throw new ApiError(400, "NO_PACK", "Generate a Codex Pack before approval.", {}, "product");
      await api("/api/tasks/" + task.id + "/codex-packs/" + pack.id + "/approve", { method: "POST" });
      return "Codex Pack v" + pack.version + " approved for this task baseline.";
    });
  }

  async function runCodex() {
    await performAction("run-codex", elements.runCodex, "Starting…", async function () {
      const task = selectedTask();
      if (!task) throw new ApiError(400, "NO_TASK", "Select a saved task first.", {}, "product");
      await api("/api/tasks/" + task.id + "/codex-runs", { method: "POST" });
      return "Codex run started in an isolated Git worktree.";
    });
  }

  async function cancelCodex() {
    await performAction("cancel-codex", elements.cancelCodex, "Cancelling…", async function () {
      const run = currentCodexRun();
      if (!run) throw new ApiError(400, "NO_RUN", "No active Codex run is available.", {}, "product");
      await api("/api/codex-runs/" + run.id + "/cancel", { method: "POST" });
      return "Codex cancellation requested.";
    });
  }

  async function decideAcceptance(decision) {
    const button = decision === "accept" ? elements.acceptResult : elements.rejectResult;
    const pending = decision === "accept" ? "Accepting…" : "Rejecting…";
    await performAction("acceptance-decision", button, pending, async function () {
      const acceptance = state.ownerAcceptance;
      if (!acceptance) throw new ApiError(400, "NO_ACCEPTANCE", "No acceptance session is ready.", {}, "product");
      await api("/api/owner-acceptance/" + acceptance.id + "/" + decision, {
        method: "POST",
        body: { note: elements.acceptanceNote.value }
      });
      return decision === "accept"
        ? "Result accepted. Compact Sync created. No merge or push was performed."
        : "Result rejected. The decision and note were saved.";
    });
  }

  async function runCompactSync() {
    await performAction("run-compact-sync", elements.runCompactSync, "Running…", async function () {
      const task = selectedTask();
      if (!task || task.action !== "Compact Sync") {
        throw new ApiError(400, "ACTION_REQUIRED", "Choose Compact Sync in Advanced task execution settings and save the task first.", {}, "product");
      }
      await api("/api/tasks/" + task.id + "/run", { method: "POST", body: { action: "compact_sync" } });
      return "Compact Sync completed. Result and acceptance evidence were saved.";
    });
  }

  async function createSchedule() {
    await performAction("create-schedule", elements.createSchedule, "Creating…", async function () {
      const task = selectedTask();
      const interval = Number(elements.scheduleInterval.value);
      if (!task || task.action !== "Compact Sync") {
        throw new ApiError(400, "ACTION_REQUIRED", "Save a Compact Sync task before creating a schedule.", {}, "product");
      }
      if (!Number.isInteger(interval) || interval < 1) {
        throw new ApiError(400, "INTERVAL_REQUIRED", "Enter an interval of at least one second.", {}, "product");
      }
      const schedule = await api("/api/schedules", {
        method: "POST",
        body: { task_id: task.id, name: "Compact Sync every " + interval + " seconds", interval_seconds: interval }
      });
      state.selectedScheduleId = schedule.id;
      return "Recurring Compact Sync schedule created.";
    });
  }

  async function patchSchedule(paused) {
    const button = paused ? elements.pauseSchedule : elements.resumeSchedule;
    await performAction(paused ? "pause-schedule" : "resume-schedule", button, paused ? "Pausing…" : "Resuming…", async function () {
      const schedule = currentSchedule();
      if (!schedule) throw new ApiError(400, "NO_SCHEDULE", "Create a schedule first.", {}, "product");
      await api("/api/schedules/" + schedule.id, { method: "PATCH", body: { paused: paused } });
      return paused ? "Schedule paused." : "Schedule resumed.";
    });
  }

  function openAccountMenu() {
    elements.accountMenu.hidden = false;
    elements.accountMenuButton.setAttribute("aria-expanded", "true");
    elements.logoutButton.focus();
  }

  function closeAccountMenu() {
    elements.accountMenu.hidden = true;
    elements.accountMenuButton.setAttribute("aria-expanded", "false");
  }

  function toggleAccountMenu() {
    if (elements.accountMenu.hidden) openAccountMenu();
    else closeAccountMenu();
  }

  function openTaskDrawer() {
    elements.taskSidebar.classList.add("is-open");
    elements.sidebarBackdrop.hidden = false;
    elements.mobileMenuToggle.setAttribute("aria-expanded", "true");
    elements.mobileMenuToggle.setAttribute("aria-label", "Close task navigation");
    elements.body.classList.add("drawer-open");
    elements.newTask.focus();
  }

  function closeTaskDrawer() {
    elements.taskSidebar.classList.remove("is-open");
    elements.sidebarBackdrop.hidden = true;
    elements.mobileMenuToggle.setAttribute("aria-expanded", "false");
    elements.mobileMenuToggle.setAttribute("aria-label", "Open task navigation");
    elements.body.classList.remove("drawer-open");
  }

  function bindEvents() {
    elements.headerSignup.addEventListener("click", function () { openAuthView("signup"); });
    elements.landingSignup.addEventListener("click", function () { openAuthView("signup"); });
    elements.loginToSignup.addEventListener("click", function () { openAuthView("signup"); });
    elements.headerLogin.addEventListener("click", function () { openAuthView("login"); });
    elements.landingLogin.addEventListener("click", function () { openAuthView("login"); });
    elements.signupToLogin.addEventListener("click", function () {
      elements.loginUsername.value = elements.signupUsername.value;
      openAuthView("login");
    });
    elements.signupBack.addEventListener("click", showLanding);
    elements.loginBack.addEventListener("click", showLanding);
    elements.retrySession.addEventListener("click", initializeSession);
    elements.signupForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitAuth("signup");
    });
    elements.loginForm.addEventListener("submit", function (event) {
      event.preventDefault();
      submitAuth("login");
    });
    [elements.signupUsername, elements.signupPassword].forEach(function (input) {
      input.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        elements.signupForm.requestSubmit();
      });
    });
    [elements.loginUsername, elements.loginPassword].forEach(function (input) {
      input.addEventListener("keydown", function (event) {
        if (event.key !== "Enter") return;
        event.preventDefault();
        elements.loginForm.requestSubmit();
      });
    });
    elements.signupPasswordToggle.addEventListener("click", function () {
      togglePassword(elements.signupPassword, elements.signupPasswordToggle);
    });
    elements.loginPasswordToggle.addEventListener("click", function () {
      togglePassword(elements.loginPassword, elements.loginPasswordToggle);
    });
    [elements.signupUsername, elements.signupPassword].forEach(function (input) {
      input.addEventListener("input", function () {
        const fields = authFields("signup");
        if (input === fields.username) setFieldError(fields.username, fields.usernameError, "");
        if (input === fields.password) setFieldError(fields.password, fields.passwordError, "");
        setAuthFormError("signup", "");
      });
    });
    [elements.loginUsername, elements.loginPassword].forEach(function (input) {
      input.addEventListener("input", function () {
        const fields = authFields("login");
        if (input === fields.username) setFieldError(fields.username, fields.usernameError, "");
        if (input === fields.password) setFieldError(fields.password, fields.passwordError, "");
        setAuthFormError("login", "");
      });
    });
    elements.accountMenuButton.addEventListener("click", toggleAccountMenu);
    elements.logoutButton.addEventListener("click", logout);
    elements.mobileMenuToggle.addEventListener("click", function () {
      if (elements.taskSidebar.classList.contains("is-open")) closeTaskDrawer();
      else openTaskDrawer();
    });
    elements.sidebarClose.addEventListener("click", closeTaskDrawer);
    elements.sidebarBackdrop.addEventListener("click", closeTaskDrawer);
    elements.newTask.addEventListener("click", function () { beginNewTask(true); });
    elements.taskWorkflow.addEventListener("change", syncTaskRequirements);
    elements.taskAction.addEventListener("change", renderActionAvailability);
    elements.taskForm.addEventListener("submit", function (event) {
      event.preventDefault();
      saveTask();
    });
    elements.recomposeTeam.addEventListener("click", recomposeTeam);
    elements.generatePack.addEventListener("click", generatePack);
    elements.approvePack.addEventListener("click", approvePack);
    elements.runCodex.addEventListener("click", runCodex);
    elements.cancelCodex.addEventListener("click", cancelCodex);
    elements.acceptResult.addEventListener("click", function () { decideAcceptance("accept"); });
    elements.rejectResult.addEventListener("click", function () { decideAcceptance("reject"); });
    elements.runCompactSync.addEventListener("click", runCompactSync);
    elements.createSchedule.addEventListener("click", createSchedule);
    elements.pauseSchedule.addEventListener("click", function () { patchSchedule(true); });
    elements.resumeSchedule.addEventListener("click", function () { patchSchedule(false); });
    elements.packHistory.addEventListener("change", function () {
      state.selectedPackId = elements.packHistory.value ? Number(elements.packHistory.value) : null;
      renderPack();
    });

    document.addEventListener("click", function (event) {
      if (!elements.accountMenu.hidden && !elements.accountMenu.contains(event.target) && !elements.accountMenuButton.contains(event.target)) {
        closeAccountMenu();
      }
    });
    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") return;
      if (!elements.accountMenu.hidden) {
        closeAccountMenu();
        elements.accountMenuButton.focus();
      }
      if (elements.taskSidebar.classList.contains("is-open")) {
        closeTaskDrawer();
        elements.mobileMenuToggle.focus();
      }
    });
    window.addEventListener("resize", function () {
      if (window.innerWidth > 760) closeTaskDrawer();
    });
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden && state.auth === AUTH_STATES.SIGNED_IN) refreshWorkspace({ force: true });
    });
  }

  bindEvents();
  renderAuthShell();
  initializeSession();
  window.setInterval(function () {
    if (state.auth === AUTH_STATES.SIGNED_IN && !document.hidden) refreshWorkspace();
  }, POLL_INTERVAL_MS);
}());
