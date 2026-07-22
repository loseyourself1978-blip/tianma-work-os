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
  const UI_VERSION = "0.17.0";
  const TASK_DETAIL_DEFAULTS = Object.freeze({
    objective: "Complete the Development task exactly as specified.",
    source_sync_summary: "None provided.",
    required_output: "The outputs explicitly requested by the Development task.",
    acceptance_target: "The Development task requirements and explicit boundaries are satisfied.",
    implementation_scope: "Only changes required by the Development task are permitted.",
    forbidden_scope: DEFAULT_BOUNDARY
  });
  const ACTIVE_CODEX_RUN_STATUSES = Object.freeze(["queued", "starting", "running", "verifying"]);
  const RUN_BLOCKER_STATUS = Object.freeze({
    TASK_MISSING: "Task required",
    PACK_MISSING: "Pack required",
    PACK_STALE: "Approval expired",
    APPROVAL_REQUIRED: "Approval required",
    APPROVAL_STALE: "Approval expired",
    CODING_SETUP_REQUIRED: "Coding needs setup",
    CODING_RUNTIME_UNAVAILABLE: "Coding unavailable",
    VERIFICATION_SETUP_REQUIRED: "Verification needs setup",
    VERIFICATION_RUNTIME_UNAVAILABLE: "Verification unavailable",
    SOURCE_SNAPSHOT_MISSING: "Source snapshot required",
    SOURCE_CHANGED_SINCE_APPROVAL: "Approval expired",
    ACTIVE_RUN_EXISTS: "Run active"
  });
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
    taskDetails: byId("task-details"),
    taskObjective: byId("task-objective"),
    taskSource: byId("task-source"),
    taskOutput: byId("task-output"),
    taskAcceptanceTarget: byId("task-acceptance-target"),
    taskImplementationScope: byId("task-implementation-scope"),
    taskForbiddenScope: byId("task-forbidden-scope"),
    taskObjectiveProvenance: byId("task-objective-provenance"),
    taskSourceProvenance: byId("task-source-provenance"),
    taskOutputProvenance: byId("task-output-provenance"),
    taskAcceptanceProvenance: byId("task-acceptance-provenance"),
    taskImplementationProvenance: byId("task-implementation-provenance"),
    taskForbiddenScopeProvenance: byId("task-forbidden-scope-provenance"),
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
    aiModelAssignments: byId("ai-model-assignments"),
    codingSetupReason: byId("coding-setup-reason"),
    setupCodex: byId("setup-codex"),
    manageCodex: byId("manage-codex"),
    codexSetupDialog: byId("codex-setup-dialog"),
    codexSetupForm: byId("codex-setup-form"),
    codexSetupTitle: byId("codex-setup-title"),
    codexSetupCapabilityLabel: byId("codex-setup-capability-label"),
    setupCapability: byId("setup-capability"),
    setupExecutionTarget: byId("setup-execution-target"),
    setupModelPicker: byId("setup-model-picker"),
    setupModelSearch: byId("setup-model-search"),
    setupModelOptions: byId("setup-model-options"),
    setupModelSearchStatus: byId("setup-model-search-status"),
    setupModelError: byId("setup-model-error"),
    setupSelectedModel: byId("setup-selected-model"),
    setupModelIndependenceNote: byId("setup-model-independence-note"),
    setupCatalogDetails: byId("setup-catalog-details"),
    setupCatalogProvider: byId("setup-catalog-provider"),
    setupCatalogStatus: byId("setup-catalog-status"),
    setupCatalogSource: byId("setup-catalog-source"),
    setupCatalogVersion: byId("setup-catalog-version"),
    setupCatalogCliVersion: byId("setup-catalog-cli-version"),
    setupCatalogWarnings: byId("setup-catalog-warnings"),
    setupAvailabilityStatus: byId("setup-availability-status"),
    checkCodexAvailability: byId("check-codex-availability"),
    saveAssignCodex: byId("save-assign-codex"),
    cancelCodexSetup: byId("cancel-codex-setup"),
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
    packFrozenTask: byId("pack-frozen-task"),
    packDevelopmentTask: byId("pack-development-task"),
    packTaskIdentity: byId("pack-task-identity"),
    packTaskVersion: byId("pack-task-version"),
    packTaskDigest: byId("pack-task-digest"),
    packVersion: byId("pack-version"),
    packApproval: byId("pack-approval"),
    packStages: byId("pack-stages"),
    packAcceptanceTarget: byId("pack-acceptance-target"),
    packBoundaries: byId("pack-boundaries"),
    packRoutingStatus: byId("pack-routing-status"),
    packSourceSnapshot: byId("pack-source-snapshot"),
    packApprovalEvidence: byId("pack-approval-evidence"),
    generatePack: byId("generate-pack"),
    approvePack: byId("approve-pack"),
    reviewPack: byId("review-pack"),
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
    viewResult: byId("view-result"),
    resultCard: byId("result-card"),
    codexRunId: byId("codex-run-id"),
    taskRunId: byId("task-run-id"),
    taskRunAction: byId("task-run-action"),
    worktreeBranch: byId("worktree-branch"),
    worktreePath: byId("worktree-path"),
    runExitCode: byId("run-exit-code"),
    runStarted: byId("run-started"),
    runFinished: byId("run-finished"),
    runError: byId("run-error"),
    verificationStatus: byId("verification-status"),
    verificationExitCode: byId("verification-exit-code"),
    codexStdout: byId("codex-stdout"),
    codexStderr: byId("codex-stderr"),
    verificationStdout: byId("verification-stdout"),
    verificationStderr: byId("verification-stderr"),
    codingJsonl: byId("coding-jsonl"),
    verificationJsonl: byId("verification-jsonl"),
    resultStatus: byId("result-status"),
    resultTask: byId("result-task"),
    resultTaskIdentity: byId("result-task-identity"),
    resultTaskVersion: byId("result-task-version"),
    resultTaskDigest: byId("result-task-digest"),
    resultPackVersion: byId("result-pack-version"),
    resultLifecycle: byId("result-lifecycle"),
    resultCodingProcess: byId("result-coding-process"),
    resultCodingExitCode: byId("result-coding-exit-code"),
    resultCodingFailure: byId("result-coding-failure"),
    resultCodingProcessProof: byId("result-coding-process-proof"),
    resultCodingTurnProof: byId("result-coding-turn-proof"),
    resultCodingRequestedModel: byId("result-coding-requested-model"),
    resultCodingActualModel: byId("result-coding-actual-model"),
    resultCodingInvocationFailure: byId("result-coding-invocation-failure"),
    resultChangedFiles: byId("result-changed-files"),
    resultUnexpectedFiles: byId("result-unexpected-files"),
    resultDiffEvidence: byId("result-diff-evidence"),
    resultSummary: byId("result-summary"),
    resultTests: byId("result-tests"),
    resultGitEvidence: byId("result-git-evidence"),
    resultTaskAcceptance: byId("result-task-acceptance"),
    resultTaskAcceptanceChecks: byId("result-task-acceptance-checks"),
    resultBoundary: byId("result-boundary"),
    resultVerificationAssignedModel: byId("result-verification-assigned-model"),
    resultVerificationStatus: byId("result-verification-status"),
    resultVerificationProcessStarted: byId("result-verification-process-started"),
    resultVerificationTurnTerminal: byId("result-verification-turn-terminal"),
    resultVerificationProcessExitCode: byId("result-verification-process-exit-code"),
    resultVerificationSummary: byId("result-verification-summary"),
    resultVerificationProcessProof: byId("result-verification-process-proof"),
    resultVerificationTurnProof: byId("result-verification-turn-proof"),
    resultVerificationRequestedModel: byId("result-verification-requested-model"),
    resultVerificationActualModel: byId("result-verification-actual-model"),
    resultVerificationInvocationFailure: byId("result-verification-invocation-failure"),
    resultVerificationVerdict: byId("result-verification-verdict"),
    resultVerificationChecks: byId("result-verification-checks"),
    resultSourceSnapshot: byId("result-source-snapshot"),
    resultRoutingSnapshot: byId("result-routing-snapshot"),
    resultReview: byId("result-review"),
    resultCommit: byId("result-commit"),
    assignmentTechnicalDetails: byId("assignment-technical-details"),
    packRoutingDetails: byId("pack-routing-details"),
    modelInvocationDetails: byId("model-invocation-details"),
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

  const TASK_DETAIL_FIELDS = Object.freeze([
    {
      key: "objective",
      input: elements.taskObjective,
      badge: elements.taskObjectiveProvenance,
      provenanceKey: "objective_provenance"
    },
    {
      key: "source_sync_summary",
      input: elements.taskSource,
      badge: elements.taskSourceProvenance,
      provenanceKey: "source_context_provenance"
    },
    {
      key: "required_output",
      input: elements.taskOutput,
      badge: elements.taskOutputProvenance,
      provenanceKey: "required_output_provenance"
    },
    {
      key: "acceptance_target",
      input: elements.taskAcceptanceTarget,
      badge: elements.taskAcceptanceProvenance,
      provenanceKey: "acceptance_target_provenance"
    },
    {
      key: "implementation_scope",
      input: elements.taskImplementationScope,
      badge: elements.taskImplementationProvenance,
      provenanceKey: "implementation_scope_provenance"
    },
    {
      key: "forbidden_scope",
      input: elements.taskForbiddenScope,
      badge: elements.taskForbiddenScopeProvenance,
      provenanceKey: "forbidden_scope_provenance"
    }
  ]);

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
    codexSetup: null,
    codexSetupDrafts: { coding: null, verification: null },
    codexSetupCapability: "coding",
    codexSetupLoadSequence: 0,
    runEligibility: null,
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
    taskDetailProvenance: {},
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
    if (value === "runtime_available_model_configured_not_invoked") {
      return "Runtime available / Model configured / Not yet invoked";
    }
    return String(value || "waiting")
      .split("_")
      .map(function (part) { return part.charAt(0).toUpperCase() + part.slice(1); })
      .join(" ");
  }

  function runStateSummary(status) {
    const summaries = {
      queued: "Run accepted and queued for isolated execution.",
      starting: "The approved source snapshot is being prepared.",
      running: "Coding invocation is running in the isolated workspace.",
      verifying: "Coding has reached a terminal process state; independent Verification is running.",
      completed: "Coding and Verification completed and acceptance evidence is available.",
      failed: "The Run failed. Review the failed process or acceptance checks below.",
      cancelled: "The Run was cancelled. Review the persisted process and boundary evidence below.",
      timed_out: "The Run timed out. Review the persisted process and boundary evidence below.",
      blocked: "The Run was blocked before completion. Review the blocking evidence below."
    };
    return summaries[String(status || "").toLowerCase()] || "Execution state persisted; review the evidence below.";
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
    } else if (/waiting|review|required|setup|queued|starting|running|verifying|draft|unavailable/.test(normalized)) {
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

  function authenticatedUserFromPayload(data) {
    if (!data || data.authenticated !== true || !data.user || typeof data.user.username !== "string") {
      return null;
    }
    return { username: data.user.username };
  }

  async function probeAmbiguousSignupSession(error) {
    if (
      !error
      || [400, 409].indexOf(error.status) !== -1
      || ["network", "payload"].indexOf(error.category) === -1
    ) return null;
    try {
      const session = await api(AUTH_ROUTES.SESSION);
      return authenticatedUserFromPayload(session);
    } catch (probeError) {
      return null;
    }
  }

  async function completeSignedInTransition(user, fields, mode) {
    fields.password.value = "";
    hidePassword(fields.password, mode === "signup" ? elements.signupPasswordToggle : elements.loginPasswordToggle);
    state.user = user;
    state.auth = AUTH_STATES.SIGNED_IN;
    state.errorScope = null;
    resetProtectedState();
    renderAuthShell();
    setFeedback("Loading your workbench…", "neutral");
    try {
      await refreshWorkspace({ force: true });
    } catch (error) {
      setFeedback("Signed in. Workspace data could not be refreshed. Try again.", "error");
    }
    if (state.auth === AUTH_STATES.SIGNED_IN) elements.workbenchMain.focus();
  }

  function renderAuthSubmissionFailure(mode, fields, error) {
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

    let authenticatedUser = null;
    try {
      const data = await api(mode === "signup" ? AUTH_ROUTES.SIGNUP : AUTH_ROUTES.LOGIN, {
        method: "POST",
        body: {
          username: fields.username.value.trim(),
          password: fields.password.value
        }
      });
      authenticatedUser = authenticatedUserFromPayload(data);
      if (!authenticatedUser) {
        throw new ApiError(200, "UNEXPECTED_RESPONSE", "Something went wrong. Try again.", {}, "payload");
      }
    } catch (error) {
      if (!(error instanceof ApiError)) {
        error = new ApiError(0, "UNEXPECTED_RESPONSE", "Something went wrong. Try again.", {}, "payload");
      }
      if (mode === "signup") authenticatedUser = await probeAmbiguousSignupSession(error);
      if (!authenticatedUser) {
        renderAuthSubmissionFailure(mode, fields, error);
        return;
      }
    }
    await completeSignedInTransition(authenticatedUser, fields, mode);
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
    state.codexSetup = null;
    state.codexSetupDrafts = { coding: null, verification: null };
    state.codexSetupCapability = "coding";
    state.codexSetupLoadSequence += 1;
    state.runEligibility = null;
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
    state.taskDetailProvenance = {};
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
    state.runEligibility = null;
    state.selectedPackId = null;
    state.selectedScheduleId = null;
    state.renderedPlanId = null;
    state.renderedAcceptanceId = null;
    state.renderedAcceptanceSignature = null;
  }

  function normalizedProvenance(value, fallback) {
    if (value === "owner-edited" || value === "owner_edited") return "owner-edited";
    if (value === "derived") return "derived";
    return fallback || "derived";
  }

  function setTaskDetailProvenance(key, value) {
    const field = TASK_DETAIL_FIELDS.find(function (item) { return item.key === key; });
    if (!field) return;
    const provenance = normalizedProvenance(value, "derived");
    state.taskDetailProvenance[key] = provenance;
    field.badge.textContent = provenance;
    field.badge.dataset.provenance = provenance;
  }

  function initializeTaskDetailDefaults() {
    state.taskDetailProvenance = {};
    TASK_DETAIL_FIELDS.forEach(function (field) {
      field.input.value = TASK_DETAIL_DEFAULTS[field.key];
      setTaskDetailProvenance(field.key, "derived");
    });
  }

  function initializeNewTaskForm() {
    elements.taskWorkflow.value = "product_development";
    elements.taskTitle.value = "";
    initializeTaskDetailDefaults();
    elements.taskDetails.open = false;
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
    setFeedback("New task ready. Development task is the only required Owner input.", "neutral");
    if (shouldFocus) elements.taskTitle.focus();
  }

  function syncTaskRequirements() {
    elements.taskTitle.required = true;
    elements.taskProject.required = false;
    TASK_DETAIL_FIELDS.forEach(function (field) { field.input.required = false; });
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
      if (!state.health || state.health.version !== UI_VERSION) {
        throw new ApiError(
          409,
          "RUNTIME_ASSET_MISMATCH",
          "The Workbench assets and runtime version do not match. Restart the current Vol.17 runtime.",
          {},
          "product"
        );
      }
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
          api("/api/tasks/" + task.id + "/owner-acceptance"),
          api("/api/tasks/" + task.id + "/run-eligibility")
        ]);
        state.acceptance = detail[0] || null;
        state.aiPlan = detail[1] || null;
        state.packs = Array.isArray(detail[2]) ? detail[2] : [];
        state.codexRuns = Array.isArray(detail[3]) ? detail[3] : [];
        state.ownerAcceptance = detail[4] && detail[4].acceptance ? detail[4].acceptance : null;
        state.runEligibility = detail[5] && typeof detail[5] === "object" ? detail[5] : null;
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
    const runtimeAvailable = detection && detection.execution_ready === true;
    elements.codexHeaderStatus.textContent = runtimeAvailable
      ? "Codex runtime: Available"
      : "Codex runtime: Needs setup";
    elements.codexHeaderStatus.dataset.status = runtimeAvailable ? "ready" : "setup";
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
    elements.taskTitle.value = task.development_task || task.title || "";
    state.taskDetailProvenance = {};
    TASK_DETAIL_FIELDS.forEach(function (field) {
      const persistedValue = field.key === "forbidden_scope"
        ? task.forbidden_scope || task.boundary_risk
        : task[field.key];
      field.input.value = persistedValue || TASK_DETAIL_DEFAULTS[field.key];
      const explicitProvenance = task[field.provenanceKey]
        || objectRecord(task.detail_provenance)[field.key]
        || objectRecord(task.task_detail_provenance)[field.key];
      const fallback = persistedValue ? "owner-edited" : "derived";
      setTaskDetailProvenance(field.key, normalizedProvenance(explicitProvenance, fallback));
    });
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

  function objectRecord(value) {
    return value && typeof value === "object" && !Array.isArray(value) ? value : {};
  }

  function boundedText(value, fallback, maximum) {
    const text = value === null || value === undefined ? "" : String(value).trim();
    if (!text) return fallback;
    const limit = maximum || 600;
    return text.length > limit ? text.slice(0, limit) + "…" : text;
  }

  function modelDisplayName(model, fallback) {
    if (typeof model === "string") return boundedText(model, fallback || "No model assigned", 160);
    const record = objectRecord(model);
    return boundedText(
      record.display_name || record.name || record.model_name,
      fallback || "No model assigned",
      160
    );
  }

  function modelStableIdentifier(model) {
    if (typeof model === "string") return boundedText(model, "None", 240);
    const record = objectRecord(model);
    return boundedText(record.stable_id || record.provider_model_id || record.id, "None", 240);
  }

  function modelIdentifiers(model) {
    if (typeof model === "string") return [boundedText(model, "", 240)].filter(Boolean);
    const record = objectRecord(model);
    return [record.stable_id, record.provider_model_id, record.model_name, record.id]
      .map(function (value) { return boundedText(value, "", 240); })
      .filter(function (value, index, values) { return value && values.indexOf(value) === index; });
  }

  function modelProviderName(model) {
    const record = objectRecord(model);
    if (typeof record.provider === "string") return boundedText(record.provider, "None", 160);
    return boundedText(objectRecord(record.provider).name, "None", 160);
  }

  function invocationModeLabel(value) {
    const mode = String(value || "").toLowerCase();
    if (mode === "real") return "Real";
    if (mode === "simulated") return "Simulated";
    if (mode === "manual") return "Manual";
    if (mode === "not_applicable" || mode === "deterministic") return "No invocation";
    if (mode === "unavailable") return "Not available";
    return "Not recorded";
  }

  function planTeamItem(plan, capability) {
    const team = plan && Array.isArray(plan.team) ? plan.team : [];
    return team.find(function (item) { return item.capability === capability; }) || null;
  }

  function routeForCapability(routes, capability) {
    return routes.find(function (route) { return route.capability === capability; }) || null;
  }

  function assignmentReadiness(item, model, route) {
    if (item && item.readiness) return item.readiness;
    const modelRecord = objectRecord(model);
    if (modelRecord.configuration_status === "disabled" || modelRecord.availability_status === "disabled") {
      return "disabled";
    }
    if ((item && item.invocation_mode) === "simulated" || modelRecord.invocation_mode === "simulated") {
      return "simulated";
    }
    if (modelRecord.configuration_status === "configured" && modelRecord.availability_status === "available") {
      return modelRecord.evidence_status === "verified" && modelRecord.last_verified_at
        ? "ready"
        : "runtime_available_model_configured_not_invoked";
    }
    if (route && route.status) return route.status;
    return model ? "needs_review" : "needs_setup";
  }

  function normalizeAssignment(item, plan, routes) {
    const record = objectRecord(item);
    const capability = boundedText(record.capability || record.role, "Unassigned capability", 80);
    const route = routeForCapability(routes || [], capability);
    const teamItem = planTeamItem(plan, capability);
    const assignedModel = record.assigned_model || record.model || (route ? route.selected : null);
    const fallbackModel = record.fallback_model || (route ? route.fallback : null);
    const assignedModelIdentifier = modelStableIdentifier(assignedModel);
    const deterministicNoInvocation = record.requires_model_invocation === false
      || String(record.execution_mode || "").toLowerCase() === "deterministic"
      || (record.is_executable_assignment === false && assignedModelIdentifier === "None")
      || (capability === "planning" && assignedModelIdentifier === "None");
    const requiresModelInvocation = !deterministicNoInvocation;
    const isExecutableAssignment = record.is_executable_assignment === true
      || (requiresModelInvocation && assignedModelIdentifier !== "None");
    const displayName = deterministicNoInvocation
      ? "Deterministic / No model invocation"
      : boundedText(record.display_name, "", 160) || modelDisplayName(assignedModel, "No model assigned");
    const responsibility = boundedText(
      record.responsibility || (teamItem && teamItem.role_label),
      "Task-specific capability responsibility",
      300
    );
    const invocationMode = deterministicNoInvocation
      ? "not_applicable"
      : record.invocation_mode || objectRecord(assignedModel).invocation_mode || "unavailable";
    return {
      raw: record,
      capability: capability,
      assignedModel: assignedModel,
      fallbackModel: fallbackModel,
      displayName: displayName,
      responsibility: responsibility,
      readiness: deterministicNoInvocation ? "not_required" : assignmentReadiness(record, assignedModel, route),
      invocationMode: invocationMode,
      requiresModelInvocation: requiresModelInvocation,
      isExecutableAssignment: isExecutableAssignment,
      executionMode: deterministicNoInvocation ? "deterministic" : boundedText(record.execution_mode, "model", 40),
      assignmentReason: boundedText(record.assignment_reason || (route && route.reason), "No assignment reason recorded.", 600),
      routingSource: boundedText(record.routing_source, "Not recorded", 120),
      fallbackAllowed: record.fallback_allowed === true,
      fallbackReason: boundedText(record.fallback_reason || (route && route.fallback_reason), "No fallback reason recorded.", 500),
      independenceRequired: record.independence_required === true,
      independenceStatus: boundedText(record.independence_status, "Not recorded", 120)
    };
  }

  function assignmentsFromPayload(payload) {
    const source = objectRecord(payload);
    const plan = objectRecord(source.plan);
    const routes = Array.isArray(source.routes) ? source.routes : [];
    const explicit = Array.isArray(source.assignments)
      ? source.assignments
      : Array.isArray(plan.assignments)
        ? plan.assignments
        : [];
    if (explicit.length) {
      return explicit.map(function (item) { return normalizeAssignment(item, plan, routes); });
    }
    const team = Array.isArray(plan.team) ? plan.team : [];
    const capabilities = team.length
      ? team.map(function (item) { return item.capability; })
      : Array.isArray(plan.required_capabilities)
        ? plan.required_capabilities
        : routes.map(function (route) { return route.capability; });
    return capabilities.filter(function (capability, index) {
      return capability && capabilities.indexOf(capability) === index;
    }).map(function (capability) {
      return normalizeAssignment({ capability: capability }, plan, routes);
    });
  }

  function currentModelAssignments() {
    return assignmentsFromPayload(state.aiPlan || {});
  }

  function renderModelAssignmentTable(target, rows, emptyText, claimForRow) {
    clearChildren(target);
    if (!rows.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = emptyText;
      target.appendChild(empty);
      return;
    }
    const labels = ["Capability", "Assigned model", "Responsibility", "Readiness", "Real / Simulated"];
    const table = document.createElement("table");
    table.className = "model-assignment-table";
    const head = document.createElement("thead");
    const headRow = document.createElement("tr");
    labels.forEach(function (label) {
      const cell = document.createElement("th");
      cell.scope = "col";
      cell.textContent = label;
      headRow.appendChild(cell);
    });
    head.appendChild(headRow);
    table.appendChild(head);
    const body = document.createElement("tbody");
    rows.forEach(function (row) {
      const tableRow = document.createElement("tr");
      const modelClaim = (row.requiresModelInvocation === false
        ? row.displayName
        : claimForRow ? claimForRow(row) : "Assigned to " + row.displayName)
        + (row.capability === "verification" && row.independenceStatus === "separate_invocation"
          ? " · Same model, separate verification invocation"
          : "");
      const values = [
        humanStatus(row.capability),
        modelClaim,
        row.responsibility,
        humanStatus(row.readiness),
        invocationModeLabel(row.invocationMode)
      ];
      values.forEach(function (value, index) {
        const cell = document.createElement("td");
        cell.dataset.label = labels[index];
        cell.textContent = value;
        if (index === 3 || index === 4) cell.className = "model-state-cell";
        tableRow.appendChild(cell);
      });
      body.appendChild(tableRow);
    });
    table.appendChild(body);
    target.appendChild(table);
  }

  function assignmentTechnicalLine(assignment) {
    const record = assignment.raw;
    const fallback = assignment.fallbackModel
      ? modelStableIdentifier(assignment.fallbackModel) + " / " + modelProviderName(assignment.fallbackModel)
      : "None";
    const diagnostic = boundedText(objectRecord(assignment.assignedModel).safe_diagnostic, "None", 500);
    return [
      "assignment=" + boundedText(record.id, "unpersisted", 40),
      "capability=" + assignment.capability,
      "model_id=" + modelStableIdentifier(assignment.assignedModel),
      "provider=" + modelProviderName(assignment.assignedModel),
      "routing_source=" + assignment.routingSource,
      "reason=" + assignment.assignmentReason,
      "diagnostic=" + diagnostic,
      "evidence_source=" + boundedText(objectRecord(assignment.assignedModel).evidence_source, "none", 80),
      "fallback=" + fallback,
      "fallback_allowed=" + String(assignment.fallbackAllowed),
      "fallback_reason=" + assignment.fallbackReason,
      "requires_model_invocation=" + String(assignment.requiresModelInvocation),
      "is_executable_assignment=" + String(assignment.isExecutableAssignment),
      "execution_mode=" + assignment.executionMode,
      "independence=" + (assignment.independenceRequired ? assignment.independenceStatus : "not_required"),
      "assignment_version=" + boundedText(record.assignment_version, "None", 40),
      "task_version=" + boundedText(record.task_version, "None", 40),
      "snapshot=" + boundedText(record.routing_snapshot_hash, "None", 80)
    ].join(" / ");
  }

  function routingSnapshotForPack(pack) {
    if (!pack) return null;
    if (pack.model_routing_snapshot && typeof pack.model_routing_snapshot === "object") {
      return pack.model_routing_snapshot;
    }
    const metadata = objectRecord(pack.generation_metadata);
    return metadata.model_routing_snapshot && typeof metadata.model_routing_snapshot === "object"
      ? metadata.model_routing_snapshot
      : null;
  }

  function assignmentsForPack(pack) {
    const snapshot = routingSnapshotForPack(pack);
    return snapshot ? assignmentsFromPayload(snapshot) : [];
  }

  function packHasFrozenTask(pack) {
    if (!pack) return false;
    return Boolean(
      String(pack.development_task || "").trim()
      && String(pack.development_task_digest || "").trim()
      && pack.task_id !== null
      && pack.task_id !== undefined
      && pack.task_version !== null
      && pack.task_version !== undefined
    );
  }

  function packAssignmentCounts(snapshot, assignments) {
    const record = objectRecord(snapshot);
    const plan = objectRecord(record.plan);
    const plannedCapabilities = Array.isArray(plan.required_capabilities) ? plan.required_capabilities : [];
    const declaredCapabilityCount = Number(record.capability_count);
    const declaredExecutableCount = Number(record.executable_assignment_count);
    const capabilityCount = Number.isFinite(declaredCapabilityCount) && declaredCapabilityCount >= 0
      ? declaredCapabilityCount
      : plannedCapabilities.length || assignments.length;
    const executableCount = Number.isFinite(declaredExecutableCount) && declaredExecutableCount >= 0
      ? declaredExecutableCount
      : assignments.filter(function (assignment) { return assignment.isExecutableAssignment; }).length;
    const declaredNonExecuting = Array.isArray(record.non_executing_capabilities)
      ? record.non_executing_capabilities
      : [];
    const derivedNonExecuting = assignments.filter(function (assignment) {
      return assignment.requiresModelInvocation === false
        || (assignment.requiresModelInvocation && !assignment.isExecutableAssignment);
    }).map(function (assignment) { return assignment.capability; });
    const nonExecuting = declaredNonExecuting.concat(derivedNonExecuting).filter(function (capability, index, values) {
      return capability && values.indexOf(capability) === index;
    });
    return {
      capabilityCount: capabilityCount,
      executableCount: executableCount,
      nonExecuting: nonExecuting
    };
  }

  function packAssignmentSummary(snapshot, assignments) {
    const counts = packAssignmentCounts(snapshot, assignments);
    return "Capabilities: " + counts.capabilityCount
      + " · Executable model assignments: " + counts.executableCount
      + " · Unassigned/non-executing capabilities: "
      + (counts.nonExecuting.length ? counts.nonExecuting.map(humanStatus).join(", ") : "None");
  }

  function renderPackRoutingDetails(pack) {
    const snapshot = routingSnapshotForPack(pack);
    if (!snapshot) {
      appendTextList(elements.packRoutingDetails, [], "No persisted routing snapshot selected.");
      return;
    }
    const assignments = assignmentsFromPayload(snapshot);
    const header = [
      "assignment_version=" + boundedText(snapshot.assignment_version, "None", 40),
      "task_version=" + boundedText(snapshot.task_version, "None", 40),
      "routing_snapshot=" + boundedText(snapshot.routing_snapshot_hash, "None", 80),
      "provider_state=" + boundedText(snapshot.provider_state_hash, "None", 80)
    ].join(" / ");
    appendTextList(
      elements.packRoutingDetails,
      [header].concat(assignments.map(assignmentTechnicalLine)),
      "The selected pack contains no model assignments."
    );
  }

  function modelInvocationsForRun(run) {
    if (!run) return [];
    if (Array.isArray(run.model_invocations)) return run.model_invocations;
    const result = objectRecord(run.result);
    return Array.isArray(result.model_invocations) ? result.model_invocations : [];
  }

  function evidenceObjectSummary(value, allowedKeys) {
    const record = objectRecord(value);
    const parts = [];
    allowedKeys.forEach(function (key) {
      const item = record[key];
      if (item === null || item === undefined || item === "") return;
      if (["string", "number", "boolean"].indexOf(typeof item) === -1) return;
      parts.push(key + "=" + boundedText(item, "", 160));
    });
    return parts.length ? parts.join(", ") : "None";
  }

  function verifiedRealInvocation(evidence) {
    const record = objectRecord(evidence);
    const actualIdentifier = boundedText(record.actual_invoked_model_identifier, "", 240);
    const realMode = String(record.invocation_mode || "").toLowerCase() === "real";
    const outcome = String(record.outcome || "").toLowerCase();
    return Boolean(
      actualIdentifier
      && realMode
      && outcome === "succeeded"
      && record.verified_real_invocation === true
    );
  }

  function actualInvocationDisplayName(evidence, assignment) {
    const record = objectRecord(evidence);
    const actualIdentifier = boundedText(record.actual_invoked_model_identifier, "", 240);
    const configuredModel = record.configured_model;
    const knownIdentifiers = modelIdentifiers(configuredModel)
      .concat(assignment ? modelIdentifiers(assignment.assignedModel) : [])
      .concat(assignment ? modelIdentifiers(assignment.fallbackModel) : [])
      .filter(function (value, index, values) { return values.indexOf(value) === index; });
    if (actualIdentifier && knownIdentifiers.indexOf(actualIdentifier) === -1) return actualIdentifier;
    const explicit = boundedText(record.actual_invoked_model_display_name, "", 160);
    if (explicit) return explicit;
    if (actualIdentifier && modelIdentifiers(configuredModel).indexOf(actualIdentifier) !== -1) {
      return modelDisplayName(configuredModel, assignment ? assignment.displayName : "Verified model");
    }
    if (assignment && modelIdentifiers(assignment.assignedModel).indexOf(actualIdentifier) !== -1) {
      return assignment.displayName;
    }
    if (assignment && modelIdentifiers(assignment.fallbackModel).indexOf(actualIdentifier) !== -1) {
      return modelDisplayName(assignment.fallbackModel, "Verified fallback model");
    }
    if (actualIdentifier) return actualIdentifier;
    return modelDisplayName(configuredModel, assignment ? assignment.displayName : "Verified model");
  }

  function invocationIdentifierExplanation(evidence, assignment) {
    const record = objectRecord(evidence);
    const actualIdentifier = boundedText(record.actual_invoked_model_identifier, "", 240);
    if (!actualIdentifier) return "No actual invoked model identifier recorded.";
    const knownIdentifiers = modelIdentifiers(record.configured_model)
      .concat(assignment ? modelIdentifiers(assignment.assignedModel) : [])
      .concat(assignment ? modelIdentifiers(assignment.fallbackModel) : [])
      .filter(function (value, index, values) { return values.indexOf(value) === index; });
    return knownIdentifiers.indexOf(actualIdentifier) !== -1
      ? "Actual invoked identifier matches configured, assigned, or fallback evidence."
      : "Assigned-vs-actual mismatch: the actual invoked identifier is outside configured, assigned, and fallback identifiers.";
  }

  function invocationRow(evidence, assignment) {
    const record = objectRecord(evidence);
    const fallbackAssignment = assignment || normalizeAssignment(
      {
        capability: record.capability,
        assigned_model: record.configured_model,
        responsibility: record.responsibility,
        readiness: record.readiness,
        invocation_mode: record.invocation_mode
      },
      {},
      []
    );
    const verified = verifiedRealInvocation(record);
    const outcome = boundedText(record.outcome, fallbackAssignment.readiness, 80);
    return {
      raw: fallbackAssignment.raw,
      evidence: record,
      capability: boundedText(record.capability, fallbackAssignment.capability, 80),
      assignedModel: fallbackAssignment.assignedModel,
      fallbackModel: fallbackAssignment.fallbackModel,
      displayName: verified
        ? actualInvocationDisplayName(record, fallbackAssignment)
        : modelDisplayName(record.configured_model, fallbackAssignment.displayName),
      responsibility: boundedText(record.responsibility, fallbackAssignment.responsibility, 300),
      readiness: verified ? "verified" : outcome,
      invocationMode: record.invocation_mode || fallbackAssignment.invocationMode,
      verifiedReal: verified
    };
  }

  function invocationTechnicalLine(evidence, assignment) {
    const record = objectRecord(evidence);
    const configuredModel = record.configured_model;
    return [
      "evidence=" + boundedText(record.id, "unpersisted", 40),
      "capability=" + boundedText(record.capability, "None", 80),
      "assignment_version=" + boundedText(record.assignment_version, "None", 40),
      "configured_model_id=" + modelStableIdentifier(configuredModel),
      "provider=" + boundedText(record.provider || modelProviderName(configuredModel), "None", 160),
      "actual_model_id=" + boundedText(record.actual_invoked_model_identifier, "None", 240),
      "identifier_check=" + invocationIdentifierExplanation(record, assignment),
      "mode=" + boundedText(record.invocation_mode, "unavailable", 40),
      "outcome=" + boundedText(record.outcome, "not_recorded", 80),
      "verified_real=" + String(verifiedRealInvocation(record)),
      "process={" + evidenceObjectSummary(record.process_evidence, ["process_observed", "exit_code", "duration_ms", "isolated_worktree", "read_only_sandbox", "approved_pack_stdin_complete", "codex_jsonl_observed", "codex_thread_started", "codex_turn_completed", "model_argument_observed", "model_identity_observed", "model_reroute_observed", "stdout_present", "stderr_present", "verification_verdict_observed", "workspace_unchanged_after_verification", "changed_files_checked", "unexpected_files_checked", "exact_content_checked", "test_evidence_checked", "git_boundary_checked", "remote_boundary_checked"]) + "}",
      "provider_evidence={" + evidenceObjectSummary(record.provider_evidence, ["provider_response_observed", "status_code", "request_id_fingerprint", "model_identifier_match"]) + "}",
      "usage={" + evidenceObjectSummary(record.usage_metadata, ["input_tokens", "output_tokens", "total_tokens", "cached_input_tokens"]) + "}",
      "timed_out=" + String(record.timed_out === true),
      "cancelled=" + String(record.cancelled === true),
      "truncated=" + String(record.output_truncated === true),
      "diagnostic=" + boundedText(record.diagnostic_code || record.error_category || record.safe_summary, "None", 500)
    ].join(" / ");
  }

  function renderRunModelEvidence(run) {
    if (!run) {
      appendTextList(elements.modelInvocationDetails, [], "No invocation evidence recorded.");
      return;
    }
    const pack = state.packs.find(function (item) { return item.id === run.pack_id; }) || currentPack();
    const assignments = assignmentsForPack(pack).length ? assignmentsForPack(pack) : currentModelAssignments();
    const invocations = modelInvocationsForRun(run);
    appendTextList(
      elements.modelInvocationDetails,
      invocations.map(function (evidence) {
        const capability = boundedText(objectRecord(evidence).capability, "", 80);
        const assignment = assignments.find(function (item) { return item.capability === capability; }) || null;
        return invocationTechnicalLine(evidence, assignment);
      }),
      "No invocation evidence recorded."
    );
  }

  function firstEvidenceValue(record, keys, fallback) {
    const source = objectRecord(record);
    for (let index = 0; index < keys.length; index += 1) {
      const value = source[keys[index]];
      if (value !== null && value !== undefined && value !== "") return value;
    }
    return fallback;
  }

  function evidenceBoolean(record, keys) {
    const source = objectRecord(record);
    return keys.some(function (key) { return source[key] === true; });
  }

  function evidenceFailure(record) {
    return boundedText(
      firstEvidenceValue(record, ["sanitized_failure", "failure", "failure_reason", "safe_summary", "error"], ""),
      "None",
      600
    );
  }

  function evidenceStatus(record, fallback) {
    return boundedText(
      firstEvidenceValue(record, ["status", "process_status", "outcome", "state"], fallback || "not_started"),
      fallback || "not_started",
      80
    );
  }

  function evidenceExitCode(record) {
    const value = firstEvidenceValue(record, ["exit_code", "process_exit", "exit_status"], null);
    return value === null || value === undefined ? "None" : String(value);
  }

  function invocationView(record) {
    const source = objectRecord(record);
    const processEvidence = objectRecord(source.process_evidence);
    const turnEvidence = objectRecord(source.turn_evidence);
    const processVerified = evidenceBoolean(source, ["process_execution_verified", "process_verified"])
      || evidenceBoolean(processEvidence, ["process_execution_verified", "process_verified", "process_observed"]);
    const turnVerified = evidenceBoolean(source, ["codex_turn_verified", "turn_verified", "real_invocation_verified"])
      || evidenceBoolean(turnEvidence, ["codex_turn_verified", "turn_verified", "turn_completed"]);
    const requestedModel = boundedText(
      firstEvidenceValue(source, ["requested_model_identifier", "requested_model", "model_argument"], ""),
      "None",
      240
    );
    const actualModel = boundedText(
      firstEvidenceValue(source, ["actual_resolved_model_identifier", "actual_resolved_model", "actual_invoked_model_identifier"], ""),
      "",
      240
    );
    const actualModelVerified = evidenceBoolean(source, [
      "actual_model_identity_verified",
      "actual_resolved_model_verified",
      "model_identity_verified"
    ]);
    const failure = evidenceFailure(source);
    const invocationStatus = String(evidenceStatus(source, "not_started")).toLowerCase();
    const invocationFailed = ["failed", "cancelled", "timed_out", "blocked"].indexOf(invocationStatus) !== -1
      || (failure !== "None" && !turnVerified);
    return {
      processProof: processVerified ? "Process execution verified" : "Process execution not verified",
      turnProof: turnVerified
        ? "Real Codex CLI invocation: Verified"
        : invocationFailed
          ? "Real invocation: Failed"
          : "Real Codex CLI invocation: Not verified",
      requestedModel: requestedModel,
      actualModel: actualModel && actualModelVerified
        ? actualModel
        : "Not independently exposed by available CLI evidence",
      failure: failure
    };
  }

  function diagnosticText(value, fallback) {
    if (value === null || value === undefined || value === "") return fallback;
    let textValue;
    if (typeof value === "string") {
      textValue = value;
    } else {
      try {
        textValue = JSON.stringify(value, null, 2);
      } catch (_error) {
        textValue = String(value);
      }
    }
    return boundedText(textValue, fallback, 50000);
  }

  function checkLabel(check) {
    if (typeof check === "string") return boundedText(check, "Unnamed check", 500);
    const record = objectRecord(check);
    return boundedText(
      record.summary || record.label || record.name || record.check || record.id,
      "Unnamed check",
      500
    );
  }

  function renderEvidenceChecks(target, record, emptyText) {
    const source = objectRecord(record);
    const failed = Array.isArray(source.failed_checks) ? source.failed_checks : [];
    const passed = Array.isArray(source.passed_checks) ? source.passed_checks : [];
    const values = failed.map(function (check) { return "Failed — " + checkLabel(check); })
      .concat(passed.map(function (check) { return "Passed — " + checkLabel(check); }));
    appendTextList(target, values, emptyText);
  }

  function renderStructuredTests(tests) {
    clearChildren(elements.resultTests);
    const actualTests = Array.isArray(tests) ? tests.filter(function (test) {
      const record = objectRecord(test);
      return record.evidence_type === "test_execution";
    }) : [];
    if (!actualTests.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No actual test executions reported.";
      elements.resultTests.appendChild(empty);
      return;
    }
    actualTests.forEach(function (test) {
      const record = objectRecord(test);
      const item = document.createElement("article");
      const heading = document.createElement("strong");
      const status = document.createElement("span");
      const summary = document.createElement("p");
      item.className = "result-test-item";
      item.dataset.status = String(record.status || "not_recorded");
      heading.textContent = boundedText(record.command_label, "Unnamed test command", 300);
      status.textContent = humanStatus(record.status || "not_recorded")
        + " · exit " + (record.exit_code === null || record.exit_code === undefined ? "not recorded" : String(record.exit_code));
      summary.textContent = boundedText(record.summary, "No concise test summary recorded.", 600);
      item.appendChild(heading);
      item.appendChild(status);
      item.appendChild(summary);
      elements.resultTests.appendChild(item);
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
      renderModelAssignmentTable(
        elements.aiModelAssignments,
        [],
        "Save a task to compose model assignments."
      );
      appendTextList(elements.assignmentTechnicalDetails, [], "No model assignments loaded.");
      setStatusLabel(elements.aiTeamStatus, "waiting");
      return;
    }

    const required = Array.isArray(plan.required_capabilities) ? plan.required_capabilities : [];
    const assignments = assignmentsFromPayload(payload);
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
    renderModelAssignmentTable(
      elements.aiModelAssignments,
      assignments,
      "No model assignments were returned for this plan."
    );
    appendTextList(
      elements.assignmentTechnicalDetails,
      assignments.map(assignmentTechnicalLine),
      "No model assignments loaded."
    );
    setStatusLabel(elements.aiTeamStatus, "composed");
    if (state.renderedPlanId !== plan.id) {
      if (plan.risk_level) elements.riskLevel.value = plan.risk_level;
      if (plan.urgency) elements.aiUrgency.value = plan.urgency;
      state.renderedPlanId = plan.id;
    }
  }

  function renderPack() {
    const pack = currentPack();
    const snapshot = routingSnapshotForPack(pack);
    const snapshotAssignments = snapshot ? assignmentsFromPayload(snapshot) : [];
    const frozenTaskComplete = packHasFrozenTask(pack);
    const eligibilityBlocker = primaryRunBlocker(effectiveRunEligibility());
    const eligibilityBlockerCode = String(eligibilityBlocker && eligibilityBlocker.code || "");
    const approvalExpired = Boolean(
      pack && pack.approved && [
        "PACK_STALE",
        "APPROVAL_STALE",
        "SOURCE_SNAPSHOT_MISSING",
        "SOURCE_CHANGED_SINCE_APPROVAL"
      ].indexOf(eligibilityBlockerCode) !== -1
    );
    elements.packStatus.textContent = pack && !frozenTaskComplete
      ? "Incomplete Pack"
      : approvalExpired
      ? "Approval expired"
      : pack
        ? humanStatus(pack.status)
        : "Not generated";
    elements.packFrozenTask.hidden = !pack;
    elements.packDevelopmentTask.textContent = pack
      ? String(pack.development_task || "Frozen Development task missing from this Pack.")
      : "No frozen Development task.";
    elements.packTaskIdentity.textContent = pack && pack.task_id !== null && pack.task_id !== undefined
      ? "Task #" + pack.task_id
      : "None";
    elements.packTaskVersion.textContent = pack && pack.task_version !== null && pack.task_version !== undefined
      ? String(pack.task_version)
      : "None";
    elements.packTaskDigest.textContent = pack && pack.development_task_digest
      ? String(pack.development_task_digest)
      : "None — approval blocked";
    elements.packVersion.textContent = pack ? "v" + pack.version : "None";
    elements.packApproval.textContent = !pack
      ? "Required before execution"
      : approvalExpired
        ? "Expired — Regenerate Codex Pack"
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
    elements.packRoutingStatus.textContent = !pack
      ? "Waiting for assignments"
      : snapshot
        ? packAssignmentSummary(snapshot, snapshotAssignments)
        : "No routing snapshot recorded";
    const sourceSnapshot = pack ? objectRecord(pack.source_snapshot) : {};
    elements.packSourceSnapshot.textContent = pack && pack.source_snapshot_digest
      ? String(pack.source_snapshot_digest).slice(0, 16) + "… / "
        + String(Array.isArray(sourceSnapshot.included_manifest) ? sourceSnapshot.included_manifest.length : 0)
        + " included file(s)"
      : "Generate a Pack to capture the approved source state.";
    elements.packApprovalEvidence.textContent = !pack
      ? "Generate a pack to freeze the routing snapshot."
      : !frozenTaskComplete
        ? "Approval blocked: the Pack does not contain the complete frozen Development task and its digest."
      : approvalExpired
        ? boundedText(
            eligibilityBlocker && eligibilityBlocker.message,
            "Approval no longer matches the executable snapshot. Regenerate Codex Pack.",
            500
          )
        : pack.approved
        ? snapshot
          ? "Approved for this exact task baseline and model-routing snapshot."
          : "Approved legacy pack; no model-routing snapshot was recorded."
        : snapshot
          ? "Approval will bind this exact task baseline and model-routing snapshot."
          : "Regenerate after composing model assignments.";
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
    renderPackRoutingDetails(selected);
    elements.generatePack.textContent = pack ? "Regenerate Codex Pack" : "Generate Codex Pack";
    elements.reviewPack.hidden = !pack;
  }

  function effectiveRunEligibility() {
    const explicit = objectRecord(state.runEligibility);
    if (typeof explicit.eligible === "boolean") return explicit;
    const status = objectRecord(state.codexStatus);
    const embedded = objectRecord(status.run_eligibility || status.runEligibility);
    if (typeof embedded.eligible === "boolean") return embedded;
    return null;
  }

  function primaryRunBlocker(eligibility) {
    if (!eligibility) return null;
    const primary = objectRecord(eligibility.primary_blocker || eligibility.primaryBlocker);
    if (primary.code) return primary;
    const blockers = Array.isArray(eligibility.blockers) ? eligibility.blockers : [];
    return blockers.length ? objectRecord(blockers[0]) : null;
  }

  function preferredSetupCapability() {
    const blocker = primaryRunBlocker(effectiveRunEligibility());
    if (blocker && /^VERIFICATION_/.test(String(blocker.code || ""))) return "verification";
    if (blocker && /^CODING_/.test(String(blocker.code || ""))) return "coding";
    const assignments = currentModelAssignments();
    const coding = assignments.find(function (item) { return item.capability === "coding"; });
    const verification = assignments.find(function (item) { return item.capability === "verification"; });
    return coding && coding.assignedModel && (!verification || !verification.assignedModel)
      ? "verification"
      : "coding";
  }

  function renderCodex() {
    const detection = state.codexStatus;
    const run = currentCodexRun();
    const assignments = currentModelAssignments();
    const coding = assignments.find(function (item) { return item.capability === "coding"; });
    const verification = assignments.find(function (item) { return item.capability === "verification"; });
    const pack = currentPack();
    const eligibility = effectiveRunEligibility();
    const blocker = primaryRunBlocker(eligibility);
    let status;
    let reason;
    let nextAction;
    if (eligibility) {
      status = eligibility.eligible
        ? "Ready"
        : RUN_BLOCKER_STATUS[String(blocker && blocker.code || "")] || "Blocked";
      reason = eligibility.eligible
        ? "All server-validated execution conditions are satisfied."
        : boundedText(blocker && blocker.message, "Resolve the current execution blocker.", 500);
      nextAction = eligibility.eligible
        ? "Run Codex"
        : boundedText(
            blocker && (blocker.next_action || blocker.nextAction) || eligibility.next_action || eligibility.nextAction,
            "Resolve the blocker",
            160
          );
    } else {
      // Compatibility fallback for older runtimes. Current Vol.17 runtimes return
      // /api/tasks/{taskId}/run-eligibility and never rely on this local gate.
      const ready = detection && detection.execution_ready === true;
      status = ready ? "Ready" : "Needs setup";
      reason = detection && detection.readiness_reason
        ? detection.readiness_reason
        : "Checking the supported local command.";
      nextAction = ready ? "Run Codex" : "Set up Codex";
      if (ready && (!coding || !coding.assignedModel || !verification || !verification.assignedModel)) {
        status = "Needs setup";
        reason = "Coding and Verification both require explicit assignments.";
        nextAction = !coding || !coding.assignedModel ? "Set up Codex" : "Set up Verification";
      } else if (ready && (!pack || pack.status === "invalidated")) {
        status = "Approval expired";
        nextAction = "Regenerate Codex Pack";
      } else if (ready && !pack.approved) {
        status = "Approval required";
        nextAction = "Approve Codex Pack";
      }
    }
    elements.codexReadiness.textContent = status;
    elements.codexReason.textContent = reason;
    elements.runStatus.textContent = run ? humanStatus(run.status) : "Not started";
    const active = run && ACTIVE_CODEX_RUN_STATUSES.indexOf(run.status) !== -1;
    elements.codexNextAction.textContent = active
      ? "Wait for completion or select Cancel Run."
      : nextAction;
    elements.codingSetupReason.textContent = reason + " Next Owner action: " + (active ? "Wait or Cancel Run" : nextAction) + ".";
    const configured = Boolean(
      detection && detection.configuration_status === "configured"
      || coding && coding.assignedModel
      || verification && verification.assignedModel
    );
    const blockerCode = String(blocker && blocker.code || "");
    const setupRequired = blockerCode === "CODING_SETUP_REQUIRED"
      || blockerCode === "VERIFICATION_SETUP_REQUIRED";
    elements.setupCodex.hidden = configured && !setupRequired;
    elements.setupCodex.textContent = blockerCode === "VERIFICATION_SETUP_REQUIRED"
      ? "Set up Verification"
      : "Set up Codex";
    elements.setupCodex.disabled = state.pending.has("codex-setup");
    elements.manageCodex.hidden = !configured;
    elements.manageCodex.disabled = state.pending.has("codex-setup");
    elements.codexRunId.textContent = run ? "#" + run.id : "None";
    elements.worktreeBranch.textContent = run && run.worktree_branch ? run.worktree_branch : "None";
    elements.worktreePath.textContent = run && run.worktree_path ? run.worktree_path : "None";
    elements.runExitCode.textContent = run && run.exit_code !== null && run.exit_code !== undefined ? String(run.exit_code) : "None";
    setStatusLabel(elements.runStatus, elements.runStatus.textContent);
  }

  function capabilityLabel(capability) {
    return capability === "verification" ? "Verification" : "Coding";
  }

  function normalizedSetupCapability(capability) {
    return capability === "verification" ? "verification" : "coding";
  }

  function configurationForSetup(setup, capability) {
    const payload = objectRecord(setup);
    const capabilityPayload = objectRecord(objectRecord(payload.capabilities)[capability]);
    return objectRecord(capabilityPayload.configuration || payload.configuration);
  }

  function evidenceForSetup(setup, capability) {
    const payload = objectRecord(setup);
    const capabilityPayload = objectRecord(objectRecord(payload.capabilities)[capability]);
    return objectRecord(capabilityPayload.availability_evidence || payload.availability_evidence);
  }

  function canonicalModelIdentifier(model) {
    const source = objectRecord(model);
    return String(source.canonical_model_id || source.provider_model_id || "").trim();
  }

  function assignedModelForCapability(capability) {
    const assignment = currentModelAssignments().find(function (item) {
      return item.capability === capability;
    });
    return objectRecord(assignment && assignment.assignedModel);
  }

  function catalogModelsForCapability(catalog, capability) {
    const payload = objectRecord(catalog);
    const adapter = objectRecord(payload.adapter);
    const provider = objectRecord(payload.provider);
    const seen = new Set();
    return (Array.isArray(payload.models) ? payload.models : []).filter(function (item) {
      const entry = objectRecord(item);
      const identifier = canonicalModelIdentifier(entry);
      const capabilities = Array.isArray(entry.supported_capabilities)
        ? entry.supported_capabilities
        : [];
      if (!identifier || identifier.length > 240 || seen.has(identifier)) return false;
      if (adapter.id && entry.adapter_id && entry.adapter_id !== adapter.id) return false;
      if (provider.id && entry.provider_id && entry.provider_id !== provider.id) return false;
      if (capabilities.length && capabilities.indexOf(capability) === -1) return false;
      seen.add(identifier);
      return true;
    });
  }

  function preservedAssignmentRecord(catalog, capability) {
    const catalogAssignment = objectRecord(objectRecord(catalog).currently_assigned_model);
    if (canonicalModelIdentifier(catalogAssignment)) return catalogAssignment;
    return assignedModelForCapability(capability);
  }

  function legacyCatalogEntry(record, catalog) {
    const source = objectRecord(record);
    const payload = objectRecord(catalog);
    return {
      adapter_id: objectRecord(payload.adapter).id || "codex_cli",
      provider_id: objectRecord(payload.provider).id || "local_codex_cli",
      canonical_model_id: canonicalModelIdentifier(source),
      display_name: source.display_name || canonicalModelIdentifier(source),
      aliases: [],
      selectable: false,
      recommended: false,
      lifecycle_status: source.lifecycle_status || "legacy",
      compatibility_status: "review_required",
      compatibility_source: "preserved_assignment",
      catalog_version: payload.catalog_version || "",
      supported_capabilities: [],
      model_family: "",
      performance_tier: "",
      disabled_reason: "Existing legacy/custom model — review required",
      preserved_legacy: true
    };
  }

  function setupDraft(setup, catalog, capability) {
    const models = catalogModelsForCapability(catalog, capability);
    const assignment = preservedAssignmentRecord(catalog, capability);
    const assignedIdentifier = canonicalModelIdentifier(assignment);
    const explicitlyNotListed = assignment.catalog_listed === false;
    const listedEntry = explicitlyNotListed ? null : models.find(function (item) {
      return canonicalModelIdentifier(item) === assignedIdentifier;
    });
    const selectedEntry = listedEntry || (assignedIdentifier ? legacyCatalogEntry(assignment, catalog) : null);
    const selectedIdentifier = canonicalModelIdentifier(selectedEntry);
    const configuration = configurationForSetup(setup, capability);
    const configurationMatches = Boolean(
      selectedIdentifier && canonicalModelIdentifier(configuration) === selectedIdentifier
    );
    const checkedModels = new Map();
    if (configurationMatches) {
      checkedModels.set(selectedIdentifier, {
        configuration: configuration,
        evidence: evidenceForSetup(setup, capability)
      });
    }
    return {
      setup: setup,
      catalog: catalog,
      capability: capability,
      models: models,
      selectedEntry: selectedEntry,
      persistedModelIdentifier: assignedIdentifier,
      checkedModels: checkedModels,
      checkedConfiguration: configurationMatches ? configuration : null,
      checkedEvidence: configurationMatches ? evidenceForSetup(setup, capability) : null,
      query: selectedIdentifier,
      filtering: false,
      listOpen: false,
      activeOptionIndex: -1
    };
  }

  function activeSetupDraft() {
    return state.codexSetupDrafts[normalizedSetupCapability(elements.setupCapability.value)];
  }

  function modelSearchFields(entry) {
    const source = objectRecord(entry);
    const aliases = Array.isArray(source.aliases) ? source.aliases : [];
    return [source.display_name, canonicalModelIdentifier(source)].concat(aliases).map(function (value) {
      return String(value || "").toLowerCase();
    });
  }

  function visibleModelEntries(draft) {
    if (!draft) return [];
    const entries = draft.models.slice();
    const selected = objectRecord(draft.selectedEntry);
    if (selected.preserved_legacy && canonicalModelIdentifier(selected)) entries.unshift(selected);
    if (!draft.filtering) return entries;
    const query = String(draft.query || "").trim().toLowerCase();
    if (!query) return entries;
    return entries.filter(function (entry) {
      return modelSearchFields(entry).some(function (value) { return value.indexOf(query) !== -1; });
    });
  }

  function setModelFieldError(message) {
    const visible = Boolean(message);
    elements.setupModelSearch.setAttribute("aria-invalid", visible ? "true" : "false");
    elements.setupModelError.textContent = message || "";
    elements.setupModelError.hidden = !visible;
  }

  function setSetupPrimaryAction(availabilityVerified) {
    elements.checkCodexAvailability.classList.toggle("button-primary", !availabilityVerified);
    elements.checkCodexAvailability.classList.toggle("button-secondary", availabilityVerified);
    elements.saveAssignCodex.classList.toggle("button-primary", availabilityVerified);
    elements.saveAssignCodex.classList.toggle("button-secondary", !availabilityVerified);
  }

  function renderCatalogDetails(catalog) {
    const payload = objectRecord(catalog);
    const adapter = objectRecord(payload.adapter);
    const provider = objectRecord(payload.provider);
    const warnings = Array.isArray(payload.warnings) ? payload.warnings : [];
    elements.setupExecutionTarget.value = adapter.id === "codex_cli" ? adapter.id : "codex_cli";
    elements.setupExecutionTarget.options[0].textContent = boundedText(
      adapter.display_name,
      "Local Codex CLI",
      160
    );
    elements.setupCatalogProvider.textContent = boundedText(provider.display_name, "Local Codex CLI", 160);
    elements.setupCatalogStatus.textContent = humanStatus(payload.catalog_status || "not_reported");
    elements.setupCatalogSource.textContent = boundedText(payload.catalog_source, "Not reported", 240);
    elements.setupCatalogVersion.textContent = boundedText(payload.catalog_version, "Not reported", 120);
    elements.setupCatalogCliVersion.textContent = boundedText(payload.installed_cli_version, "Not reported", 240);
    clearChildren(elements.setupCatalogWarnings);
    if (!warnings.length) {
      const item = document.createElement("li");
      item.textContent = "No catalog warnings.";
      elements.setupCatalogWarnings.appendChild(item);
      return;
    }
    warnings.slice(0, 8).forEach(function (warning) {
      const item = document.createElement("li");
      item.textContent = boundedText(warning, "Catalog warning withheld.", 300);
      elements.setupCatalogWarnings.appendChild(item);
    });
  }

  function renderSelectedModel(draft) {
    const entry = objectRecord(draft && draft.selectedEntry);
    const identifier = canonicalModelIdentifier(entry);
    if (!identifier) {
      elements.setupSelectedModel.textContent = "";
      elements.setupSelectedModel.hidden = true;
      return;
    }
    const status = entry.preserved_legacy
      ? "Existing legacy/custom model — review required"
      : [humanStatus(entry.lifecycle_status), humanStatus(entry.compatibility_status)]
        .filter(function (value) { return value && value !== "None"; })
        .join(" · ");
    elements.setupSelectedModel.textContent = (entry.preserved_legacy ? status : "Selected model")
      + ": " + boundedText(entry.display_name, identifier, 160)
      + " · Exact ID: " + identifier
      + (entry.preserved_legacy || !status ? "" : " · " + status);
    elements.setupSelectedModel.hidden = false;
  }

  function selectedIdentifierForCapability(capability) {
    const draft = state.codexSetupDrafts[capability];
    const draftIdentifier = canonicalModelIdentifier(draft && draft.selectedEntry);
    return draftIdentifier || canonicalModelIdentifier(assignedModelForCapability(capability));
  }

  function renderModelIndependence(draft) {
    const verificationIdentifier = draft && draft.capability === "verification"
      ? canonicalModelIdentifier(draft.selectedEntry)
      : selectedIdentifierForCapability("verification");
    const codingIdentifier = draft && draft.capability === "coding"
      ? canonicalModelIdentifier(draft.selectedEntry)
      : selectedIdentifierForCapability("coding");
    const sameModel = Boolean(
      draft
      && draft.capability === "verification"
      && verificationIdentifier
      && verificationIdentifier === codingIdentifier
    );
    elements.setupModelIndependenceNote.hidden = !sameModel;
  }

  function modelOptionStatus(entry) {
    const source = objectRecord(entry);
    const parts = [];
    if (source.recommended === true) parts.push("Recommended");
    if (source.lifecycle_status) parts.push(humanStatus(source.lifecycle_status));
    if (source.compatibility_status) parts.push(humanStatus(source.compatibility_status));
    if (source.performance_tier) parts.push(boundedText(source.performance_tier, "", 80));
    return parts.join(" · ");
  }

  function selectModelEntry(entry) {
    const draft = activeSetupDraft();
    if (!draft) return;
    if (entry.selectable !== true) {
      elements.setupModelSearchStatus.textContent = boundedText(
        entry.disabled_reason,
        "This model cannot be selected.",
        300
      );
      return;
    }
    const identifier = canonicalModelIdentifier(entry);
    const checked = draft.checkedModels.get(identifier);
    draft.selectedEntry = entry;
    draft.query = identifier;
    draft.filtering = false;
    draft.listOpen = false;
    draft.activeOptionIndex = -1;
    draft.checkedConfiguration = checked ? checked.configuration : null;
    draft.checkedEvidence = checked ? checked.evidence : null;
    elements.setupModelSearch.value = identifier;
    setModelFieldError("");
    renderCodexSetup(draft, draft.capability);
  }

  function renderModelOptions(draft) {
    const entries = visibleModelEntries(draft);
    const selectedIdentifier = canonicalModelIdentifier(draft && draft.selectedEntry);
    clearChildren(elements.setupModelOptions);
    if (!entries.length) {
      const empty = document.createElement("li");
      empty.className = "model-option-empty";
      empty.setAttribute("role", "presentation");
      empty.textContent = draft && draft.filtering && String(draft.query || "").trim()
        ? "No matching supported model"
        : "No supported models are available from this catalog.";
      elements.setupModelOptions.appendChild(empty);
      if (draft) draft.activeOptionIndex = -1;
    } else {
      if (draft.activeOptionIndex >= entries.length) draft.activeOptionIndex = entries.length - 1;
      entries.forEach(function (entry, index) {
        const identifier = canonicalModelIdentifier(entry);
        const option = document.createElement("li");
        option.id = "setup-model-option-" + draft.capability + "-" + String(index);
        option.className = "model-option";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", identifier === selectedIdentifier ? "true" : "false");
        option.setAttribute("aria-disabled", entry.selectable === true ? "false" : "true");
        option.dataset.canonicalModelId = identifier;
        option.dataset.selectable = entry.selectable === true ? "true" : "false";
        option.dataset.lifecycleStatus = String(entry.lifecycle_status || "");
        if (index === draft.activeOptionIndex) option.dataset.active = "true";

        const name = document.createElement("strong");
        name.className = "model-option-name";
        name.textContent = boundedText(entry.display_name, identifier, 160);
        const exactId = document.createElement("code");
        exactId.className = "model-option-id";
        exactId.textContent = identifier;
        const metadata = document.createElement("span");
        metadata.className = "model-option-meta";
        metadata.textContent = modelOptionStatus(entry) || "Catalog metadata not reported";
        option.appendChild(name);
        option.appendChild(exactId);
        option.appendChild(metadata);
        if (entry.purpose) {
          const purpose = document.createElement("span");
          purpose.className = "model-option-purpose";
          purpose.textContent = boundedText(entry.purpose, "", 240);
          option.appendChild(purpose);
        }
        if (entry.selectable !== true) {
          const reason = document.createElement("span");
          reason.className = "model-option-reason";
          reason.textContent = boundedText(entry.disabled_reason, "This model cannot be selected.", 300);
          option.appendChild(reason);
        }
        option.addEventListener("pointerdown", function (event) { event.preventDefault(); });
        option.addEventListener("click", function () { selectModelEntry(entry); });
        elements.setupModelOptions.appendChild(option);
      });
    }

    elements.setupModelOptions.hidden = !(draft && draft.listOpen);
    elements.setupModelSearch.setAttribute("aria-expanded", draft && draft.listOpen ? "true" : "false");
    if (draft && draft.listOpen && draft.activeOptionIndex >= 0 && entries[draft.activeOptionIndex]) {
      elements.setupModelSearch.setAttribute(
        "aria-activedescendant",
        "setup-model-option-" + draft.capability + "-" + String(draft.activeOptionIndex)
      );
    } else {
      elements.setupModelSearch.removeAttribute("aria-activedescendant");
    }

    if (!entries.length && draft && draft.filtering && String(draft.query || "").trim()) {
      elements.setupModelSearchStatus.textContent = "No matching supported model";
    } else if (draft && draft.listOpen) {
      elements.setupModelSearchStatus.textContent = String(entries.length) + " model option"
        + (entries.length === 1 ? "" : "s") + " shown.";
    } else if (selectedIdentifier) {
      elements.setupModelSearchStatus.textContent = "Selected exact model ID: " + selectedIdentifier + ".";
    } else if (!entries.length) {
      elements.setupModelSearchStatus.textContent = "No supported models are available from this catalog.";
    } else {
      elements.setupModelSearchStatus.textContent = "Choose one of " + String(entries.length) + " supported model options.";
    }
  }

  function renderSetupActionState(draft) {
    const entry = objectRecord(draft && draft.selectedEntry);
    const identifier = canonicalModelIdentifier(entry);
    const configuration = objectRecord(draft && draft.checkedConfiguration);
    const evidence = objectRecord(draft && draft.checkedEvidence);
    const verified = Boolean(
      entry.selectable === true
      && identifier
      && canonicalModelIdentifier(configuration) === identifier
      && evidence.result === "available"
    );
    const selectable = entry.selectable === true && Boolean(identifier);
    const hasOptions = Boolean(
      draft && (draft.models.length || objectRecord(draft.selectedEntry).preserved_legacy)
    );
    elements.setupModelSearch.disabled = !hasOptions;
    elements.checkCodexAvailability.disabled = !selectable || state.pending.has("check-codex-availability");
    elements.saveAssignCodex.disabled = !verified || state.pending.has("save-assign-codex");
    setSetupPrimaryAction(verified);

    if (entry.preserved_legacy) {
      elements.setupAvailabilityStatus.textContent = "Existing legacy/custom model — review required. The stored assignment is preserved; choose a supported catalog model to change it.";
    } else if (verified) {
      elements.setupAvailabilityStatus.textContent = "Runtime and authentication ready for "
        + capabilityLabel(draft.capability) + " — checked " + formatTime(evidence.checked_at)
        + ". The requested model identifier is configured; model support and resolution are not independently verified until an explicit Owner-approved invocation.";
    } else if (selectable && evidence.result) {
      elements.setupAvailabilityStatus.textContent = humanStatus(evidence.result) + " for "
        + capabilityLabel(draft.capability) + " — checked " + formatTime(evidence.checked_at) + ".";
    } else if (selectable) {
      elements.setupAvailabilityStatus.textContent = "Check required. This selected catalog model has not been checked for local runtime and authentication readiness.";
    } else if (draft && draft.filtering && String(draft.query || "").trim()) {
      elements.setupAvailabilityStatus.textContent = "Select a supported model from the filtered options before checking availability.";
    } else {
      elements.setupAvailabilityStatus.textContent = "Select a supported model, then click Check availability.";
    }
  }

  function renderCodexSetup(draft, capability) {
    const label = capabilityLabel(capability);
    const assignment = currentModelAssignments().find(function (item) { return item.capability === capability; });
    elements.setupCapability.value = capability;
    elements.codexSetupCapabilityLabel.textContent = label.toUpperCase();
    elements.codexSetupTitle.textContent = assignment && assignment.assignedModel
      ? "Manage Codex"
      : "Set up Codex";
    elements.setupModelSearch.value = draft.query || "";
    renderCatalogDetails(draft.catalog);
    renderSelectedModel(draft);
    renderModelIndependence(draft);
    renderModelOptions(draft);
    elements.saveAssignCodex.textContent = assignment && assignment.assignedModel ? "Save changes" : "Save and assign";
    renderSetupActionState(draft);
  }

  async function loadCodexSetup(capability, requestToken) {
    const normalized = normalizedSetupCapability(capability);
    const task = selectedTask();
    const taskQuery = task ? "&task_id=" + encodeURIComponent(String(task.id)) : "";
    const responses = await Promise.all([
      api("/api/codex/setup?capability=" + encodeURIComponent(normalized) + taskQuery),
      api("/api/model-catalog?adapter=codex_cli&capability=" + encodeURIComponent(normalized) + taskQuery)
    ]);
    if (requestToken && requestToken !== state.codexSetupLoadSequence) return null;
    const setup = responses[0];
    const catalog = responses[1];
    const draft = setupDraft(setup, catalog, normalized);
    state.codexSetupDrafts[normalized] = draft;
    state.codexSetup = setup;
    state.codexSetupCapability = normalized;
    renderCodexSetup(draft, normalized);
    return draft;
  }

  async function openCodexSetup(preferredCapability) {
    const capability = preferredCapability === "verification" || preferredCapability === "coding"
      ? preferredCapability
      : preferredSetupCapability();
    const token = ++state.codexSetupLoadSequence;
    state.codexSetup = null;
    state.codexSetupDrafts = { coding: null, verification: null };
    state.codexSetupCapability = capability;
    elements.setupCatalogDetails.open = false;
    elements.setupCapability.value = capability;
    elements.setupModelSearch.value = "";
    elements.setupModelSearch.disabled = true;
    elements.setupModelOptions.hidden = true;
    elements.setupModelSearch.setAttribute("aria-expanded", "false");
    elements.setupModelSearch.removeAttribute("aria-activedescendant");
    elements.setupModelSearchStatus.textContent = "Loading supported models…";
    elements.setupAvailabilityStatus.textContent = "Loading the selected capability configuration…";
    elements.saveAssignCodex.disabled = true;
    elements.checkCodexAvailability.disabled = true;
    setModelFieldError("");
    const draft = await loadCodexSetup(capability, token);
    if (!draft || token !== state.codexSetupLoadSequence) return;
    if (!elements.codexSetupDialog.open) elements.codexSetupDialog.showModal();
  }

  function openModelOptions(startAtEnd) {
    const draft = activeSetupDraft();
    if (!draft || elements.setupModelSearch.disabled) return;
    draft.listOpen = true;
    const entries = visibleModelEntries(draft);
    if (entries.length) {
      const selectedIdentifier = canonicalModelIdentifier(draft.selectedEntry);
      const selectedIndex = entries.findIndex(function (entry) {
        return canonicalModelIdentifier(entry) === selectedIdentifier;
      });
      draft.activeOptionIndex = startAtEnd
        ? entries.length - 1
        : selectedIndex >= 0 ? selectedIndex : -1;
    } else {
      draft.activeOptionIndex = -1;
    }
    renderModelOptions(draft);
  }

  function closeModelOptions() {
    const draft = activeSetupDraft();
    if (!draft) return;
    draft.listOpen = false;
    draft.activeOptionIndex = -1;
    renderModelOptions(draft);
  }

  function moveActiveModelOption(direction) {
    const draft = activeSetupDraft();
    if (!draft) return;
    const entries = visibleModelEntries(draft);
    if (!entries.length) return;
    draft.activeOptionIndex = draft.activeOptionIndex < 0
      ? direction > 0 ? 0 : entries.length - 1
      : (draft.activeOptionIndex + direction + entries.length) % entries.length;
    renderModelOptions(draft);
  }

  function handleModelSearchInput() {
    const draft = activeSetupDraft();
    if (!draft) return;
    draft.query = elements.setupModelSearch.value;
    draft.filtering = true;
    draft.selectedEntry = null;
    draft.listOpen = true;
    draft.activeOptionIndex = -1;
    setModelFieldError("");
    renderSelectedModel(draft);
    renderModelIndependence(draft);
    renderModelOptions(draft);
    renderSetupActionState(draft);
  }

  function handleModelSearchKeydown(event) {
    const draft = activeSetupDraft();
    if (!draft) return;
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (!draft.listOpen) openModelOptions(false);
      else moveActiveModelOption(1);
      return;
    }
    if (event.key === "ArrowUp") {
      event.preventDefault();
      if (!draft.listOpen) openModelOptions(true);
      else moveActiveModelOption(-1);
      return;
    }
    if (event.key === "Enter") {
      event.preventDefault();
      if (!draft.listOpen) {
        openModelOptions(false);
        return;
      }
      const entry = visibleModelEntries(draft)[draft.activeOptionIndex];
      if (entry) selectModelEntry(entry);
      return;
    }
    if (event.key === "Escape" && draft.listOpen) {
      event.preventDefault();
      event.stopPropagation();
      closeModelOptions();
      return;
    }
    if (event.key === "Tab" && draft.listOpen) closeModelOptions();
  }

  async function checkCodexAvailability() {
    const capability = normalizedSetupCapability(elements.setupCapability.value);
    const draft = state.codexSetupDrafts[capability];
    const selectedEntry = objectRecord(draft && draft.selectedEntry);
    const selectedIdentifier = canonicalModelIdentifier(selectedEntry);
    if (!draft || selectedEntry.selectable !== true || !selectedIdentifier) {
      setModelFieldError("Select a supported model from the list before checking availability.");
      elements.setupAvailabilityStatus.textContent = "Check blocked. Select a supported catalog model, then click Check availability.";
      elements.setupModelSearch.focus();
      return;
    }
    await performAction("check-codex-availability", elements.checkCodexAvailability, "Checking…", async function () {
      const result = await api("/api/codex/setup/check", {
        method: "POST",
        body: {
          model_identifier: selectedIdentifier,
          capability: capability
        }
      });
      const returnedIdentifier = canonicalModelIdentifier(result.configuration);
      if (returnedIdentifier !== selectedIdentifier) {
        throw new ApiError(
          409,
          "CATALOG_SELECTION_MISMATCH",
          "The checked configuration did not match the selected catalog model.",
          {},
          "product"
        );
      }
      draft.setup = {
        configuration: result.configuration,
        availability_evidence: result.availability_evidence,
        capability: capability
      };
      draft.checkedConfiguration = result.configuration;
      draft.checkedEvidence = result.availability_evidence;
      draft.checkedModels.set(selectedIdentifier, {
        configuration: result.configuration,
        evidence: result.availability_evidence
      });
      if (state.codexSetupCapability === capability) {
        state.codexSetup = draft.setup;
        renderCodexSetup(draft, capability);
      }
      return result.available
        ? "Local Codex CLI runtime and authentication are ready for " + capabilityLabel(capability)
          + ". The requested model identifier is configured; support and resolution remain unverified until an explicit Owner-approved invocation."
        : "Local Codex CLI remains unavailable for " + capabilityLabel(capability) + ".";
    });
    if (state.auth === AUTH_STATES.SIGNED_IN && elements.codexSetupDialog.open && activeSetupDraft()) {
      renderCodexSetup(activeSetupDraft(), normalizedSetupCapability(elements.setupCapability.value));
    }
  }

  async function saveAndAssignCodex() {
    const task = selectedTask();
    const capability = normalizedSetupCapability(elements.setupCapability.value);
    const draft = state.codexSetupDrafts[capability];
    const configuration = objectRecord(draft && draft.checkedConfiguration);
    const evidence = objectRecord(draft && draft.checkedEvidence);
    const selectedIdentifier = canonicalModelIdentifier(draft && draft.selectedEntry);
    if (
      !task
      || !configuration.id
      || !selectedIdentifier
      || canonicalModelIdentifier(configuration) !== selectedIdentifier
      || evidence.result !== "available"
    ) {
      setFeedback("Save a task and check availability before assigning " + capabilityLabel(capability) + ".", "error");
      return;
    }
    await performAction("save-assign-codex", elements.saveAssignCodex, "Saving…", async function () {
      const result = await api("/api/tasks/" + task.id + "/codex/setup/assign", {
        method: "POST",
        body: { model_id: configuration.id, capability: capability }
      });
      elements.codexSetupDialog.close();
      if (result.changed === false) {
        return "The same Local Codex CLI model remains assigned to " + capabilityLabel(capability)
          + ". Assignment version, routing snapshot, and Pack approval were preserved.";
      }
      return "Local Codex CLI was assigned to " + capabilityLabel(capability) + ". Regenerate and approve the Codex Pack.";
    });
  }

  function resetCodexSetupDialog() {
    state.codexSetupLoadSequence += 1;
    state.codexSetup = null;
    state.codexSetupDrafts = { coding: null, verification: null };
    elements.setupModelSearch.value = "";
    elements.setupModelSearch.disabled = true;
    elements.setupModelOptions.hidden = true;
    elements.setupModelSearch.setAttribute("aria-expanded", "false");
    elements.setupModelSearch.removeAttribute("aria-activedescendant");
    elements.setupSelectedModel.hidden = true;
    elements.setupModelIndependenceNote.hidden = true;
    elements.setupCatalogDetails.open = false;
    setModelFieldError("");
  }

  function fileEvidenceLabel(item) {
    if (typeof item === "string") return boundedText(item, "Unknown file", 300);
    return boundedText(objectRecord(item).path, "Unknown file", 300);
  }

  function evidenceSummaryLine(record, fallbackStatus, fallbackSummary) {
    const source = objectRecord(record);
    const status = evidenceStatus(source, fallbackStatus);
    const summary = boundedText(
      firstEvidenceValue(source, ["summary", "safe_summary", "reason"], ""),
      "",
      600
    );
    const failure = evidenceFailure(source);
    const detail = summary
      || (failure !== "None" ? failure : Object.keys(source).length ? "" : fallbackSummary || "");
    return humanStatus(status) + (detail ? " — " + detail : "");
  }

  function codingStatusFallback(run) {
    const status = String(run && run.status || "not_started");
    if (status === "queued") return "not_started";
    if (status === "starting") return "starting";
    if (status === "running") return "running";
    if (status === "verifying" || status === "completed") return "completed";
    if (status === "failed" && Number(run.exit_code) === 0) return "completed";
    return status;
  }

  function resultReviewText(status) {
    const normalized = String(status || "");
    if (["queued", "starting", "running", "verifying"].indexOf(normalized) !== -1) {
      return "Execution is active. Review the persisted stage evidence as it advances.";
    }
    if (["failed", "blocked", "timed_out", "cancelled"].indexOf(normalized) !== -1) {
      return "Review the failed process, invocation, or acceptance checks below.";
    }
    return state.ownerAcceptance
      ? "Complete the Owner Acceptance checklist."
      : "Inspect the structured result evidence before making an Owner decision.";
  }

  function renderResult() {
    const task = selectedTask();
    const run = currentCodexRun();
    const legacyRun = currentLegacyRun();
    const hasPersistedRun = Boolean(run);
    elements.resultCard.hidden = !hasPersistedRun;
    elements.viewResult.hidden = !hasPersistedRun;

    if (run) {
      const result = objectRecord(run.result);
      const changes = objectRecord(result.run_produced_changes);
      const codingProcess = objectRecord(result.coding_process);
      const codingInvocation = objectRecord(result.coding_invocation);
      const gitEvidence = objectRecord(result.git_evidence);
      const taskAcceptance = objectRecord(result.task_acceptance);
      const verificationProcess = Object.keys(objectRecord(result.verification_process)).length
        ? objectRecord(result.verification_process)
        : objectRecord(run.verification_target);
      const verificationInvocation = objectRecord(result.verification_invocation);
      const verificationVerdict = objectRecord(result.verification_verdict);
      const advancedDiagnostics = objectRecord(result.advanced_diagnostics);
      const changed = Array.isArray(changes.changed_files)
        ? changes.changed_files
        : Array.isArray(result.changed_files) ? result.changed_files : [];
      const unexpected = Array.isArray(changes.unexpected_files)
        ? changes.unexpected_files
        : Array.isArray(result.unexpected_files) ? result.unexpected_files : [];
      const sanitizedDiff = Object.keys(objectRecord(changes.sanitized_diff_evidence)).length
        ? objectRecord(changes.sanitized_diff_evidence)
        : objectRecord(result.sanitized_diff_evidence);
      const diffRecords = Array.isArray(sanitizedDiff.records) ? sanitizedDiff.records : [];
      const commits = Array.isArray(result.commits) ? result.commits : [];
      const codingView = invocationView(codingInvocation);
      const verificationView = invocationView(verificationInvocation);
      const verificationTarget = objectRecord(run.verification_target);
      const assignedVerificationModel = firstEvidenceValue(
        verificationProcess,
        ["assigned_model_identifier", "assigned_model"],
        firstEvidenceValue(verificationTarget, ["model_identifier", "model"], "None")
      );
      const terminalFailure = [
        evidenceFailure(codingProcess),
        codingView.failure,
        evidenceFailure(verificationProcess),
        verificationView.failure,
        evidenceFailure(taskAcceptance)
      ].find(function (value) { return value && value !== "None"; });

      elements.resultStatus.textContent = humanStatus(run.status);
      elements.resultLifecycle.textContent = humanStatus(run.status);
      elements.resultSummary.textContent = runStateSummary(run.status);
      elements.resultReview.textContent = resultReviewText(run.status);

      elements.resultTask.textContent = String(
        run.development_task || "Frozen Development task unavailable for this Run."
      );
      elements.resultTaskIdentity.textContent = run.task_id !== null && run.task_id !== undefined
        ? "Task #" + run.task_id
        : "None";
      elements.resultTaskVersion.textContent = run.task_version !== null && run.task_version !== undefined
        ? String(run.task_version)
        : "None";
      elements.resultTaskDigest.textContent = run.development_task_digest || "None";
      elements.resultPackVersion.textContent = run.pack_version !== null && run.pack_version !== undefined
        ? "v" + run.pack_version
        : "None";

      elements.resultCodingProcess.textContent = humanStatus(evidenceStatus(codingProcess, codingStatusFallback(run)));
      elements.resultCodingExitCode.textContent = Object.keys(codingProcess).length
        ? evidenceExitCode(codingProcess)
        : run.exit_code === null || run.exit_code === undefined ? "None" : String(run.exit_code);
      elements.resultCodingFailure.textContent = evidenceFailure(codingProcess);
      elements.resultCodingProcessProof.textContent = codingView.processProof;
      elements.resultCodingTurnProof.textContent = codingView.turnProof;
      elements.resultCodingRequestedModel.textContent = codingView.requestedModel;
      elements.resultCodingActualModel.textContent = codingView.actualModel;
      elements.resultCodingInvocationFailure.textContent = codingView.failure;

      elements.resultChangedFiles.textContent = changed.length ? changed.map(fileEvidenceLabel).join(", ") : "None";
      elements.resultUnexpectedFiles.textContent = unexpected.length ? unexpected.map(fileEvidenceLabel).join(", ") : "None";
      elements.resultDiffEvidence.textContent = diffRecords.length
        ? diffRecords.map(function (item) {
            const record = objectRecord(item);
            return boundedText(record.path, "Unknown file", 300)
              + " · " + humanStatus(record.change_type)
              + " · +" + String(record.added_lines === null ? "?" : record.added_lines || 0)
              + " / -" + String(record.removed_lines === null ? "?" : record.removed_lines || 0)
              + " lines · content withheld";
          }).join(" | ")
        : "No Run-produced file diff evidence.";

      elements.resultGitEvidence.textContent = evidenceSummaryLine(
        gitEvidence,
        "not_available",
        "No Git evidence collection result recorded."
      );
      elements.resultTaskAcceptance.textContent = evidenceSummaryLine(
        taskAcceptance,
        "needs_owner_review",
        "No task-acceptance determination recorded."
      );
      renderEvidenceChecks(elements.resultTaskAcceptanceChecks, taskAcceptance, "No acceptance checks reported.");

      elements.resultVerificationAssignedModel.textContent = typeof assignedVerificationModel === "object"
        ? modelStableIdentifier(assignedVerificationModel)
        : boundedText(assignedVerificationModel, "None", 240);
      elements.resultVerificationStatus.textContent = humanStatus(evidenceStatus(verificationProcess, "not_started"));
      elements.resultVerificationProcessStarted.textContent = evidenceBoolean(
        verificationProcess,
        ["process_started", "process_spawned"]
      ) ? "Yes" : "No";
      elements.resultVerificationTurnTerminal.textContent = humanStatus(firstEvidenceValue(
        verificationProcess,
        ["turn_terminal_state", "terminal_turn_state", "final_turn_status"],
        "not_reached"
      ));
      elements.resultVerificationProcessExitCode.textContent = evidenceExitCode(verificationProcess);
      elements.resultVerificationSummary.textContent = evidenceFailure(verificationProcess);
      elements.resultVerificationProcessProof.textContent = verificationView.processProof;
      elements.resultVerificationTurnProof.textContent = verificationView.turnProof;
      elements.resultVerificationRequestedModel.textContent = verificationView.requestedModel;
      elements.resultVerificationActualModel.textContent = verificationView.actualModel;
      elements.resultVerificationInvocationFailure.textContent = verificationView.failure;
      elements.resultVerificationVerdict.textContent = evidenceSummaryLine(
        verificationVerdict,
        "not_reached",
        "Verification verdict was not reached."
      );
      renderEvidenceChecks(elements.resultVerificationChecks, verificationVerdict, "No verification checks reported.");

      renderStructuredTests(result.tests);
      elements.resultCommit.textContent = commits.length
        ? commits.join(" | ")
        : result.post_run_commit
          ? "No new commit; worktree at " + String(result.post_run_commit).slice(0, 12)
          : "No commit evidence";
      const boundary = objectRecord(result.boundary_confirmation);
      const boundaryVerified = boundary.isolated_worktree === true
        && boundary.source_main_unchanged === true
        && boundary.merge_commits_created === false
        && boundary.remote_state_observed === true
        && boundary.remote_state_unchanged === true
        && boundary.git_transport_protocols_allowed === false
        && boundary.codex_tool_network_access_allowed === false
        && boundary.automatic_merge === false
        && boundary.automatic_push === false
        && commits.length === 0;
      elements.resultBoundary.textContent = boundaryVerified
        ? "Verified isolated worktree; no commit or remote-state mutation, and Git push transport remained blocked."
        : Object.keys(boundary).length
          ? evidenceSummaryLine(boundary, "needs_review", "Boundary evidence requires review; inspect Advanced.")
          : "No boundary evidence recorded.";

      elements.resultSourceSnapshot.textContent = run.source_snapshot_digest
        || result.source_snapshot_digest
        || "None";
      elements.resultRoutingSnapshot.textContent = run.routing_snapshot_hash || "None";
      elements.taskRunId.textContent = "None";
      elements.taskRunAction.textContent = "Approved Codex Pack v" + (run.pack_version || "?");
      elements.runStarted.textContent = formatTime(run.started_at);
      elements.runFinished.textContent = formatTime(run.finished_at);
      elements.runError.textContent = ["failed", "blocked", "timed_out", "cancelled"].indexOf(run.status) !== -1
        ? terminalFailure || boundedText(run.owner_summary, "Execution did not complete successfully.", 600)
        : "None";
      elements.verificationStatus.textContent = humanStatus(evidenceStatus(verificationProcess, "not_started"));
      elements.verificationExitCode.textContent = evidenceExitCode(verificationProcess);
      elements.codingJsonl.textContent = diagnosticText(
        run.coding_jsonl_diagnostics || advancedDiagnostics.coding_jsonl,
        "No coding JSONL diagnostics."
      );
      elements.verificationJsonl.textContent = diagnosticText(
        run.verification_jsonl_diagnostics || advancedDiagnostics.verification_jsonl,
        "No verification JSONL diagnostics."
      );
      elements.codexStdout.textContent = diagnosticText(run.stdout, "No standard output.");
      elements.codexStderr.textContent = diagnosticText(run.stderr, "No standard error.");
      elements.verificationStdout.textContent = diagnosticText(run.verification_stdout, "No verification output.");
      elements.verificationStderr.textContent = diagnosticText(run.verification_stderr, "No verification error.");
    } else {
      elements.resultStatus.textContent = "Not run";
      elements.resultLifecycle.textContent = task ? humanStatus(task.status) : "Waiting";
      elements.resultSummary.textContent = "No result yet.";
      elements.resultReview.textContent = "Run Codex to create review evidence.";
      elements.resultTask.textContent = "None";
      elements.resultTaskIdentity.textContent = "None";
      elements.resultTaskVersion.textContent = "None";
      elements.resultTaskDigest.textContent = "None";
      elements.resultPackVersion.textContent = "None";
      elements.resultCodingProcess.textContent = "Not started";
      elements.resultCodingExitCode.textContent = "None";
      elements.resultCodingFailure.textContent = "None";
      elements.resultCodingProcessProof.textContent = "Not verified";
      elements.resultCodingTurnProof.textContent = "Not verified";
      elements.resultCodingRequestedModel.textContent = "None";
      elements.resultCodingActualModel.textContent = "Not independently exposed by available CLI evidence";
      elements.resultCodingInvocationFailure.textContent = "None";
      elements.resultChangedFiles.textContent = "None";
      elements.resultUnexpectedFiles.textContent = "None";
      elements.resultDiffEvidence.textContent = "No Run diff evidence.";
      elements.resultGitEvidence.textContent = "Not available";
      elements.resultTaskAcceptance.textContent = "Needs Owner review";
      renderEvidenceChecks(elements.resultTaskAcceptanceChecks, {}, "No acceptance checks reported.");
      elements.resultVerificationAssignedModel.textContent = "None";
      elements.resultVerificationStatus.textContent = "Not started";
      elements.resultVerificationProcessStarted.textContent = "No";
      elements.resultVerificationTurnTerminal.textContent = "Not reached";
      elements.resultVerificationProcessExitCode.textContent = "None";
      elements.resultVerificationSummary.textContent = "None";
      elements.resultVerificationProcessProof.textContent = "Not verified";
      elements.resultVerificationTurnProof.textContent = "Not verified";
      elements.resultVerificationRequestedModel.textContent = "None";
      elements.resultVerificationActualModel.textContent = "Not independently exposed by available CLI evidence";
      elements.resultVerificationInvocationFailure.textContent = "None";
      elements.resultVerificationVerdict.textContent = "Not reached";
      renderEvidenceChecks(elements.resultVerificationChecks, {}, "No verification checks reported.");
      renderStructuredTests([]);
      elements.resultCommit.textContent = legacyRun ? "No Git commit" : "No commit";
      elements.resultBoundary.textContent = "No boundary evidence recorded.";
      elements.resultSourceSnapshot.textContent = "None";
      elements.resultRoutingSnapshot.textContent = "None";
      elements.taskRunId.textContent = legacyRun ? "#" + legacyRun.id : "None";
      elements.taskRunAction.textContent = legacyRun ? legacyRun.action || "None" : "None";
      elements.runStarted.textContent = legacyRun ? formatTime(legacyRun.started_at) : "Not started";
      elements.runFinished.textContent = legacyRun ? formatTime(legacyRun.finished_at) : "Not finished";
      elements.runError.textContent = legacyRun ? legacyRun.error || "None" : "None";
      elements.verificationStatus.textContent = "Not started";
      elements.verificationExitCode.textContent = "None";
      elements.codingJsonl.textContent = "No coding JSONL diagnostics.";
      elements.verificationJsonl.textContent = "No verification JSONL diagnostics.";
      elements.codexStdout.textContent = legacyRun ? "No process output for the internal worker." : "No output.";
      elements.codexStderr.textContent = legacyRun ? "No process errors for the internal worker." : "No errors.";
      elements.verificationStdout.textContent = "No verification output.";
      elements.verificationStderr.textContent = "No verification errors.";
    }
    renderRunModelEvidence(run);
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
    const activeRun = codexRun && ACTIVE_CODEX_RUN_STATUSES.indexOf(codexRun.status) !== -1;
    const eligibility = effectiveRunEligibility();
    const acceptance = state.ownerAcceptance;
    const schedule = currentSchedule();
    const authenticated = state.auth === AUTH_STATES.SIGNED_IN;

    elements.saveTask.disabled = !authenticated || state.pending.has("save-task");
    elements.recomposeTeam.disabled = !authenticated || !task || state.pending.has("recompose-team");
    elements.setupCodex.disabled = !authenticated || state.pending.has("codex-setup");
    elements.manageCodex.disabled = !authenticated || state.pending.has("codex-setup");
    elements.generatePack.disabled = !authenticated || !task || task.workflow_type !== "product_development" || !plan || state.pending.has("generate-pack");
    elements.approvePack.disabled = !pack
      || !packHasFrozenTask(pack)
      || pack.status !== "approval_required"
      || state.pending.has("approve-pack");
    elements.approvePack.title = pack && !packHasFrozenTask(pack)
      ? "Approval requires the complete frozen Development task, Task version, and digest."
      : "Approve this exact Task, Pack, source, and routing binding.";
    elements.runCodex.disabled = !authenticated
      || !eligibility
      || eligibility.eligible !== true
      || state.pending.has("run-codex");
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
    const payload = {
      project_id: Number(elements.taskProject.value),
      development_task: elements.taskTitle.value,
      action: elements.taskAction.value,
      workflow_type: elements.taskWorkflow.value,
      forbidden_scope: elements.taskForbiddenScope.value || DEFAULT_BOUNDARY,
      boundary_risk: elements.taskForbiddenScope.value || DEFAULT_BOUNDARY
    };
    TASK_DETAIL_FIELDS.forEach(function (field) {
      if (field.key === "forbidden_scope") return;
      if (state.taskDetailProvenance[field.key] === "owner-edited") {
        payload[field.key] = field.input.value;
      }
    });
    return payload;
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
      return "AI Team recomposed. Approval is preserved only when the routing snapshot is unchanged.";
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
      if (!packHasFrozenTask(pack)) {
        throw new ApiError(
          409,
          "PACK_TASK_BINDING_INCOMPLETE",
          "Review Pack cannot be approved because its frozen Development task binding is incomplete.",
          {},
          "product"
        );
      }
      await api("/api/tasks/" + task.id + "/codex-packs/" + pack.id + "/approve", { method: "POST" });
      return "Codex Pack v" + pack.version + " approved for this task baseline.";
    });
  }

  async function runCodex() {
    await performAction("run-codex", elements.runCodex, "Checking eligibility…", async function () {
      const task = selectedTask();
      if (!task) throw new ApiError(400, "NO_TASK", "Select a saved task first.", {}, "product");
      await api("/api/tasks/" + task.id + "/codex-runs", { method: "POST" });
      return "Codex run queued. TWOS will verify the isolated worktree before process launch.";
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
    TASK_DETAIL_FIELDS.forEach(function (field) {
      field.input.addEventListener("input", function () {
        setTaskDetailProvenance(field.key, "owner-edited");
      });
    });
    elements.recomposeTeam.addEventListener("click", recomposeTeam);
    elements.setupCodex.addEventListener("click", function () {
      openCodexSetup().catch(function (error) { setFeedback(productActionMessage(error), "error"); });
    });
    elements.manageCodex.addEventListener("click", function () {
      openCodexSetup().catch(function (error) { setFeedback(productActionMessage(error), "error"); });
    });
    elements.setupCapability.addEventListener("change", function () {
      const capability = normalizedSetupCapability(elements.setupCapability.value);
      const token = ++state.codexSetupLoadSequence;
      state.codexSetupCapability = capability;
      state.codexSetup = null;
      elements.saveAssignCodex.disabled = true;
      elements.checkCodexAvailability.disabled = true;
      elements.setupModelSearch.disabled = true;
      elements.setupModelOptions.hidden = true;
      elements.setupModelSearch.setAttribute("aria-expanded", "false");
      elements.setupModelSearch.removeAttribute("aria-activedescendant");
      setModelFieldError("");
      elements.setupAvailabilityStatus.textContent = "Loading the selected capability configuration…";
      const cached = state.codexSetupDrafts[capability];
      if (cached) {
        state.codexSetup = cached.setup;
        renderCodexSetup(cached, capability);
        return;
      }
      elements.setupModelSearchStatus.textContent = "Loading supported models…";
      loadCodexSetup(capability, token).catch(function (error) {
        if (token !== state.codexSetupLoadSequence) return;
        elements.saveAssignCodex.disabled = true;
        elements.checkCodexAvailability.disabled = true;
        elements.setupModelSearch.disabled = true;
        elements.setupModelSearchStatus.textContent = "Supported models could not be loaded.";
        elements.setupAvailabilityStatus.textContent = "Configuration could not be loaded. Cancel or try again.";
        setFeedback(productActionMessage(error), "error");
      });
    });
    elements.setupModelSearch.addEventListener("focus", function () { openModelOptions(false); });
    elements.setupModelSearch.addEventListener("click", function () { openModelOptions(false); });
    elements.setupModelSearch.addEventListener("input", handleModelSearchInput);
    elements.setupModelSearch.addEventListener("keydown", handleModelSearchKeydown);
    elements.checkCodexAvailability.addEventListener("click", checkCodexAvailability);
    elements.saveAssignCodex.addEventListener("click", saveAndAssignCodex);
    elements.cancelCodexSetup.addEventListener("click", function () { elements.codexSetupDialog.close(); });
    elements.codexSetupDialog.addEventListener("close", resetCodexSetupDialog);
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
      if (
        elements.codexSetupDialog.open
        && !elements.setupModelOptions.hidden
        && !elements.setupModelPicker.contains(event.target)
      ) closeModelOptions();
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
