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
  const SETUP_ROUTES = Object.freeze({
    STATUS: "/api/setup/status",
    START: "/api/setup/start",
    OWNER: "/api/setup/owner",
    WORKSPACE: "/api/setup/workspace",
    OPTIONAL_TOOLS: "/api/setup/optional-tools",
    FINISH: "/api/setup/finish"
  });
  const FIRST_RUN_ACTION_TIMEOUT_MS = 15000;
  const FIRST_RUN_RECONCILE_TIMEOUT_MS = 5000;

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
  const ACTIVE_CODEX_RUN_STATUSES = Object.freeze([
    "queued",
    "starting",
    "running",
    "coding",
    "verifying",
    "settling",
    "verification_eligible",
    "result_pending"
  ]);
  const TERMINAL_CODEX_RUN_STATUSES = Object.freeze([
    "completed",
    "failed",
    "blocked",
    "timed_out",
    "cancelled",
    "process_lost",
    "result_available",
    "result_unavailable",
    "result_integrity_blocked"
  ]);
  const RESULT_AVAILABLE_STATUSES = Object.freeze(["result_available"]);
  const RESULT_BLOCKED_STATUSES = Object.freeze(["result_unavailable", "result_integrity_blocked", "process_lost"]);
  const APPLY_PLAN_STATE_LABELS = Object.freeze({
    awaiting_owner_approval: "AWAITING OWNER APPROVAL",
    ready_for_owner_review: "READY FOR OWNER REVIEW",
    review_with_source_changes: "REVIEW WITH SOURCE CHANGES",
    blocked_by_conflict: "BLOCKED BY CONFLICT",
    blocked_by_candidate: "BLOCKED BY CANDIDATE",
    blocked_by_repository: "BLOCKED BY REPOSITORY",
    expired: "EXPIRED"
  });
  const APPLY_PLAN_DISPOSITIONS = Object.freeze(["INCLUDED", "EXCLUDED", "BLOCKED"]);
  const APPLY_SESSION_STATE_LABELS = Object.freeze({
    PREFLIGHT_BLOCKED: "PREFLIGHT BLOCKED",
    APPLYING: "APPLYING",
    APPLIED: "APPLIED",
    APPLY_FAILED_RECOVERED: "APPLY FAILED — SOURCE RECOVERED",
    APPLY_FAILED_PARTIAL: "APPLY FAILED — PARTIAL SOURCE CHANGE",
    REVERTING: "REVERTING",
    REVERTED: "REVERTED",
    REVERT_BLOCKED: "REVERT BLOCKED",
    REVERT_FAILED_PARTIAL: "REVERT FAILED — PARTIAL SOURCE CHANGE",
    NOT_REQUESTED: "NOT REQUESTED"
  });
  const POST_APPLY_VERIFICATION_STATE_LABELS = Object.freeze({
    READY: "READY",
    VERIFYING: "VERIFYING",
    PASSED: "PASSED",
    BLOCKED: "BLOCKED",
    FAILED: "FAILED"
  });
  const COMMIT_BUILDER_STATE_LABELS = Object.freeze({
    REVIEW_REQUIRED: "READY TO REVIEW",
    READY: "READY TO REVIEW",
    READY_TO_STAGE: "READY TO STAGE",
    STAGING_BLOCKED: "STAGING BLOCKED",
    READY_TO_COMMIT: "READY TO COMMIT",
    COMMIT_BLOCKED: "COMMIT BLOCKED",
    STAGING: "STAGE RECOVERY REQUIRED",
    STAGED: "STAGED",
    COMMITTING: "COMMIT RECOVERY REQUIRED",
    COMMITTED: "LOCAL COMMIT CREATED",
    BLOCKED: "BLOCKED",
    FAILED: "FAILED",
    INTEGRITY_BLOCKED: "INTEGRITY BLOCKED",
    EXPIRED: "EXPIRED"
  });
  const PUSH_DELIVERY_STATE_LABELS = Object.freeze({
    READY_TO_PUSH: "READY TO PUSH",
    PUSHING: "PUSHING",
    PUSHED: "PUSHED",
    PUSH_BLOCKED: "PUSH BLOCKED",
    REMOTE_MOVED: "REMOTE MOVED",
    PUSH_FAILED: "PUSH FAILED",
    RECONCILIATION_BLOCKED: "RECONCILIATION BLOCKED"
  });
  const OWNER_COMMIT_STATE_LABELS = Object.freeze({
    COMMIT_REVIEW_REQUIRED: "READY TO REVIEW",
    COMMIT_APPROVAL_REQUIRED: "AWAITING COMMIT APPROVAL",
    COMMIT_CONFIRMATION_REQUIRED: "READY TO COMMIT",
    COMMITTING: "LOCAL COMMIT IN PROGRESS",
    LOCAL_COMMIT_CREATED: "LOCAL COMMIT CREATED",
    COMMITTED: "LOCAL COMMIT CREATED",
    NEEDS_SETUP: "NEEDS SETUP",
    BLOCKED: "COMMIT BLOCKED",
    FAILED: "COMMIT FAILED",
    INTEGRITY_BLOCKED: "COMMIT INTEGRITY BLOCKED",
    NEEDS_REVIEW: "COMMIT NEEDS REVIEW"
  });
  const OWNER_PUSH_STATE_LABELS = Object.freeze({
    PUSH_REVIEW_REQUIRED: "READY TO REVIEW PUSH PLAN",
    PUSH_APPROVAL_REQUIRED: "AWAITING PUSH PLAN APPROVAL",
    PUSH_CONFIRMATION_REQUIRED: "READY TO PUSH",
    PUSHING: "PUSHING",
    DELIVERED: "DELIVERED",
    SUCCEEDED: "DELIVERED",
    ALREADY_DELIVERED: "ALREADY DELIVERED",
    NEEDS_SETUP: "PUSH NEEDS SETUP",
    BLOCKED: "PUSH BLOCKED",
    FAILED: "PUSH FAILED",
    TIMED_OUT: "PUSH TIMED OUT",
    NEEDS_REVIEW: "PUSH NEEDS REVIEW"
  });
  const OWNER_PUSH_CONFIRMATION_LABELS = Object.freeze({
    ready_for_confirmation: "Ready for confirmation",
    submitting: "Submitting Push request",
    running: "Push in progress",
    succeeded: "Push delivered",
    already_delivered: "Already delivered",
    blocked: "Push blocked",
    failed: "Push failed",
    timed_out: "Push timed out",
    needs_review: "Push needs review"
  });
  const OWNER_PUSH_RESPONSE_TIMEOUT_MS = 45 * 1000;
  const OWNER_PUSH_REFRESH_WAIT_MS = 15 * 1000;
  const OWNER_PUSH_RECONCILIATION_POLL_MS = 2 * 1000;
  const OWNER_PUSH_RECONCILIATION_MAX_POLLS = 60;
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
  const ACTIVE_RUN_POLL_INTERVAL_MS = 2000;
  const MAX_IMPORT_BYTES = 1024 * 1024;
  const RUN_LOCAL_MODEL_NOT_EXPOSED = "Not exposed by the current Codex CLI protocol.";

  class ApiError extends Error {
    constructor(status, code, message, fields, category, details) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.code = code || "UNEXPECTED_RESPONSE";
      this.fields = fields && typeof fields === "object" ? fields : {};
      this.category = category || "api";
      this.details = details && typeof details === "object" ? details : {};
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
    firstRunView: byId("first-run-view"),
    firstRunState: byId("first-run-state"),
    firstRunProgress: byId("first-run-progress"),
    firstRunMessage: byId("first-run-message"),
    firstRunCurrentStep: byId("first-run-current-step"),
    firstRunNextAction: byId("first-run-next-action"),
    firstRunBlockingReason: byId("first-run-blocking-reason"),
    firstRunAuthorizationState: byId("first-run-authorization-state"),
    firstRunWelcome: byId("first-run-welcome"),
    firstRunInstallation: byId("first-run-installation"),
    firstRunOwner: byId("first-run-owner"),
    firstRunWorkspace: byId("first-run-workspace"),
    firstRunTools: byId("first-run-tools"),
    firstRunFinish: byId("first-run-finish"),
    firstRunBlocked: byId("first-run-blocked"),
    firstRunSourceVersion: byId("first-run-source-version"),
    firstRunDataRoot: byId("first-run-data-root"),
    firstRunBindAddress: byId("first-run-bind-address"),
    firstRunDatabaseState: byId("first-run-database-state"),
    firstRunRuntimeState: byId("first-run-runtime-state"),
    firstRunLocalAddress: byId("first-run-local-address"),
    firstRunStart: byId("first-run-start"),
    firstRunConfirmInstallation: byId("first-run-confirm-installation"),
    firstRunOwnerForm: byId("first-run-owner-form"),
    firstRunSetupAuthorization: byId("first-run-setup-authorization"),
    firstRunOwnerUsername: byId("first-run-owner-username"),
    firstRunOwnerPassword: byId("first-run-owner-password"),
    firstRunOwnerPasswordConfirmation: byId("first-run-owner-password-confirmation"),
    firstRunCreateOwner: byId("first-run-create-owner"),
    firstRunWorkspaceForm: byId("first-run-workspace-form"),
    firstRunWorkspacePath: byId("first-run-workspace-path"),
    firstRunCreateWorkspace: byId("first-run-create-workspace"),
    firstRunAuthorizeWorkspace: byId("first-run-authorize-workspace"),
    firstRunCodexState: byId("first-run-codex-state"),
    firstRunReviewTools: byId("first-run-review-tools"),
    firstRunSkipTools: byId("first-run-skip-tools"),
    firstRunSummaryOwner: byId("first-run-summary-owner"),
    firstRunSummaryDataRoot: byId("first-run-summary-data-root"),
    firstRunSummaryWorkspace: byId("first-run-summary-workspace"),
    firstRunSummaryTools: byId("first-run-summary-tools"),
    firstRunSummaryAddress: byId("first-run-summary-address"),
    firstRunFinishSetup: byId("first-run-finish-setup"),
    firstRunRefreshStatus: byId("first-run-refresh-status"),
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
    selectedTaskContext: byId("selected-task-context"),
    selectedTaskName: byId("selected-task-name"),
    selectedTaskLoadState: byId("selected-task-load-state"),
    taskForm: byId("task-form"),
    firstRunFirstTaskBanner: byId("first-run-first-task-banner"),
    firstRunFirstTaskNextAction: byId("first-run-first-task-next-action"),
    taskNameField: byId("task-name-field"),
    taskName: byId("task-name"),
    taskTitleLabel: byId("task-title-label"),
    developmentTaskHelp: byId("development-task-help"),
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
    setupCliInstalled: byId("setup-cli-installed"),
    setupCliVersion: byId("setup-cli-version"),
    setupAuthMethod: byId("setup-auth-method"),
    setupAuthStatus: byId("setup-auth-status"),
    setupCredentialStatus: byId("setup-credential-status"),
    setupProviderConnectivity: byId("setup-provider-connectivity"),
    setupRequestedModel: byId("setup-requested-model"),
    setupActualModel: byId("setup-actual-model"),
    setupConnectivityCheckedAt: byId("setup-connectivity-checked-at"),
    setupRunTimeout: byId("setup-run-timeout"),
    setupConnectivityState: byId("setup-connectivity-state"),
    setupConnectivityBlocker: byId("setup-connectivity-blocker"),
    setupConnectivityCommand: byId("setup-connectivity-command"),
    setupConnectivityExitCode: byId("setup-connectivity-exit-code"),
    setupConnectivityDuration: byId("setup-connectivity-duration"),
    setupConnectivityDiagnostics: byId("setup-connectivity-diagnostics"),
    setupAvailabilityStatus: byId("setup-availability-status"),
    checkCodexAvailability: byId("check-codex-availability"),
    verifyCodexConnection: byId("verify-codex-connection"),
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
    runPackVersion: byId("run-pack-version"),
    codexReason: byId("codex-reason"),
    codexNextAction: byId("codex-next-action"),
    runCodex: byId("run-codex"),
    cancelCodex: byId("cancel-codex"),
    viewResult: byId("view-result"),
    startCodexConfirmationDialog: byId("start-codex-confirmation-dialog"),
    startCodexConfirmationTask: byId("start-codex-confirmation-task"),
    startCodexConfirmationPack: byId("start-codex-confirmation-pack"),
    startCodexConfirmationRouting: byId("start-codex-confirmation-routing"),
    startCodexConfirmationWorkspace: byId("start-codex-confirmation-workspace"),
    startCodexConfirmationSource: byId("start-codex-confirmation-source"),
    confirmStartCodexRun: byId("confirm-start-codex-run"),
    cancelStartCodexRun: byId("cancel-start-codex-run"),
    runActivityStatus: byId("run-activity-status"),
    runActivityNotification: byId("run-activity-notification"),
    runActivityList: byId("run-activity-list"),
    refreshRunStatus: byId("refresh-run-status"),
    reconnectCodexRun: byId("reconnect-codex-run"),
    importCodexResult: byId("import-codex-result"),
    importCodexResultFile: byId("import-codex-result-file"),
    runFallbackNote: byId("run-fallback-note"),
    resultCard: byId("result-card"),
    resultEnvelopeStatus: byId("result-envelope-status"),
    resultEnvelopeRequestedModel: byId("result-envelope-requested-model"),
    resultEnvelopeRequestedModelAccepted: byId("result-envelope-requested-model-accepted"),
    resultEnvelopeActualModel: byId("result-envelope-actual-model"),
    resultEnvelopeDuration: byId("result-envelope-duration"),
    resultEnvelopeClassification: byId("result-envelope-classification"),
    resultEnvelopeFinalResponse: byId("result-envelope-final-response"),
    resultEnvelopeChangedCount: byId("result-envelope-changed-count"),
    resultEnvelopeCoding: byId("result-envelope-coding"),
    resultEnvelopeVerification: byId("result-envelope-verification"),
    resultEnvelopeTests: byId("result-envelope-tests"),
    resultEnvelopeIntegrity: byId("result-envelope-integrity"),
    resultEnvelopeNextAction: byId("result-envelope-next-action"),
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
    handoffReviewSection: byId("handoff-review-section"),
    reviewHandoff: byId("review-handoff"),
    handoffReviewContent: byId("handoff-review-content"),
    handoffRunOutcome: byId("handoff-run-outcome"),
    handoffTaskPack: byId("handoff-task-pack"),
    handoffCodingResult: byId("handoff-coding-result"),
    handoffVerificationVerdict: byId("handoff-verification-verdict"),
    handoffTests: byId("handoff-tests"),
    handoffBoundary: byId("handoff-boundary"),
    handoffPhaseGate: byId("handoff-phase-gate"),
    handoffReconciliation: byId("handoff-reconciliation"),
    handoffChangedFiles: byId("handoff-changed-files"),
    handoffWarnings: byId("handoff-warnings"),
    handoffLimitations: byId("handoff-limitations"),
    handoffBlockers: byId("handoff-blockers"),
    instructionDraftSection: byId("instruction-draft-section"),
    instructionDraftStatus: byId("instruction-draft-status"),
    instructionDraftContent: byId("instruction-draft-content"),
    instructionDraftBoundary: byId("instruction-draft-boundary"),
    reviewInstructionDraft: byId("review-instruction-draft"),
    approveInstructionDraft: byId("approve-instruction-draft"),
    resultIntakeAdvancedCard: byId("result-intake-advanced-card"),
    resultMonitorState: byId("result-monitor-state"),
    resultRecoveryState: byId("result-recovery-state"),
    resultSourceIdentity: byId("result-source-identity"),
    resultEnvelopeRecord: byId("result-envelope-record"),
    resultEnvelopeDigest: byId("result-envelope-digest"),
    resultEnvelopeTaskBinding: byId("result-envelope-task-binding"),
    resultEnvelopePackBinding: byId("result-envelope-pack-binding"),
    resultEnvelopeAssignmentBindings: byId("result-envelope-assignment-bindings"),
    resultEnvelopeRoutingBinding: byId("result-envelope-routing-binding"),
    resultProcessIdentity: byId("result-process-identity"),
    resultSessionIdentity: byId("result-session-identity"),
    resultIngestedAt: byId("result-ingested-at"),
    resultIntakeDiagnostics: byId("result-intake-diagnostics"),
    candidateReviewSection: byId("candidate-review-section"),
    reviewChangeCandidate: byId("review-change-candidate"),
    candidateStatus: byId("candidate-status"),
    candidateSourceRun: byId("candidate-source-run"),
    candidateIncludedCount: byId("candidate-included-count"),
    candidateExcludedCount: byId("candidate-excluded-count"),
    candidateUnexpectedFiles: byId("candidate-unexpected-files"),
    candidateAcceptanceStatus: byId("candidate-acceptance-status"),
    candidateVerificationStatus: byId("candidate-verification-status"),
    candidateDriftStatus: byId("candidate-drift-status"),
    candidateNextAction: byId("candidate-next-action"),
    candidateFiles: byId("candidate-files"),
    candidateBlockers: byId("candidate-blockers"),
    candidateAdvancedCard: byId("candidate-advanced-card"),
    candidateRecordId: byId("candidate-record-id"),
    candidateDigest: byId("candidate-digest"),
    candidatePatchIdentity: byId("candidate-patch-identity"),
    candidateSourceSnapshot: byId("candidate-source-snapshot"),
    candidateTaskBinding: byId("candidate-task-binding"),
    candidatePackBinding: byId("candidate-pack-binding"),
    candidateCodingAssignment: byId("candidate-coding-assignment"),
    candidateVerificationAssignment: byId("candidate-verification-assignment"),
    candidateRoutingSnapshot: byId("candidate-routing-snapshot"),
    candidateRunBinding: byId("candidate-run-binding"),
    candidateCodingEvidence: byId("candidate-coding-evidence"),
    candidateVerificationEvidence: byId("candidate-verification-evidence"),
    candidateCreatedAt: byId("candidate-created-at"),
    candidateDriftEvaluation: byId("candidate-drift-evaluation"),
    candidateDriftBaseline: byId("candidate-drift-baseline"),
    candidateDriftCurrent: byId("candidate-drift-current"),
    candidateDriftHead: byId("candidate-drift-head"),
    candidateConflictPaths: byId("candidate-conflict-paths"),
    candidateManifestDetails: byId("candidate-manifest-details"),
    candidateDriftDiagnostics: byId("candidate-drift-diagnostics"),
    applyPlanReviewSection: byId("apply-plan-review-section"),
    reviewApplyPlan: byId("review-apply-plan"),
    approveApplyPlan: byId("approve-apply-plan"),
    applyPlanStatus: byId("apply-plan-status"),
    applyPlanApprovalStatus: byId("apply-plan-approval-status"),
    applyPlanCandidateStatus: byId("apply-plan-candidate-status"),
    applyPlanDriftStatus: byId("apply-plan-drift-status"),
    applyPlanManifestCoverage: byId("apply-plan-manifest-coverage"),
    applyPlanConflicts: byId("apply-plan-conflicts"),
    applyPlanUnexpectedFiles: byId("apply-plan-unexpected-files"),
    applyPlanNextAction: byId("apply-plan-next-action"),
    applyPlanIncludedCount: byId("apply-plan-included-count"),
    applyPlanExcludedCount: byId("apply-plan-excluded-count"),
    applyPlanBlockedCount: byId("apply-plan-blocked-count"),
    applyPlanIncludedPaths: byId("apply-plan-included-paths"),
    applyPlanExcludedPaths: byId("apply-plan-excluded-paths"),
    applyPlanBlockedPaths: byId("apply-plan-blocked-paths"),
    applyPlanPreconditions: byId("apply-plan-preconditions"),
    applyPlanReversibility: byId("apply-plan-reversibility"),
    applyPlanPreValidation: byId("apply-plan-pre-validation"),
    applyPlanPostValidation: byId("apply-plan-post-validation"),
    applyPlanBoundaries: byId("apply-plan-boundaries"),
    applyPlanBlockers: byId("apply-plan-blockers"),
    applyPlanAdvancedCard: byId("apply-plan-advanced-card"),
    applyPlanHistory: byId("apply-plan-history"),
    applyPlanRecordId: byId("apply-plan-record-id"),
    applyPlanVersion: byId("apply-plan-version"),
    applyPlanStatusAtCreation: byId("apply-plan-status-at-creation"),
    applyPlanDigest: byId("apply-plan-digest"),
    applyPlanBindingDigest: byId("apply-plan-binding-digest"),
    applyPlanCandidateRecord: byId("apply-plan-candidate-record"),
    applyPlanCandidateDigest: byId("apply-plan-candidate-digest"),
    applyPlanDriftEvaluation: byId("apply-plan-drift-evaluation"),
    applyPlanDriftFingerprint: byId("apply-plan-drift-fingerprint"),
    applyPlanRepositoryIdentity: byId("apply-plan-repository-identity"),
    applyPlanRepositoryLocator: byId("apply-plan-repository-locator"),
    applyPlanRepositoryFingerprint: byId("apply-plan-repository-fingerprint"),
    applyPlanBranch: byId("apply-plan-branch"),
    applyPlanHead: byId("apply-plan-head"),
    applyPlanCurrentSource: byId("apply-plan-current-source"),
    applyPlanIndexFingerprint: byId("apply-plan-index-fingerprint"),
    applyPlanWorktreeFingerprint: byId("apply-plan-worktree-fingerprint"),
    applyPlanStagedCount: byId("apply-plan-staged-count"),
    applyPlanPolicyVersion: byId("apply-plan-policy-version"),
    applyPlanTaskBinding: byId("apply-plan-task-binding"),
    applyPlanPackBinding: byId("apply-plan-pack-binding"),
    applyPlanRunBinding: byId("apply-plan-run-binding"),
    applyPlanSourceSnapshot: byId("apply-plan-source-snapshot"),
    applyPlanCreatedAt: byId("apply-plan-created-at"),
    applyPlanSupersedes: byId("apply-plan-supersedes"),
    applyPlanSupersessionReason: byId("apply-plan-supersession-reason"),
    applyPlanOperationOrder: byId("apply-plan-operation-order"),
    applyPlanEntryDetails: byId("apply-plan-entry-details"),
    applyPlanExpiryReasons: byId("apply-plan-expiry-reasons"),
    applyPlanDiagnostics: byId("apply-plan-diagnostics"),
    applySessionSection: byId("apply-session-section"),
    applySessionBoundaryNote: byId("apply-session-boundary-note"),
    applyAcceptedChanges: byId("apply-accepted-changes"),
    revertAppliedChanges: byId("revert-applied-changes"),
    applySessionApproval: byId("apply-session-approval"),
    applySessionReadiness: byId("apply-session-readiness"),
    applySessionState: byId("apply-session-state"),
    applySessionResultSummary: byId("apply-session-result-summary"),
    applySessionChangedCount: byId("apply-session-changed-count"),
    applySessionValidation: byId("apply-session-validation"),
    applySessionRecovery: byId("apply-session-recovery"),
    applySessionDrift: byId("apply-session-drift"),
    applySessionOperationCounts: byId("apply-session-operation-counts"),
    applySessionUnrelated: byId("apply-session-unrelated"),
    applySessionIndexBoundary: byId("apply-session-index-boundary"),
    applySessionRevertAvailability: byId("apply-session-revert-availability"),
    applySessionNextAction: byId("apply-session-next-action"),
    applySessionPaths: byId("apply-session-paths"),
    applySessionBlockers: byId("apply-session-blockers"),
    applySessionAdvancedCard: byId("apply-session-advanced-card"),
    applySessionRecordId: byId("apply-session-record-id"),
    applySessionApplyState: byId("apply-session-apply-state"),
    applySessionRevertState: byId("apply-session-revert-state"),
    applySessionPlanRecord: byId("apply-session-plan-record"),
    applySessionPlanDigest: byId("apply-session-plan-digest"),
    applySessionCandidateRecord: byId("apply-session-candidate-record"),
    applySessionCandidateDigest: byId("apply-session-candidate-digest"),
    applySessionJournalDigest: byId("apply-session-journal-digest"),
    applySessionDriftEvaluation: byId("apply-session-drift-evaluation"),
    applySessionRepositoryFingerprint: byId("apply-session-repository-fingerprint"),
    applySessionBranch: byId("apply-session-branch"),
    applySessionHead: byId("apply-session-head"),
    applySessionIndexFingerprint: byId("apply-session-index-fingerprint"),
    applySessionCreatedAt: byId("apply-session-created-at"),
    applySessionApplyFinishedAt: byId("apply-session-apply-finished-at"),
    applySessionRevertFinishedAt: byId("apply-session-revert-finished-at"),
    applySessionEntryDetails: byId("apply-session-entry-details"),
    applySessionIntegrity: byId("apply-session-integrity"),
    applySessionCompensation: byId("apply-session-compensation"),
    applySessionDiagnostics: byId("apply-session-diagnostics"),
    postApplyVerificationSection: byId("post-apply-verification-section"),
    verifyAppliedChanges: byId("verify-applied-changes"),
    postApplyVerificationStatus: byId("post-apply-verification-status"),
    postApplyVerificationChangedSummary: byId("post-apply-verification-changed-summary"),
    postApplyVerificationUnexpectedSummary: byId("post-apply-verification-unexpected-summary"),
    postApplyVerificationTestsSummary: byId("post-apply-verification-tests-summary"),
    postApplyVerificationBoundariesSummary: byId("post-apply-verification-boundaries-summary"),
    postApplyVerificationNextAction: byId("post-apply-verification-next-action"),
    postApplyVerificationChangedFiles: byId("post-apply-verification-changed-files"),
    postApplyVerificationUnexpectedFiles: byId("post-apply-verification-unexpected-files"),
    postApplyVerificationTests: byId("post-apply-verification-tests"),
    postApplyVerificationBoundaries: byId("post-apply-verification-boundaries"),
    postApplyVerificationBlockers: byId("post-apply-verification-blockers"),
    postApplyVerificationAdvancedCard: byId("post-apply-verification-advanced-card"),
    postApplyVerificationRecordId: byId("post-apply-verification-record-id"),
    postApplyVerificationPolicyVersion: byId("post-apply-verification-policy-version"),
    postApplyVerificationDigest: byId("post-apply-verification-digest"),
    postApplyObservationDigest: byId("post-apply-observation-digest"),
    postApplyVerificationSessionBinding: byId("post-apply-verification-session-binding"),
    postApplyVerificationPlanBinding: byId("post-apply-verification-plan-binding"),
    postApplyVerificationCandidateBinding: byId("post-apply-verification-candidate-binding"),
    postApplyVerificationRepositoryIdentity: byId("post-apply-verification-repository-identity"),
    postApplyVerificationRepositoryFingerprints: byId("post-apply-verification-repository-fingerprints"),
    postApplyVerificationExpectedBranch: byId("post-apply-verification-expected-branch"),
    postApplyVerificationObservedBranch: byId("post-apply-verification-observed-branch"),
    postApplyVerificationExpectedHead: byId("post-apply-verification-expected-head"),
    postApplyVerificationObservedHead: byId("post-apply-verification-observed-head"),
    postApplyVerificationSourceSnapshot: byId("post-apply-verification-source-snapshot"),
    postApplyVerificationCreatedAt: byId("post-apply-verification-created-at"),
    postApplyVerificationExpectedPaths: byId("post-apply-verification-expected-paths"),
    postApplyVerificationObservedPaths: byId("post-apply-verification-observed-paths"),
    postApplyVerificationDiagnostics: byId("post-apply-verification-diagnostics"),
    commitBuilderSection: byId("commit-builder-section"),
    canonicalCommitBuilderControls: document.querySelector(".canonical-commit-builder-controls"),
    legacyCommitBuilderControls: document.querySelector(".legacy-commit-builder-controls"),
    reviewOwnerCommit: byId("review-owner-commit"),
    approveCommitProposal: byId("approve-commit-proposal"),
    confirmOwnerLocalCommit: byId("confirm-owner-local-commit"),
    reviewCommitPlan: byId("review-commit-plan"),
    stageApprovedFiles: byId("stage-approved-files"),
    createLocalCommit: byId("create-local-commit"),
    commitMessageFields: byId("commit-message-fields"),
    commitPlanSubject: byId("commit-plan-subject"),
    commitPlanBody: byId("commit-plan-body"),
    commitBuilderStatus: byId("commit-builder-status"),
    ownerCommitApplyState: byId("owner-commit-apply-state"),
    ownerCommitPostApplyValidation: byId("owner-commit-post-apply-validation"),
    commitPlanSummary: byId("commit-plan-summary"),
    commitProposalApproval: byId("commit-proposal-approval"),
    commitApprovedSummary: byId("commit-approved-summary"),
    commitIncludedCount: byId("commit-included-count"),
    commitExcludedSummary: byId("commit-excluded-summary"),
    commitUnrelatedWarning: byId("commit-unrelated-warning"),
    commitBuilderBranch: byId("commit-builder-branch"),
    commitBuilderHead: byId("commit-builder-head"),
    commitExpectedParent: byId("commit-expected-parent"),
    commitBuilderSubject: byId("commit-builder-subject"),
    commitAuthorReadiness: byId("commit-author-readiness"),
    commitBuilderValidation: byId("commit-builder-validation"),
    commitStageSummary: byId("commit-stage-summary"),
    localCommitSummary: byId("local-commit-summary"),
    ownerLocalCommitSha: byId("owner-commit-result-oid"),
    commitBuilderNextAction: byId("commit-builder-next-action"),
    commitApprovedFiles: byId("commit-approved-files"),
    commitExcludedFiles: byId("commit-excluded-files"),
    commitBuilderBoundaries: byId("commit-builder-boundaries"),
    commitBuilderBlockers: byId("commit-builder-blockers"),
    commitBuilderAdvancedCard: byId("commit-builder-advanced-card"),
    commitPlanRecordId: byId("commit-plan-record-id"),
    commitProposalVersion: byId("commit-proposal-version"),
    commitProposalApprovalRecord: byId("commit-proposal-approval-record"),
    commitProposalApprovalDigest: byId("commit-proposal-approval-digest"),
    commitPlanPolicyVersion: byId("commit-plan-policy-version"),
    commitPlanDigest: byId("commit-plan-digest"),
    commitPlanVerificationBinding: byId("commit-plan-verification-binding"),
    commitPlanApplySessionBinding: byId("commit-plan-apply-session-binding"),
    commitPlanRepositoryIdentity: byId("commit-plan-repository-identity"),
    commitPlanBranch: byId("commit-plan-branch"),
    commitPlanHead: byId("commit-plan-head"),
    commitPlanIndex: byId("commit-plan-index"),
    stageSessionRecordId: byId("stage-session-record-id"),
    stageSessionDigest: byId("stage-session-digest"),
    stageSessionPathCount: byId("stage-session-path-count"),
    localCommitRecordId: byId("local-commit-record-id"),
    localCommitSha: byId("local-commit-sha"),
    localCommitParentSha: byId("local-commit-parent-sha"),
    localCommitTreeSha: byId("local-commit-tree-sha"),
    localCommitMessageDigest: byId("local-commit-message-digest"),
    commitProposalMessageBody: byId("commit-proposal-message-body"),
    commitProposalAuthor: byId("commit-proposal-author"),
    localCommitArgv: byId("local-commit-argv"),
    localCommitProcessIdentity: byId("local-commit-process-identity"),
    commitBuilderCreatedAt: byId("commit-builder-created-at"),
    commitBuilderPathEvidence: byId("commit-builder-path-evidence"),
    commitBuilderDiagnostics: byId("commit-builder-diagnostics"),
    pushDeliverySection: byId("push-delivery-section"),
    canonicalPushDeliveryControls: document.querySelector(".canonical-push-delivery-controls"),
    legacyPushDeliveryControls: document.querySelector(".legacy-push-delivery-controls"),
    reviewPushPlan: byId("review-push-plan"),
    approvePushPlan: byId("approve-push-plan"),
    confirmOwnerPush: byId("confirm-owner-push"),
    pushToOriginMain: byId("push-to-origin-main"),
    viewDeliveryResult: byId("view-delivery-result"),
    pushGateStatus: byId("push-gate-status"),
    pushPlanApproval: byId("push-plan-approval"),
    pushLocalCommit: byId("push-local-commit"),
    pushCommitSubject: byId("push-commit-subject"),
    pushDestination: byId("push-destination"),
    pushRemoteBase: byId("push-remote-base"),
    pushProposedNewSha: byId("push-proposed-new-sha"),
    pushFastForwardReadiness: byId("push-fast-forward-readiness"),
    pushAheadBehind: byId("push-ahead-behind"),
    pushCleanliness: byId("push-cleanliness"),
    pushProgress: byId("push-progress"),
    pushFinalRemoteSha: byId("push-final-remote-sha"),
    pushReceiptSummary: byId("push-receipt-summary"),
    pushNextAction: byId("push-next-action"),
    pushBlockers: byId("push-blockers"),
    deliveryResult: byId("delivery-result"),
    deliveryResultStatus: byId("delivery-result-status"),
    deliveryRunResult: byId("delivery-run-result"),
    deliveryIndependentVerification: byId("delivery-independent-verification"),
    deliveryCandidate: byId("delivery-candidate"),
    deliverySourceDrift: byId("delivery-source-drift"),
    deliveryApplyResult: byId("delivery-apply-result"),
    deliveryPostApplyVerification: byId("delivery-post-apply-verification"),
    deliveryStagedPaths: byId("delivery-staged-paths"),
    deliveryLocalCommit: byId("delivery-local-commit"),
    deliveryCommitSubject: byId("delivery-commit-subject"),
    deliveryPushStatus: byId("delivery-push-status"),
    deliveryReconciliation: byId("delivery-reconciliation"),
    deliveryLocalHead: byId("delivery-local-head"),
    deliveryOriginMain: byId("delivery-origin-main"),
    deliveryAheadBehind: byId("delivery-ahead-behind"),
    deliveryWorktreeIndex: byId("delivery-worktree-index"),
    deliveryBoundaries: byId("delivery-boundaries"),
    deliveryWarnings: byId("delivery-warnings"),
    deliveryBlockers: byId("delivery-blockers"),
    deliveryNextAction: byId("delivery-next-action"),
    pushDeliveryAdvancedCard: byId("push-delivery-advanced-card"),
    pushCommitBinding: byId("push-commit-binding"),
    pushPlanRecordId: byId("push-plan-record-id"),
    pushPlanVersion: byId("push-plan-version"),
    pushPlanDigest: byId("push-plan-digest"),
    pushPlanApprovalRecord: byId("push-plan-approval-record"),
    pushPlanApprovalDigest: byId("push-plan-approval-digest"),
    pushCandidateBinding: byId("push-candidate-binding"),
    pushApplyPlanBinding: byId("push-apply-plan-binding"),
    pushVerificationBinding: byId("push-verification-binding"),
    pushPreflightRecordId: byId("push-preflight-record-id"),
    pushPreflightDigest: byId("push-preflight-digest"),
    pushAttemptRecordId: byId("push-attempt-record-id"),
    pushAttemptDigest: byId("push-attempt-digest"),
    pushExactRefspec: byId("push-exact-refspec"),
    pushRemoteFingerprint: byId("push-remote-fingerprint"),
    pushRepositoryFingerprint: byId("push-repository-fingerprint"),
    pushRemoteDescriptor: byId("push-remote-descriptor"),
    pushExecutionArgv: byId("push-execution-argv"),
    pushProcessIdentity: byId("push-process-identity"),
    pushRemoteReceipt: byId("push-remote-receipt"),
    pushSanitizedDiagnostics: byId("push-sanitized-diagnostics"),
    applyConfirmationDialog: byId("apply-confirmation-dialog"),
    applyConfirmationPlan: byId("apply-confirmation-plan"),
    applyConfirmationCandidate: byId("apply-confirmation-candidate"),
    applyConfirmationDrift: byId("apply-confirmation-drift"),
    applyConfirmationOperations: byId("apply-confirmation-operations"),
    applyConfirmationIncluded: byId("apply-confirmation-included"),
    applyConfirmationExcluded: byId("apply-confirmation-excluded"),
    applyConfirmationUnrelated: byId("apply-confirmation-unrelated"),
    applyConfirmationIndex: byId("apply-confirmation-index"),
    confirmApplyAcceptedChanges: byId("confirm-apply-accepted-changes"),
    cancelApplyAcceptedChanges: byId("cancel-apply-accepted-changes"),
    revertConfirmationDialog: byId("revert-confirmation-dialog"),
    revertConfirmationSession: byId("revert-confirmation-session"),
    revertConfirmationPaths: byId("revert-confirmation-paths"),
    revertConfirmationOperations: byId("revert-confirmation-operations"),
    revertConfirmationPreconditions: byId("revert-confirmation-preconditions"),
    revertConfirmationUnrelated: byId("revert-confirmation-unrelated"),
    revertConfirmationIndex: byId("revert-confirmation-index"),
    confirmRevertAppliedChanges: byId("confirm-revert-applied-changes"),
    cancelRevertAppliedChanges: byId("cancel-revert-applied-changes"),
    stageConfirmationDialog: byId("stage-confirmation-dialog"),
    stageConfirmationPlan: byId("stage-confirmation-plan"),
    stageConfirmationVerification: byId("stage-confirmation-verification"),
    stageConfirmationApproved: byId("stage-confirmation-approved"),
    stageConfirmationExcluded: byId("stage-confirmation-excluded"),
    stageConfirmationHead: byId("stage-confirmation-head"),
    stageConfirmationIndex: byId("stage-confirmation-index"),
    confirmStageApprovedFiles: byId("confirm-stage-approved-files"),
    cancelStageApprovedFiles: byId("cancel-stage-approved-files"),
    localCommitConfirmationDialog: byId("local-commit-confirmation-dialog"),
    localCommitConfirmationStage: byId("local-commit-confirmation-stage"),
    localCommitConfirmationPaths: byId("local-commit-confirmation-paths"),
    localCommitConfirmationSubject: byId("local-commit-confirmation-subject"),
    localCommitConfirmationBody: byId("local-commit-confirmation-body"),
    localCommitConfirmationBranch: byId("local-commit-confirmation-branch"),
    localCommitConfirmationParent: byId("local-commit-confirmation-parent"),
    confirmCreateLocalCommit: byId("confirm-create-local-commit"),
    cancelCreateLocalCommit: byId("cancel-create-local-commit"),
    pushConfirmationDialog: byId("push-confirmation-dialog"),
    pushConfirmationRepository: byId("push-confirmation-repository"),
    pushConfirmationBranch: byId("push-confirmation-branch"),
    pushConfirmationCommit: byId("push-confirmation-commit"),
    pushConfirmationSubject: byId("push-confirmation-subject"),
    pushConfirmationRemoteBase: byId("push-confirmation-remote-base"),
    pushConfirmationDestination: byId("push-confirmation-destination"),
    pushConfirmationAheadBehind: byId("push-confirmation-ahead-behind"),
    pushConfirmationCleanliness: byId("push-confirmation-cleanliness"),
    pushConfirmationFastForward: byId("push-confirmation-fast-forward"),
    confirmPushToOriginMain: byId("confirm-push-to-origin-main"),
    cancelPushToOriginMain: byId("cancel-push-to-origin-main"),
    ownerLocalCommitConfirmationDialog: byId("owner-local-commit-confirmation-dialog"),
    ownerCommitConfirmationProposal: byId("owner-commit-confirmation-proposal"),
    ownerCommitConfirmationPaths: byId("owner-commit-confirmation-paths"),
    ownerCommitConfirmationSubject: byId("owner-commit-confirmation-subject"),
    ownerCommitConfirmationBody: byId("owner-commit-confirmation-body"),
    ownerCommitConfirmationAuthor: byId("owner-commit-confirmation-author"),
    ownerCommitConfirmationBranch: byId("owner-commit-confirmation-branch"),
    ownerCommitConfirmationParent: byId("owner-commit-confirmation-parent"),
    confirmApprovedLocalCommit: byId("confirm-approved-local-commit"),
    cancelApprovedLocalCommit: byId("cancel-approved-local-commit"),
    ownerPushConfirmationDialog: byId("owner-push-confirmation-dialog"),
    ownerPushConfirmationPlan: byId("owner-push-confirmation-plan"),
    ownerPushConfirmationRemote: byId("owner-push-confirmation-remote"),
    ownerPushConfirmationBranch: byId("owner-push-confirmation-branch"),
    ownerPushConfirmationOldSha: byId("owner-push-confirmation-old-sha"),
    ownerPushConfirmationNewSha: byId("owner-push-confirmation-new-sha"),
    ownerPushConfirmationFastForward: byId("owner-push-confirmation-fast-forward"),
    ownerPushConfirmationStatus: byId("owner-push-confirmation-status"),
    ownerPushConfirmationStatusLabel: byId("owner-push-confirmation-status-label"),
    ownerPushConfirmationStatusMessage: byId("owner-push-confirmation-status-message"),
    confirmApprovedPush: byId("confirm-approved-push"),
    cancelApprovedPush: byId("cancel-approved-push"),
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
    firstRun: null,
    firstOwnerRequestId: null,
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
    runActivity: [],
    resultEnvelopes: Object.create(null),
    handoffReviews: Object.create(null),
    instructionDrafts: Object.create(null),
    selectedActivityRunId: null,
    taskSelectionEpoch: 0,
    taskLoadState: "loading",
    taskLoadMessage: "Loading your saved task selection.",
    ownerAcceptance: null,
    deliveryCandidateReviews: Object.create(null),
    deliveryCandidateReviewLoads: new Set(),
    applyPlanReviews: Object.create(null),
    applyPlanReviewLoads: new Set(),
    applySessionReviews: Object.create(null),
    applySessionReviewLoads: new Set(),
    postApplyVerificationReviews: Object.create(null),
    postApplyVerificationReviewLoads: new Set(),
    commitBuilderReviews: Object.create(null),
    commitBuilderReviewLoads: new Set(),
    commitBuilderRequestSequences: Object.create(null),
    pushDeliveryReviews: Object.create(null),
    pushDeliveryReviewLoads: new Set(),
    pushDeliveryRequestSequences: Object.create(null),
    pushDeliveryResultVisible: new Set(),
    ownerDeliveryProjections: Object.create(null),
    ownerDeliveryProjectionLoads: new Set(),
    ownerDeliveryRequestSequences: Object.create(null),
    runConfirmationContext: null,
    applyConfirmationContext: null,
    revertConfirmationContext: null,
    stageConfirmationContext: null,
    localCommitConfirmationContext: null,
    pushConfirmationContext: null,
    ownerCommitConfirmationContext: null,
    ownerPushConfirmationContext: null,
    ownerPushConfirmationState: {
      phase: "ready_for_confirmation",
      message: "The approved Push Plan is ready for one explicit confirmation.",
      request_identity: ""
    },
    ownerPushConfirmationUncertainty: null,
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
    const timeoutMs = Number(request.timeoutMs || 0);
    delete request.timeoutMs;
    let timeoutId = null;
    let timeoutController = null;
    if (Number.isFinite(timeoutMs) && timeoutMs > 0 && typeof AbortController === "function") {
      timeoutController = new AbortController();
      request.signal = timeoutController.signal;
      timeoutId = window.setTimeout(function () { timeoutController.abort(); }, timeoutMs);
    }
    if (request.body && typeof request.body !== "string") {
      request.headers = Object.assign({}, request.headers, { "Content-Type": "application/json" });
      request.body = JSON.stringify(request.body);
    }

    let response;
    let responseText;
    try {
      response = await fetch(path, request);
      responseText = await response.text();
    } catch (error) {
      if (timeoutController && timeoutController.signal.aborted) {
        throw new ApiError(
          0,
          "REQUEST_TIMEOUT",
          "The request timed out. TWOS will reconcile persisted evidence before another action is available.",
          {},
          "network"
        );
      }
      throw new ApiError(0, "NETWORK_ERROR", "Unable to connect. Try again.", {}, "network");
    } finally {
      if (timeoutId !== null) window.clearTimeout(timeoutId);
    }

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
      const legacyDetails = legacy.details && typeof legacy.details === "object"
        ? legacy.details
        : {};
      const trustedLegacyEnvelope = Boolean(
        data
        && Object.keys(data).length === 1
        && data.error
        && typeof legacy.code === "string"
        && typeof legacy.message === "string"
        && typeof legacy.request_id === "string"
        && Object.prototype.hasOwnProperty.call(legacy, "details")
      );
      const code = typeof data.code === "string"
        ? data.code
        : typeof legacyDetails.code === "string"
          ? legacyDetails.code
          : typeof legacy.code === "string" ? legacy.code : "HTTP_ERROR";
      const message = typeof data.message === "string"
        ? data.message
        : typeof legacyDetails.message === "string"
          ? legacyDetails.message
          : typeof legacy.message === "string"
            ? legacy.message
          : typeof data.detail === "string"
            ? data.detail
            : "Something went wrong. Try again.";
      const fields = data.fields && typeof data.fields === "object"
        ? data.fields
        : legacyDetails.fields && typeof legacyDetails.fields === "object"
          ? legacyDetails.fields
          : {};
      throw new ApiError(
        response.status,
        code,
        message,
        fields,
        trustedLegacyEnvelope ? "twos" : "api",
        legacyDetails
      );
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

  function runStateSummary(status, terminalTruth) {
    const truth = objectRecord(terminalTruth);
    const verification = objectRecord(truth.verification);
    const coding = objectRecord(truth.coding);
    const workspace = objectRecord(truth.workspace);
    if (coding.status === "failed") {
      return "Coding failed. Review the process evidence and any partial Run Result separately.";
    }
    if (coding.status === "succeeded" && verification.status === "not_required") {
      return "Coding completed; independent Verification was not required. Review the available Run evidence.";
    }
    if (coding.status === "succeeded" && verification.started === false) {
      return "Coding completed; independent Verification was not started. Review the available Run evidence.";
    }
    if (coding.status === "succeeded" && verification.status === "failed") {
      return "Coding completed; independent Verification failed. Review the exact Verification reason.";
    }
    if (coding.status === "succeeded" && verification.status === "unavailable") {
      return "Coding completed; independent Verification is unavailable. Review the exact Verification reason.";
    }
    if (coding.status === "succeeded" && workspace.state === "conflict") {
      return "Coding completed; workspace evidence needs Owner review because a conflict was captured.";
    }
    if (coding.status === "succeeded" && verification.status === "passed") {
      return "Coding and independent Verification completed. Review the available Run evidence.";
    }
    const summaries = {
      queued: "Run accepted and queued for isolated execution.",
      starting: "The approved source snapshot is being prepared.",
      running: "Coding invocation is running in the isolated workspace.",
      coding: "Coding invocation is running in the isolated workspace.",
      verifying: "Coding has reached a terminal process state; independent Verification is running.",
      settling: "Terminal evidence is being reconciled into one authoritative Run Result.",
      result_pending: "Terminal evidence is being reconciled into one authoritative Run Result.",
      completed: "Coding completed. Review the persisted phase evidence.",
      result_available: "A Run Result is available for review; availability does not by itself establish objective success.",
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
    if (/fail|error|timed out|cancel|integrity blocked|process lost|unavailable|unreachable|not installed|blocked/.test(normalized)) {
      element.classList.add("is-error");
    } else if (/not verified|waiting|review|required|setup|queued|starting|running|verifying|draft/.test(normalized)) {
      element.classList.add("is-warning");
    } else if (/accepted|approved|complete|configured|healthy|pass|ready|saved|verified|result available|pushed|delivered/.test(normalized)) {
      element.classList.add("is-success");
    }
  }

  function firstRunIsIncomplete() {
    return Boolean(
      state.firstRun
      && state.firstRun.enabled === true
      && state.firstRun.state !== "ready"
    );
  }

  function firstRunFirstTaskPending() {
    return Boolean(
      state.firstRun
      && state.firstRun.enabled === true
      && state.firstRun.state === "ready"
      && state.firstRun.first_task_created !== true
      && state.tasks.length === 0
    );
  }

  function firstRunToolStatus() {
    const tools = state.firstRun && Array.isArray(state.firstRun.optional_tools)
      ? state.firstRun.optional_tools
      : [];
    const codex = tools.find(function (item) { return item && item.name === "Codex"; });
    return codex ? String(codex.status || "not_checked") : "not_checked";
  }

  function setFirstRunMessage(message, tone) {
    elements.firstRunMessage.textContent = message || "";
    elements.firstRunMessage.hidden = !message;
    elements.firstRunMessage.dataset.tone = tone || "error";
  }

  function firstRunAuthorizationSummary(setup) {
    const authorization = setup && setup.setup_authorization && typeof setup.setup_authorization === "object"
      ? setup.setup_authorization
      : {};
    if (authorization.required !== true) return "Consumed after first Owner creation";
    if (authorization.expired === true) {
      return "Expired · restart the local launcher to issue a replacement";
    }
    if (authorization.available === true) return "Available · single-use local code";
    return "Unavailable · restart the local launcher before Owner creation";
  }

  function renderFirstRun() {
    const setup = state.firstRun || {};
    const installation = setup.installation || {};
    const current = String(setup.current_step || "welcome");
    const completed = Array.isArray(setup.completed_steps) ? setup.completed_steps : [];
    elements.firstRunState.textContent = humanStatus(setup.state || "uninitialized");
    setStatusLabel(elements.firstRunState, elements.firstRunState.textContent);
    Array.from(elements.firstRunProgress.querySelectorAll("[data-setup-step]")).forEach(function (item) {
      const step = item.dataset.setupStep;
      item.dataset.state = step === current
        ? "current"
        : completed.indexOf(step) !== -1 ? "complete" : "pending";
    });
    elements.firstRunCurrentStep.textContent = current === "failed" ? "Blocked" : humanStatus(current);
    replaceText(elements.firstRunNextAction, setup.next_action, "Refresh First Run status.");
    replaceText(elements.firstRunBlockingReason, setup.blocking_reason, "None");
    elements.firstRunAuthorizationState.textContent = firstRunAuthorizationSummary(setup);
    setVisible(elements.firstRunWelcome, current === "welcome");
    setVisible(elements.firstRunInstallation, current === "installation");
    setVisible(elements.firstRunOwner, current === "owner");
    setVisible(elements.firstRunWorkspace, current === "workspace");
    setVisible(elements.firstRunTools, current === "optional_tools");
    setVisible(elements.firstRunFinish, current === "finish");
    setVisible(elements.firstRunBlocked, current === "failed");
    replaceText(elements.firstRunSourceVersion, installation.source_version, "Not available");
    replaceText(elements.firstRunDataRoot, installation.data_root_summary, "Private data root");
    elements.firstRunBindAddress.textContent = installation.localhost_only === true
      ? "127.0.0.1 only"
      : "Blocked: localhost boundary unavailable";
    elements.firstRunDatabaseState.textContent = installation.database_initialized === true
      ? "Initialized"
      : "Not initialized";
    elements.firstRunRuntimeState.textContent = installation.isolated_runtime === true
      ? "Isolated"
      : "Isolation unavailable";
    const address = installation.bind_host && installation.port
      ? installation.bind_host + ":" + installation.port
      : "Local address unavailable";
    elements.firstRunLocalAddress.textContent = address;
    elements.firstRunCodexState.textContent = humanStatus(firstRunToolStatus());
    setStatusLabel(elements.firstRunCodexState, elements.firstRunCodexState.textContent);
    elements.firstRunSummaryOwner.textContent = setup.owner_exists ? "Created" : "Not created";
    replaceText(elements.firstRunSummaryDataRoot, installation.data_root_summary, "Not available");
    replaceText(elements.firstRunSummaryWorkspace, installation.workspace_summary, "Not authorized");
    elements.firstRunSummaryTools.textContent = humanStatus(firstRunToolStatus());
    elements.firstRunSummaryAddress.textContent = address;
    if (setup.state === "failed") {
      setFirstRunMessage(setup.blocking_reason || "First Run is blocked. Review the local runtime log.", "error");
    }
    const busy = state.pending.has("first-run-action");
    [
      elements.firstRunStart,
      elements.firstRunConfirmInstallation,
      elements.firstRunCreateOwner,
      elements.firstRunAuthorizeWorkspace,
      elements.firstRunReviewTools,
      elements.firstRunSkipTools,
      elements.firstRunFinishSetup,
      elements.firstRunRefreshStatus
    ].forEach(function (button) { button.disabled = busy; });
  }

  function renderAuthShell() {
    elements.body.dataset.authState = state.auth;
    const isLoading = state.auth === AUTH_STATES.LOADING;
    const sessionError = state.auth === AUTH_STATES.ERROR && state.errorScope === "session";
    const isSignedIn = state.auth === AUTH_STATES.SIGNED_IN;
    const firstRunIncomplete = firstRunIsIncomplete();
    const firstRunNeedsLogin = firstRunIncomplete
      && state.firstRun.owner_exists === true
      && !isSignedIn;
    const showFirstRun = !isLoading && !sessionError && firstRunIncomplete && !firstRunNeedsLogin;
    const showPublic = !isLoading && !sessionError && !showFirstRun && (!isSignedIn || firstRunNeedsLogin);

    setVisible(elements.loadingView, isLoading);
    setVisible(elements.sessionErrorView, sessionError);
    setVisible(elements.firstRunView, showFirstRun);
    setVisible(elements.publicView, showPublic);
    setVisible(elements.appView, isSignedIn && !firstRunIncomplete);

    if (showFirstRun) renderFirstRun();

    if (showPublic) {
      if (firstRunNeedsLogin) state.authView = "login";
      setVisible(elements.landingView, state.authView === "landing");
      setVisible(elements.signupView, state.authView === "signup");
      setVisible(elements.loginView, state.authView === "login");
      const signupAvailable = !state.firstRun || state.firstRun.enabled !== true;
      setVisible(elements.headerSignup, signupAvailable);
      setVisible(elements.landingSignup, signupAvailable);
      setVisible(elements.loginToSignup, signupAvailable);
      if (
        firstRunNeedsLogin
        && (!elements.loginFormError.textContent || elements.loginFormError.hidden)
      ) {
        setAuthFormError("login", "Log in as the first Owner to resume First Run.");
      }
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
    if (firstRunIsIncomplete()) {
      setFirstRunMessage("Signed in. Refreshing the persisted First Run step…", "neutral");
    } else {
      setFeedback("Signed in. Refreshing setup and workspace state…", "neutral");
    }
    try {
      state.firstRun = await api(SETUP_ROUTES.STATUS, {
        timeoutMs: FIRST_RUN_RECONCILE_TIMEOUT_MS
      });
      renderAuthShell();
      if (!firstRunIsIncomplete()) {
        setFeedback("Loading your workbench…", "neutral");
        await refreshWorkspace({ force: true });
      }
    } catch (error) {
      renderAuthShell();
      if (!firstRunIsIncomplete()) {
        setFeedback("Signed in, but setup state could not be refreshed. Reload this page to retry the read-only setup check before continuing.", "error");
      } else {
        setFirstRunMessage("Signed in, but setup state could not be refreshed. No setup action was started; try Check Setup Status.", "error");
      }
    }
    if (state.auth === AUTH_STATES.SIGNED_IN && !firstRunIsIncomplete()) elements.workbenchMain.focus();
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
      state.firstRun = await api(SETUP_ROUTES.STATUS, {
        timeoutMs: FIRST_RUN_RECONCILE_TIMEOUT_MS
      });
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
        if (!firstRunIsIncomplete()) {
          setFeedback("Loading your workbench…", "neutral");
          await refreshWorkspace({ force: true });
        }
      } else {
        state.user = null;
        state.auth = AUTH_STATES.SIGNED_OUT;
        state.authView = state.firstRun && state.firstRun.owner_exists ? "login" : "landing";
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

  function setupStepCompleted(setup, step) {
    return Boolean(
      setup
      && Array.isArray(setup.completed_steps)
      && setup.completed_steps.indexOf(step) !== -1
    );
  }

  function adoptFirstRunSession(setup) {
    const identity = setup && setup.user && typeof setup.user.username === "string"
      ? setup.user
      : setup && setup.owner && typeof setup.owner.username === "string"
        ? setup.owner
        : null;
    if (setup && setup.authenticated === true && identity) {
      state.user = { username: identity.username };
      state.auth = AUTH_STATES.SIGNED_IN;
      state.errorScope = null;
      return true;
    }
    return false;
  }

  async function reconcileFirstRunStatus(options) {
    const config = options || {};
    const setup = await api(SETUP_ROUTES.STATUS, {
      timeoutMs: FIRST_RUN_RECONCILE_TIMEOUT_MS
    });
    if (!setup || setup.enabled !== true) {
      throw new ApiError(409, "SETUP_STATE_INVALID", "First Run state could not be confirmed.", {}, "payload");
    }
    state.firstRun = setup;
    adoptFirstRunSession(setup);
    if (config.checkSession === true && setup.owner_exists === true && state.auth !== AUTH_STATES.SIGNED_IN) {
      let session;
      try {
        session = await api(AUTH_ROUTES.SESSION, {
          timeoutMs: FIRST_RUN_RECONCILE_TIMEOUT_MS
        });
      } catch (error) {
        state.user = null;
        state.auth = AUTH_STATES.SIGNED_OUT;
        state.errorScope = "form";
        state.authView = "login";
        renderAuthShell();
        throw error;
      }
      if (authenticatedUserFromPayload(session)) {
        state.user = authenticatedUserFromPayload(session);
        state.auth = AUTH_STATES.SIGNED_IN;
        state.errorScope = null;
        state.firstRun.authenticated = true;
        state.firstRun.owner = { username: state.user.username };
      } else {
        state.user = null;
        state.auth = AUTH_STATES.SIGNED_OUT;
        state.errorScope = "form";
        state.authView = "login";
      }
    }
    renderAuthShell();
    return setup;
  }

  async function runFirstRunAction(button, pendingLabel, request, options) {
    const config = options || {};
    if (state.pending.has("first-run-action")) return;
    state.pending.add("first-run-action");
    const originalLabel = button.textContent;
    setFirstRunMessage("", "neutral");
    button.textContent = pendingLabel;
    button.setAttribute("aria-busy", "true");
    renderFirstRun();
    try {
      const response = await request();
      if (!response || response.enabled !== true) {
        throw new ApiError(409, "SETUP_STATE_INVALID", "First Run state could not be confirmed.", {}, "payload");
      }
      state.firstRun = response;
      adoptFirstRunSession(response);
      renderAuthShell();
      return response;
    } catch (error) {
      setFirstRunMessage("The request did not settle visibly. TWOS is checking persisted setup state before another action is available…", "neutral");
      renderFirstRun();
      let reconciled = null;
      try {
        reconciled = await reconcileFirstRunStatus({
          checkSession: config.checkSession === true
        });
      } catch (reconcileError) {
        reconciled = null;
      }
      if (reconciled && typeof config.settled === "function" && config.settled(reconciled)) {
        if (firstRunIsIncomplete()) {
          setFirstRunMessage("The persisted setup state confirms that the action completed. No duplicate action was sent.", "success");
        }
        return reconciled;
      }
      const message = error instanceof ApiError
        ? error.message
        : "First Run could not continue. Review the local runtime log and try again.";
      const currentSetup = reconciled || state.firstRun;
      if (currentSetup && currentSetup.owner_exists === true && state.auth !== AUTH_STATES.SIGNED_IN) {
        clearAuthErrors("login");
        setAuthFormError("login", "The first Owner exists. Log in to resume First Run; no duplicate Owner request was sent automatically.");
        renderAuthShell();
      } else {
        setFirstRunMessage(
          reconciled
            ? message + " Persisted setup state was refreshed; retry only the visible current step."
            : message + " Setup status also could not be refreshed. No automatic retry occurred.",
          "error"
        );
        if (firstRunIsIncomplete()) renderFirstRun();
      }
      return null;
    } finally {
      state.pending.delete("first-run-action");
      button.textContent = originalLabel;
      button.removeAttribute("aria-busy");
      if (firstRunIsIncomplete()) renderFirstRun();
    }
  }

  async function startFirstRun() {
    await runFirstRunAction(elements.firstRunStart, "Starting…", function () {
      return api(SETUP_ROUTES.START, {
        method: "POST",
        timeoutMs: FIRST_RUN_ACTION_TIMEOUT_MS,
        body: { confirmation: "START_FIRST_RUN" }
      });
    }, {
      settled: function (setup) { return setupStepCompleted(setup, "welcome"); }
    });
  }

  async function confirmFirstRunInstallation() {
    await runFirstRunAction(elements.firstRunConfirmInstallation, "Confirming…", function () {
      return api(SETUP_ROUTES.START, {
        method: "POST",
        timeoutMs: FIRST_RUN_ACTION_TIMEOUT_MS,
        body: { confirmation: "CONFIRM_INSTALLATION" }
      });
    }, {
      settled: function (setup) { return setupStepCompleted(setup, "installation"); }
    });
  }

  async function createFirstRunOwner() {
    if (state.pending.has("first-run-action")) return;
    if (!elements.firstRunOwnerForm.checkValidity()) {
      elements.firstRunOwnerForm.reportValidity();
      return;
    }
    if (elements.firstRunOwnerPassword.value !== elements.firstRunOwnerPasswordConfirmation.value) {
      setFirstRunMessage("The password confirmation does not match.", "error");
      elements.firstRunOwnerPasswordConfirmation.focus();
      return;
    }
    if (!state.firstOwnerRequestId) {
      try {
        state.firstOwnerRequestId = secureRequestIdentity("");
      } catch (error) {
        setFirstRunMessage(
          "This browser cannot create a secure First Owner request identity. No Owner request was sent.",
          "error"
        );
        return;
      }
    }
    const response = await runFirstRunAction(elements.firstRunCreateOwner, "Creating Owner…", function () {
      return api(SETUP_ROUTES.OWNER, {
        method: "POST",
        timeoutMs: FIRST_RUN_ACTION_TIMEOUT_MS,
        body: {
          username: elements.firstRunOwnerUsername.value.trim(),
          password: elements.firstRunOwnerPassword.value,
          password_confirmation: elements.firstRunOwnerPasswordConfirmation.value,
          setup_authorization: elements.firstRunSetupAuthorization.value,
          request_id: state.firstOwnerRequestId
        }
      });
    }, {
      checkSession: true,
      settled: function (setup) { return setup.owner_exists === true; }
    });
    if (response && response.owner_exists === true) {
      elements.firstRunOwnerPassword.value = "";
      elements.firstRunOwnerPasswordConfirmation.value = "";
      elements.firstRunSetupAuthorization.value = "";
      state.firstOwnerRequestId = null;
      if (adoptFirstRunSession(response)) {
        renderAuthShell();
      } else if (state.auth !== AUTH_STATES.SIGNED_IN) {
        clearAuthErrors("login");
        setAuthFormError("login", "The first Owner was created. Log in to resume First Run.");
        state.authView = "login";
        renderAuthShell();
      }
    }
  }

  async function authorizeFirstRunWorkspace() {
    if (!elements.firstRunWorkspaceForm.checkValidity()) {
      elements.firstRunWorkspaceForm.reportValidity();
      return;
    }
    await runFirstRunAction(elements.firstRunAuthorizeWorkspace, "Authorizing…", function () {
      return api(SETUP_ROUTES.WORKSPACE, {
        method: "POST",
        timeoutMs: FIRST_RUN_ACTION_TIMEOUT_MS,
        body: {
          path: elements.firstRunWorkspacePath.value,
          create_if_missing: elements.firstRunCreateWorkspace.checked
        }
      });
    }, {
      settled: function (setup) { return setupStepCompleted(setup, "workspace"); }
    });
  }

  async function completeOptionalToolReview(decision, button) {
    await runFirstRunAction(button, decision === "skip" ? "Skipping…" : "Reviewing…", function () {
      return api(SETUP_ROUTES.OPTIONAL_TOOLS, {
        method: "POST",
        timeoutMs: FIRST_RUN_ACTION_TIMEOUT_MS,
        body: { decision: decision }
      });
    }, {
      settled: function (setup) { return setupStepCompleted(setup, "optional_tools"); }
    });
  }

  async function finishFirstRunSetup() {
    const response = await runFirstRunAction(elements.firstRunFinishSetup, "Finishing…", function () {
      return api(SETUP_ROUTES.FINISH, {
        method: "POST",
        timeoutMs: FIRST_RUN_ACTION_TIMEOUT_MS,
        body: { confirmation: "FINISH_FIRST_RUN" }
      });
    }, {
      settled: function (setup) { return setup.state === "ready"; }
    });
    if (!response || response.state !== "ready") return;
    resetProtectedState();
    state.creatingTask = false;
    renderAuthShell();
    setFeedback("Setup complete. Create your first task; no Run or provider action starts automatically.", "success");
    await refreshWorkspace({ force: true });
    elements.newTask.focus();
  }

  async function refreshFirstRunStatus() {
    if (state.pending.has("first-run-action")) return;
    state.pending.add("first-run-action");
    const originalLabel = elements.firstRunRefreshStatus.textContent;
    elements.firstRunRefreshStatus.textContent = "Checking…";
    elements.firstRunRefreshStatus.setAttribute("aria-busy", "true");
    renderFirstRun();
    try {
      await reconcileFirstRunStatus({ checkSession: true });
      if (firstRunIsIncomplete()) {
        setFirstRunMessage("Setup status refreshed. No setup or external action was started.", "success");
      }
    } catch (error) {
      setFirstRunMessage("Setup status could not be refreshed. No setup or external action was started.", "error");
    } finally {
      state.pending.delete("first-run-action");
      elements.firstRunRefreshStatus.textContent = originalLabel;
      elements.firstRunRefreshStatus.removeAttribute("aria-busy");
      if (firstRunIsIncomplete()) renderFirstRun();
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
    state.runActivity = [];
    state.resultEnvelopes = Object.create(null);
    state.handoffReviews = Object.create(null);
    state.instructionDrafts = Object.create(null);
    state.selectedActivityRunId = null;
    state.taskSelectionEpoch += 1;
    state.taskLoadState = "loading";
    state.taskLoadMessage = "Loading your saved task selection.";
    state.ownerAcceptance = null;
    state.deliveryCandidateReviews = Object.create(null);
    state.deliveryCandidateReviewLoads = new Set();
    state.applyPlanReviews = Object.create(null);
    state.applyPlanReviewLoads = new Set();
    state.applySessionReviews = Object.create(null);
    state.applySessionReviewLoads = new Set();
    state.postApplyVerificationReviews = Object.create(null);
    state.postApplyVerificationReviewLoads = new Set();
    state.commitBuilderReviews = Object.create(null);
    state.commitBuilderReviewLoads = new Set();
    state.commitBuilderRequestSequences = Object.create(null);
    state.pushDeliveryReviews = Object.create(null);
    state.pushDeliveryReviewLoads = new Set();
    state.pushDeliveryRequestSequences = Object.create(null);
    state.pushDeliveryResultVisible = new Set();
    state.ownerDeliveryProjections = Object.create(null);
    state.ownerDeliveryProjectionLoads = new Set();
    state.ownerDeliveryRequestSequences = Object.create(null);
    state.runConfirmationContext = null;
    state.applyConfirmationContext = null;
    state.revertConfirmationContext = null;
    state.stageConfirmationContext = null;
    state.localCommitConfirmationContext = null;
    state.pushConfirmationContext = null;
    state.ownerCommitConfirmationContext = null;
    state.ownerPushConfirmationContext = null;
    state.ownerPushConfirmationState = {
      phase: "ready_for_confirmation",
      message: "The approved Push Plan is ready for one explicit confirmation.",
      request_identity: ""
    };
    state.ownerPushConfirmationUncertainty = null;
    if (elements.startCodexConfirmationDialog.open) elements.startCodexConfirmationDialog.close();
    if (elements.applyConfirmationDialog.open) elements.applyConfirmationDialog.close();
    if (elements.revertConfirmationDialog.open) elements.revertConfirmationDialog.close();
    if (elements.stageConfirmationDialog.open) elements.stageConfirmationDialog.close();
    if (elements.localCommitConfirmationDialog.open) elements.localCommitConfirmationDialog.close();
    if (elements.pushConfirmationDialog.open) elements.pushConfirmationDialog.close();
    if (elements.ownerLocalCommitConfirmationDialog.open) elements.ownerLocalCommitConfirmationDialog.close();
    if (elements.ownerPushConfirmationDialog.open) elements.ownerPushConfirmationDialog.close();
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
    if (error.category === "twos" && !looksInternal && message && message.length <= 220) {
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
      if (key === "review-commit-plan") {
        const verification = currentPassedPostApplyVerification(currentCodexRun());
        if (verification && verification.id) {
          state.commitBuilderReviews[String(verification.id)] = {
            post_apply_verification_id: String(verification.id),
            action_state: "STAGING_BLOCKED",
            eligibility: {
              status: "BLOCKED",
              can_review: true,
              blockers: [{
                code: error instanceof ApiError ? error.code : "COMMIT_PLAN_REQUEST_FAILED",
                message: productActionMessage(error)
              }],
              next_action: "Commit Plan request failed. Review the diagnostic evidence and resolve the blocker: " + productActionMessage(error)
            },
            plan: null,
            stage: null,
            commit: null,
            actions: {
              can_review_commit_plan: true,
              can_stage_approved_files: false,
              can_create_local_commit: false
            }
          };
        }
      }
      if (key === "push-preflight" || key === "confirm-push-to-origin-main") {
        const commit = currentCommittedLocalCommit(currentCodexRun());
        const commitId = String(commitBuilderRecordId(commit) || "");
        if (commitId) {
          const previous = objectRecord(state.pushDeliveryReviews[commitId]);
          const previousReadiness = objectRecord(previous.readiness);
          const previousExecution = objectRecord(previous.push_execution);
          const uncertain = key === "confirm-push-to-origin-main";
          storePushDeliveryReview(commitId, {
            local_commit_execution_id: commitId,
            action_state: uncertain ? "RECONCILIATION_BLOCKED" : "PUSH_BLOCKED",
            readiness: Object.assign({}, previousReadiness, {
              status: uncertain ? "RECONCILIATION_BLOCKED" : "PUSH_BLOCKED",
              status_label: uncertain ? "RECONCILIATION BLOCKED" : "PUSH BLOCKED",
              blockers: [{
                code: error instanceof ApiError ? error.code : "PUSH_REQUEST_FAILED",
                message: productActionMessage(error)
              }],
              next_action: uncertain
                ? "Push result could not be confirmed. Reload the live Delivery Result before any new action."
                : "Push preflight request failed. Retry only when the live remote can be inspected safely."
            }),
            push_execution: previousExecution,
            delivery_result: previous.delivery_result || null,
            actions: {
              can_push_to_origin_main: !uncertain,
              can_confirm_push: false,
              can_view_delivery_result: false
            }
          });
          state.pushConfirmationContext = null;
          if (elements.pushConfirmationDialog.open) elements.pushConfirmationDialog.close();
        }
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
    const selected = state.selectedActivityRunId === null
      ? null
      : state.codexRuns.find(function (run) {
          return String(run.id) === String(state.selectedActivityRunId);
        });
    return selected || (state.codexRuns.length ? state.codexRuns[0] : null);
  }

  function isTerminalCodexRun(run) {
    return Boolean(run && TERMINAL_CODEX_RUN_STATUSES.indexOf(authoritativeRunStatus(run)) !== -1);
  }

  function resultEnvelopeForRun(run) {
    return run ? state.resultEnvelopes[String(run.id)] || null : null;
  }

  function handoffReviewForRun(run) {
    return run ? state.handoffReviews[String(run.id)] || null : null;
  }

  function instructionDraftForRun(run) {
    return run ? state.instructionDrafts[String(run.id)] || null : null;
  }

  function runActivityItems(payload) {
    if (Array.isArray(payload)) return payload;
    const record = objectRecord(payload);
    if (Array.isArray(record.runs)) return record.runs;
    if (Array.isArray(record.items)) return record.items;
    if (Array.isArray(record.activity)) return record.activity;
    return [];
  }

  function lifecycleSnapshotVersion(record) {
    const value = lifecycleRecordForActivity(record).snapshot_version;
    const version = Number(value);
    return Number.isFinite(version) && version >= 0 ? version : null;
  }

  function mergeRunActivityLifecycleSnapshots(previous, incoming) {
    const priorItems = Array.isArray(previous) ? previous : [];
    return (Array.isArray(incoming) ? incoming : []).map(function (next) {
      const nextRunId = rawRunIdFromActivity(next);
      const prior = priorItems.find(function (candidate) {
        const priorRunId = rawRunIdFromActivity(candidate);
        return nextRunId !== null
          && nextRunId !== undefined
          && priorRunId !== null
          && priorRunId !== undefined
          && String(priorRunId) === String(nextRunId);
      });
      if (!prior) return next;
      const priorLifecycle = lifecycleRecordForActivity(prior);
      const nextLifecycle = lifecycleRecordForActivity(next);
      const priorVersion = lifecycleSnapshotVersion(prior);
      const nextVersion = lifecycleSnapshotVersion(next);
      if (
        Object.keys(priorLifecycle).length
        && (!Object.keys(nextLifecycle).length
          || priorVersion !== null && (nextVersion === null || nextVersion < priorVersion))
      ) {
        return Object.assign({}, objectRecord(next), { lifecycle: priorLifecycle });
      }
      return next;
    });
  }

  function resultEnvelopeRecord(payload) {
    const record = objectRecord(payload);
    return objectRecord(
      record.envelope
      || record.result_envelope
      || record.resultEnvelope
      || record.result
      || record
    );
  }

  function handoffReviewRecord(payload) {
    const record = objectRecord(payload);
    return objectRecord(record.review || record.handoff_review || record.handoffReview || record);
  }

  function instructionDraftRecord(payload) {
    const record = objectRecord(payload);
    const nested = record.instruction_draft || record.instructionDraft || record.draft;
    if (nested) return objectRecord(nested);
    return record.instruction_text || record.draft_text || record.draft_digest || record.instruction_digest
      ? record
      : {};
  }

  function resultEnvelopeIsValid(envelope) {
    const record = objectRecord(envelope);
    if (!Object.keys(record).length) return false;
    const integrity = String(
      record.integrity_state || record.result_integrity || record.integrity || ""
    ).toLowerCase();
    if (/blocked|invalid|mismatch|incomplete|unavailable/.test(integrity)) return false;
    if (integrity !== "verified") return false;
    return Boolean(
      record.id !== null && record.id !== undefined
      || record.result_digest
      || record.ingested_at
    );
  }

  async function loadResultIntake(run) {
    if (!run || run.id === null || run.id === undefined) return;
    const key = String(run.id);
    try {
      const payload = await api("/api/codex-runs/" + encodeURIComponent(run.id) + "/result-envelope");
      const envelope = resultEnvelopeRecord(payload);
      if (Object.keys(envelope).length && objectRecord(payload).monitor) {
        envelope.monitor = objectRecord(payload).monitor;
      }
      state.resultEnvelopes[key] = Object.keys(envelope).length ? envelope : null;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      if (error instanceof ApiError && error.status === 404) {
        state.resultEnvelopes[key] = null;
        return;
      }
      state.resultEnvelopes[key] = {
        integrity_state: "result_unavailable",
        intake_message: productActionMessage(error)
      };
    }
  }

  async function loadHandoffReview(run) {
    if (!run || !resultEnvelopeIsValid(resultEnvelopeForRun(run))) return;
    const key = String(run.id);
    try {
      const payload = await api("/api/codex-runs/" + encodeURIComponent(run.id) + "/handoff-review");
      const review = handoffReviewRecord(payload);
      const draft = instructionDraftRecord(payload);
      state.handoffReviews[key] = Object.keys(review).length ? review : null;
      if (Object.keys(draft).length) state.instructionDrafts[key] = draft;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      if (error instanceof ApiError && error.status === 404) {
        state.handoffReviews[key] = null;
        return;
      }
      state.handoffReviews[key] = {
        reconciliation: "BLOCKED",
        blockers: [productActionMessage(error)],
        review_message: "Review Handoff could not be loaded."
      };
    }
  }

  function deliveryCandidateReviewForRun(run) {
    if (!run) return null;
    return state.deliveryCandidateReviews[String(run.id)] || null;
  }

  async function loadDeliveryCandidateReview(run) {
    if (!isTerminalCodexRun(run)) return;
    const key = String(run.id);
    if (state.deliveryCandidateReviewLoads.has(key)) return;
    state.deliveryCandidateReviewLoads.add(key);
    try {
      const review = await api("/api/codex-runs/" + run.id + "/delivery-candidate");
      if (!review || Number(review.run_id) !== Number(run.id)) {
        throw new ApiError(
          200,
          "CANDIDATE_BINDING_MISMATCH",
          "Change Candidate review did not match the selected Run.",
          {},
          "product"
        );
      }
      state.deliveryCandidateReviews[key] = review;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      state.deliveryCandidateReviews[key] = {
        run_id: run.id,
        candidate: null,
        drift: null,
        blockers: [{
          code: "CANDIDATE_REVIEW_LOAD_FAILED",
          message: productActionMessage(error)
        }],
        next_action: "Select Review Change Candidate to try again."
      };
    }
  }

  function deliveryCandidateReviewAvailable(run) {
    const review = objectRecord(deliveryCandidateReviewForRun(run));
    const candidate = objectRecord(review.candidate);
    const drift = objectRecord(review.drift);
    return Boolean(
      candidate.id !== null && candidate.id !== undefined
      || drift.evaluation_id !== null && drift.evaluation_id !== undefined
      || Array.isArray(review.blockers) && review.blockers.length
      || Array.isArray(drift.blockers) && drift.blockers.length
    );
  }

  function applyPlanReviewForRun(run) {
    if (!run) return null;
    return state.applyPlanReviews[String(run.id)] || null;
  }

  async function loadApplyPlanReview(run) {
    if (!isTerminalCodexRun(run) || !deliveryCandidateReviewAvailable(run)) return;
    const key = String(run.id);
    if (state.applyPlanReviewLoads.has(key)) return;
    state.applyPlanReviewLoads.add(key);
    try {
      const review = await api("/api/codex-runs/" + run.id + "/apply-plans");
      if (!review || Number(review.run_id) !== Number(run.id)) {
        throw new ApiError(
          200,
          "APPLY_PLAN_BINDING_MISMATCH",
          "Apply Plan review did not match the selected Run.",
          {},
          "product"
        );
      }
      state.applyPlanReviews[key] = review;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      state.applyPlanReviews[key] = {
        run_id: run.id,
        plan: null,
        history: [],
        blockers: [{
          code: "APPLY_PLAN_REVIEW_LOAD_FAILED",
          message: productActionMessage(error)
        }],
        next_action: "Select Review Apply Plan to try again."
      };
    }
  }

  function currentApplyPlanForRun(run) {
    return objectRecord(objectRecord(applyPlanReviewForRun(run)).plan);
  }

  function applySessionReviewForPlan(plan) {
    if (!plan || plan.id === null || plan.id === undefined) return null;
    return state.applySessionReviews[String(plan.id)] || null;
  }

  async function loadApplySessionReview(run, force) {
    const plan = currentApplyPlanForRun(run);
    if (!plan.id) return;
    const key = String(plan.id);
    if (!force && state.applySessionReviewLoads.has(key)) return;
    state.applySessionReviewLoads.add(key);
    try {
      const review = await api(
        "/api/apply-plans/" + encodeURIComponent(plan.id) + "/apply-sessions"
      );
      if (!review || String(review.plan_id || "") !== key) {
        throw new ApiError(
          200,
          "APPLY_SESSION_BINDING_MISMATCH",
          "Apply readiness did not match the selected Apply Plan.",
          {},
          "product"
        );
      }
      state.applySessionReviews[key] = review;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      state.applySessionReviews[key] = {
        plan_id: plan.id,
        session: null,
        actions: { can_apply: false, can_revert: false },
        blockers: [{
          code: "APPLY_SESSION_REVIEW_LOAD_FAILED",
          message: productActionMessage(error)
        }],
        next_action: "Review Apply readiness again."
      };
    }
  }

  function postApplyVerificationContextAvailable(applySession) {
    const record = objectRecord(applySession);
    return normalizedApplySessionState(record.apply_state) === "APPLIED"
      && normalizedApplySessionState(record.revert_state) === "NOT_REQUESTED";
  }

  function postApplyVerificationReviewForSession(applySession) {
    const record = objectRecord(applySession);
    if (!record.id) return null;
    return state.postApplyVerificationReviews[String(record.id)] || null;
  }

  async function loadPostApplyVerification(run, force) {
    const parts = applySessionReviewParts(run);
    const applySession = objectRecord(parts.session);
    if (!applySession.id || !postApplyVerificationContextAvailable(applySession)) return;
    const key = String(applySession.id);
    if (!force && state.postApplyVerificationReviewLoads.has(key)) return;
    state.postApplyVerificationReviewLoads.add(key);
    try {
      const review = await api(
        "/api/apply-sessions/" + encodeURIComponent(applySession.id)
          + "/post-apply-verifications"
      );
      if (!review || String(review.apply_session_id || "") !== key) {
        throw new ApiError(
          200,
          "POST_APPLY_VERIFICATION_BINDING_MISMATCH",
          "Post-Apply Verification did not match the selected Apply session.",
          {},
          "product"
        );
      }
      state.postApplyVerificationReviews[key] = review;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      state.postApplyVerificationReviews[key] = {
        apply_session_id: applySession.id,
        eligibility: {
          status: "BLOCKED",
          status_label: "BLOCKED",
          can_verify: false,
          blockers: [{
            code: "POST_APPLY_VERIFICATION_LOAD_FAILED",
            message: productActionMessage(error)
          }],
          next_action: "Restore repository access, then reload Post-Apply Verification."
        },
        verification: null,
        history: [],
        actions: { can_verify: false }
      };
    }
  }

  function currentPassedPostApplyVerification(run) {
    const parts = applySessionReviewParts(run);
    const applySession = objectRecord(parts.session);
    const review = objectRecord(postApplyVerificationReviewForSession(applySession));
    const verification = objectRecord(review.verification);
    return String(applySession.state || applySession.apply_state || "").toUpperCase() === "APPLIED"
      && String(verification.status || "").toUpperCase() === "PASSED"
      ? verification
      : null;
  }

  function commitBuilderReviewForVerification(verification) {
    if (!verification || !verification.id) return null;
    return state.commitBuilderReviews[String(verification.id)] || null;
  }

  function commitBuilderReviewBinding(review) {
    const value = objectRecord(review);
    const verification = objectRecord(value.post_apply_verification);
    const plan = objectRecord(value.plan || value.commit_plan);
    const advanced = objectRecord(plan.advanced);
    return String(
      value.post_apply_verification_id
      || value.verification_id
      || verification.id
      || advanced.verification_id
      || ""
    );
  }

  async function loadCommitBuilder(run, force) {
    const verification = currentPassedPostApplyVerification(run);
    if (!verification || !verification.id) return;
    const key = String(verification.id);
    if (!force && state.commitBuilderReviewLoads.has(key)) return;
    state.commitBuilderReviewLoads.add(key);
    const requestEpoch = state.taskSelectionEpoch;
    const requestSequence = (state.commitBuilderRequestSequences[key] || 0) + 1;
    state.commitBuilderRequestSequences[key] = requestSequence;
    try {
      const review = await api(
        "/api/post-apply-verifications/" + encodeURIComponent(key)
          + "/commit-plans"
      );
      if (requestEpoch !== state.taskSelectionEpoch
          || state.commitBuilderRequestSequences[key] !== requestSequence
          || String(currentPassedPostApplyVerification(currentCodexRun()).id || "") !== key) {
        return;
      }
      if (!review || commitBuilderReviewBinding(review) !== key) {
        throw new ApiError(
          200,
          "COMMIT_BUILDER_BINDING_MISMATCH",
          "Commit workflow review did not match the verified Apply result.",
          {},
          "product"
        );
      }
      state.commitBuilderReviews[key] = review;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      if (requestEpoch !== state.taskSelectionEpoch
          || state.commitBuilderRequestSequences[key] !== requestSequence) return;
      state.commitBuilderReviews[key] = {
        post_apply_verification_id: key,
        eligibility: {
          status: "BLOCKED",
          status_label: "BLOCKED",
          can_review: false,
          blockers: [{
            code: "COMMIT_BUILDER_REVIEW_LOAD_FAILED",
            message: productActionMessage(error)
          }],
          next_action: "Restore repository access, then reload the Commit workflow."
        },
        plan: null,
        stage: null,
        commit: null,
        actions: {
          can_review_commit_plan: false,
          can_stage_approved_files: false,
          can_create_local_commit: false
        }
      };
    }
  }

  function currentCommittedLocalCommit(run) {
    const commit = objectRecord(commitBuilderParts(run).commit);
    return String(commit.state || commit.status || "").toUpperCase() === "COMMITTED"
      && commitBuilderRecordId(commit)
      ? commit
      : null;
  }

  function pushDeliveryReviewForLocalCommit(commit) {
    const key = commit ? String(commitBuilderRecordId(commit) || "") : "";
    return key ? state.pushDeliveryReviews[key] || null : null;
  }

  function pushDeliveryReviewBinding(review) {
    const value = objectRecord(review);
    const localCommit = objectRecord(value.local_commit);
    return String(
      value.local_commit_execution_id
      || value.commit_execution_id
      || localCommit.id
      || localCommit.commit_execution_id
      || ""
    );
  }

  function pushDeliveryLoadFailure(commitId, error) {
    return {
      local_commit_execution_id: String(commitId),
      action_state: "PUSH_BLOCKED",
      readiness: {
        status: "PUSH_BLOCKED",
        status_label: "PUSH BLOCKED",
        blockers: [{
          code: error instanceof ApiError ? error.code : "PUSH_DELIVERY_LOAD_FAILED",
          message: productActionMessage(error)
        }],
        next_action: "Push readiness could not be loaded. Review the diagnostic evidence, then retry only when meaningful."
      },
      push_execution: null,
      delivery_result: null,
      actions: {
        can_push_to_origin_main: false,
        can_confirm_push: false,
        can_view_delivery_result: false
      }
    };
  }

  async function loadPushDelivery(run, force) {
    const commit = currentCommittedLocalCommit(run);
    if (!commit) return;
    const key = String(commitBuilderRecordId(commit));
    if (!force && state.pushDeliveryReviewLoads.has(key)) return;
    state.pushDeliveryReviewLoads.add(key);
    const requestEpoch = state.taskSelectionEpoch;
    const requestSequence = (state.pushDeliveryRequestSequences[key] || 0) + 1;
    state.pushDeliveryRequestSequences[key] = requestSequence;
    try {
      const review = await api(
        "/api/local-commits/" + encodeURIComponent(key) + "/push-delivery"
      );
      const current = currentCommittedLocalCommit(currentCodexRun());
      if (requestEpoch !== state.taskSelectionEpoch
          || state.pushDeliveryRequestSequences[key] !== requestSequence
          || String(commitBuilderRecordId(current) || "") !== key) return;
      if (!review || pushDeliveryReviewBinding(review) !== key) {
        throw new ApiError(
          200,
          "PUSH_DELIVERY_BINDING_MISMATCH",
          "Push readiness did not match the selected local Commit result.",
          {},
          "product"
        );
      }
      state.pushDeliveryReviews[key] = review;
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      if (requestEpoch !== state.taskSelectionEpoch
          || state.pushDeliveryRequestSequences[key] !== requestSequence) return;
      state.pushDeliveryReviews[key] = pushDeliveryLoadFailure(key, error);
    }
  }

  function ownerDeliveryProjectionForRun(run) {
    if (!run || run.id === null || run.id === undefined) return null;
    return state.ownerDeliveryProjections[String(run.id)] || null;
  }

  function canonicalOwnerDeliveryAvailable(run) {
    const projection = objectRecord(ownerDeliveryProjectionForRun(run));
    return Boolean(
      projection.commit_delivery
      || projection.push_delivery
      || projection.delivery_contract === "VOL19_19_1D"
      || projection.contract_version === "19.1D"
    );
  }

  async function loadOwnerDelivery(run, force) {
    if (!run || run.id === null || run.id === undefined) return;
    const key = String(run.id);
    if (!force && state.ownerDeliveryProjectionLoads.has(key)) return;
    state.ownerDeliveryProjectionLoads.add(key);
    const requestEpoch = state.taskSelectionEpoch;
    const requestSequence = (state.ownerDeliveryRequestSequences[key] || 0) + 1;
    state.ownerDeliveryRequestSequences[key] = requestSequence;
    try {
      const projection = await api(
        "/api/codex-runs/" + encodeURIComponent(key) + "/delivery"
      );
      if (requestEpoch !== state.taskSelectionEpoch
          || state.ownerDeliveryRequestSequences[key] !== requestSequence
          || String(objectRecord(currentCodexRun()).id || "") !== key) return;
      if (!projection || String(projection.run_id || "") !== key) {
        throw new ApiError(
          200,
          "OWNER_DELIVERY_BINDING_MISMATCH",
          "Owner delivery status did not match the selected Run.",
          {},
          "product"
        );
      }
      state.ownerDeliveryProjections[key] = projection;
      resolveOwnerPushConfirmationUncertainty(key, projection, requestSequence);
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      if (requestEpoch !== state.taskSelectionEpoch
          || state.ownerDeliveryRequestSequences[key] !== requestSequence) return;
      state.ownerDeliveryProjections[key] = {
        run_id: run.id,
        delivery_contract: "VOL19_19_1D",
        load_error: {
          code: error instanceof ApiError ? error.code : "OWNER_DELIVERY_LOAD_FAILED",
          message: productActionMessage(error)
        }
      };
    }
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
    state.firstDeliveryGuide = null;
    state.runConfirmationContext = null;
    if (elements.startCodexConfirmationDialog.open) elements.startCodexConfirmationDialog.close();
    state.pushConfirmationContext = null;
    if (elements.pushConfirmationDialog.open) elements.pushConfirmationDialog.close();
    state.ownerCommitConfirmationContext = null;
    state.ownerPushConfirmationContext = null;
    state.ownerPushConfirmationUncertainty = null;
    if (elements.ownerLocalCommitConfirmationDialog.open) elements.ownerLocalCommitConfirmationDialog.close();
    if (elements.ownerPushConfirmationDialog.open) elements.ownerPushConfirmationDialog.close();
    state.aiPlan = null;
    state.acceptance = null;
    state.packs = [];
    state.codexRuns = [];
    state.selectedActivityRunId = null;
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
    elements.taskWorkflow.value = firstRunFirstTaskPending()
      ? "general"
      : "product_development";
    elements.taskName.value = "";
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
    state.selectedActivityRunId = null;
    state.taskSelectionEpoch += 1;
    state.taskLoadState = "empty";
    state.taskLoadMessage = firstRunFirstTaskPending()
      ? "Enter a task title and goal, then save the first task."
      : "Enter a Development task, then save it.";
    state.renderedTaskId = null;
    resetTaskDetails();
    initializeNewTaskForm();
    renderWorkspace();
    closeTaskDrawer();
    setFeedback(
      firstRunFirstTaskPending()
        ? "Step 7 of 7: create the first task. Saving will not start a Run or contact a provider."
        : "New task ready. Development task is the only required Owner input.",
      "neutral"
    );
    if (shouldFocus) {
      if (firstRunFirstTaskPending()) elements.taskName.focus();
      else elements.taskTitle.focus();
    }
  }

  function syncTaskRequirements() {
    const firstTask = firstRunFirstTaskPending() && state.creatingTask;
    elements.taskName.required = firstTask;
    setVisible(elements.taskNameField, firstTask);
    setVisible(elements.firstRunFirstTaskBanner, firstTask);
    elements.taskTitleLabel.textContent = firstTask ? "Goal or objective" : "Development task";
    elements.developmentTaskHelp.textContent = firstTask
      ? "Describe what you want to accomplish. Saving creates only this Task and its internal AI Team plan; it does not create a Pack, start a Run, or contact a provider."
      : "Describe the complete development task. TWOS preserves this text and derives the execution details deterministically.";
    if (firstTask) {
      replaceText(
        elements.firstRunFirstTaskNextAction,
        state.firstRun && state.firstRun.next_action,
        "Create and save the first task. Saving does not start a Run or contact a provider."
      );
    }
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
    let requestedTaskId = null;
    let requestSelectionEpoch = null;
    try {
      const base = await Promise.all([
        api("/api/health"),
        api("/api/projects"),
        api("/api/tasks"),
        api("/api/runs"),
        api("/api/schedules"),
        api("/api/audit"),
        api("/api/codex/status"),
        api("/api/run-activity")
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
      state.runActivity = mergeRunActivityLifecycleSnapshots(
        state.runActivity,
        runActivityItems(base[7])
      );

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
          state.taskSelectionEpoch += 1;
          state.taskLoadState = state.selectedTaskId === null ? "empty" : "loading";
          state.taskLoadMessage = state.selectedTaskId === null
            ? "Create a task to begin."
            : "Loading the selected Task.";
          state.renderedTaskId = null;
          resetTaskDetails();
        }
      }
      if (!state.tasks.length && !state.creatingTask) {
        state.creatingTask = true;
        state.taskSelectionEpoch += 1;
        state.taskLoadState = "empty";
        state.taskLoadMessage = firstRunFirstTaskPending()
          ? "Step 7 of 7: create and save the first task."
          : "Create your first Development task.";
        initializeNewTaskForm();
      }

      const task = selectedTask();
      if (task) {
        requestedTaskId = task.id;
        requestSelectionEpoch = state.taskSelectionEpoch;
        const detail = await Promise.all([
          api("/api/tasks/" + task.id + "/acceptance"),
          api("/api/tasks/" + task.id + "/ai-plan"),
          api("/api/tasks/" + task.id + "/codex-packs"),
          api("/api/tasks/" + task.id + "/codex-runs"),
          api("/api/tasks/" + task.id + "/owner-acceptance"),
          api("/api/tasks/" + task.id + "/run-eligibility")
        ]);
        if (
          requestSelectionEpoch !== state.taskSelectionEpoch
          || String(state.selectedTaskId) !== String(requestedTaskId)
        ) {
          state.refreshQueued = true;
          return;
        }
        state.acceptance = detail[0] || null;
        state.aiPlan = detail[1] || null;
        state.packs = Array.isArray(detail[2]) ? detail[2] : [];
        state.codexRuns = Array.isArray(detail[3]) ? detail[3] : [];
        state.ownerAcceptance = detail[4] && detail[4].acceptance ? detail[4].acceptance : null;
        state.runEligibility = detail[5] && typeof detail[5] === "object" ? detail[5] : null;
        if (
          state.selectedActivityRunId !== null
          && !state.codexRuns.some(function (run) {
            return String(run.id) === String(state.selectedActivityRunId);
          })
        ) state.selectedActivityRunId = null;
        const selectedRun = currentCodexRun();
        if (selectedRun) {
          const exactAcceptance = await api(
            "/api/tasks/" + encodeURIComponent(task.id)
              + "/owner-acceptance?run_id=" + encodeURIComponent(selectedRun.id)
          );
          if (
            requestSelectionEpoch !== state.taskSelectionEpoch
            || String(state.selectedTaskId) !== String(requestedTaskId)
          ) {
            state.refreshQueued = true;
            return;
          }
          state.ownerAcceptance = exactAcceptance && exactAcceptance.acceptance
            ? exactAcceptance.acceptance
            : null;
        }
        await loadResultIntake(currentCodexRun());
        await loadHandoffReview(currentCodexRun());
        await loadDeliveryCandidateReview(currentCodexRun());
        await loadApplyPlanReview(currentCodexRun());
        await loadApplySessionReview(currentCodexRun(), true);
        await loadPostApplyVerification(currentCodexRun(), true);
        await loadCommitBuilder(currentCodexRun(), true);
        await loadPushDelivery(currentCodexRun(), true);
        await loadOwnerDelivery(currentCodexRun(), true);
        await loadFirstDeliveryGuide(task, requestSelectionEpoch);
        if (
          requestSelectionEpoch !== state.taskSelectionEpoch
          || String(state.selectedTaskId) !== String(requestedTaskId)
        ) {
          state.refreshQueued = true;
          return;
        }
        state.taskLoadState = "success";
        state.taskLoadMessage = "Selected Task loaded.";
      } else {
        resetTaskDetails();
        state.taskLoadState = "empty";
        state.taskLoadMessage = state.creatingTask
          ? firstRunFirstTaskPending()
            ? "Step 7 of 7: enter a task title and goal, then save it."
            : "Enter a Development task, then save it."
          : "Select a saved Task.";
      }

      state.workspaceLoaded = true;
      renderWorkspace();
      if (elements.feedback.textContent === "Loading your workbench…") {
        setFeedback(state.tasks.length ? "Workbench ready." : "Create your first task to begin.", "neutral");
      } else if (elements.feedback.textContent === "Loading task…") {
        setFeedback("Selected Task loaded.", "success");
      } else if (elements.feedback.textContent === "Loading the selected Run Result…") {
        setFeedback("Run Result loaded.", "success");
      }
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleExpiredSession();
      } else {
        if (
          requestedTaskId !== null
          && requestSelectionEpoch === state.taskSelectionEpoch
          && String(state.selectedTaskId) === String(requestedTaskId)
        ) {
          state.taskLoadState = "failure";
          state.taskLoadMessage = "The selected Task could not be loaded. Refresh Run Status or choose it again.";
          renderSelectedTaskContext();
        }
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
    renderSelectedTaskContext();
    renderAIPlan();
    renderPack();
    renderCodex();
    renderRunActivity();
    renderResult();
    renderOwnerAcceptance();
    renderCompactSync();
    renderWorkerAcceptance();
    renderSchedules();
    renderRegistries();
    renderAudit();
    renderActionAvailability();
    renderHeaderStatus();
    renderFirstDeliveryGuide();
  }

  function renderHeaderStatus() {
    const detection = state.codexStatus;
    const connectivity = objectRecord(objectRecord(detection).connectivity);
    const runtimeAvailable = detection && detection.execution_ready === true
      && connectivity.ready_for_real_run === true;
    elements.codexHeaderStatus.textContent = detection && detection.passive === true && detection.authentication_ready !== true
      ? "Codex: " + String(detection.readiness_state || "Not checked")
      : runtimeAvailable
      ? "Codex: Ready for real Run"
      : "Codex: " + connectivityStateLabel(connectivity.readiness_state);
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

  function taskDisplayName(task) {
    const record = objectRecord(task);
    return String(record.title || record.development_task || "Untitled Development task").trim()
      || "Untitled Development task";
  }

  function renderSelectedTaskContext() {
    const task = selectedTask();
    let name;
    let stateValue = state.taskLoadState;
    let message = state.taskLoadMessage;
    if (state.creatingTask) {
      name = "New task";
      stateValue = "empty";
      message = firstRunFirstTaskPending()
        ? "Step 7 of 7: enter a task title and goal, then save it."
        : "Enter a Development task, then save it.";
    } else if (!task) {
      name = state.workspaceLoaded ? "No Task selected" : "Loading task…";
      stateValue = state.workspaceLoaded ? "empty" : "loading";
      message = state.workspaceLoaded ? "Choose a saved Task or create a new one." : "Loading your saved task selection.";
    } else {
      name = taskDisplayName(task);
      if (stateValue === "success") message = "Selected Task loaded.";
    }
    elements.selectedTaskName.textContent = name;
    elements.selectedTaskName.title = task ? name : "";
    elements.selectedTaskLoadState.textContent = message;
    elements.selectedTaskContext.dataset.state = stateValue;
  }

  function renderTaskList() {
    elements.newTask.textContent = firstRunFirstTaskPending() ? "Create First Task" : "New task";
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
      title.textContent = taskDisplayName(task);
      button.title = taskDisplayName(task);
      button.setAttribute("aria-label", "Select Task: " + taskDisplayName(task));
      status.textContent = humanStatus(task.status);
      button.appendChild(title);
      button.appendChild(status);
      button.addEventListener("click", function () {
        state.creatingTask = false;
        state.newTaskInitialized = false;
        state.selectedTaskId = task.id;
        state.selectedActivityRunId = null;
        state.taskSelectionEpoch += 1;
        state.taskLoadState = "loading";
        state.taskLoadMessage = "Loading the selected Task.";
        state.renderedTaskId = null;
        resetTaskDetails();
        renderTaskList();
        renderSelectedTaskContext();
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
    elements.taskName.value = task.title || "";
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

  function appendRunActivityFact(target, label, value) {
    const item = document.createElement("span");
    const heading = document.createElement("b");
    heading.textContent = label;
    item.appendChild(heading);
    item.appendChild(document.createTextNode(value));
    target.appendChild(item);
  }

  function lifecycleRecordForActivity(record) {
    return objectRecord(objectRecord(record).lifecycle);
  }

  function rawRunIdFromActivity(record) {
    const source = objectRecord(record);
    const monitor = objectRecord(source.monitor);
    const run = objectRecord(source.run);
    const envelope = resultEnvelopeRecord(
      source.result_envelope || source.resultEnvelope || source.envelope
    );
    return source.run_id || monitor.run_id || run.id || envelope.run_id;
  }

  function lifecycleForRun(run) {
    if (!run || run.id === null || run.id === undefined) return {};
    const matching = state.runActivity.find(function (record) {
      const runId = rawRunIdFromActivity(record);
      return runId !== null && runId !== undefined && String(runId) === String(run.id);
    });
    return lifecycleRecordForActivity(matching);
  }

  function authoritativeRunStatus(run) {
    const lifecycle = lifecycleForRun(run);
    const matching = run && state.runActivity.find(function (record) {
      const runId = rawRunIdFromActivity(record);
      return runId !== null && runId !== undefined && String(runId) === String(run.id);
    });
    const record = objectRecord(matching);
    const monitor = objectRecord(record.monitor);
    const nestedRun = objectRecord(record.run);
    return String(
      lifecycle.state
      || record.monitor_state
      || monitor.monitor_state
      || record.status
      || nestedRun.status
      || run && run.status
      || ""
    ).toLowerCase();
  }

  function lifecycleIsActive(status) {
    return ACTIVE_CODEX_RUN_STATUSES.indexOf(String(status || "").toLowerCase()) !== -1;
  }

  function formatLifecycleDuration(value, fallback) {
    const milliseconds = Number(value);
    if (!Number.isFinite(milliseconds) || milliseconds < 0) return fallback || "Not available";
    const totalSeconds = Math.floor(milliseconds / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours) return hours + " hr " + minutes + " min " + seconds + " sec";
    if (minutes) return minutes + " min " + seconds + " sec";
    return seconds + " sec";
  }

  function lifecycleBoolean(value, positive, negative) {
    if (value === true) return positive;
    if (value === false) return negative;
    return "Not reported";
  }

  function lifecycleActivityText(value, fallback) {
    const text = ownerSafeText(value, fallback || "Waiting for the next lifecycle event.", 180);
    if (/reasoning|chain[- ]of[- ]thought|\bcot\b|internal (?:thought|analysis|monologue)|thinking|deliberat/i.test(text)) {
      return "Codex is reasoning";
    }
    return text.replace(/[\r\n]+/g, " ");
  }

  function lifecycleEventView(value) {
    const event = objectRecord(value);
    const type = ownerSafeText(
      event.type || event.event_type || event.kind || event.state || event.phase,
      "Activity update",
      80
    );
    const reasoningEvent = /reasoning|chain[- ]of[- ]thought|\bcot\b|thinking|deliberat/i.test(
      [type, event.category, event.item_type].filter(Boolean).join(" ")
    );
    const activity = lifecycleActivityText(
      reasoningEvent
        ? "Codex is reasoning"
        : event.safe_summary || event.current_activity || event.activity || event.label || type,
      "Activity update"
    );
    const eventPath = event.repository_relative_path || event.repository_path;
    const path = eventPath
      ? repositoryRelativePath(eventPath)
      : "";
    return {
      sequence: Number.isFinite(Number(event.sequence)) ? String(Number(event.sequence)) : "",
      type: humanStatus(type),
      phase: humanStatus(event.phase || "not reported"),
      activity: activity,
      reasoning: reasoningEvent,
      status: humanStatus(event.status || event.state || "not reported"),
      path: path === "File path withheld" ? "" : path,
      count: Number.isFinite(Number(event.event_count)) && Number(event.event_count) > 0
        ? Number(event.event_count)
        : null,
      duration: event.duration_ms === null || event.duration_ms === undefined
        ? ""
        : formatLifecycleDuration(event.duration_ms, ""),
      occurredAt: event.occurred_at || event.created_at || event.timestamp || event.recorded_at
    };
  }

  function appendLifecycleTimeline(target, events) {
    const source = Array.isArray(events) ? events : [];
    const bounded = source.slice(-12).map(lifecycleEventView);
    clearChildren(target);
    if (!bounded.length) {
      const empty = document.createElement("li");
      empty.textContent = "No safe lifecycle events have been recorded yet.";
      target.appendChild(empty);
      return;
    }
    bounded.forEach(function (event) {
      const item = document.createElement("li");
      const heading = document.createElement("span");
      const detail = document.createElement("span");
      heading.className = "live-codex-event-heading";
      heading.textContent = (event.sequence ? "#" + event.sequence + " · " : "")
        + event.type + " · " + formatTime(event.occurredAt);
      detail.className = "live-codex-event-detail";
      detail.textContent = event.phase + " · " + event.status + " · " + event.activity
        + (event.path ? " · " + event.path : "")
        + (event.count ? " · " + event.count + " updates" : "")
        + (event.duration ? " · " + event.duration : "");
      item.appendChild(heading);
      item.appendChild(detail);
      target.appendChild(item);
    });
    if (source.length > bounded.length) {
      const notice = document.createElement("li");
      notice.className = "live-codex-timeline-notice";
      notice.textContent = "Showing the latest " + bounded.length + " of " + source.length + " safe lifecycle events.";
      target.insertBefore(notice, target.firstChild);
    }
  }

  function safeLifecycleIdentifier(value) {
    const text = String(value === null || value === undefined ? "" : value).trim();
    if (!text) return "Not recorded";
    if (!/^[A-Za-z0-9._:-]{1,160}$/.test(text)) return "Withheld";
    return text;
  }

  function safeLifecycleNumberMap(value, emptyText) {
    const record = objectRecord(value);
    const entries = Object.keys(record).sort().slice(0, 24).map(function (key) {
      const number = Number(record[key]);
      if (!/^[A-Za-z0-9._:-]{1,80}$/.test(key) || !Number.isFinite(number) || number < 0) return "";
      return key + ": " + String(number);
    }).filter(Boolean);
    return entries.length ? entries.join(" · ") : emptyText;
  }

  function appendLifecycleAdvanced(target, lifecycle) {
    const advanced = objectRecord(lifecycle.advanced);
    const facts = [
      ["Lifecycle snapshot version", safeLifecycleIdentifier(lifecycle.snapshot_version)],
      ["Execution attempt", safeLifecycleIdentifier(advanced.execution_attempt_id || advanced.attempt_id)],
      ["Monitor", safeLifecycleIdentifier(advanced.monitor_id)],
      ["Execution", safeLifecycleIdentifier(advanced.execution_id)],
      ["Process PID", safeLifecycleIdentifier(advanced.process_id)],
      ["Bridge PID", safeLifecycleIdentifier(advanced.sidecar_process_id)],
      ["Executable fingerprint", safeLifecycleIdentifier(advanced.executable_fingerprint)],
      ["Local log reference", ownerSafeText(advanced.protected_log_reference, "Not recorded", 1000)],
      ["Process-start identity", safeLifecycleIdentifier(advanced.process_start_identity)],
      ["Terminal-event identity", safeLifecycleIdentifier(advanced.terminal_event_identity)],
      ["Receipt digest", safeLifecycleIdentifier(advanced.receipt_digest)],
      ["Stream offsets", safeLifecycleNumberMap(advanced.stream_offsets || advanced.offsets, "Not recorded")],
      ["Event histogram", safeLifecycleNumberMap(advanced.event_histogram || advanced.type_histogram || advanced.histogram, "Not recorded")],
      ["Result sidecar", humanStatus(advanced.sidecar_state || advanced.result_sidecar_state || "not recorded")],
      ["Evidence envelope integrity", humanStatus(lifecycle.result_integrity || "pending")],
      [
        "Exit code",
        advanced.exit_code !== null
          && advanced.exit_code !== undefined
          && advanced.exit_code !== ""
          && Number.isInteger(Number(advanced.exit_code))
          ? String(Number(advanced.exit_code))
          : "Not recorded"
      ],
      ["Reconciliation version", safeLifecycleIdentifier(advanced.reconciliation_version || advanced.reconcile_version)]
    ];
    facts.forEach(function (fact) {
      appendRunActivityFact(target, fact[0], ownerSafeText(fact[1], "Not recorded", 360));
    });
  }

  function appendLiveCodexActivity(target, view) {
    const lifecycle = view.lifecycle;
    const truth = objectRecord(view.terminalTruth);
    const truthCoding = objectRecord(truth.coding);
    const truthVerification = objectRecord(truth.verification);
    const truthResult = objectRecord(truth.result);
    const truthWorkspace = objectRecord(truth.workspace);
    const truthReview = objectRecord(truth.owner_review);
    const events = Array.isArray(lifecycle.events) ? lifecycle.events : [];
    const latestEvent = events.length ? lifecycleEventView(events[events.length - 1]) : null;
    const facts = document.createElement("span");
    const timelineHeading = document.createElement("strong");
    const timeline = document.createElement("ol");
    const advanced = document.createElement("details");
    const advancedSummary = document.createElement("summary");
    const advancedFacts = document.createElement("span");
    target.className = "live-codex-activity";
    target.setAttribute("aria-label", "Live Codex Activity for " + view.taskName);
    facts.className = "live-codex-facts";
    appendRunActivityFact(facts, "Run outcome", view.primaryLabel);
    appendRunActivityFact(facts, "Coding outcome", humanStatus(truthCoding.status || view.coding));
    appendRunActivityFact(facts, "Independent Verification", humanStatus(truthVerification.status || view.verification));
    appendRunActivityFact(facts, "Result availability", humanStatus(truthResult.state || "unavailable"));
    appendRunActivityFact(facts, "Workspace evidence", humanStatus(truthWorkspace.state || "incomplete"));
    appendRunActivityFact(facts, "Evidence envelope integrity", humanStatus(truthResult.integrity || view.integrity));
    appendRunActivityFact(
      facts,
      "Owner warning",
      ownerWorkflowText(truthReview.summary, "No additional warning.", 600)
    );
    appendRunActivityFact(facts, "Current execution state", humanStatus(view.status));
    appendRunActivityFact(facts, "Coding / Verification phase", humanStatus(lifecycle.phase || "not reported"));
    appendRunActivityFact(
      facts,
      "Current observable activity",
      latestEvent && latestEvent.reasoning
        ? "Codex is reasoning"
        : lifecycleActivityText(lifecycle.current_activity, "Waiting for the next lifecycle event.")
    );
    appendRunActivityFact(facts, "Run started at", formatTime(lifecycle.started_at));
    appendRunActivityFact(facts, "Current elapsed time", formatLifecycleDuration(lifecycle.elapsed_ms));
    appendRunActivityFact(facts, "Coding elapsed time", formatLifecycleDuration(lifecycle.coding_elapsed_ms));
    appendRunActivityFact(facts, "Verification elapsed time", formatLifecycleDuration(lifecycle.verification_elapsed_ms));
    appendRunActivityFact(
      facts,
      "Result-settlement elapsed time",
      formatLifecycleDuration(
        lifecycle.result_settlement_elapsed_ms !== null
          && lifecycle.result_settlement_elapsed_ms !== undefined
          ? lifecycle.result_settlement_elapsed_ms
          : lifecycle.settlement_elapsed_ms
      )
    );
    appendRunActivityFact(facts, "Last observable activity at", formatTime(lifecycle.last_activity_at));
    appendRunActivityFact(
      facts,
      "Time since last activity",
      lifecycle.inactivity_ms === null || lifecycle.inactivity_ms === undefined
        ? "Not available"
        : formatLifecycleDuration(lifecycle.inactivity_ms) + " ago"
    );
    appendRunActivityFact(facts, "Process live", lifecycleBoolean(lifecycle.process_live, "Yes", "No"));
    appendRunActivityFact(facts, "Monitor attached", lifecycleBoolean(lifecycle.monitor_attached, "Yes", "No"));
    appendRunActivityFact(facts, "Coding started", lifecycleBoolean(lifecycle.coding_started, "Yes", "No"));
    appendRunActivityFact(facts, "Process exited", lifecycleBoolean(lifecycle.process_exited, "Yes", "No"));
    appendRunActivityFact(facts, "Verification started", lifecycleBoolean(lifecycle.verification_started, "Yes", "No"));
    appendRunActivityFact(
      facts,
      "Terminal evidence observed",
      lifecycleBoolean(lifecycle.terminal_evidence_observed, "Yes", "No")
    );
    appendRunActivityFact(
      facts,
      "Latest safe event summary",
      latestEvent ? latestEvent.type + " · " + latestEvent.activity : "No safe event recorded"
    );
    appendRunActivityFact(facts, "Blocker code", safeLifecycleIdentifier(lifecycle.blocker_code));
    appendRunActivityFact(facts, "Event count", String(events.length));
    appendRunActivityFact(facts, "Exact next Owner action", view.nextAction);
    timelineHeading.className = "live-codex-timeline-title";
    timelineHeading.textContent = "Safe activity timeline";
    timeline.className = "live-codex-timeline";
    appendLifecycleTimeline(timeline, events);
    advanced.className = "live-codex-advanced";
    advancedSummary.textContent = "Advanced";
    advancedFacts.className = "live-codex-advanced-facts";
    appendLifecycleAdvanced(advancedFacts, lifecycle);
    advanced.appendChild(advancedSummary);
    advanced.appendChild(timelineHeading);
    advanced.appendChild(timeline);
    advanced.appendChild(advancedFacts);
    target.appendChild(facts);
    target.appendChild(advanced);
  }

  function selectRunActivity(view) {
    if (view.taskId === null || view.taskId === undefined) return;
    state.creatingTask = false;
    state.newTaskInitialized = false;
    state.selectedTaskId = view.taskId;
    state.taskSelectionEpoch += 1;
    state.taskLoadState = "loading";
    state.taskLoadMessage = "Loading the selected Task and Run Result.";
    state.renderedTaskId = null;
    resetTaskDetails();
    state.selectedActivityRunId = view.runId;
    renderTaskList();
    renderSelectedTaskContext();
    closeTaskDrawer();
    setFeedback("Loading the selected Run Result…", "neutral");
    refreshWorkspace({ force: true });
  }

  function activityResultIsBlocked(view) {
    if (!view) return false;
    const truth = objectRecord(view.terminalTruth);
    const primary = String(truth.primary_status || "").toLowerCase();
    if (["needs_review", "failed", "cancelled", "timed_out", "interrupted", "blocked"].indexOf(primary) !== -1) {
      return true;
    }
    if (truth.result && truth.result.available === true) return false;
    return RESULT_BLOCKED_STATUSES.indexOf(view.status) !== -1
      || !lifecycleIsActive(view.status) && /blocked|invalid|unavailable/.test(view.integrity);
  }

  function activityResultIsAvailable(view) {
    if (!view || activityResultIsBlocked(view)) return false;
    if (view.terminalTruth && view.terminalTruth.result) return view.terminalTruth.result.available === true;
    if (view.lifecycleAvailable) {
      return RESULT_AVAILABLE_STATUSES.indexOf(view.status) !== -1;
    }
    return RESULT_AVAILABLE_STATUSES.indexOf(view.status) !== -1
      || !lifecycleIsActive(view.status) && resultEnvelopeIsValid(view.envelope);
  }

  function renderRunActivity() {
    const views = state.runActivity.map(activityView);
    const observed = views.filter(function (view) {
      return activityNeedsBrowserObservation(view);
    });
    const active = views.filter(function (view) {
      return lifecycleIsActive(view.status);
    });
    const available = views.filter(activityResultIsAvailable);
    const blocked = views.filter(activityResultIsBlocked);
    const headline = views.find(function (view) {
      return activityResultIsBlocked(view)
        || activityResultIsAvailable(view)
        || activityNeedsBrowserObservation(view);
    });

    elements.runActivityStatus.textContent = active.length
      ? active.length + " active"
      : observed.length
        ? "Result intake pending"
        : blocked.length
          ? blocked.length + " result" + (blocked.length === 1 ? "" : "s") + " need Owner review"
          : available.length
            ? available.length + " result" + (available.length === 1 ? "" : "s") + " available"
            : views.length ? humanStatus(views[0].status) : "No Runs";
    setStatusLabel(elements.runActivityStatus, elements.runActivityStatus.textContent);

    if (headline && activityResultIsBlocked(headline)) {
      elements.runActivityNotification.dataset.state = headline.primaryStatus === "needs_review"
        ? "review"
        : "blocked";
      elements.runActivityNotification.textContent = headline.taskName
        + " · " + headline.primaryLabel
        + " · Evidence envelope integrity " + humanStatus(headline.integrity)
        + " · " + headline.nextAction;
    } else if (headline && activityResultIsAvailable(headline)) {
      const latest = headline;
      elements.runActivityNotification.dataset.state = "ready";
      elements.runActivityNotification.textContent = latest.taskName
        + " · " + latest.primaryLabel
        + " · Verification " + latest.verification
        + " · " + latest.nextAction;
    } else {
      elements.runActivityNotification.dataset.state = observed.length ? "monitoring" : "empty";
      elements.runActivityNotification.textContent = observed.length
        ? observed[0].taskName + " · " + humanStatus(observed[0].status) + " · TWOS is monitoring independently of this browser."
        : "No Run result needs Owner review.";
    }

    clearChildren(elements.runActivityList);
    if (!views.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No Codex Runs yet. An explicitly started Run will appear here automatically.";
      elements.runActivityList.appendChild(empty);
    } else {
      views.forEach(function (view) {
        const item = document.createElement("article");
        const itemOpen = document.createElement("button");
        const main = document.createElement("span");
        const heading = document.createElement("span");
        const title = document.createElement("strong");
        const status = document.createElement("span");
        const facts = document.createElement("span");
        const action = document.createElement("span");
        const liveActivity = document.createElement("section");
        item.className = "run-activity-item";
        item.dataset.runId = String(view.runId || "");
        item.setAttribute(
          "aria-current",
          state.selectedActivityRunId !== null && String(state.selectedActivityRunId) === String(view.runId)
            ? "true"
            : "false"
        );
        itemOpen.type = "button";
        itemOpen.className = "run-activity-item-open";
        itemOpen.setAttribute("aria-label", "Review Run Result for " + view.taskName);
        itemOpen.disabled = view.taskId === null || view.taskId === undefined;
        main.className = "run-activity-item-main";
        heading.className = "run-activity-item-heading";
        title.textContent = view.taskName;
        title.title = view.taskName;
        status.className = "status-label";
        status.textContent = lifecycleIsActive(view.status) ? humanStatus(view.status) : view.primaryLabel;
        setStatusLabel(status, status.textContent);
        heading.appendChild(title);
        heading.appendChild(status);
        facts.className = "run-activity-item-grid";
        appendRunActivityFact(facts, "Requested model", view.requestedModel);
        appendRunActivityFact(facts, "Requested model accepted", view.requestedModelAccepted);
        appendRunActivityFact(facts, "Run-local effective model", view.runLocalEffectiveModel);
        appendRunActivityFact(facts, "Started", formatTime(view.startedAt));
        appendRunActivityFact(facts, "Finished", formatTime(view.finishedAt));
        appendRunActivityFact(facts, "Duration", view.duration);
        appendRunActivityFact(facts, "Coding", view.coding);
        appendRunActivityFact(facts, "Verification", view.verification);
        appendRunActivityFact(
          facts,
          "Result availability",
          humanStatus(objectRecord(view.terminalTruth.result).state || "unavailable")
        );
        appendRunActivityFact(
          facts,
          "Workspace evidence",
          humanStatus(objectRecord(view.terminalTruth.workspace).state || "incomplete")
        );
        appendRunActivityFact(facts, "Tests", view.tests);
        appendRunActivityFact(facts, "Evidence envelope integrity", humanStatus(view.integrity));
        appendRunActivityFact(facts, "Exact Owner action", view.nextAction);
        main.appendChild(heading);
        main.appendChild(facts);
        action.className = "run-activity-item-action";
        action.textContent = "Review Run Result";
        itemOpen.appendChild(main);
        itemOpen.appendChild(action);
        itemOpen.addEventListener("click", function () { selectRunActivity(view); });
        item.appendChild(itemOpen);
        appendLiveCodexActivity(liveActivity, view);
        item.appendChild(liveActivity);
        elements.runActivityList.appendChild(item);
      });
    }

    const current = currentRunActivity();
    const hasRun = Boolean(current && current.runId !== null && current.runId !== undefined);
    const recoveryBlocked = Boolean(current && current.recoveryBlocked);
    const reconnectable = hasRun && !recoveryBlocked && (
      current.canReconnect
      || ["process_lost", "result_pending", "result_unavailable"].indexOf(current.status) !== -1
    );
    const importable = hasRun && !recoveryBlocked && (
      current.canImport
      || isTerminalCodexRun({ status: current.status })
      || ["result_pending", "result_unavailable", "result_integrity_blocked"].indexOf(current.status) !== -1
    );
    elements.refreshRunStatus.disabled = !hasRun || state.pending.has("refresh-run-status");
    elements.reconnectCodexRun.disabled = !reconnectable || state.pending.has("reconnect-codex-run");
    elements.importCodexResult.disabled = !importable || state.pending.has("import-codex-result");
    elements.runFallbackNote.textContent = recoveryBlocked
      ? "Source snapshot unavailable. Regenerate Codex Pack; result import and reconnect are not valid for a Run that never launched."
      : hasRun
      ? "Recovery controls target the selected Run for " + current.taskName + ". Structured import is a fallback, not the normal workflow."
      : "Select a Run to use recovery controls. Structured import is a fallback, not the normal workflow.";
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

  function ownerSafeText(value, fallback, maximum) {
    let text = boundedText(value, fallback || "Not available", maximum || 600);
    text = text
      .replace(/([a-z][a-z0-9+.-]*:\/\/)[^/\s:@]+:[^/\s@]+@/gi, "$1[credentials hidden]@")
      .replace(/\bfile:\/\/[^\s,;'"<>]+/gi, "[host file URI hidden]")
      .replace(/(^|[\s("'=])\/(?:Users|home|private|tmp|var|opt|Volumes|root|srv|mnt|workspace|Applications|Library)\/[^\s"'<>]*/g, "$1[host path hidden]")
      .replace(/(^|[\s("'=])[A-Za-z]:\\[^\s"'<>]*/g, "$1[host path hidden]")
      .replace(/\b(password|passwd|token|secret|api[_-]?key)\s*[:=]\s*[^\s,;]+/gi, "$1=[hidden]");
    return text;
  }

  function repositoryRelativePath(value) {
    const path = String(value || "").trim().replace(/\\/g, "/");
    if (
      !path
      || path.charAt(0) === "/"
      || /^[A-Za-z]:\//.test(path)
      || path.split("/").some(function (part) { return !part || part === "." || part === ".."; })
    ) return "File path withheld";
    return boundedText(path, "File path withheld", 360);
  }

  function formatDuration(value, startedAt, finishedAt) {
    let seconds = value === null || value === undefined || value === ""
      ? Number.NaN
      : Number(value);
    if (!Number.isFinite(seconds) && startedAt && finishedAt) {
      const start = new Date(startedAt).getTime();
      const finish = new Date(finishedAt).getTime();
      if (Number.isFinite(start) && Number.isFinite(finish) && finish >= start) {
        seconds = (finish - start) / 1000;
      }
    }
    if (!Number.isFinite(seconds) || seconds < 0) return "Not available";
    if (seconds < 60) return Math.round(seconds) + " sec";
    const minutes = Math.floor(seconds / 60);
    const remaining = Math.round(seconds % 60);
    return minutes + " min " + remaining + " sec";
  }

  function ownerSafeList(value, emptyText) {
    const items = Array.isArray(value) ? value : [];
    return items.map(function (item) {
      const record = objectRecord(item);
      return ownerSafeText(
        record.summary
        || record.safe_summary
        || record.message
        || record.label
        || record.status
        || record.verdict
        || record.path
        || item,
        emptyText,
        500
      );
    }).filter(Boolean);
  }

  function ownerSafeSummary(value, fallback, maximum) {
    if (Array.isArray(value)) {
      const items = ownerSafeList(value, fallback);
      return items.length ? items.join(" · ") : fallback;
    }
    if (value && typeof value === "object") {
      const record = objectRecord(value);
      const concise = record.summary
        || record.safe_summary
        || record.message
        || record.status
        || record.verdict
        || record.result
        || record.outcome;
      if (concise) return ownerSafeText(concise, fallback, maximum || 500);
      const safeFacts = Object.keys(record).filter(function (key) {
        return !/(^id$|_id$|digest|identity|path|command|environment|token|secret)/i.test(key)
          && ["string", "number", "boolean"].indexOf(typeof record[key]) !== -1;
      }).map(function (key) {
        return humanStatus(key) + ": " + ownerSafeText(record[key], "Not available", 160);
      });
      return safeFacts.length
        ? boundedText(safeFacts.join(" · "), fallback, maximum || 500)
        : fallback;
    }
    return ownerSafeText(value, fallback, maximum || 500);
  }

  function ownerWorkflowText(value, fallback, maximum) {
    const text = ownerSafeText(value, fallback, maximum);
    if (
      /app[- ]server/i.test(text)
      || /server notification|notification method/i.test(text)
      || /APP_SERVER_[A-Z_]+|UNKNOWN_(?:NONCRITICAL|CRITICAL)_NOTIFICATION/.test(text)
    ) {
      return "Codex CLI compatibility details are available under Advanced.";
    }
    return text;
  }

  function ownerWorkflowSummary(value, fallback, maximum) {
    return ownerWorkflowText(
      ownerSafeSummary(value, fallback, maximum),
      fallback,
      maximum
    );
  }

  function runLocalEffectiveModelView(record, monitor, envelope) {
    const sources = [
      {
        available: record.actual_model_verified === true,
        value: record.actual_model
      },
      {
        available: monitor.actual_model_verified === true,
        value: monitor.actual_model
      },
      {
        available: envelope.effective_model_available === true,
        value: envelope.effective_model
      },
      {
        available: envelope.actual_model_verified === true,
        value: envelope.actual_model
      }
    ];
    const verified = sources.find(function (source) {
      return source.available && typeof source.value === "string" && source.value.trim();
    });
    return {
      available: Boolean(verified),
      display: verified
        ? ownerSafeText(verified.value, RUN_LOCAL_MODEL_NOT_EXPOSED, 160)
        : RUN_LOCAL_MODEL_NOT_EXPOSED
    };
  }

  function requestedModelAcceptanceView(record, coding, status) {
    const accepted = record.requested_model_accepted === true
      || coding.requested_model_accepted === true;
    return {
      accepted: accepted,
      display: accepted
        ? "Yes — confirmed by Run evidence"
        : lifecycleIsActive(status)
          ? "Pending Run evidence"
          : "Not confirmed by Run evidence"
    };
  }

  function activityView(item) {
    const record = objectRecord(item);
    const lifecycle = lifecycleRecordForActivity(record);
    const monitor = objectRecord(record.monitor);
    const run = objectRecord(record.run);
    const envelope = resultEnvelopeRecord(
      record.result_envelope || record.resultEnvelope || record.envelope
    );
    const terminalTruth = objectRecord(record.terminal_truth || record.terminalTruth);
    const terminalReview = objectRecord(terminalTruth.owner_review);
    const tests = record.tests_summary || record.tests || envelope.tests_summary || envelope.tests;
    const verification = objectRecord(
      record.verification_result || envelope.verification_evidence || envelope.verification_verdict
    );
    const coding = objectRecord(
      record.coding_result || envelope.coding_result || envelope.coding_evidence
    );
    const actions = objectRecord(record.actions);
    const startedAt = lifecycle.started_at || record.started_at || monitor.started_at || run.started_at;
    const finishedAt = lifecycle.terminal_at || record.finished_at || monitor.terminal_at || run.finished_at;
    const monitorState = String(
      lifecycle.state || record.monitor_state || monitor.monitor_state || record.status || run.status || "queued"
    ).toLowerCase();
    const integrity = String(
      lifecycle.result_integrity
      || record.result_integrity
      || envelope.integrity_state
      || record.integrity_state
      || "pending"
    ).toLowerCase();
    const runId = record.run_id || monitor.run_id || run.id || envelope.run_id;
    const taskId = record.task_id || monitor.task_id || run.task_id || envelope.task_id;
    const effectiveModel = runLocalEffectiveModelView(record, monitor, envelope);
    const requestedAcceptance = requestedModelAcceptanceView(
      Object.assign({}, envelope, record),
      coding,
      monitorState
    );
    let testsSummary;
    if (Array.isArray(tests)) {
      testsSummary = tests.length
        ? tests.map(function (test) {
            const testRecord = objectRecord(test);
            return ownerSafeText(
              testRecord.summary || testRecord.status || testRecord.command_label || test,
              "Test recorded",
              120
            );
          }).join(" · ")
        : "No tests reported";
    } else {
      testsSummary = ownerSafeText(
        objectRecord(tests).summary || tests,
        "No tests reported",
        220
      );
    }
    return {
      raw: record,
      terminalTruth: terminalTruth,
      primaryStatus: terminalTruth.primary_status || monitorState,
      primaryLabel: terminalTruth.primary_label || humanStatus(monitorState),
      lifecycle: lifecycle,
      lifecycleAvailable: Object.keys(lifecycle).length > 0,
      lifecycleActive: Object.keys(lifecycle).length > 0 && lifecycleIsActive(monitorState),
      runId: runId,
      taskId: taskId,
      taskName: ownerSafeText(
        record.task_name || record.task_title || run.task_name || run.development_task,
        "Untitled Development task",
        1000
      ),
      status: monitorState,
      requestedModel: ownerSafeText(
        record.requested_model || monitor.requested_model || envelope.requested_model,
        "Not recorded",
        160
      ),
      requestedModelAccepted: requestedAcceptance.display,
      requestedModelAcceptedConfirmed: requestedAcceptance.accepted,
      runLocalEffectiveModel: effectiveModel.display,
      runLocalEffectiveModelAvailable: effectiveModel.available,
      startedAt: startedAt,
      finishedAt: finishedAt,
      duration: lifecycle.elapsed_ms !== null && lifecycle.elapsed_ms !== undefined
        ? formatLifecycleDuration(lifecycle.elapsed_ms)
        : formatDuration(
            record.duration_seconds !== null && record.duration_seconds !== undefined
              ? record.duration_seconds
              : record.duration_ms !== null && record.duration_ms !== undefined
                ? Number(record.duration_ms) / 1000
                : envelope.execution_duration_seconds !== null && envelope.execution_duration_seconds !== undefined
                  ? envelope.execution_duration_seconds
                  : envelope.duration_ms !== null && envelope.duration_ms !== undefined
                    ? Number(envelope.duration_ms) / 1000
                    : envelope.execution_duration,
            startedAt,
            finishedAt
          ),
      coding: ownerWorkflowText(
        terminalTruth.coding && terminalTruth.coding.status
          || record.coding_summary || coding.safe_summary || coding.summary || coding.status || envelope.coding_result,
        "Not available",
        220
      ),
      verification: ownerWorkflowText(
        terminalTruth.verification && terminalTruth.verification.status
          || record.verification_summary || verification.summary || verification.verdict || verification.status,
        "Not available",
        220
      ),
      tests: testsSummary,
      integrity: integrity,
      nextAction: ownerWorkflowText(
        terminalReview.next_action || lifecycle.next_action || record.next_action || actions.next_action || envelope.next_action,
        RESULT_AVAILABLE_STATUSES.indexOf(monitorState) !== -1
          ? "Open Run Result and Review Handoff."
          : lifecycleIsActive(monitorState)
            ? "TWOS is monitoring this Run."
            : "Review the persisted Run state.",
        300
      ),
      canReconnect: actions.can_reconnect === true,
      canImport: actions.can_import === true,
      recoveryBlocked: actions.recovery_blocked === true,
      envelope: envelope
    };
  }

  function currentRunActivity() {
    const run = currentCodexRun();
    const runId = run ? run.id : state.selectedActivityRunId;
    const matchingRun = state.runActivity.map(activityView).find(function (item) {
      return runId !== null && runId !== undefined && String(item.runId) === String(runId);
    });
    if (matchingRun) return matchingRun;
    const task = selectedTask();
    return state.runActivity.map(activityView).find(function (item) {
      return task && String(item.taskId) === String(task.id);
    }) || null;
  }

  function activityNeedsBrowserObservation(activity) {
    if (!activity) return false;
    if (lifecycleIsActive(activity.status)) return true;
    return ["completed", "failed", "cancelled", "timed_out"].indexOf(activity.status) !== -1
      && !resultEnvelopeIsValid(activity.envelope)
      && !/blocked|invalid|unavailable/.test(activity.integrity);
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
        : RUN_LOCAL_MODEL_NOT_EXPOSED,
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
    const blockerCode = String(blocker && blocker.code || "");
    const runStatus = run ? authoritativeRunStatus(run) : "";
    const runLifecycle = lifecycleForRun(run);
    const active = Boolean(run && lifecycleIsActive(runStatus));
    const terminal = Boolean(run && isTerminalCodexRun(run));
    const terminalBlocked = terminal && activityResultIsBlocked({
      status: runStatus,
      integrity: runLifecycle.result_integrity || "",
      lifecycleAvailable: Object.keys(runLifecycle).length > 0
    });
    if (
      elements.startCodexConfirmationDialog.open
      && (!state.runConfirmationContext
        || !pack
        || eligibility && eligibility.eligible !== true
        || String(state.runConfirmationContext.pack_id) !== String(pack.id)
        || String(state.runConfirmationContext.pack_version) !== String(pack.version))
    ) {
      elements.startCodexConfirmationDialog.close();
      state.runConfirmationContext = null;
    }
    let status;
    let reason;
    let nextAction;
    if (eligibility) {
      status = eligibility.eligible
        ? "Ready for real Run"
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
      const connectivity = objectRecord(objectRecord(detection).connectivity);
      const ready = detection && detection.execution_ready === true
        && connectivity.ready_for_real_run === true;
      status = ready ? "Ready for real Run" : connectivityStateLabel(connectivity.readiness_state);
      reason = detection && detection.readiness_reason
        ? detection.readiness_reason
        : boundedText(connectivity.blocker, "Checking the supported local command.", 500);
      nextAction = ready ? "Run Codex" : "Verify Codex Connection";
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
    if (!active && terminal && blockerCode === "ACTIVE_RUN_EXISTS") {
      status = "Recheck required";
      reason = "The current Run is terminal. Refresh readiness before starting a new Run.";
    }
    const lifecycleNextAction = runLifecycle.next_action
      ? ownerWorkflowText(runLifecycle.next_action, "Review blocker evidence", 300)
      : "";
    const displayedNextAction = active
      ? "Wait for completion or select Cancel Run."
      : terminal && lifecycleNextAction
        ? lifecycleNextAction
        : terminalBlocked
          ? "Review blocker evidence"
          : nextAction;
    elements.codexReadiness.textContent = status;
    elements.runPackVersion.textContent = pack
      ? "Pack #" + pack.id + " · v" + pack.version + " · "
        + (pack.approved ? "Approved" : humanStatus(pack.status))
      : "No approved Pack";
    elements.codexReason.textContent = reason;
    const runTerminalTruth = objectRecord(run && (run.terminal_truth || run.terminalTruth));
    elements.runStatus.textContent = run
      ? active
        ? humanStatus(run.canonical_status || runStatus)
        : runTerminalTruth.primary_label || humanStatus(run.canonical_status || runStatus)
      : "Not started";
    elements.codexNextAction.textContent = displayedNextAction;
    elements.codingSetupReason.textContent = reason + " Next Owner action: " + displayedNextAction + ".";
    const configured = Boolean(
      detection && detection.configuration_status === "configured"
      || coding && coding.assignedModel
      || verification && verification.assignedModel
    );
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
    elements.worktreePath.textContent = run && run.worktree_path
      ? "Isolated runtime workspace (host path withheld)"
      : "None";
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

  function setSetupPrimaryAction(availabilityVerified, connectionReady) {
    elements.checkCodexAvailability.classList.remove("button-primary");
    elements.checkCodexAvailability.classList.add("button-secondary");
    elements.verifyCodexConnection.classList.toggle("button-primary", !connectionReady);
    elements.verifyCodexConnection.classList.toggle("button-secondary", connectionReady);
    elements.saveAssignCodex.classList.toggle("button-primary", availabilityVerified && connectionReady);
    elements.saveAssignCodex.classList.toggle("button-secondary", !(availabilityVerified && connectionReady));
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

  function connectivityForSetup(draft) {
    const setup = objectRecord(draft && draft.setup);
    const direct = objectRecord(setup.connectivity);
    const selected = canonicalModelIdentifier(objectRecord(draft && draft.selectedEntry));
    if (
      Object.keys(direct).length
      && (!selected || !direct.requested_model || direct.requested_model === selected)
    ) return direct;
    const global = objectRecord(objectRecord(state.codexStatus).connectivity);
    if (!selected || !global.requested_model || global.requested_model === selected) return global;
    return {
      cli_installed: direct.cli_installed !== undefined ? direct.cli_installed : global.cli_installed,
      cli_version: direct.cli_version || global.cli_version,
      authentication: direct.authentication || global.authentication,
      requested_model: selected,
      readiness_state: "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED",
      ready_for_real_run: false,
      provider_reachable: false,
      model_available: false,
      resolved_model: null,
      actual_model: null,
      last_connectivity_check: null,
      blocker: "This selected model has not been verified by the Owner.",
      configured_run_timeout_seconds: direct.configured_run_timeout_seconds
        || global.configured_run_timeout_seconds,
      advanced: { diagnostics: { provider_probe_performed: false } }
    };
  }

  function connectivityStateLabel(value) {
    const labels = {
      CLI_NOT_INSTALLED: "CLI not installed",
      AUTHENTICATION_REQUIRED: "Authentication required",
      AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED: "Authenticated — connectivity not verified",
      PROTOCOL_COMPATIBILITY_BLOCKED: "Protocol compatibility blocked",
      PROVIDER_UNREACHABLE: "Provider unreachable",
      MODEL_UNAVAILABLE: "Model unavailable",
      READY_FOR_REAL_RUN: "Ready for real Run",
      BLOCKED: "Blocked"
    };
    return labels[String(value || "")] || "Connectivity not verified";
  }

  function connectivityBoolean(value, trueLabel, falseLabel, pendingLabel) {
    if (value === true) return trueLabel;
    if (value === false) return falseLabel;
    return pendingLabel;
  }

  function renderSetupConnectivity(draft) {
    const connectivity = connectivityForSetup(draft);
    const authentication = objectRecord(connectivity.authentication);
    const advanced = objectRecord(connectivity.advanced);
    const diagnostics = objectRecord(advanced.diagnostics);
    const requested = connectivity.requested_model
      || canonicalModelIdentifier(objectRecord(draft && draft.selectedEntry));
    const hasEvidence = Boolean(connectivity.evidence_id || connectivity.last_connectivity_check);
    const readinessState = connectivity.readiness_state || "AUTHENTICATED_CONNECTIVITY_NOT_VERIFIED";
    const runTimeout = connectivity.configured_run_timeout_seconds
      || objectRecord(state.codexStatus).configured_run_timeout_seconds;

    elements.setupCliInstalled.textContent = connectivityBoolean(
      connectivity.cli_installed,
      "Installed",
      "Not installed",
      "Not reported"
    );
    elements.setupCliVersion.textContent = boundedText(connectivity.cli_version, "Not reported", 120);
    elements.setupAuthMethod.textContent = boundedText(authentication.method, "Unknown", 120);
    elements.setupAuthStatus.textContent = authentication.authenticated === true
      ? "Authenticated"
      : authentication.state === "AUTHENTICATION_REQUIRED"
        ? "Authentication required"
        : humanStatus(authentication.state || "unknown");
    elements.setupCredentialStatus.textContent = authentication.credential_store_accessible === true
      ? "Accessible · " + boundedText(authentication.credential_store, "storage type withheld", 80)
      : authentication.credential_store_accessible === false
        ? "Unavailable or not verified · values withheld"
        : "Not verified · values withheld";
    elements.setupProviderConnectivity.textContent = hasEvidence
      ? connectivityBoolean(connectivity.provider_reachable, "Reachable", "Unreachable", "Not verified")
      : "Not verified";
    elements.setupRequestedModel.textContent = boundedText(requested, "Select a model", 240);
    elements.setupActualModel.textContent = boundedText(
      connectivity.resolved_model || connectivity.actual_model,
      readinessState === "READY_FOR_REAL_RUN"
        ? RUN_LOCAL_MODEL_NOT_EXPOSED
        : "Not verified",
      240
    );
    elements.setupConnectivityCheckedAt.textContent = connectivity.last_connectivity_check
      ? formatTime(connectivity.last_connectivity_check)
      : "Never";
    elements.setupRunTimeout.textContent = Number.isFinite(Number(runTimeout)) && Number(runTimeout) > 0
      ? String(Number(runTimeout)) + " seconds"
      : "Not reported";
    elements.setupConnectivityState.textContent = connectivityStateLabel(readinessState);
    setStatusLabel(elements.setupConnectivityState, elements.setupConnectivityState.textContent);

    let blocker = ownerWorkflowText(
      connectivity.blocker || connectivity.safe_summary,
      "Select a model, then explicitly verify its real Codex connection.",
      600
    );
    if (authentication.state === "AUTHENTICATION_REQUIRED") {
      blocker = "Use the native Codex CLI login flow (`codex login`), then return and select Verify Codex Connection.";
    }
    if (readinessState === "PROTOCOL_COMPATIBILITY_BLOCKED") {
      blocker = "The installed Codex CLI is not compatible with this TWOS runtime. Open Advanced for technical details.";
    }
    const connectivityNextAction = ownerWorkflowText(
      connectivity.next_action,
      readinessState === "READY_FOR_REAL_RUN"
        ? "Run Codex"
        : "Resolve the blocker, then explicitly verify the connection again.",
      240
    );
    elements.setupConnectivityBlocker.textContent = blocker
      + " Next Owner action: " + connectivityNextAction;
    elements.setupConnectivityCommand.textContent = boundedText(
      advanced.sanitized_command,
      "Not run",
      500
    );
    elements.setupConnectivityExitCode.textContent = connectivity.exit_code === null
      || connectivity.exit_code === undefined
      ? "Not run"
      : String(connectivity.exit_code);
    elements.setupConnectivityDuration.textContent = connectivity.duration_ms === null
      || connectivity.duration_ms === undefined
      ? "Not run"
      : formatDuration(Number(connectivity.duration_ms) / 1000);
    const protocolSchema = objectRecord(diagnostics.protocol_schema);
    const protocolTranscript = Array.isArray(diagnostics.protocol_transcript)
      ? diagnostics.protocol_transcript
      : [];
    const criticalMethod = boundedText(diagnostics.critical_protocol_method, "", 240);
    const criticalEntry = protocolTranscript.find(function (entry) {
      return criticalMethod && objectRecord(entry).method === criticalMethod;
    }) || protocolTranscript[protocolTranscript.length - 1];
    const safeProtocolDetails = [
      criticalMethod ? "Safe method: " + criticalMethod : "",
      protocolSchema.cli_version ? "Schema CLI: " + boundedText(protocolSchema.cli_version, "", 120) : "",
      protocolSchema.schema_digest ? "Schema digest: " + boundedText(protocolSchema.schema_digest, "", 80) : "",
      criticalEntry && criticalEntry.sequence ? "Message sequence: " + String(criticalEntry.sequence) : "",
      criticalEntry && criticalEntry.payload_shape
        ? "Payload shape: " + JSON.stringify(criticalEntry.payload_shape)
        : ""
    ].filter(Boolean).join(" · ");
    elements.setupConnectivityDiagnostics.textContent = ownerSafeText(
      safeProtocolDetails || diagnostics.output_summary || connectivity.safe_summary,
      hasEvidence
        ? "No additional sanitized diagnostic was returned."
        : "No Provider probe has been run for this Owner and model.",
      1800
    );
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
    const connectivity = connectivityForSetup(draft);
    const connectionReady = Boolean(
      connectivity.readiness_state === "READY_FOR_REAL_RUN"
      && connectivity.ready_for_real_run === true
      && connectivity.requested_model === identifier
    );
    const selectable = entry.selectable === true && Boolean(identifier);
    const hasOptions = Boolean(
      draft && (draft.models.length || objectRecord(draft.selectedEntry).preserved_legacy)
    );
    elements.setupModelSearch.disabled = !hasOptions;
    elements.checkCodexAvailability.disabled = !selectable || state.pending.has("check-codex-availability");
    elements.verifyCodexConnection.disabled = !selectable || state.pending.has("verify-codex-connection");
    elements.saveAssignCodex.disabled = !verified || !connectionReady || state.pending.has("save-assign-codex");
    setSetupPrimaryAction(verified, connectionReady);

    if (entry.preserved_legacy) {
      elements.setupAvailabilityStatus.textContent = "Existing legacy/custom model — review required. The stored assignment is preserved; choose a supported catalog model to change it.";
    } else if (verified && connectionReady) {
      const effectiveModel = connectivity.resolved_model || connectivity.actual_model;
      elements.setupAvailabilityStatus.textContent = "CLI, authentication, Provider connectivity, and requested-model execution are ready for "
        + capabilityLabel(draft.capability) + ". Run-local effective model: "
        + ownerSafeText(effectiveModel, RUN_LOCAL_MODEL_NOT_EXPOSED, 240)
        + " — checked " + formatTime(evidence.checked_at) + ".";
    } else if (selectable && evidence.result) {
      elements.setupAvailabilityStatus.textContent = humanStatus(evidence.result) + " for "
        + capabilityLabel(draft.capability) + " — checked " + formatTime(evidence.checked_at) + ".";
    } else if (selectable) {
      elements.setupAvailabilityStatus.textContent = "Setup prerequisite check required. This does not verify Provider connectivity or model availability.";
    } else if (draft && draft.filtering && String(draft.query || "").trim()) {
      elements.setupAvailabilityStatus.textContent = "Select a supported model from the filtered options before checking availability.";
    } else {
      elements.setupAvailabilityStatus.textContent = "Select a supported model, check CLI and authentication, then explicitly Verify Codex Connection.";
    }
    renderSetupConnectivity(draft);
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
    if (state.firstRun && state.firstRun.enabled === true) return openGuidedToolSetup();
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
    elements.verifyCodexConnection.disabled = true;
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
        capability: capability,
        connectivity: objectRecord(draft.setup).connectivity
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
      return result.execution_prerequisites_available
        ? "Local Codex CLI and authentication prerequisites are available for "
          + capabilityLabel(capability)
          + ". Provider connectivity and model availability remain unverified until the Owner selects Verify Codex Connection."
        : "Local Codex CLI or authentication prerequisites remain unavailable for "
          + capabilityLabel(capability) + ".";
    });
    if (state.auth === AUTH_STATES.SIGNED_IN && elements.codexSetupDialog.open && activeSetupDraft()) {
      renderCodexSetup(activeSetupDraft(), normalizedSetupCapability(elements.setupCapability.value));
    }
  }

  async function verifyCodexConnection() {
    const capability = normalizedSetupCapability(elements.setupCapability.value);
    const draft = state.codexSetupDrafts[capability];
    const selectedEntry = objectRecord(draft && draft.selectedEntry);
    const selectedIdentifier = canonicalModelIdentifier(selectedEntry);
    if (!draft || selectedEntry.selectable !== true || !selectedIdentifier) {
      setModelFieldError("Select a supported model before verifying the real Codex connection.");
      elements.setupConnectivityBlocker.textContent = "Connection verification is blocked until a supported model is selected.";
      elements.setupModelSearch.focus();
      return;
    }
    await performAction(
      "verify-codex-connection",
      elements.verifyCodexConnection,
      "Verifying connection…",
      async function () {
        const result = await api("/api/codex/setup/verify-connection", {
          method: "POST",
          body: {
            model_identifier: selectedIdentifier,
            capability: capability
          }
        });
        if (result.requested_model && result.requested_model !== selectedIdentifier) {
          throw new ApiError(
            409,
            "CONNECTIVITY_MODEL_MISMATCH",
            "The connection evidence did not match the selected model.",
            {},
            "product"
          );
        }
        const configuration = objectRecord(result.configuration);
        const checkedAt = result.last_connectivity_check || new Date().toISOString();
        draft.setup = Object.assign({}, objectRecord(draft.setup), {
          configuration: Object.keys(configuration).length
            ? configuration
            : objectRecord(draft.setup).configuration,
          availability_evidence: {
            configuration_identity: configuration.stable_id || configuration.configuration_identity || "",
            adapter: "codex_cli",
            invocation_mode: "real",
            checked_at: checkedAt,
            result: result.ready_for_real_run === true ? "available" : "unavailable",
            evidence_type: "owner_triggered_connectivity_probe",
            failure_classification: result.blocker_code || "",
            runtime_identity: result.cli_version || ""
          },
          connectivity: result,
          capability: capability
        });
        draft.checkedConfiguration = Object.keys(configuration).length
          ? configuration
          : objectRecord(draft.setup).configuration;
        draft.checkedEvidence = draft.setup.availability_evidence;
        draft.checkedModels.set(selectedIdentifier, {
          configuration: draft.checkedConfiguration,
          evidence: draft.checkedEvidence
        });
        renderCodexSetup(draft, capability);
        if (result.ready_for_real_run === true) {
          const effectiveModel = result.resolved_model || result.actual_model;
          return "Codex connection verified. Authentication passed, the Provider responded, and requested model “"
            + ownerSafeText(selectedIdentifier, "Unknown", 160) + "” was accepted. Run-local effective model: "
            + ownerSafeText(effectiveModel, RUN_LOCAL_MODEL_NOT_EXPOSED, 160) + ".";
        }
        const publicBlocker = result.readiness_state === "PROTOCOL_COMPATIBILITY_BLOCKED"
          ? "The installed Codex CLI is not compatible with this TWOS runtime. Open Advanced for technical details."
          : ownerWorkflowText(
              result.blocker || result.safe_summary,
              "Review the connection blocker.",
              500
            );
        throw new ApiError(
          409,
          result.blocker_code || result.readiness_state || "CODEX_CONNECTION_BLOCKED",
          connectivityStateLabel(result.readiness_state)
            + ". "
            + publicBlocker,
          {},
          "product"
        );
      }
    );
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
    if (typeof item === "string") return repositoryRelativePath(item);
    return repositoryRelativePath(
      objectRecord(item).path || objectRecord(item).repository_relative_path
    );
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
    if (status === "running" || status === "coding") return "running";
    if (["verifying", "settling", "result_pending", "completed", "result_available"].indexOf(status) !== -1) return "completed";
    if (status === "failed" && Number(run.exit_code) === 0) return "completed";
    return status;
  }

  function resultReviewText(status) {
    const normalized = String(status || "");
    if (lifecycleIsActive(normalized)) {
      return "Execution is active. Review the persisted stage evidence as it advances.";
    }
    if (["failed", "blocked", "timed_out", "cancelled"].indexOf(normalized) !== -1) {
      return normalized === "timed_out"
        ? "Review Handoff is BLOCKED: no verified actual model, Verification, or accepted source result exists."
        : "Review the failed process, invocation, or acceptance checks below.";
    }
    return state.ownerAcceptance
      ? "Complete the Owner Acceptance checklist."
      : "Inspect the structured result evidence before making an Owner decision.";
  }

  function sanitizedCandidateText(value, fallback, maximum) {
    let text = boundedText(value, fallback, maximum);
    text = text.replace(
      /([a-z][a-z0-9+.-]*:\/\/)([^/\s:@]+):([^@\s/]+)@/gi,
      "$1[credentials withheld]@"
    );
    text = text.replace(
      /((?:[A-Z0-9_]*(?:TOKEN|PASSWORD|SECRET|CREDENTIAL|AUTHORIZATION|API[_-]?KEY)[A-Z0-9_]*)["']?\s*[:=]\s*["']?)[^\s,"'}\]]+/gi,
      "$1[withheld]"
    );
    text = text.replace(
      /(^|[\s"'(=])\/(?:Users|home|private|tmp|var\/folders)\/[^\s"',)}\]]+/gm,
      "$1[path withheld]"
    );
    return text.replace(
      /[A-Za-z]:\\(?:Users|Documents and Settings)\\[^\s"',)}\]]+/g,
      "[path withheld]"
    );
  }

  function candidateRelativePath(value) {
    const path = boundedText(value, "", 500);
    if (
      !path
      || path.charAt(0) === "/"
      || path.charAt(0) === "\\"
      || /^[A-Za-z]:[\\/]/.test(path)
      || path.split(/[\\/]/).some(function (part) { return part === ".."; })
    ) return "[unsafe path withheld]";
    return path;
  }

  function candidateFileName(entry) {
    const record = objectRecord(entry);
    const suppliedName = boundedText(record.name, "", 300);
    const source = suppliedName || candidateRelativePath(record.path);
    const parts = source.split(/[\\/]/);
    return boundedText(parts[parts.length - 1], "Unnamed file", 300);
  }

  function candidateOperation(value) {
    const operation = String(value || "").toUpperCase();
    return ["CREATE", "MODIFY", "DELETE"].indexOf(operation) !== -1 ? operation : "UNKNOWN";
  }

  function renderCandidateFiles(candidate, reviewed) {
    clearChildren(elements.candidateFiles);
    const files = candidate && Array.isArray(candidate.changed_files)
      ? candidate.changed_files
      : [];
    if (!files.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = candidate
        ? "This immutable Candidate contains no changed files."
        : reviewed
          ? "No immutable Candidate manifest is available."
          : "Review Change Candidate to inspect the Run-produced file manifest.";
      elements.candidateFiles.appendChild(empty);
      return;
    }
    files.forEach(function (file) {
      const record = objectRecord(file);
      const operation = candidateOperation(record.operation);
      const item = document.createElement("article");
      const heading = document.createElement("div");
      const name = document.createElement("strong");
      const operationLabel = document.createElement("span");
      const metadata = document.createElement("p");
      item.className = "candidate-file-item";
      item.dataset.operation = operation.toLowerCase();
      heading.className = "candidate-file-heading";
      name.textContent = candidateFileName(record);
      operationLabel.className = "candidate-operation";
      operationLabel.textContent = operation;
      metadata.textContent = record.unexpected === true
        ? "Unexpected Run-produced file"
        : String(record.content_kind || "").toLowerCase() === "binary"
          ? "Binary file · metadata only"
          : "Expected Run-produced file";
      heading.appendChild(name);
      heading.appendChild(operationLabel);
      item.appendChild(heading);
      item.appendChild(metadata);
      elements.candidateFiles.appendChild(item);
    });
  }

  function candidateBlockerLines(review, drift) {
    const combined = (Array.isArray(review && review.blockers) ? review.blockers : [])
      .concat(Array.isArray(drift && drift.blockers) ? drift.blockers : []);
    const seen = new Set();
    return combined.map(function (blocker) {
      const record = objectRecord(blocker);
      const code = boundedText(record.code, "", 100);
      const message = sanitizedCandidateText(record.message, "Candidate review is blocked.", 600);
      return (code ? code + " — " : "") + message;
    }).filter(function (line) {
      if (!line || seen.has(line)) return false;
      seen.add(line);
      return true;
    });
  }

  function candidateBindingText(label, id, version) {
    if (id === null || id === undefined || id === "") return "None";
    const versionText = version === null || version === undefined || version === ""
      ? ""
      : " / v" + String(version);
    return label + " #" + String(id) + versionText;
  }

  function candidateManifestDetailLines(candidate) {
    const files = candidate && Array.isArray(candidate.changed_files)
      ? candidate.changed_files
      : [];
    return files.map(function (file) {
      const record = objectRecord(file);
      const beforeSize = record.before_size === null || record.before_size === undefined
        ? "none"
        : String(record.before_size);
      const afterSize = record.after_size === null || record.after_size === undefined
        ? "none"
        : String(record.after_size);
      return candidateRelativePath(record.path)
        + " · " + candidateOperation(record.operation)
        + " · before=" + boundedText(record.before_hash, "none", 200)
        + " · after=" + boundedText(record.after_hash, "none", 200)
        + " · size=" + beforeSize + "→" + afterSize
        + " · kind=" + boundedText(record.content_kind, "unknown", 80)
        + " · evidence=" + boundedText(record.evidence_identity, "none", 240)
        + (record.unexpected === true ? " · unexpected" : "");
    });
  }

  function candidateVerificationFallback(run) {
    const result = objectRecord(run && run.result);
    const verdict = objectRecord(result.verification_verdict);
    return boundedText(verdict.status, "Not available", 120);
  }

  function setCandidateStatusLabel(element, value) {
    setStatusLabel(element, value);
    const normalized = String(value || "").toLowerCase();
    if (normalized.indexOf("conflict detected") !== -1) {
      element.classList.remove("is-success", "is-warning");
      element.classList.add("is-error");
    } else if (normalized.indexOf("source changed since run") !== -1) {
      element.classList.remove("is-success", "is-error");
      element.classList.add("is-warning");
    }
  }

  function renderDeliveryCandidateReview(run) {
    const terminal = isTerminalCodexRun(run);
    elements.candidateReviewSection.hidden = !terminal;
    elements.candidateAdvancedCard.hidden = !terminal;
    if (!terminal) return;

    const review = objectRecord(deliveryCandidateReviewForRun(run));
    const candidate = objectRecord(review.candidate);
    const candidateAdvanced = objectRecord(candidate.advanced);
    const drift = objectRecord(review.drift);
    const available = candidate.id !== null && candidate.id !== undefined;
    const resultDerived = Boolean(
      candidate.derivation_version === "twos.result_delivery_candidate.v1"
      || candidate.result_envelope_id
      || candidateAdvanced.result_digest
    );
    elements.reviewChangeCandidate.hidden = resultDerived || !terminal;
    const blockers = candidateBlockerLines(review, drift);
    const reviewed = available || Object.keys(drift).length > 0 || blockers.length > 0;
    const statusText = available
      ? boundedText(
        candidate.readiness_state
          ? humanStatus(candidate.readiness_state)
          : candidate.status_label || humanStatus(candidate.status || "available"),
        "Available",
        160
      )
      : drift.status_label
        ? boundedText(drift.status_label, "Candidate unavailable", 160)
        : blockers.length
          ? "Candidate unavailable"
          : "Not reviewed";
    const driftText = Object.keys(drift).length
      ? boundedText(drift.status_label || humanStatus(drift.status), "Not evaluated", 160)
      : "Not evaluated";
    const files = available && Array.isArray(candidate.changed_files) ? candidate.changed_files : [];
    const unexpected = files.filter(function (file) { return objectRecord(file).unexpected === true; });
    const unexpectedCount = candidate.unexpected_file_count === null
      || candidate.unexpected_file_count === undefined
      ? unexpected.length
      : Number(candidate.unexpected_file_count);
    const acceptanceStatus = available
      ? candidate.acceptance_status
      : state.ownerAcceptance && state.ownerAcceptance.status;
    const verificationStatus = available
      ? candidate.verification_status
      : candidateVerificationFallback(run);

    elements.candidateStatus.textContent = statusText;
    elements.candidateSourceRun.textContent = available
      ? "Run #" + String(candidate.run_id || run.id)
      : "Not available";
    elements.candidateIncludedCount.textContent = available
      ? String(files.length)
      : "0";
    elements.candidateExcludedCount.textContent = available
      ? String(Number(candidate.excluded_file_count || 0))
      : "0";
    elements.candidateDriftStatus.textContent = driftText;
    setCandidateStatusLabel(elements.candidateStatus, statusText);
    setCandidateStatusLabel(elements.candidateDriftStatus, driftText);
    elements.candidateUnexpectedFiles.textContent = unexpectedCount > 0
      ? String(unexpectedCount) + " — " + unexpected.map(candidateFileName).join(", ")
      : available ? "None" : "Not available";
    elements.candidateAcceptanceStatus.textContent = humanStatus(
      candidate.result_review_state || acceptanceStatus || "not_available"
    );
    elements.candidateVerificationStatus.textContent = humanStatus(verificationStatus || "not_available");
    elements.candidateNextAction.textContent = sanitizedCandidateText(
      review.next_action || drift.next_action,
      "Review Change Candidate",
      300
    );
    renderCandidateFiles(available ? candidate : null, reviewed);
    appendTextList(
      elements.candidateBlockers,
      blockers,
      reviewed ? "No blockers reported." : "No blocker has been evaluated."
    );

    elements.candidateRecordId.textContent = available ? "#" + String(candidate.id) : "None";
    elements.candidateDigest.textContent = boundedText(
      candidateAdvanced.candidate_digest || candidate.candidate_digest,
      "None",
      500
    );
    elements.candidatePatchIdentity.textContent = boundedText(
      candidateAdvanced.patch_identity || candidate.patch_identity,
      "None",
      500
    );
    elements.candidateSourceSnapshot.textContent = boundedText(
      candidateAdvanced.source_snapshot_identity || candidate.source_snapshot_identity,
      "None",
      500
    );
    elements.candidateTaskBinding.textContent = candidateBindingText(
      "Task",
      candidate.task_id,
      candidate.task_version
    );
    elements.candidatePackBinding.textContent = candidateBindingText(
      "Pack",
      candidate.pack_id,
      candidate.pack_version
    );
    elements.candidateCodingAssignment.textContent = candidateBindingText(
      "Assignment",
      candidateAdvanced.coding_assignment_id ?? candidate.coding_assignment_id,
      candidateAdvanced.coding_assignment_version ?? candidate.coding_assignment_version
    );
    elements.candidateVerificationAssignment.textContent = candidateBindingText(
      "Assignment",
      candidateAdvanced.verification_assignment_id ?? candidate.verification_assignment_id,
      candidateAdvanced.verification_assignment_version ?? candidate.verification_assignment_version
    );
    elements.candidateRoutingSnapshot.textContent = boundedText(
      candidateAdvanced.routing_snapshot_identity || candidate.routing_snapshot_identity,
      "None",
      500
    );
    elements.candidateRunBinding.textContent = candidate.run_id === null || candidate.run_id === undefined
      ? "None"
      : "Run #" + String(candidate.run_id);
    elements.candidateCodingEvidence.textContent = boundedText(
      candidateAdvanced.coding_attempt_identity
        || candidateAdvanced.coding_evidence_identity
        || candidate.coding_evidence_identity,
      "None",
      500
    );
    elements.candidateVerificationEvidence.textContent = boundedText(
      candidateAdvanced.verification_receipt_identity
        || candidateAdvanced.verification_evidence_identity
        || candidate.verification_evidence_identity,
      "None",
      500
    );
    elements.candidateCreatedAt.textContent = available ? formatTime(candidate.created_at) : "Not recorded";
    elements.candidateDriftEvaluation.textContent = drift.evaluation_id === null || drift.evaluation_id === undefined
      ? "Not evaluated"
      : "#" + String(drift.evaluation_id) + " / " + formatTime(drift.evaluated_at);
    elements.candidateDriftBaseline.textContent = boundedText(drift.baseline_source_digest, "None", 500);
    elements.candidateDriftCurrent.textContent = boundedText(drift.current_source_digest, "None", 500);
    elements.candidateDriftHead.textContent = boundedText(drift.current_head, "None", 500);
    elements.candidateConflictPaths.textContent = Array.isArray(drift.conflict_paths) && drift.conflict_paths.length
      ? drift.conflict_paths.map(candidateRelativePath).join(", ")
      : "None";
    appendTextList(
      elements.candidateManifestDetails,
      candidateManifestDetailLines(available ? candidate : null),
      "No immutable Candidate manifest is available."
    );
    elements.candidateDriftDiagnostics.textContent = sanitizedCandidateText(
      diagnosticText(drift.diagnostics, ""),
      "No Source Drift diagnostics are available.",
      8000
    );
  }

  function normalizedApplyPlanState(value) {
    const normalized = String(value || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "");
    return Object.prototype.hasOwnProperty.call(APPLY_PLAN_STATE_LABELS, normalized)
      ? normalized
      : "";
  }

  function applyPlanStateLabel(plan) {
    const stateValue = normalizedApplyPlanState(plan.effective_state || plan.status_label);
    return stateValue ? APPLY_PLAN_STATE_LABELS[stateValue] : "Not reviewed";
  }

  function setApplyPlanStatusLabel(element, value) {
    const stateValue = normalizedApplyPlanState(value);
    element.classList.remove("is-success", "is-warning", "is-error");
    element.dataset.planState = stateValue || "not_reviewed";
    if (stateValue === "ready_for_owner_review") {
      element.classList.add("is-success");
    } else if (
      stateValue === "awaiting_owner_approval"
      || stateValue === "review_with_source_changes"
      || stateValue === "expired"
    ) {
      element.classList.add("is-warning");
    } else if (stateValue.indexOf("blocked_by_") === 0) {
      element.classList.add("is-error");
    }
  }

  function applyPlanDisposition(value) {
    const disposition = String(value || "").trim().toUpperCase();
    return APPLY_PLAN_DISPOSITIONS.indexOf(disposition) !== -1
      ? disposition
      : "BLOCKED";
  }

  function applyPlanOperation(value, scopeOnly) {
    if (scopeOnly) return "SCOPE ONLY";
    return candidateOperation(value);
  }

  function sanitizedApplyPlanText(value, fallback, maximum) {
    let text = sanitizedCandidateText(value, fallback, maximum);
    text = text.replace(
      /(^|[\s"'(=])\/(?!\/)[^\s"',)}\]]+/gm,
      "$1[path withheld]"
    );
    return text.replace(
      /\b[A-Za-z]:\\[^\s"',)}\]]+/g,
      "[path withheld]"
    );
  }

  function applyPlanSafeLine(value, fallback, maximum) {
    if (value === null || value === undefined || value === "") return fallback;
    if (typeof value === "string" || typeof value === "number") {
      return sanitizedApplyPlanText(value, fallback, maximum || 800);
    }
    const record = objectRecord(value);
    const direct = firstEvidenceValue(
      record,
      ["message", "reason", "summary", "description", "label", "name", "path", "code"],
      ""
    );
    if (direct) return sanitizedApplyPlanText(direct, fallback, maximum || 800);
    const diagnostic = diagnosticText(record, "");
    return sanitizedApplyPlanText(diagnostic, fallback, maximum || 800);
  }

  function applyPlanTextList(value, fallback) {
    const record = objectRecord(value);
    const nested = Array.isArray(record.requirements)
      ? record.requirements
      : null;
    const items = Array.isArray(value) ? value : nested || (value ? [value] : []);
    return items.map(function (item) {
      return applyPlanSafeLine(item, "", 1200);
    }).filter(Boolean).concat(items.length ? [] : fallback ? [fallback] : []);
  }

  function applyPlanReversibilityLines(value, fallback) {
    if (Array.isArray(value)) return applyPlanTextList(value, fallback);
    const record = objectRecord(value);
    const lines = applyPlanTextList(
      Array.isArray(record.requirements) ? record.requirements : record.capture,
      ""
    );
    if (record.future_reverse_operation) {
      lines.push(
        "Future reverse operation: "
        + sanitizedApplyPlanText(record.future_reverse_operation, "None", 160)
      );
    }
    return lines.length ? lines : fallback ? [fallback] : [];
  }

  function applyPlanFindingLines(value) {
    const items = Array.isArray(value) ? value : [];
    return items.map(function (item) {
      if (typeof item === "string") return candidateRelativePath(item);
      const record = objectRecord(item);
      const rawPath = record.path || record.name;
      const path = rawPath ? candidateRelativePath(rawPath) : "";
      const reason = applyPlanSafeLine(record.reason || record.message, "", 500);
      return path && reason ? path + " — " + reason : path || reason;
    }).filter(Boolean);
  }

  function appendPlannedChecks(target, checks, fallback) {
    clearChildren(target);
    const lines = applyPlanTextList(checks, fallback);
    lines.forEach(function (line) {
      const item = document.createElement("li");
      const label = document.createElement("span");
      label.className = "planned-check-label";
      label.textContent = "PLANNED CHECK";
      item.appendChild(label);
      item.appendChild(document.createTextNode(" " + line));
      target.appendChild(item);
    });
  }

  function applyPlanEntryPath(record) {
    return candidateRelativePath(record.path || record.name);
  }

  function applyPlanEntryTechnicalLine(entry) {
    const record = objectRecord(entry);
    const beforeMode = record.before_mode === null || record.before_mode === undefined
      ? "none"
      : String(record.before_mode);
    const afterMode = record.after_mode === null || record.after_mode === undefined
      ? "none"
      : String(record.after_mode);
    return applyPlanEntryPath(record)
      + " · " + applyPlanOperation(record.operation, false)
      + " · " + applyPlanDisposition(record.disposition)
      + " · before=" + boundedText(record.before_hash, "none", 200)
      + " · after=" + boundedText(record.after_hash, "none", 200)
      + " · mode=" + beforeMode + "→" + afterMode
      + " · kind=" + boundedText(record.content_kind || record.file_type, "unknown", 100);
  }

  function createApplyPlanEntryCard(entry, scopeOnly) {
    const record = objectRecord(entry);
    const disposition = scopeOnly ? "EXCLUDED" : applyPlanDisposition(record.disposition);
    const card = document.createElement("article");
    const heading = document.createElement("div");
    const path = document.createElement("strong");
    const operation = document.createElement("span");
    const reason = document.createElement("p");
    const flags = document.createElement("div");
    const preconditions = applyPlanTextList(record.preconditions, "");
    const reversibility = applyPlanReversibilityLines(record.reversibility, "");

    card.className = "apply-plan-path-card";
    card.dataset.disposition = disposition.toLowerCase();
    heading.className = "apply-plan-path-heading";
    path.textContent = applyPlanEntryPath(record);
    operation.className = "candidate-operation";
    operation.textContent = applyPlanOperation(record.operation, scopeOnly);
    reason.className = "apply-plan-path-reason";
    reason.textContent = applyPlanSafeLine(
      record.reason,
      scopeOnly
        ? "Current source path is outside this Candidate operation scope."
        : "No disposition reason was reported.",
      800
    );
    flags.className = "apply-plan-path-flags";

    if (record.unexpected === true) {
      const unexpected = document.createElement("span");
      unexpected.textContent = "Unexpected";
      flags.appendChild(unexpected);
    }
    if (String(record.content_kind || "").toLowerCase() === "binary") {
      const binary = document.createElement("span");
      binary.textContent = "Binary · metadata only";
      flags.appendChild(binary);
    }
    const conflicts = applyPlanFindingLines(record.conflicts);
    if (conflicts.length) {
      const conflict = document.createElement("span");
      conflict.textContent = "Conflict";
      flags.appendChild(conflict);
    }

    heading.appendChild(path);
    heading.appendChild(operation);
    card.appendChild(heading);
    card.appendChild(reason);
    if (flags.childNodes.length) card.appendChild(flags);

    if (preconditions.length) {
      const title = document.createElement("h5");
      const list = document.createElement("ul");
      title.textContent = "Future preconditions";
      list.className = "apply-plan-path-requirements";
      preconditions.forEach(function (line) {
        const item = document.createElement("li");
        item.textContent = line;
        list.appendChild(item);
      });
      card.appendChild(title);
      card.appendChild(list);
    }
    if (reversibility.length) {
      const title = document.createElement("h5");
      const list = document.createElement("ul");
      title.textContent = "Reversibility evidence";
      list.className = "apply-plan-path-requirements";
      reversibility.forEach(function (line) {
        const item = document.createElement("li");
        item.textContent = line;
        list.appendChild(item);
      });
      card.appendChild(title);
      card.appendChild(list);
    }
    return card;
  }

  function renderApplyPlanPathGroup(target, entries, disposition, reviewed) {
    clearChildren(target);
    if (!entries.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = reviewed
        ? "No " + disposition.toLowerCase() + " paths."
        : "No paths reviewed.";
      target.appendChild(empty);
      return;
    }
    entries.forEach(function (item) {
      target.appendChild(createApplyPlanEntryCard(item.entry, item.scopeOnly));
    });
  }

  function renderApplyPlanPaths(plan, reviewed) {
    const entries = Array.isArray(plan.entries)
      ? plan.entries.filter(function (entry) { return entry && typeof entry === "object"; })
      : [];
    const grouped = {
      INCLUDED: [],
      EXCLUDED: [],
      BLOCKED: []
    };
    entries.forEach(function (entry) {
      const disposition = applyPlanDisposition(entry.disposition);
      grouped[disposition].push({ entry: entry, scopeOnly: false });
    });
    const scopeExclusions = Array.isArray(plan.scope_exclusions) ? plan.scope_exclusions : [];
    scopeExclusions.forEach(function (item) {
      const record = typeof item === "string"
        ? { path: item, reason: "Current source path is outside this Candidate operation scope." }
        : objectRecord(item);
      grouped.EXCLUDED.push({ entry: record, scopeOnly: true });
    });

    elements.applyPlanIncludedCount.textContent = String(grouped.INCLUDED.length);
    elements.applyPlanExcludedCount.textContent = String(grouped.EXCLUDED.length);
    elements.applyPlanBlockedCount.textContent = String(grouped.BLOCKED.length);
    renderApplyPlanPathGroup(elements.applyPlanIncludedPaths, grouped.INCLUDED, "INCLUDED", reviewed);
    renderApplyPlanPathGroup(elements.applyPlanExcludedPaths, grouped.EXCLUDED, "EXCLUDED", reviewed);
    renderApplyPlanPathGroup(elements.applyPlanBlockedPaths, grouped.BLOCKED, "BLOCKED", reviewed);
  }

  function applyPlanBlockerLines(review, plan) {
    const combined = (Array.isArray(review.blockers) ? review.blockers : [])
      .concat(Array.isArray(plan.blockers) ? plan.blockers : []);
    const seen = new Set();
    return combined.map(function (blocker) {
      const record = objectRecord(blocker);
      const code = boundedText(record.code, "", 120);
      const message = applyPlanSafeLine(
        record.message || record.reason,
        "Apply Plan review is blocked.",
        800
      );
      return (code ? code + " — " : "") + message;
    }).filter(function (line) {
      if (!line || seen.has(line)) return false;
      seen.add(line);
      return true;
    });
  }

  function applyPlanNextActionFallback(stateValue) {
    const actions = {
      awaiting_owner_approval: "Explicitly approve this exact Apply Plan.",
      ready_for_owner_review: "Review Apply readiness, then explicitly confirm Apply Accepted Changes.",
      review_with_source_changes: "Review the unrelated source changes before explicitly confirming Apply.",
      blocked_by_conflict: "Resolve the Candidate-path conflict and produce a newly approved Run.",
      blocked_by_candidate: "Restore a valid immutable Candidate before reviewing again.",
      blocked_by_repository: "Restore repository access before reviewing again.",
      expired: "Review Apply Plan again to create a freshly bound Plan."
    };
    return actions[stateValue] || "Review Apply Plan.";
  }

  function renderApplyPlanHistory(review, plan) {
    clearChildren(elements.applyPlanHistory);
    const history = Array.isArray(review.history)
      ? review.history.filter(function (item) { return item && typeof item === "object"; })
      : [];
    const currentId = plan.id === null || plan.id === undefined ? "" : String(plan.id);
    const hasCurrent = history.some(function (item) { return String(item.id) === currentId; });
    if (currentId && !hasCurrent) {
      history.unshift({
        id: plan.id,
        version: plan.version,
        status_label: applyPlanStateLabel(plan),
        created_at: plan.created_at
      });
    }
    if (!history.length) {
      const option = document.createElement("option");
      option.value = "";
      option.textContent = "No persisted Apply Plan";
      elements.applyPlanHistory.appendChild(option);
      elements.applyPlanHistory.disabled = true;
      return;
    }
    history.sort(function (left, right) {
      return Number(right.version || 0) - Number(left.version || 0);
    }).forEach(function (item) {
      const option = document.createElement("option");
      const stateLabel = applyPlanStateLabel(item);
      option.value = String(item.id);
      option.textContent = "Plan v" + String(item.version || "?")
        + " · " + stateLabel
        + " · " + formatTime(item.created_at);
      option.selected = option.value === currentId;
      elements.applyPlanHistory.appendChild(option);
    });
    elements.applyPlanHistory.disabled = state.pending.has("apply-plan-history");
  }

  function applyPlanBindingValue(value, label) {
    if (value === null || value === undefined || value === "") return "None";
    if (typeof value === "number" || /^\d+$/.test(String(value))) {
      return label + " #" + String(value);
    }
    if (typeof value === "string") {
      return sanitizedApplyPlanText(value, "None", 800);
    }
    const record = objectRecord(value);
    const id = record.id === null || record.id === undefined
      ? record.task_id ?? record.pack_id ?? record.run_id
      : record.id;
    const version = record.version ?? record.task_version ?? record.pack_version;
    return candidateBindingText(label, id, version);
  }

  function renderApplyPlanAdvanced(review, plan, reviewed) {
    const advanced = objectRecord(plan.advanced);
    const operationOrder = objectRecord(advanced.operation_order);
    const operationOrderLines = [];
    if (operationOrder.policy) {
      operationOrderLines.push(
        "Policy: " + sanitizedApplyPlanText(operationOrder.policy, "None", 300)
      );
    }
    if (operationOrder.explanation) {
      operationOrderLines.push(
        sanitizedApplyPlanText(operationOrder.explanation, "", 1200)
      );
    }
    if (Array.isArray(operationOrder.operations)) {
      operationOrder.operations.forEach(function (item) {
        const record = objectRecord(item);
        operationOrderLines.push(
          "#" + String(record.ordinal || "?")
          + " · " + applyPlanOperation(record.operation, false)
          + " · " + candidateRelativePath(record.path)
          + (Array.isArray(record.dependencies) && record.dependencies.length
            ? " · dependencies=" + record.dependencies.join(",")
            : "")
        );
      });
    }
    renderApplyPlanHistory(review, plan);
    elements.applyPlanRecordId.textContent = plan.id === null || plan.id === undefined
      ? "None"
      : "#" + String(plan.id);
    elements.applyPlanVersion.textContent = plan.version === null || plan.version === undefined
      ? "None"
      : "v" + String(plan.version);
    elements.applyPlanStatusAtCreation.textContent = plan.status_at_creation
      ? applyPlanStateLabel({ effective_state: plan.status_at_creation })
      : "None";
    elements.applyPlanDigest.textContent = boundedText(advanced.plan_digest, "None", 500);
    elements.applyPlanBindingDigest.textContent = boundedText(advanced.binding_digest, "None", 500);
    elements.applyPlanCandidateRecord.textContent = advanced.candidate_id === null
      || advanced.candidate_id === undefined
      ? "None"
      : "#" + String(advanced.candidate_id);
    elements.applyPlanCandidateDigest.textContent = boundedText(advanced.candidate_digest, "None", 500);
    elements.applyPlanDriftEvaluation.textContent = advanced.drift_evaluation_id === null
      || advanced.drift_evaluation_id === undefined
      ? "None"
      : "#" + String(advanced.drift_evaluation_id);
    elements.applyPlanDriftFingerprint.textContent = boundedText(advanced.drift_semantic_fingerprint, "None", 500);
    elements.applyPlanRepositoryIdentity.textContent = sanitizedApplyPlanText(
      advanced.repository_identity,
      "None",
      800
    );
    elements.applyPlanRepositoryLocator.textContent = boundedText(
      advanced.repository_locator_fingerprint,
      "None",
      500
    );
    elements.applyPlanRepositoryFingerprint.textContent = boundedText(
      advanced.repository_fingerprint,
      "None",
      500
    );
    elements.applyPlanBranch.textContent = boundedText(advanced.branch, "None", 200);
    elements.applyPlanHead.textContent = boundedText(advanced.head, "None", 500);
    elements.applyPlanCurrentSource.textContent = boundedText(advanced.current_source_digest, "None", 500);
    elements.applyPlanIndexFingerprint.textContent = boundedText(advanced.index_fingerprint, "None", 500);
    elements.applyPlanWorktreeFingerprint.textContent = boundedText(advanced.worktree_fingerprint, "None", 500);
    elements.applyPlanStagedCount.textContent = advanced.staged_path_count === null
      || advanced.staged_path_count === undefined
      ? "None"
      : String(advanced.staged_path_count);
    elements.applyPlanPolicyVersion.textContent = boundedText(advanced.policy_version, "None", 300);
    elements.applyPlanTaskBinding.textContent = applyPlanBindingValue(advanced.task_binding, "Task");
    elements.applyPlanPackBinding.textContent = applyPlanBindingValue(advanced.pack_binding, "Pack");
    elements.applyPlanRunBinding.textContent = applyPlanBindingValue(advanced.run_id, "Run");
    elements.applyPlanSourceSnapshot.textContent = boundedText(advanced.source_snapshot_identity, "None", 500);
    elements.applyPlanCreatedAt.textContent = reviewed ? formatTime(plan.created_at) : "Not recorded";
    elements.applyPlanSupersedes.textContent = advanced.supersedes_plan_record === null
      || advanced.supersedes_plan_record === undefined
      ? "None"
      : "#" + String(advanced.supersedes_plan_record);
    elements.applyPlanSupersessionReason.textContent = applyPlanSafeLine(
      advanced.supersession_reason,
      "None",
      800
    );
    appendTextList(
      elements.applyPlanOperationOrder,
      operationOrderLines,
      "No operation order is available."
    );
    const advancedEntries = Array.isArray(advanced.entries) ? advanced.entries : [];
    appendTextList(
      elements.applyPlanEntryDetails,
      advancedEntries.map(applyPlanEntryTechnicalLine),
      "No Apply Plan entry metadata is available."
    );
    appendTextList(
      elements.applyPlanExpiryReasons,
      applyPlanTextList(advanced.expiry_reasons, "No expiry reason is recorded."),
      "No expiry reason is recorded."
    );
    elements.applyPlanDiagnostics.textContent = sanitizedApplyPlanText(
      diagnosticText(advanced.diagnostics, ""),
      "No Apply Plan diagnostics are available.",
      8000
    );
  }

  function renderApplyPlanReview(run) {
    const terminal = isTerminalCodexRun(run);
    const candidateReviewed = terminal && deliveryCandidateReviewAvailable(run);
    elements.applyPlanReviewSection.hidden = !candidateReviewed;
    if (!candidateReviewed) {
      elements.reviewApplyPlan.hidden = true;
      elements.approveApplyPlan.hidden = true;
      elements.applyPlanAdvancedCard.hidden = true;
      return;
    }

    const review = objectRecord(applyPlanReviewForRun(run));
    const plan = objectRecord(review.plan);
    const reviewed = plan.id !== null && plan.id !== undefined
      || Boolean(normalizedApplyPlanState(plan.effective_state || plan.status_label));
    const stateValue = normalizedApplyPlanState(plan.effective_state || plan.status_label);
    const statusLabel = reviewed ? applyPlanStateLabel(plan) : "Not reviewed";
    const candidateReview = objectRecord(deliveryCandidateReviewForRun(run));
    const candidate = objectRecord(candidateReview.candidate);
    const candidateDrift = objectRecord(candidateReview.drift);
    const candidateStatus = plan.candidate_status_label
      || candidate.status_label
      || (deliveryCandidateReviewAvailable(run) ? "Candidate unavailable" : "Not reviewed");
    const driftStatus = plan.drift_status_label
      || (plan.drift_status ? humanStatus(plan.drift_status) : "")
      || candidateDrift.status_label
      || "Not evaluated";
    const candidateEntryCount = Number(plan.candidate_entry_count);
    const classifiedEntryCount = Number(plan.classified_entry_count);
    const conflicts = applyPlanFindingLines(plan.conflicts);
    const unexpected = applyPlanFindingLines(plan.unexpected_files);
    const blockers = applyPlanBlockerLines(review, plan);
    const plannedValidation = objectRecord(plan.planned_validation);
    const resultDerived = Boolean(
      candidate.result_envelope_id
      || candidate.derivation_version === "twos.result_delivery_candidate.v1"
      || objectRecord(candidate.advanced).result_digest
    );
    const candidateAccepted = candidate.result_review_state === "accepted_for_delivery";
    const candidateReady = candidate.readiness_state === "ready";
    const approvalState = String(plan.approval_state || "NOT REQUIRED").toUpperCase();
    const canPreparePlan = !resultDerived || (candidateAccepted && candidateReady);
    elements.reviewApplyPlan.hidden = !canPreparePlan || (
      reviewed && stateValue !== "expired"
    );
    elements.approveApplyPlan.hidden = !(
      reviewed
      && plan.approval_required === true
      && approvalState === "PENDING"
    );

    elements.applyPlanStatus.textContent = statusLabel;
    elements.applyPlanApprovalStatus.textContent = reviewed
      ? humanStatus(approvalState)
      : "Not approved";
    setStatusLabel(
      elements.applyPlanApprovalStatus,
      elements.applyPlanApprovalStatus.textContent
    );
    setApplyPlanStatusLabel(elements.applyPlanStatus, statusLabel);
    elements.applyPlanCandidateStatus.textContent = sanitizedApplyPlanText(
      candidateStatus,
      "Not reviewed",
      200
    );
    elements.applyPlanDriftStatus.textContent = sanitizedApplyPlanText(
      driftStatus,
      "Not evaluated",
      200
    );
    setCandidateStatusLabel(elements.applyPlanDriftStatus, driftStatus);
    elements.applyPlanManifestCoverage.textContent = Number.isFinite(candidateEntryCount)
      && Number.isFinite(classifiedEntryCount)
      ? "Classified " + String(classifiedEntryCount) + " of " + String(candidateEntryCount) + " Candidate entries"
      : reviewed ? "Coverage unavailable" : "Not reviewed";
    elements.applyPlanConflicts.textContent = conflicts.length
      ? String(conflicts.length) + " — " + conflicts.join(", ")
      : reviewed ? "None" : "Not reviewed";
    elements.applyPlanUnexpectedFiles.textContent = unexpected.length
      ? String(unexpected.length) + " — " + unexpected.join(", ")
      : reviewed ? "None" : "Not reviewed";
    elements.applyPlanNextAction.textContent = sanitizedApplyPlanText(
      plan.next_action || review.next_action,
      applyPlanNextActionFallback(stateValue),
      500
    );

    renderApplyPlanPaths(plan, reviewed);
    appendTextList(
      elements.applyPlanPreconditions,
      applyPlanTextList(
        plan.future_preconditions,
        reviewed
          ? "No future preconditions were reported."
          : "Review Apply Plan to inspect future preconditions."
      ),
      "Review Apply Plan to inspect future preconditions."
    );
    appendTextList(
      elements.applyPlanReversibility,
      applyPlanReversibilityLines(
        plan.reversibility_requirements,
        reviewed
          ? "No future reversibility requirements were reported."
          : "No future reversibility requirements have been reviewed."
      ),
      "No future reversibility requirements have been reviewed."
    );
    appendPlannedChecks(
      elements.applyPlanPreValidation,
      plannedValidation.pre_apply,
      reviewed ? "No pre-apply checks were reported." : "Review Apply Plan to inspect pre-apply checks."
    );
    appendPlannedChecks(
      elements.applyPlanPostValidation,
      plannedValidation.post_apply,
      reviewed ? "No post-apply checks were reported." : "No post-apply checks have been planned."
    );
    const boundaries = applyPlanTextList(plan.boundaries, "");
    [
      "Review Apply Plan never changes source.",
      "Apply and Revert each require a separate explicit Owner confirmation.",
      "Apply and Revert never stage, commit, or push."
    ].forEach(function (boundary) {
      if (boundaries.indexOf(boundary) === -1) boundaries.push(boundary);
    });
    appendTextList(elements.applyPlanBoundaries, boundaries, "Review Apply Plan never changes source.");
    appendTextList(
      elements.applyPlanBlockers,
      blockers,
      reviewed ? "No blockers reported." : "No blocker has been evaluated."
    );

    elements.applyPlanAdvancedCard.hidden = !reviewed;
    renderApplyPlanAdvanced(review, plan, reviewed);
  }

  function normalizedApplySessionState(value) {
    const normalized = String(value || "").trim().toUpperCase();
    return Object.prototype.hasOwnProperty.call(APPLY_SESSION_STATE_LABELS, normalized)
      ? normalized
      : "";
  }

  function applySessionStateLabel(value, fallback) {
    const stateValue = normalizedApplySessionState(value);
    return stateValue ? APPLY_SESSION_STATE_LABELS[stateValue] : fallback || "Not started";
  }

  function applySessionDisplayState(session) {
    const revertState = normalizedApplySessionState(session.revert_state);
    if (revertState && revertState !== "NOT_REQUESTED") return revertState;
    return normalizedApplySessionState(session.apply_state);
  }

  function setApplySessionStatusLabel(element, value) {
    const stateValue = normalizedApplySessionState(value);
    element.classList.remove("is-success", "is-warning", "is-error");
    if (stateValue === "APPLIED" || stateValue === "REVERTED") {
      element.classList.add("is-success");
    } else if (
      stateValue === "APPLYING"
      || stateValue === "REVERTING"
      || stateValue === "APPLY_FAILED_RECOVERED"
      || stateValue === "REVERT_BLOCKED"
    ) {
      element.classList.add("is-warning");
    } else if (
      stateValue === "PREFLIGHT_BLOCKED"
      || stateValue === "APPLY_FAILED_PARTIAL"
      || stateValue === "REVERT_FAILED_PARTIAL"
    ) {
      element.classList.add("is-error");
    }
  }

  function applySessionOperationCounts(entries, supplied) {
    const counts = { CREATE: 0, MODIFY: 0, DELETE: 0 };
    const provided = objectRecord(supplied);
    Object.keys(counts).forEach(function (operation) {
      const value = Number(provided[operation] !== undefined
        ? provided[operation]
        : provided[operation.toLowerCase()]);
      if (Number.isFinite(value) && value >= 0) counts[operation] = value;
    });
    if (!Object.keys(provided).length) {
      (Array.isArray(entries) ? entries : []).forEach(function (entry) {
        const record = objectRecord(entry);
        if (applyPlanDisposition(record.disposition) !== "INCLUDED") return;
        const operation = String(record.operation || "").toUpperCase();
        if (Object.prototype.hasOwnProperty.call(counts, operation)) counts[operation] += 1;
      });
    }
    return counts;
  }

  function applySessionCountsText(counts) {
    return "CREATE " + String(counts.CREATE)
      + " · MODIFY " + String(counts.MODIFY)
      + " · DELETE " + String(counts.DELETE);
  }

  function applySessionPathsFrom(value) {
    return (Array.isArray(value) ? value : []).map(function (item) {
      const record = objectRecord(item);
      if (typeof item === "string") return candidateRelativePath(item);
      return candidateRelativePath(record.path || record.display_path || record.repository_path);
    }).filter(Boolean);
  }

  function applySessionReviewParts(run) {
    const plan = currentApplyPlanForRun(run);
    const review = objectRecord(applySessionReviewForPlan(plan));
    const session = objectRecord(review.session);
    const actions = objectRecord(review.actions);
    const applyConfirmation = objectRecord(review.apply_confirmation);
    const revertConfirmation = objectRecord(review.revert_confirmation);
    return { plan, review, session, actions, applyConfirmation, revertConfirmation };
  }

  function renderApplySessionPaths(plan, review) {
    clearChildren(elements.applySessionPaths);
    const confirmation = objectRecord(review.apply_confirmation);
    let records = [];
    if (Array.isArray(confirmation.entries)) {
      records = confirmation.entries;
    } else if (Array.isArray(plan.entries)) {
      records = plan.entries;
    }
    if (!records.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = "No exact Apply path scope is available.";
      elements.applySessionPaths.appendChild(empty);
      return;
    }
    records.forEach(function (item) {
      const record = objectRecord(item);
      const disposition = applyPlanDisposition(record.disposition);
      const card = document.createElement("article");
      const path = document.createElement("strong");
      const detail = document.createElement("span");
      card.className = "apply-session-scope-card";
      card.dataset.disposition = disposition.toLowerCase();
      path.textContent = candidateRelativePath(
        record.path || record.display_path || record.repository_path
      );
      detail.textContent = disposition + " · " + candidateOperation(record.operation);
      card.appendChild(path);
      card.appendChild(detail);
      elements.applySessionPaths.appendChild(card);
    });
  }

  function applySessionAdvancedEntryLine(entry) {
    const record = objectRecord(entry);
    const beforeMode = record.before_mode === null || record.before_mode === undefined
      ? "none"
      : String(record.before_mode);
    const afterMode = record.after_mode === null || record.after_mode === undefined
      ? "none"
      : String(record.after_mode);
    return candidateRelativePath(record.path || record.display_path || record.repository_path)
      + " · " + candidateOperation(record.operation)
      + " · " + applyPlanDisposition(record.disposition)
      + " · before=" + boundedText(record.before_hash, "none", 200)
      + " · after=" + boundedText(record.after_hash, "none", 200)
      + " · mode=" + beforeMode + "→" + afterMode
      + " · type=" + boundedText(record.file_type || record.content_kind, "unknown", 80)
      + " · reverse=" + boundedText(record.reverse_operation, "none", 100);
  }

  function renderApplySessionAdvanced(session) {
    const advanced = objectRecord(session.advanced);
    const available = session.id !== null && session.id !== undefined;
    elements.applySessionAdvancedCard.hidden = !available;
    if (!available) return;
    elements.applySessionRecordId.textContent = "#" + String(session.id);
    elements.applySessionApplyState.textContent = applySessionStateLabel(session.apply_state, "None");
    elements.applySessionRevertState.textContent = applySessionStateLabel(session.revert_state, "None");
    elements.applySessionPlanRecord.textContent = boundedText(
      advanced.apply_plan_id || session.apply_plan_id,
      "None",
      300
    );
    elements.applySessionPlanDigest.textContent = boundedText(advanced.apply_plan_digest, "None", 500);
    elements.applySessionCandidateRecord.textContent = boundedText(
      advanced.candidate_id,
      "None",
      300
    );
    elements.applySessionCandidateDigest.textContent = boundedText(advanced.candidate_digest, "None", 500);
    elements.applySessionJournalDigest.textContent = boundedText(
      advanced.journal_digest || session.journal_digest,
      "None",
      500
    );
    elements.applySessionDriftEvaluation.textContent = advanced.source_drift_evaluation_id === null
      || advanced.source_drift_evaluation_id === undefined
      ? "None"
      : "#" + String(advanced.source_drift_evaluation_id);
    elements.applySessionRepositoryFingerprint.textContent = boundedText(
      advanced.repository_fingerprint,
      "None",
      500
    );
    elements.applySessionBranch.textContent = boundedText(advanced.branch, "None", 200);
    elements.applySessionHead.textContent = boundedText(advanced.pre_apply_head, "None", 500);
    elements.applySessionIndexFingerprint.textContent = boundedText(
      advanced.pre_apply_index_fingerprint,
      "None",
      500
    );
    elements.applySessionCreatedAt.textContent = formatTime(session.created_at);
    elements.applySessionApplyFinishedAt.textContent = formatTime(session.apply_finished_at);
    elements.applySessionRevertFinishedAt.textContent = formatTime(session.revert_finished_at);
    appendTextList(
      elements.applySessionEntryDetails,
      (Array.isArray(advanced.entries) ? advanced.entries : []).map(applySessionAdvancedEntryLine),
      "No durable Apply journal entry metadata is available."
    );
    elements.applySessionIntegrity.textContent = sanitizedApplyPlanText(
      diagnosticText(
        advanced.integrity || session.integrity || {
          apply: session.apply_integrity,
          revert: session.revert_integrity
        },
        ""
      ),
      "No Apply or Revert integrity evidence is available.",
      8000
    );
    elements.applySessionCompensation.textContent = sanitizedApplyPlanText(
      diagnosticText(
        advanced.compensation || session.compensation || {
          apply: session.apply_compensation,
          revert: session.revert_compensation
        },
        ""
      ),
      "No failure or compensation evidence is recorded.",
      8000
    );
    elements.applySessionDiagnostics.textContent = sanitizedApplyPlanText(
      diagnosticText(advanced.diagnostics || session.diagnostics, ""),
      "No Apply session diagnostics are available.",
      8000
    );
  }

  function renderApplySessionReview(run) {
    const parts = applySessionReviewParts(run);
    const planReviewed = parts.plan.id !== null && parts.plan.id !== undefined;
    const planId = planReviewed ? String(parts.plan.id) : "";
    if (
      elements.applyConfirmationDialog.open
      && (!state.applyConfirmationContext
        || String(state.applyConfirmationContext.plan_id) !== planId)
    ) {
      elements.applyConfirmationDialog.close();
      state.applyConfirmationContext = null;
    }
    if (
      elements.revertConfirmationDialog.open
      && (!state.revertConfirmationContext
        || String(state.revertConfirmationContext.session_id)
          !== String(parts.session.id || ""))
    ) {
      elements.revertConfirmationDialog.close();
      state.revertConfirmationContext = null;
    }
    elements.applySessionSection.hidden = !planReviewed;
    if (!planReviewed) {
      elements.applyAcceptedChanges.hidden = true;
      elements.revertAppliedChanges.hidden = true;
      elements.applySessionAdvancedCard.hidden = true;
      return;
    }
    const planEntries = Array.isArray(parts.plan.entries) ? parts.plan.entries : [];
    const counts = applySessionOperationCounts(
      planEntries,
      parts.applyConfirmation.operation_counts
    );
    const stateValue = applySessionDisplayState(parts.session);
    const blockers = applyPlanTextList(parts.review.blockers, "");
    const included = applySessionPathsFrom(
      parts.applyConfirmation.included_paths
      || planEntries.filter(function (entry) {
        return applyPlanDisposition(objectRecord(entry).disposition) === "INCLUDED";
      })
    );
    const excluded = applySessionPathsFrom(
      parts.applyConfirmation.excluded_paths
      || planEntries.filter(function (entry) {
        return applyPlanDisposition(objectRecord(entry).disposition) !== "INCLUDED";
      })
    );
    const unrelated = applySessionPathsFrom(
      parts.applyConfirmation.unrelated_paths
      || parts.review.unrelated_paths
    );
    const stagedCount = Number(
      parts.applyConfirmation.staged_path_count !== undefined
        ? parts.applyConfirmation.staged_path_count
        : objectRecord(parts.plan.advanced).staged_path_count
    );
    const readinessLabel = sanitizedApplyPlanText(
      parts.review.readiness_label
      || parts.review.status_label
      || parts.plan.status_label,
      "Not evaluated",
      220
    );
    const displayState = stateValue
      ? applySessionStateLabel(stateValue)
      : "Not started";

    const planApprovalState = sanitizedApplyPlanText(
      parts.review.plan_approval_state || parts.review.approval_state,
      "PENDING",
      100
    );
    const applyConfirmationState = sanitizedApplyPlanText(
      parts.review.apply_confirmation_state,
      parts.session.id ? "CONFIRMED" : "PENDING",
      100
    );
    elements.applySessionApproval.textContent = parts.plan.approval_required === true
      ? "Plan " + humanStatus(planApprovalState)
        + " · Apply confirmation " + humanStatus(applyConfirmationState)
      : sanitizedApplyPlanText(
          parts.review.approval_state,
          parts.session.id ? "OWNER CONFIRMED" : "AWAITING OWNER CONFIRMATION",
          100
        );
    elements.applySessionReadiness.textContent = readinessLabel;
    elements.applySessionState.textContent = sanitizedApplyPlanText(
      parts.review.execution_state,
      displayState,
      100
    );
    elements.applySessionResultSummary.textContent = sanitizedApplyPlanText(
      parts.review.result_summary,
      "Awaiting explicit Owner confirmation.",
      300
    );
    elements.applySessionChangedCount.textContent = String(
      Number(parts.review.changed_file_count || 0)
    );
    elements.applySessionValidation.textContent = sanitizedApplyPlanText(
      parts.review.validation_result,
      "NOT RUN",
      100
    );
    elements.applySessionRecovery.textContent = parts.review.recovery_available === true
      ? "Available"
      : "Not available";
    setApplyPlanStatusLabel(elements.applySessionReadiness, parts.plan.effective_state);
    setApplySessionStatusLabel(elements.applySessionState, stateValue);
    elements.applySessionDrift.textContent = sanitizedApplyPlanText(
      parts.applyConfirmation.drift_status_label
      || parts.applyConfirmation.drift_status
      || parts.plan.drift_status_label,
      "Not evaluated",
      200
    );
    elements.applySessionOperationCounts.textContent = applySessionCountsText(counts);
    elements.applySessionUnrelated.textContent = unrelated.length
      ? String(unrelated.length) + " preserved — " + unrelated.join(", ")
      : "None reported";
    elements.applySessionIndexBoundary.textContent = Number.isFinite(stagedCount)
      ? "Index observed · staged paths " + String(stagedCount)
      : "Not evaluated";
    elements.applySessionRevertAvailability.textContent = parts.actions.can_revert === true
      ? "Available after separate confirmation"
      : parts.session.revert_state
        ? applySessionStateLabel(parts.session.revert_state, "Not available")
        : "Not available";
    elements.applySessionNextAction.textContent = sanitizedApplyPlanText(
      parts.review.next_action,
      parts.actions.can_apply === true
        ? "Select Apply Accepted Changes."
        : parts.actions.can_revert === true
          ? "Select Revert Applied Changes."
          : "Resolve the reported blocker.",
      500
    );
    renderApplySessionPaths(parts.plan, parts.review);
    appendTextList(
      elements.applySessionBlockers,
      blockers,
      "No Apply or Revert blocker is reported."
    );

    elements.applyAcceptedChanges.hidden = parts.actions.can_apply !== true;
    elements.revertAppliedChanges.hidden = parts.actions.can_revert !== true;
    elements.applyAcceptedChanges.disabled = parts.actions.can_apply !== true
      || state.pending.has("apply-accepted-changes");
    elements.revertAppliedChanges.disabled = parts.actions.can_revert !== true
      || state.pending.has("revert-applied-changes");
    elements.applyAcceptedChanges.title = included.length
      ? "Open final confirmation for " + String(included.length) + " INCLUDED path"
        + (included.length === 1 ? "." : "s.")
      : "Apply is unavailable.";
    elements.revertAppliedChanges.title = excluded.length
      ? "Open a separate confirmation to reverse this exact Apply session."
      : "Open a separate confirmation to reverse this exact Apply session.";
    renderApplySessionAdvanced(parts.session);
  }

  function normalizedPostApplyVerificationState(value) {
    const normalized = String(value || "").trim().toUpperCase();
    return Object.prototype.hasOwnProperty.call(
      POST_APPLY_VERIFICATION_STATE_LABELS,
      normalized
    ) ? normalized : "";
  }

  function setPostApplyVerificationStatusLabel(element, value) {
    const stateValue = normalizedPostApplyVerificationState(value);
    element.classList.remove("is-success", "is-warning", "is-error");
    if (stateValue === "READY" || stateValue === "PASSED") {
      element.classList.add("is-success");
    } else if (stateValue === "VERIFYING") {
      element.classList.add("is-warning");
    } else if (stateValue === "BLOCKED" || stateValue === "FAILED") {
      element.classList.add("is-error");
    }
  }

  function postApplyVerificationSafeLines(value) {
    if (Array.isArray(value)) {
      return value.map(function (item) {
        const record = objectRecord(item);
        if (Object.keys(record).length) {
          const code = boundedText(record.code || record.name, "Boundary", 120);
          const status = boundedText(record.status || record.result, "Not evaluated", 120);
          const description = applyPlanSafeLine(
            record.description || record.message || record.reason,
            "No description",
            800
          );
          return code + " · " + status + " — " + description;
        }
        return applyPlanSafeLine(item, "", 1200);
      }).filter(Boolean);
    }
    const record = objectRecord(value);
    return Object.keys(record).sort().map(function (key) {
      const item = record[key];
      const detail = typeof item === "boolean"
        ? (item ? "Passed" : "Blocked")
        : applyPlanSafeLine(item, "Not available", 1000);
      return sanitizedApplyPlanText(humanStatus(key) + " — " + detail, "", 1200);
    }).filter(Boolean);
  }

  function postApplyVerificationPathLine(value) {
    if (typeof value === "string") return candidateRelativePath(value);
    const record = objectRecord(value);
    const path = candidateRelativePath(
      record.path || record.repository_relative_path || record.repository_path
    );
    const operation = candidateOperation(record.operation || record.change_type);
    const result = boundedText(
      record.result || record.status || record.check_status,
      "Not evaluated",
      120
    );
    const expectedHash = boundedText(
      record.expected_hash || record.after_hash || record.expected_sha256,
      "none",
      200
    );
    const observedHash = boundedText(
      record.observed_hash || record.actual_hash || record.observed_sha256,
      "none",
      200
    );
    const expectedModeValue = record.expected_mode;
    const observedModeValue = record.observed_mode;
    const expectedMode = expectedModeValue === null || expectedModeValue === undefined
      ? "none"
      : String(expectedModeValue);
    const observedMode = observedModeValue === null || observedModeValue === undefined
      ? "none"
      : String(observedModeValue);
    return path + " · " + operation + " · " + result
      + " · expected=" + expectedHash + " · observed=" + observedHash
      + " · mode=" + expectedMode + "→" + observedMode;
  }

  function renderPostApplyVerificationFiles(target, entries, unexpected) {
    clearChildren(target);
    const records = Array.isArray(entries) ? entries : [];
    if (!records.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = unexpected
        ? "No unexpected files were observed."
        : "No applied paths have been verified.";
      target.appendChild(empty);
      return;
    }
    records.forEach(function (item) {
      const record = objectRecord(item);
      const operation = candidateOperation(record.operation || record.change_type);
      const result = boundedText(
        record.result || record.status || record.check_status,
        unexpected ? "Unexpected" : "Not evaluated",
        160
      );
      const card = document.createElement("article");
      const heading = document.createElement("div");
      const path = document.createElement("strong");
      const operationLabel = document.createElement("span");
      const detail = document.createElement("p");
      card.className = "post-apply-verification-file-item";
      card.dataset.operation = operation.toLowerCase();
      card.dataset.result = String(result).toLowerCase();
      heading.className = "post-apply-verification-file-heading";
      path.textContent = candidateRelativePath(
        record.path || record.repository_relative_path || record.repository_path || item
      );
      operationLabel.className = "candidate-operation";
      operationLabel.textContent = operation;
      detail.textContent = sanitizedApplyPlanText(
        result,
        unexpected ? "Unexpected repository path" : "Not evaluated",
        500
      );
      heading.appendChild(path);
      heading.appendChild(operationLabel);
      card.appendChild(heading);
      card.appendChild(detail);
      target.appendChild(card);
    });
  }

  function postApplyVerificationBinding(id, digest) {
    const identifier = id === null || id === undefined || id === ""
      ? "None"
      : "#" + String(id);
    const fingerprint = boundedText(digest, "", 500);
    return fingerprint ? identifier + " · " + fingerprint : identifier;
  }

  function renderPostApplyVerificationAdvanced(verification) {
    const available = verification.id !== null && verification.id !== undefined;
    elements.postApplyVerificationAdvancedCard.hidden = !available;
    if (!available) return;
    const advanced = objectRecord(verification.advanced);
    elements.postApplyVerificationRecordId.textContent = "#" + String(verification.id);
    elements.postApplyVerificationPolicyVersion.textContent = boundedText(
      advanced.policy_version,
      "None",
      160
    );
    elements.postApplyVerificationDigest.textContent = boundedText(
      advanced.verification_digest || verification.verification_digest,
      "None",
      500
    );
    elements.postApplyObservationDigest.textContent = boundedText(
      advanced.observation_digest,
      "None",
      500
    );
    elements.postApplyVerificationSessionBinding.textContent = postApplyVerificationBinding(
      advanced.apply_session_id,
      advanced.apply_session_digest
    );
    elements.postApplyVerificationPlanBinding.textContent = postApplyVerificationBinding(
      advanced.apply_plan_id,
      advanced.apply_plan_digest
    );
    elements.postApplyVerificationCandidateBinding.textContent = postApplyVerificationBinding(
      advanced.candidate_id,
      advanced.candidate_digest
    );
    elements.postApplyVerificationRepositoryIdentity.textContent = sanitizedApplyPlanText(
      advanced.repository_identity,
      "None",
      800
    );
    elements.postApplyVerificationRepositoryFingerprints.textContent = sanitizedApplyPlanText(
      diagnosticText(
        advanced.repository_fingerprints || advanced.repository_fingerprint,
        ""
      ),
      "None",
      1600
    );
    elements.postApplyVerificationExpectedBranch.textContent = sanitizedApplyPlanText(
      advanced.expected_branch,
      "None",
      240
    );
    elements.postApplyVerificationObservedBranch.textContent = sanitizedApplyPlanText(
      advanced.observed_branch,
      "None",
      240
    );
    elements.postApplyVerificationExpectedHead.textContent = boundedText(
      advanced.expected_head,
      "None",
      500
    );
    elements.postApplyVerificationObservedHead.textContent = boundedText(
      advanced.observed_head,
      "None",
      500
    );
    elements.postApplyVerificationSourceSnapshot.textContent = boundedText(
      advanced.source_snapshot_identity,
      "None",
      500
    );
    elements.postApplyVerificationCreatedAt.textContent = formatTime(verification.created_at);
    appendTextList(
      elements.postApplyVerificationExpectedPaths,
      (Array.isArray(advanced.expected_paths) ? advanced.expected_paths : [])
        .map(postApplyVerificationPathLine),
      "No expected path evidence is available."
    );
    appendTextList(
      elements.postApplyVerificationObservedPaths,
      (Array.isArray(advanced.observed_paths) ? advanced.observed_paths : [])
        .map(postApplyVerificationPathLine),
      "No observed path evidence is available."
    );
    elements.postApplyVerificationDiagnostics.textContent = sanitizedApplyPlanText(
      diagnosticText(advanced.diagnostics, ""),
      "No Post-Apply Verification diagnostics are available.",
      8000
    );
  }

  function renderPostApplyVerification(run) {
    const parts = applySessionReviewParts(run);
    const applySession = objectRecord(parts.session);
    const validContext = postApplyVerificationContextAvailable(applySession);
    elements.postApplyVerificationSection.hidden = !validContext;
    if (!validContext) {
      elements.verifyAppliedChanges.hidden = true;
      elements.postApplyVerificationAdvancedCard.hidden = true;
      return;
    }
    const review = objectRecord(postApplyVerificationReviewForSession(applySession));
    const eligibility = objectRecord(review.eligibility);
    const verification = objectRecord(review.verification);
    const actions = objectRecord(review.actions);
    const status = normalizedPostApplyVerificationState(
      verification.status || eligibility.status
    ) || "READY";
    const changedFiles = Array.isArray(verification.changed_files)
      ? verification.changed_files
      : [];
    const unexpectedFiles = Array.isArray(verification.unexpected_files)
      ? verification.unexpected_files
      : [];
    const tests = Array.isArray(verification.tests) ? verification.tests : [];
    const boundaryLines = postApplyVerificationSafeLines(verification.boundaries).map(
      function (line) {
        if (line.indexOf("Phase 18.4A remains separately gated") !== -1) {
          return "Stage and Local Commit are available only through separate explicit Owner controls after a PASS.";
        }
        if (line.indexOf("No Stage, Commit, Push") === 0) {
          return "Post-Apply Verification itself performs no Stage, Commit, Push, merge, rebase, tag, branch, or remote change.";
        }
        return line;
      }
    );
    const blockerLines = applyPlanTextList(eligibility.blockers, "")
      .concat(applyPlanTextList(verification.blockers, ""));
    const passedTests = tests.filter(function (item) {
      return ["PASS", "PASSED"].indexOf(
        String(objectRecord(item).status || "").toUpperCase()
      ) !== -1;
    }).length;
    const canVerify = actions.can_verify === true || eligibility.can_verify === true;

    elements.postApplyVerificationStatus.textContent = sanitizedApplyPlanText(
      verification.status_label
      || eligibility.status_label
      || POST_APPLY_VERIFICATION_STATE_LABELS[status],
      POST_APPLY_VERIFICATION_STATE_LABELS[status],
      240
    );
    setPostApplyVerificationStatusLabel(elements.postApplyVerificationStatus, status);
    elements.postApplyVerificationChangedSummary.textContent = changedFiles.length
      ? String(changedFiles.length) + " applied path" + (changedFiles.length === 1 ? "" : "s")
      : verification.id ? "No applied paths reported" : "Not verified";
    elements.postApplyVerificationUnexpectedSummary.textContent = verification.id
      ? unexpectedFiles.length
        ? String(unexpectedFiles.length) + " unexpected path"
          + (unexpectedFiles.length === 1 ? "" : "s")
        : "None"
      : "Not verified";
    elements.postApplyVerificationTestsSummary.textContent = tests.length
      ? String(passedTests) + " of " + String(tests.length) + " passed"
      : verification.id ? "No tests reported" : "Not run";
    elements.postApplyVerificationBoundariesSummary.textContent = boundaryLines.length
      ? String(boundaryLines.length) + " boundary check"
        + (boundaryLines.length === 1 ? "" : "s")
      : verification.id ? "No boundary evidence reported" : "Not verified";
    elements.postApplyVerificationNextAction.textContent = sanitizedApplyPlanText(
      status === "PASSED"
        ? "Review Commit Plan."
        : verification.next_action || eligibility.next_action,
      canVerify
        ? "Select Verify Applied Changes."
        : "Review the reported Post-Apply Verification blocker.",
      700
    );
    renderPostApplyVerificationFiles(
      elements.postApplyVerificationChangedFiles,
      changedFiles,
      false
    );
    renderPostApplyVerificationFiles(
      elements.postApplyVerificationUnexpectedFiles,
      unexpectedFiles,
      true
    );
    appendTextList(
      elements.postApplyVerificationTests,
      tests.map(function (item) {
        const record = objectRecord(item);
        const code = boundedText(record.code, "Check", 120);
        const description = applyPlanSafeLine(
          record.description || record.message,
          "No description",
          800
        );
        const testStatus = boundedText(record.status, "Not evaluated", 120);
        return code + " · " + testStatus + " — " + description;
      }),
      verification.id
        ? "No post-Apply test evidence was reported."
        : "Select Verify Applied Changes to run the planned checks."
    );
    appendTextList(
      elements.postApplyVerificationBoundaries,
      boundaryLines,
      verification.id
        ? "No repository boundary evidence was reported."
        : "Select Verify Applied Changes to inspect repository boundaries."
    );
    appendTextList(
      elements.postApplyVerificationBlockers,
      blockerLines,
      "No Post-Apply Verification blocker is reported."
    );
    elements.verifyAppliedChanges.hidden = false;
    elements.verifyAppliedChanges.disabled = !canVerify
      || state.pending.has("verify-applied-changes");
    elements.verifyAppliedChanges.title = canVerify
      ? "Run a read-only verification of this exact Apply session."
      : "Post-Apply Verification is blocked; review the reported evidence.";
    renderPostApplyVerificationAdvanced(verification);
  }

  function commitBuilderParts(run) {
    const verification = currentPassedPostApplyVerification(run);
    const review = objectRecord(commitBuilderReviewForVerification(verification));
    const plan = objectRecord(review.plan || review.commit_plan);
    return {
      verification: objectRecord(verification),
      review: review,
      eligibility: objectRecord(review.eligibility),
      plan: plan,
      stage: objectRecord(review.stage || review.stage_execution || plan.stage),
      commit: objectRecord(
        review.commit || review.local_commit || review.commit_execution || plan.commit
      ),
      actions: Object.assign({}, objectRecord(plan.actions), objectRecord(review.actions))
    };
  }

  function commitBuilderEntries(record, included) {
    const value = objectRecord(record);
    const direct = included
      ? value.approved_files || value.included_files || value.included_paths
        || value.verified_paths
      : value.excluded_files || value.excluded_paths;
    if (Array.isArray(direct)) return direct;
    const entries = Array.isArray(value.entries) ? value.entries : [];
    return entries.filter(function (item) {
      const disposition = String(objectRecord(item).disposition || "INCLUDED").toUpperCase();
      return included ? disposition === "INCLUDED" : disposition !== "INCLUDED";
    });
  }

  function commitBuilderPath(item) {
    const record = objectRecord(item);
    return candidateRelativePath(
      record.path || record.repository_path || record.repository_relative_path || item
    );
  }

  function renderCommitBuilderFiles(target, entries, excluded) {
    clearChildren(target);
    const records = Array.isArray(entries) ? entries : [];
    if (!records.length) {
      const empty = document.createElement("p");
      empty.className = "empty-state";
      empty.textContent = excluded
        ? "No files are excluded from this Commit Plan."
        : "No approved staging paths are available.";
      target.appendChild(empty);
      return;
    }
    records.forEach(function (item) {
      const record = objectRecord(item);
      const card = document.createElement("article");
      const heading = document.createElement("div");
      const path = document.createElement("strong");
      const operation = document.createElement("span");
      const detail = document.createElement("p");
      card.className = "commit-builder-file-item";
      heading.className = "commit-builder-file-heading";
      path.textContent = commitBuilderPath(item);
      operation.className = "candidate-operation";
      operation.textContent = candidateOperation(record.operation || record.change_type);
      detail.textContent = sanitizedApplyPlanText(
        record.reason || record.result || record.status,
        excluded ? "Excluded from staging" : "Approved for staging",
        500
      );
      heading.appendChild(path);
      heading.appendChild(operation);
      card.appendChild(heading);
      card.appendChild(detail);
      target.appendChild(card);
    });
  }

  function commitBuilderRecordId(record) {
    const value = objectRecord(record);
    return value.id || value.plan_id || value.stage_id || value.stage_execution_id
      || value.commit_id || value.commit_execution_id || null;
  }

  function commitBuilderRecordDigest(record) {
    const value = objectRecord(record);
    const advanced = objectRecord(value.advanced);
    return value.digest || value.plan_digest || value.stage_digest
      || value.commit_digest || value.execution_digest || value.receipt_digest
      || advanced.plan_digest || advanced.stage_digest || advanced.receipt_digest || "";
  }

  function commitBuilderState(parts) {
    const serverState = String(parts.review.action_state || "").toUpperCase();
    if (["REVIEW_REQUIRED", "READY_TO_STAGE", "STAGING_BLOCKED", "READY_TO_COMMIT",
      "COMMIT_BLOCKED", "COMMITTED"].indexOf(serverState) !== -1) return serverState;
    const commitStatus = String(parts.commit.status || parts.commit.state || "").toUpperCase();
    const stageStatus = String(parts.stage.status || parts.stage.state || "").toUpperCase();
    const planStatus = String(parts.plan.status || parts.plan.state || "").toUpperCase();
    const eligibilityStatus = String(parts.eligibility.status || "").toUpperCase();
    if (["BLOCKED", "FAILED", "INTEGRITY_BLOCKED"].indexOf(commitStatus) !== -1) {
      return commitStatus;
    }
    if (commitStatus === "COMMITTED") return "COMMITTED";
    if (["BLOCKED", "FAILED", "INTEGRITY_BLOCKED"].indexOf(stageStatus) !== -1) {
      return stageStatus;
    }
    if (["BLOCKED", "FAILED", "EXPIRED"].indexOf(planStatus) !== -1) return planStatus;
    if (["BLOCKED", "EXPIRED"].indexOf(eligibilityStatus) !== -1) {
      return eligibilityStatus;
    }
    if (commitStatus === "COMMITTING") return "COMMITTING";
    if (commitBuilderRecordId(parts.commit) && !commitStatus) return "INTEGRITY_BLOCKED";
    if (stageStatus === "STAGED") return "STAGED";
    if (stageStatus === "STAGING") return "STAGING";
    if (commitBuilderRecordId(parts.stage) && !stageStatus) return "INTEGRITY_BLOCKED";
    if (commitBuilderRecordId(parts.plan)) return "READY_TO_STAGE";
    return "REVIEW_REQUIRED";
  }

  function renderCommitBuilderAdvanced(parts) {
    const available = Boolean(
      commitBuilderRecordId(parts.plan)
      || commitBuilderRecordId(parts.stage)
      || commitBuilderRecordId(parts.commit)
    );
    elements.commitBuilderAdvancedCard.hidden = !available;
    if (!available) return;
    const planAdvanced = objectRecord(parts.plan.advanced);
    const stageAdvanced = objectRecord(parts.stage.advanced);
    const commitAdvanced = objectRecord(parts.commit.advanced);
    const reviewAdvanced = objectRecord(parts.review.advanced);
    const boundaryEvidence = objectRecord(planAdvanced.boundary_evidence);
    const boundaryIndex = objectRecord(boundaryEvidence.index);
    elements.commitPlanRecordId.textContent = postApplyVerificationBinding(
      commitBuilderRecordId(parts.plan),
      ""
    );
    elements.commitPlanPolicyVersion.textContent = boundedText(
      planAdvanced.policy_version || parts.plan.policy_version,
      "None",
      160
    );
    elements.commitPlanDigest.textContent = boundedText(
      commitBuilderRecordDigest(parts.plan),
      "None",
      500
    );
    elements.commitPlanVerificationBinding.textContent = postApplyVerificationBinding(
      parts.review.post_apply_verification_id || parts.verification.id,
      planAdvanced.verification_digest || parts.verification.verification_digest
    );
    elements.commitPlanApplySessionBinding.textContent = postApplyVerificationBinding(
      planAdvanced.apply_session_id,
      planAdvanced.apply_session_digest || planAdvanced.journal_digest
    );
    elements.commitPlanRepositoryIdentity.textContent = sanitizedApplyPlanText(
      planAdvanced.repository_identity || reviewAdvanced.repository_identity,
      "None",
      800
    );
    elements.commitPlanBranch.textContent = sanitizedApplyPlanText(
      planAdvanced.branch || reviewAdvanced.branch,
      "None",
      240
    );
    elements.commitPlanHead.textContent = boundedText(
      planAdvanced.base_head || planAdvanced.head || planAdvanced.expected_head
        || reviewAdvanced.head,
      "None",
      500
    );
    elements.commitPlanIndex.textContent = boundedText(
      planAdvanced.index_fingerprint || boundaryIndex.fingerprint
        || reviewAdvanced.index_fingerprint,
      "None",
      500
    );
    elements.stageSessionRecordId.textContent = postApplyVerificationBinding(
      commitBuilderRecordId(parts.stage),
      ""
    );
    elements.stageSessionDigest.textContent = boundedText(
      commitBuilderRecordDigest(parts.stage),
      "None",
      500
    );
    const stagedPaths = commitBuilderEntries(parts.stage, true);
    elements.stageSessionPathCount.textContent = String(
      parts.stage.staged_path_count === undefined
        ? stagedPaths.length
        : parts.stage.staged_path_count
    );
    elements.localCommitRecordId.textContent = postApplyVerificationBinding(
      commitBuilderRecordId(parts.commit),
      ""
    );
    elements.localCommitSha.textContent = boundedText(
      parts.commit.commit_oid || parts.commit.commit_sha
        || commitAdvanced.commit_oid || commitAdvanced.commit_sha,
      "None",
      500
    );
    elements.localCommitParentSha.textContent = boundedText(
      parts.commit.parent_oid || parts.commit.parent_sha
        || commitAdvanced.parent_oid || commitAdvanced.parent_sha
        || planAdvanced.base_head,
      "None",
      500
    );
    elements.localCommitMessageDigest.textContent = boundedText(
      parts.commit.message_digest || commitAdvanced.message_digest,
      "None",
      500
    );
    elements.commitBuilderCreatedAt.textContent = formatTime(
      parts.commit.created_at || parts.stage.created_at || parts.plan.created_at
    );
    const identities = reviewAdvanced.approved_path_identities
      || planAdvanced.approved_path_identities
      || stageAdvanced.staged_path_identities;
    appendTextList(
      elements.commitBuilderPathEvidence,
      Array.isArray(identities) ? identities.map(function (identity) {
        return boundedText(identity, "Unavailable", 500);
      }) : [],
      "No Commit Plan path identities are available."
    );
    elements.commitBuilderDiagnostics.textContent = sanitizedApplyPlanText(
      diagnosticText(
        parts.commit.diagnostics || parts.stage.diagnostics
          || parts.plan.diagnostics || reviewAdvanced.diagnostics,
        ""
      ),
      "No Stage or local Commit diagnostics are available.",
      8000
    );
  }

  function renderCommitBuilder(run) {
    const parts = commitBuilderParts(run);
    const validContext = Boolean(parts.verification.id);
    elements.commitBuilderSection.hidden = !validContext;
    if (!validContext) {
      elements.reviewCommitPlan.hidden = true;
      elements.stageApprovedFiles.hidden = true;
      elements.createLocalCommit.hidden = true;
      elements.commitBuilderAdvancedCard.hidden = true;
      return;
    }
    const stateValue = commitBuilderState(parts);
    const approved = commitBuilderEntries(parts.plan, true);
    const excluded = commitBuilderEntries(parts.plan, false);
    const staged = commitBuilderEntries(parts.stage, true);
    const blockers = applyPlanTextList(parts.eligibility.blockers, "")
      .concat(applyPlanTextList(parts.review.blockers, ""))
      .concat(applyPlanTextList(parts.plan.blockers, ""))
      .concat(applyPlanTextList(parts.stage.blockers, ""))
      .concat(applyPlanTextList(parts.commit.blockers, ""));
    const boundaries = postApplyVerificationSafeLines(
      parts.review.boundaries || parts.plan.boundaries
    );
    const planId = commitBuilderRecordId(parts.plan);
    const stageId = commitBuilderRecordId(parts.stage);
    const commitId = commitBuilderRecordId(parts.commit);
    const stageStatus = String(parts.stage.status || parts.stage.state || "").toUpperCase();
    const commitStatus = String(parts.commit.status || parts.commit.state || "").toUpperCase();
    const planStatus = String(parts.plan.status || parts.plan.state || "").toUpperCase();
    const eligibilityStatus = String(parts.eligibility.status || "").toUpperCase();
    const canReview = parts.actions.can_review_commit_plan === true
      || parts.eligibility.can_review === true;
    const canStage = parts.actions.can_stage_approved_files === true
      || parts.actions.can_stage === true;
    const canCommit = parts.actions.can_create_local_commit === true
      || parts.actions.can_commit === true;
    const planAdvanced = objectRecord(parts.plan.advanced);
    const validations = Array.isArray(parts.plan.validation)
      ? parts.plan.validation
      : [];
    const passedValidations = validations.filter(function (item) {
      return ["PASS", "PASSED"].indexOf(
        String(objectRecord(item).status || "").toUpperCase()
      ) !== -1;
    }).length;

    elements.commitBuilderStatus.textContent = sanitizedApplyPlanText(
      COMMIT_BUILDER_STATE_LABELS[stateValue]
        || parts.commit.status_label || parts.stage.status_label
        || parts.plan.status_label || parts.eligibility.status_label,
      COMMIT_BUILDER_STATE_LABELS[stateValue],
      240
    );
    setStatusLabel(elements.commitBuilderStatus, elements.commitBuilderStatus.textContent);
    elements.commitPlanSummary.textContent = planId
      ? "Reviewed · " + String(planId)
      : "Not reviewed";
    elements.commitApprovedSummary.textContent = planId
      ? String(approved.length) + " approved path" + (approved.length === 1 ? "" : "s")
      : "Not reviewed";
    elements.commitExcludedSummary.textContent = planId
      ? excluded.length
        ? String(excluded.length) + " excluded path" + (excluded.length === 1 ? "" : "s")
        : "None"
      : "Not reviewed";
    elements.commitBuilderBranch.textContent = planId
      ? sanitizedApplyPlanText(planAdvanced.branch, "Unavailable", 240)
      : "Not reviewed";
    elements.commitBuilderHead.textContent = planId
      ? boundedText(planAdvanced.base_head, "Unavailable", 500)
      : "Not reviewed";
    elements.commitBuilderSubject.textContent = planId
      ? sanitizedApplyPlanText(parts.plan.subject, "Unavailable", 200)
      : "Not reviewed";
    elements.commitBuilderValidation.textContent = planId
      ? validations.length
        ? String(passedValidations) + " of " + String(validations.length) + " passed"
        : "No validation evidence"
      : "Not reviewed";
    elements.commitStageSummary.textContent = !stageId
      ? "Not started"
      : stageStatus === "STAGED"
        ? staged.length
          ? String(staged.length) + " approved path" + (staged.length === 1 ? "" : "s") + " staged"
          : String(parts.stage.staged_path_count || 0) + " approved paths staged"
        : stageStatus === "STAGING"
          ? "STAGE RECOVERY REQUIRED"
          : stageStatus === "FAILED"
            ? "Failed"
            : ["BLOCKED", "INTEGRITY_BLOCKED"].indexOf(stageStatus) !== -1
              ? "Blocked"
              : "Not settled";
    elements.localCommitSummary.textContent = !commitId
      ? "Not created"
      : commitStatus === "COMMITTED"
        ? "Created · " + boundedText(
          parts.commit.commit_oid || parts.commit.commit_sha,
          String(commitId),
          200
        )
        : commitStatus === "COMMITTING"
          ? "COMMIT RECOVERY REQUIRED"
          : commitStatus === "FAILED"
            ? "Failed"
            : ["BLOCKED", "INTEGRITY_BLOCKED"].indexOf(commitStatus) !== -1
              ? "Blocked"
              : "Not settled";
    let nextAction = "";
    if (["FAILED", "INTEGRITY_BLOCKED"].indexOf(commitStatus) !== -1) {
      nextAction = parts.commit.next_action;
    } else if (["FAILED", "INTEGRITY_BLOCKED"].indexOf(stageStatus) !== -1) {
      nextAction = parts.stage.next_action;
    } else if (commitStatus === "COMMITTED") {
      nextAction = "Review Push readiness.";
    } else if (
      ["BLOCKED", "EXPIRED"].indexOf(planStatus) !== -1
      || ["BLOCKED", "EXPIRED"].indexOf(eligibilityStatus) !== -1
    ) {
      nextAction = parts.eligibility.next_action || parts.plan.next_action
        || parts.review.next_action;
    } else {
      nextAction = parts.commit.next_action || parts.stage.next_action
        || parts.plan.next_action || parts.eligibility.next_action
        || parts.review.next_action;
    }
    elements.commitBuilderNextAction.textContent = sanitizedApplyPlanText(
      nextAction,
      ["BLOCKED", "FAILED", "INTEGRITY_BLOCKED", "EXPIRED"].indexOf(stateValue) !== -1
        ? "Review blocker evidence."
        : commitStatus === "COMMITTED"
        ? "Review Push readiness."
        : canCommit
          ? "Select Create Local Commit."
          : canStage
            ? "Select Stage Approved Files."
            : "Select Review Commit Plan.",
      700
    );
    renderCommitBuilderFiles(elements.commitApprovedFiles, approved, false);
    renderCommitBuilderFiles(elements.commitExcludedFiles, excluded, true);
    appendTextList(
      elements.commitBuilderBoundaries,
      boundaries,
      "Each Stage and local Commit mutation requires a separate Owner action. This section never performs Push."
    );
    appendTextList(
      elements.commitBuilderBlockers,
      blockers,
      "No Stage or local Commit blocker is reported."
    );
    if (!planId && !elements.commitPlanSubject.value.trim()) {
      const task = selectedTask();
      const taskName = task ? task.title || task.development_task : "approved changes";
      const candidate = "Apply " + String(taskName || "approved changes");
      elements.commitPlanSubject.value = utf8ByteLength(candidate) <= 180
        ? candidate
        : "Apply approved task changes";
    }
    if (planId) {
      elements.commitPlanSubject.value = boundedText(parts.plan.subject, elements.commitPlanSubject.value, 200);
      elements.commitPlanBody.value = boundedText(parts.plan.body, elements.commitPlanBody.value, 4000);
    }
    elements.commitMessageFields.hidden = Boolean(planId);
    elements.commitPlanSubject.disabled = Boolean(planId);
    elements.commitPlanBody.disabled = Boolean(planId);
    elements.reviewCommitPlan.hidden = false;
    elements.reviewCommitPlan.disabled = !canReview
      || state.pending.has("review-commit-plan");
    elements.stageApprovedFiles.hidden = false;
    elements.stageApprovedFiles.disabled = !canStage
      || state.pending.has("stage-approved-files");
    elements.createLocalCommit.hidden = false;
    elements.createLocalCommit.disabled = !canCommit
      || state.pending.has("create-local-commit");
    renderCommitBuilderAdvanced(parts);
  }

  function pushDeliveryParts(run) {
    const commitParts = commitBuilderParts(run);
    const commit = objectRecord(currentCommittedLocalCommit(run));
    const review = objectRecord(pushDeliveryReviewForLocalCommit(commit));
    return {
      commitParts: commitParts,
      commit: commit,
      review: review,
      readiness: objectRecord(review.readiness),
      execution: objectRecord(review.push_execution),
      result: objectRecord(review.delivery_result),
      actions: objectRecord(review.actions)
    };
  }

  function pushDeliverySummary(value, fallback, maximum) {
    if (value === true) return "Yes";
    if (value === false) return "No";
    if (typeof value === "string" || typeof value === "number") {
      return sanitizedApplyPlanText(String(value), fallback, maximum || 700);
    }
    const record = objectRecord(value);
    return sanitizedApplyPlanText(
      record.status_label || record.outcome_label || record.terminal_status
        || record.summary || record.result || record.verdict
        || record.status || record.state || record.id,
      fallback,
      maximum || 700
    );
  }

  function pushAheadBehind(value) {
    const record = objectRecord(value);
    const ahead = record.ahead;
    const behind = record.behind;
    return ahead === undefined || ahead === null
      || behind === undefined || behind === null
      ? "Not evaluated"
      : String(ahead) + " / " + String(behind);
  }

  function pushCleanliness(value) {
    const record = objectRecord(value);
    if (record.worktree_clean === undefined || record.worktree_clean === null
        || record.index_clean === undefined || record.index_clean === null) {
      return "Not evaluated";
    }
    const staged = record.staged_path_count === undefined
        || record.staged_path_count === null
      ? "unknown"
      : String(record.staged_path_count);
    return "Worktree " + (record.worktree_clean === true ? "clean" : "dirty")
      + " · index " + (record.index_clean === true ? "clean" : "dirty")
      + " · staged paths " + staged;
  }

  function pushCurrentBoundary(parts) {
    const current = Object.assign({}, parts.execution, parts.readiness);
    const reconciliation = objectRecord(parts.result.reconciliation);
    ["ahead", "behind", "worktree_clean", "index_clean", "staged_path_count"]
      .forEach(function (key) {
        if (reconciliation[key] !== undefined && reconciliation[key] !== null) {
          current[key] = reconciliation[key];
        }
      });
    return current;
  }

  function pushDeliveryState(parts) {
    const stateValue = String(
      parts.review.action_state || parts.execution.state
        || parts.readiness.status || "PUSH_BLOCKED"
    ).toUpperCase();
    return Object.prototype.hasOwnProperty.call(PUSH_DELIVERY_STATE_LABELS, stateValue)
      ? stateValue
      : "PUSH_BLOCKED";
  }

  function pushDeliveryBlockers(parts) {
    return applyPlanTextList(parts.execution.blockers, "")
      .concat(applyPlanTextList(parts.readiness.blockers, ""))
      .concat(applyPlanTextList(parts.review.blockers, ""));
  }

  function deliveryStagedPaths(value) {
    if (!Array.isArray(value)) return pushDeliverySummary(value, "Not available", 1000);
    if (!value.length) return "0 paths";
    const paths = value.map(function (item) {
      const record = objectRecord(item);
      return candidateRelativePath(record.path || record.repository_path || item);
    });
    return String(paths.length) + " path" + (paths.length === 1 ? "" : "s")
      + " · " + paths.join(", ");
  }

  function renderPushDeliveryAdvanced(parts) {
    const available = Boolean(pushDeliveryReviewBinding(parts.review));
    elements.pushDeliveryAdvancedCard.hidden = !available;
    if (!available) return;
    const executionAdvanced = objectRecord(parts.execution.advanced);
    const resultAdvanced = objectRecord(parts.result.advanced);
    const readinessAdvanced = objectRecord(parts.readiness.advanced);
    const applyResult = objectRecord(parts.result.apply_result);
    const applyPlanResult = objectRecord(applyResult.apply_plan);
    const candidateResult = objectRecord(parts.result.delivery_candidate);
    const verificationResult = objectRecord(parts.result.post_apply_verification);
    const verificationAdvanced = objectRecord(verificationResult.advanced);
    elements.pushCommitBinding.textContent = postApplyVerificationBinding(
      pushDeliveryReviewBinding(parts.review),
      parts.commit.receipt_digest || commitBuilderRecordDigest(parts.commit)
    );
    elements.pushCandidateBinding.textContent = postApplyVerificationBinding(
      resultAdvanced.delivery_candidate_id || resultAdvanced.candidate_id,
      resultAdvanced.candidate_digest || candidateResult.candidate_digest
    );
    elements.pushApplyPlanBinding.textContent = postApplyVerificationBinding(
      resultAdvanced.apply_plan_id || applyResult.plan_id || applyResult.apply_plan_id
        || applyPlanResult.id,
      resultAdvanced.apply_plan_digest || applyResult.plan_digest
        || applyPlanResult.digest
    );
    elements.pushVerificationBinding.textContent = postApplyVerificationBinding(
      resultAdvanced.post_apply_verification_id || resultAdvanced.verification_id,
      resultAdvanced.verification_digest || verificationResult.verification_digest
        || verificationAdvanced.verification_digest
    );
    elements.pushPreflightRecordId.textContent = postApplyVerificationBinding(
      parts.execution.id,
      ""
    );
    elements.pushPreflightDigest.textContent = boundedText(
      parts.execution.confirmation_digest,
      "None",
      500
    );
    elements.pushAttemptRecordId.textContent = postApplyVerificationBinding(
      parts.execution.attempt_id || parts.execution.id,
      ""
    );
    elements.pushAttemptDigest.textContent = boundedText(
      parts.execution.receipt_digest || executionAdvanced.receipt_digest,
      "None",
      500
    );
    elements.pushExactRefspec.textContent = sanitizedApplyPlanText(
      parts.execution.refspec || executionAdvanced.refspec,
      "None",
      800
    );
    elements.pushRemoteFingerprint.textContent = boundedText(
      executionAdvanced.remote_config_fingerprint
        || executionAdvanced.remote_fingerprint || readinessAdvanced.remote_fingerprint,
      "None",
      500
    );
    elements.pushRepositoryFingerprint.textContent = boundedText(
      executionAdvanced.repository_locator_fingerprint
        || readinessAdvanced.repository_locator_fingerprint
        || resultAdvanced.repository_locator_fingerprint,
      "None",
      500
    );
    elements.pushSanitizedDiagnostics.textContent = sanitizedApplyPlanText(
      diagnosticText(
        parts.execution.diagnostics || parts.result.diagnostics
          || executionAdvanced.diagnostics || executionAdvanced.command_evidence
          || executionAdvanced.failure_category || resultAdvanced.diagnostics,
        ""
      ),
      "No Push diagnostics are available.",
      8000
    );
  }

  function renderDeliveryResult(parts, commitId) {
    const visible = state.pushDeliveryResultVisible.has(String(commitId));
    elements.deliveryResult.hidden = !visible;
    if (!visible) return;
    const result = parts.result;
    const reconciliation = objectRecord(result.reconciliation);
    const approved = String(
      reconciliation.approved_commit_sha || parts.execution.local_commit_sha
        || parts.readiness.local_commit_sha || parts.commit.commit_oid || ""
    );
    const localHead = String(reconciliation.local_head || "");
    const remoteHead = String(reconciliation.origin_main_sha || "");
    const reconciled = Boolean(
      approved && localHead === approved && remoteHead === approved
      && Number(reconciliation.ahead) === 0 && Number(reconciliation.behind) === 0
    );
    elements.deliveryResultStatus.textContent = pushDeliverySummary(
      result.status_label || result.status,
      result.complete === true ? "DELIVERY COMPLETE" : "NOT DELIVERED",
      240
    );
    setStatusLabel(elements.deliveryResultStatus, elements.deliveryResultStatus.textContent);
    elements.deliveryRunResult.textContent = pushDeliverySummary(
      result.run_result,
      "Not available"
    );
    elements.deliveryIndependentVerification.textContent = pushDeliverySummary(
      result.independent_verification,
      "Not available"
    );
    elements.deliveryCandidate.textContent = pushDeliverySummary(
      result.delivery_candidate,
      "Not available"
    );
    elements.deliverySourceDrift.textContent = pushDeliverySummary(
      result.source_drift,
      "Not available"
    );
    elements.deliveryApplyResult.textContent = pushDeliverySummary(
      result.apply_result,
      "Not available"
    );
    elements.deliveryPostApplyVerification.textContent = pushDeliverySummary(
      result.post_apply_verification,
      "Not available"
    );
    elements.deliveryStagedPaths.textContent = deliveryStagedPaths(result.staged_paths);
    const resultLocalCommit = objectRecord(result.local_commit);
    elements.deliveryLocalCommit.textContent = boundedText(
      resultLocalCommit.commit_oid || resultLocalCommit.commit_sha
        || resultLocalCommit.sha || approved,
      "Not available",
      500
    );
    elements.deliveryCommitSubject.textContent = sanitizedApplyPlanText(
      objectRecord(result.local_commit).subject || parts.execution.commit_subject
        || parts.readiness.commit_subject || parts.commitParts.plan.subject,
      "Not available",
      300
    );
    elements.deliveryPushStatus.textContent = pushDeliverySummary(
      result.push_status,
      PUSH_DELIVERY_STATE_LABELS[pushDeliveryState(parts)],
      300
    );
    elements.deliveryReconciliation.textContent = reconciled
      ? "Local HEAD = origin/main = approved commit."
      : pushDeliverySummary(result.reconciliation, "Not reconciled", 1000);
    elements.deliveryLocalHead.textContent = boundedText(localHead, "Not evaluated", 500);
    elements.deliveryOriginMain.textContent = boundedText(remoteHead, "Not evaluated", 500);
    elements.deliveryAheadBehind.textContent = pushAheadBehind(reconciliation);
    elements.deliveryWorktreeIndex.textContent = pushCleanliness(reconciliation);
    elements.deliveryNextAction.textContent = sanitizedApplyPlanText(
      result.next_action,
      result.complete === true && reconciled
        ? "Delivery is complete."
        : "Review the Delivery Result blocker evidence.",
      700
    );
    appendTextList(
      elements.deliveryBoundaries,
      applyPlanTextList(result.boundaries, ""),
      "No delivery boundary evidence is available."
    );
    appendTextList(
      elements.deliveryWarnings,
      applyPlanTextList(result.warnings, ""),
      "No delivery warning is reported."
    );
    appendTextList(
      elements.deliveryBlockers,
      applyPlanTextList(result.blockers, ""),
      "No Delivery Result blocker is reported."
    );
  }

  function renderPushDelivery(run) {
    const parts = pushDeliveryParts(run);
    const commitId = commitBuilderRecordId(parts.commit);
    const validContext = Boolean(commitId);
    elements.pushDeliverySection.hidden = !validContext;
    if (!validContext) {
      elements.pushToOriginMain.hidden = true;
      elements.viewDeliveryResult.hidden = true;
      elements.deliveryResult.hidden = true;
      elements.pushDeliveryAdvancedCard.hidden = true;
      return;
    }
    const stateValue = pushDeliveryState(parts);
    const blockers = pushDeliveryBlockers(parts);
    const canPush = parts.actions.can_push_to_origin_main === true;
    const canConfirm = parts.actions.can_confirm_push === true;
    const canView = parts.actions.can_view_delivery_result === true;
    const currentBoundary = pushCurrentBoundary(parts);
    const confirmationContext = state.pushConfirmationContext;
    if (confirmationContext) {
      const currentExecutionId = String(parts.execution.id || "");
      const currentConfirmationDigest = String(
        parts.execution.confirmation_digest || ""
      );
      const confirmationStillCurrent = canConfirm
        && String(confirmationContext.local_commit_execution_id) === String(commitId)
        && String(confirmationContext.push_execution_id) === currentExecutionId
        && String(confirmationContext.confirmation_digest)
          === currentConfirmationDigest;
      if (!confirmationStillCurrent) {
        state.pushConfirmationContext = null;
        if (elements.pushConfirmationDialog.open) {
          elements.pushConfirmationDialog.close();
        }
      } else {
        elements.confirmPushToOriginMain.disabled = state.pending.has(
          "confirm-push-to-origin-main"
        );
      }
    }
    elements.pushGateStatus.textContent = sanitizedApplyPlanText(
      PUSH_DELIVERY_STATE_LABELS[stateValue] || parts.readiness.status_label,
      PUSH_DELIVERY_STATE_LABELS[stateValue],
      240
    );
    setStatusLabel(elements.pushGateStatus, elements.pushGateStatus.textContent);
    elements.pushLocalCommit.textContent = boundedText(
      parts.readiness.local_commit_sha || parts.execution.local_commit_sha
        || parts.commit.commit_oid || parts.commit.commit_sha,
      "Not available",
      500
    );
    elements.pushCommitSubject.textContent = sanitizedApplyPlanText(
      parts.readiness.commit_subject || parts.execution.commit_subject
        || parts.commitParts.plan.subject,
      "Not available",
      300
    );
    elements.pushDestination.textContent = sanitizedApplyPlanText(
      parts.readiness.destination || parts.execution.destination,
      "origin/main",
      300
    );
    elements.pushRemoteBase.textContent = boundedText(
      parts.readiness.expected_remote_base_sha
        || parts.execution.expected_remote_base_sha,
      "Not evaluated",
      500
    );
    elements.pushAheadBehind.textContent = pushAheadBehind(currentBoundary);
    elements.pushCleanliness.textContent = pushCleanliness(currentBoundary);
    const freshReadinessBlocked = !canConfirm
      && Array.isArray(parts.readiness.blockers)
      && parts.readiness.blockers.length > 0;
    elements.pushNextAction.textContent = sanitizedApplyPlanText(
      (freshReadinessBlocked ? parts.readiness.next_action : "")
        || parts.execution.next_action || parts.readiness.next_action
        || parts.review.next_action,
      stateValue === "PUSHED" ? "View Delivery Result." : "Review Push blockers.",
      700
    );
    appendTextList(
      elements.pushBlockers,
      blockers,
      stateValue === "PUSHED"
        ? "No Push blocker is reported."
        : "No Push blocker is reported."
    );
    elements.pushToOriginMain.hidden = false;
    elements.pushToOriginMain.disabled = !canPush
      || state.pending.has("push-preflight");
    elements.viewDeliveryResult.hidden = false;
    elements.viewDeliveryResult.disabled = !canView
      || state.pending.has("view-delivery-result");
    renderDeliveryResult(parts, commitId);
    renderPushDeliveryAdvanced(parts);
  }

  function ownerDeliveryRecordId(value) {
    const record = objectRecord(value);
    return record.id || record.proposal_id || record.plan_id || record.execution_id
      || record.commit_execution_id || record.push_execution_id || null;
  }

  function ownerDeliveryDigest(value) {
    const record = objectRecord(value);
    const advanced = objectRecord(record.advanced);
    return record.digest || record.verification_digest || record.proposal_digest || record.plan_digest
      || record.approval_digest || record.receipt_digest
      || advanced.verification_digest || advanced.proposal_digest || advanced.plan_digest
      || advanced.approval_digest || advanced.receipt_digest || "";
  }

  function ownerDeliveryParts(run) {
    const projection = objectRecord(ownerDeliveryProjectionForRun(run));
    const commitDelivery = objectRecord(projection.commit_delivery);
    const pushDelivery = objectRecord(projection.push_delivery);
    const applyReview = objectRecord(projection.apply_session);
    const applySession = objectRecord(applyReview.session || applyReview);
    const postApplyReview = objectRecord(
      projection.post_apply_verification
      || commitDelivery.post_apply_verification
    );
    const postApply = objectRecord(postApplyReview.verification || postApplyReview);
    const prerequisites = !projection.load_error
      && String(applySession.state || applySession.apply_state || "").toUpperCase() === "APPLIED"
      && String(postApply.status || postApply.validation_result || "").toUpperCase() === "PASSED";
    const prerequisiteMessage = projection.load_error
      ? "Reload delivery status before Review Commit. " + projection.load_error.message
      : String(applySession.state || applySession.apply_state || "").toUpperCase() !== "APPLIED"
        ? "Return to Apply and complete Apply, then Validate Applied Changes before Review Commit."
        : "Return to Apply and complete Validate Applied Changes before Review Commit.";
    const proposal = objectRecord(
      commitDelivery.proposal || commitDelivery.commit_proposal
      || commitDelivery.plan || commitDelivery.commit_plan
    );
    const commitApproval = objectRecord(
      commitDelivery.approval || commitDelivery.commit_approval
      || proposal.approval
    );
    const commitExecution = objectRecord(
      commitDelivery.execution || commitDelivery.local_commit
      || commitDelivery.commit_execution || proposal.commit
    );
    const pushPlan = objectRecord(
      pushDelivery.plan || pushDelivery.push_plan
    );
    const pushApproval = objectRecord(
      pushDelivery.approval || pushDelivery.push_approval
      || pushPlan.approval
    );
    const pushExecution = objectRecord(
      pushDelivery.execution || pushDelivery.push_execution || pushPlan.execution
    );
    const pushConfirmation = objectRecord(pushDelivery.confirmation);
    const receipt = objectRecord(
      pushDelivery.receipt || pushDelivery.delivery_receipt
      || pushDelivery.delivery_result || pushExecution.receipt
    );
    return {
      projection: projection,
      applyReview: applyReview,
      applySession: applySession,
      postApply: postApply,
      commitPrerequisitesMet: prerequisites,
      commitPrerequisiteMessage: prerequisites ? "" : prerequisiteMessage,
      commitDelivery: commitDelivery,
      proposal: proposal,
      commitApproval: commitApproval,
      commitExecution: commitExecution,
      commitActions: prerequisites ? Object.assign(
        {},
        objectRecord(proposal.actions),
        objectRecord(commitDelivery.actions)
      ) : {},
      pushDelivery: pushDelivery,
      pushPlan: pushPlan,
      pushApproval: pushApproval,
      pushExecution: pushExecution,
      pushConfirmation: pushConfirmation,
      receipt: receipt,
      pushActions: Object.assign(
        {},
        objectRecord(pushPlan.actions),
        objectRecord(pushDelivery.actions)
      )
    };
  }

  function ownerVerifiedRemoteSha(parts) {
    const receipt = objectRecord(parts.receipt);
    return receipt.verified_remote_sha || "";
  }

  function canonicalCommitState(parts) {
    if (parts.commitPrerequisitesMet === false) return "BLOCKED";
    const executionState = String(
      parts.commitExecution.state || parts.commitExecution.status || ""
    ).toUpperCase();
    if (["COMMITTED", "LOCAL_COMMIT_CREATED", "SUCCEEDED"].indexOf(executionState) !== -1) {
      return "LOCAL_COMMIT_CREATED";
    }
    if (executionState === "COMMITTING" || executionState === "RUNNING") return "COMMITTING";
    if (["FAILED", "BLOCKED", "INTEGRITY_BLOCKED", "NEEDS_SETUP", "NEEDS_REVIEW"].indexOf(executionState) !== -1) {
      return executionState;
    }
    const proposalReady = Boolean(ownerDeliveryRecordId(parts.proposal));
    const approvalState = canonicalApprovalState(parts.commitApproval, "PENDING");
    if (proposalReady && approvalState !== "APPROVED"
        && (parts.commitActions.can_approve === true
          || parts.commitActions.can_approve_commit === true
          || parts.commitActions.can_approve_commit_proposal === true)) {
      return "COMMIT_APPROVAL_REQUIRED";
    }
    if (proposalReady && approvalState === "APPROVED"
        && (parts.commitActions.can_commit === true
          || parts.commitActions.can_confirm_commit === true
          || parts.commitActions.can_create_local_commit === true)) {
      return "COMMIT_CONFIRMATION_REQUIRED";
    }
    const stateValue = String(
      parts.commitDelivery.action_state || parts.commitDelivery.state
      || parts.commitDelivery.status || "COMMIT_REVIEW_REQUIRED"
    ).toUpperCase();
    return Object.prototype.hasOwnProperty.call(OWNER_COMMIT_STATE_LABELS, stateValue)
      ? stateValue
      : "COMMIT_REVIEW_REQUIRED";
  }

  function ownerPushConfirmationProjectionRelevant(parts) {
    const confirmation = objectRecord(parts.pushConfirmation);
    return Boolean(
      confirmation.plan_id || confirmation.execution_id
      || ownerDeliveryRecordId(parts.pushPlan) || ownerDeliveryRecordId(parts.pushExecution)
    );
  }

  function ownerPushConfirmationProjectionIsCanonical(projection) {
    const pushDelivery = objectRecord(objectRecord(projection).push_delivery);
    const confirmation = objectRecord(pushDelivery.confirmation);
    return Object.prototype.hasOwnProperty.call(
      OWNER_PUSH_CONFIRMATION_LABELS,
      String(confirmation.state || "").toLowerCase()
    );
  }

  function ownerPushConfirmationLocalRequestState(parts) {
    const uncertainty = objectRecord(state.ownerPushConfirmationUncertainty);
    if (!uncertainty.status) return "";
    const run = currentCodexRun();
    if (String(objectRecord(run).id || "") !== String(uncertainty.run_id || "")) {
      return "";
    }
    const planId = ownerDeliveryRecordId(objectRecord(parts).pushPlan);
    return (
      !planId || !uncertainty.plan_id
      || String(planId) === String(uncertainty.plan_id)
    ) ? String(uncertainty.status) : "";
  }

  function ownerPushConfirmationUncertaintyActive(parts) {
    return ownerPushConfirmationLocalRequestState(parts) === "uncertain";
  }

  function ownerPushConfirmationRequestInFlight(parts) {
    return ownerPushConfirmationLocalRequestState(parts) === "request_dispatched";
  }

  function beginOwnerPushConfirmationReconciliation(context) {
    const runId = String(context.run_id || "");
    state.ownerPushConfirmationUncertainty = {
      status: "request_dispatched",
      run_id: runId,
      plan_id: String(context.plan_id || ""),
      request_identity: String(context.request_identity || ""),
      minimum_projection_sequence:
        Number(state.ownerDeliveryRequestSequences[runId] || 0) + 1,
      message: ""
    };
  }

  function ownerPushRejectionProvesNoEffect(error) {
    const details = objectRecord(error instanceof ApiError ? error.details : null);
    return error instanceof ApiError
      && error.status === 409
      && details.request_accepted === false
      && details.remote_effect === "none";
  }

  function ownerPushRejectionProvesSafeRetry(error) {
    const details = objectRecord(error instanceof ApiError ? error.details : null);
    return ownerPushRejectionProvesNoEffect(error) && details.retry_safe === true;
  }

  function markOwnerPushConfirmationUncertain(context, reconciliationEvidence) {
    const current = objectRecord(state.ownerPushConfirmationUncertainty);
    const evidence = objectRecord(reconciliationEvidence);
    state.ownerPushConfirmationUncertainty = {
      status: "uncertain",
      run_id: String(context.run_id || current.run_id || ""),
      plan_id: String(context.plan_id || current.plan_id || ""),
      request_identity: String(
        context.request_identity || current.request_identity || ""
      ),
      minimum_projection_sequence: Number(
        current.minimum_projection_sequence
        || state.ownerDeliveryRequestSequences[String(context.run_id || "")]
        || 0
      ),
      allow_no_execution_reconciliation:
        evidence.allow_no_execution_reconciliation === true
        || current.allow_no_execution_reconciliation === true,
      allow_ready_reconciliation: evidence.allow_ready_reconciliation === true
        || current.allow_ready_reconciliation === true,
      message: "The Push response could not be reconciled safely. No automatic retry is available until TWOS successfully reloads canonical execution and remote evidence."
    };
  }

  function resolveOwnerPushConfirmationUncertainty(runId, projection, requestSequence) {
    const current = objectRecord(state.ownerPushConfirmationUncertainty);
    if (!current.status || String(current.run_id || "") !== String(runId || "")) {
      return false;
    }
    if (!ownerPushConfirmationProjectionIsCanonical(projection)) return false;
    const pushDelivery = objectRecord(objectRecord(projection).push_delivery);
    const confirmation = objectRecord(pushDelivery.confirmation);
    const durableExecutionObserved = confirmation.request_accepted === true
      && Boolean(confirmation.execution_id);
    if (current.allow_ready_reconciliation !== true
        && String(confirmation.state || "").toLowerCase() === "ready_for_confirmation") {
      return false;
    }
    if (!durableExecutionObserved
        && current.allow_no_execution_reconciliation !== true) {
      return false;
    }
    if (requestSequence !== null && requestSequence !== undefined
        && Number(requestSequence) < Number(current.minimum_projection_sequence || 0)) {
      return false;
    }
    state.ownerPushConfirmationUncertainty = null;
    return true;
  }

  function ownerPushConfirmationCanConfirm(parts) {
    if (ownerPushConfirmationUncertaintyActive(parts)
        || ownerPushConfirmationRequestInFlight(parts)) return false;
    const confirmation = objectRecord(parts.pushConfirmation);
    const confirmationState = String(confirmation.state || "").toLowerCase();
    if (ownerPushConfirmationProjectionRelevant(parts)
        && Object.prototype.hasOwnProperty.call(
          OWNER_PUSH_CONFIRMATION_LABELS,
          confirmationState
        )) {
      return confirmationState === "ready_for_confirmation"
        && confirmation.can_confirm === true
        && /^[0-9a-f]{64}$/.test(String(confirmation.request_identity || ""));
    }
    if (ownerPushConfirmationProjectionRelevant(parts)) return false;
    return parts.pushActions.can_confirm_push === true
      || parts.pushActions.can_push === true;
  }

  function canonicalPushState(parts) {
    const localPhase = String(state.ownerPushConfirmationState.phase || "");
    if (state.pending.has("confirm-owner-push")
        && ["submitting", "running"].indexOf(localPhase) !== -1) {
      return "PUSHING";
    }
    if (ownerPushConfirmationRequestInFlight(parts)) return "PUSHING";
    if (ownerPushConfirmationUncertaintyActive(parts)) return "NEEDS_REVIEW";
    const confirmation = objectRecord(parts.pushConfirmation);
    const confirmationState = String(confirmation.state || "").toLowerCase();
    if (ownerPushConfirmationProjectionRelevant(parts)) {
      const confirmationStates = {
        ready_for_confirmation: "PUSH_CONFIRMATION_REQUIRED",
        submitting: "PUSHING",
        running: "PUSHING",
        succeeded: "DELIVERED",
        already_delivered: "ALREADY_DELIVERED",
        blocked: "BLOCKED",
        failed: "FAILED",
        timed_out: "TIMED_OUT",
        needs_review: "NEEDS_REVIEW"
      };
      if (Object.prototype.hasOwnProperty.call(confirmationStates, confirmationState)) {
        return confirmationStates[confirmationState];
      }
      return "NEEDS_REVIEW";
    }
    const receiptState = String(
      parts.receipt.state || parts.receipt.status || parts.receipt.classification || ""
    ).toUpperCase();
    if (["DELIVERED", "SUCCEEDED", "PUSHED"].indexOf(receiptState) !== -1) return "DELIVERED";
    if (receiptState === "ALREADY_DELIVERED") return "ALREADY_DELIVERED";
    const executionState = String(
      parts.pushExecution.state || parts.pushExecution.status || ""
    ).toUpperCase();
    if (["DELIVERED", "SUCCEEDED", "PUSHED"].indexOf(executionState) !== -1) return "DELIVERED";
    if (executionState === "ALREADY_DELIVERED") return "ALREADY_DELIVERED";
    if (executionState === "PUSHING" || executionState === "RUNNING") return "PUSHING";
    if (["FAILED", "BLOCKED", "TIMED_OUT", "NEEDS_SETUP", "NEEDS_REVIEW"].indexOf(executionState) !== -1) {
      return executionState;
    }
    const planReady = Boolean(ownerDeliveryRecordId(parts.pushPlan));
    const approvalState = canonicalApprovalState(parts.pushApproval, "PENDING");
    if (planReady && approvalState !== "APPROVED"
        && (parts.pushActions.can_approve === true
          || parts.pushActions.can_approve_push_plan === true)) {
      return "PUSH_APPROVAL_REQUIRED";
    }
    if (planReady && approvalState === "APPROVED"
        && (parts.pushActions.can_push === true
          || parts.pushActions.can_confirm_push === true)) {
      return "PUSH_CONFIRMATION_REQUIRED";
    }
    const stateValue = String(
      parts.pushDelivery.action_state || parts.pushDelivery.state
      || parts.pushDelivery.status || "PUSH_REVIEW_REQUIRED"
    ).toUpperCase();
    return Object.prototype.hasOwnProperty.call(OWNER_PUSH_STATE_LABELS, stateValue)
      ? stateValue
      : "PUSH_REVIEW_REQUIRED";
  }

  function canonicalApprovalState(approval, fallback) {
    const record = objectRecord(approval);
    return String(record.state || record.status || record.approval_state || fallback).toUpperCase();
  }

  function ownerDeliveryPathEntries(record, included) {
    const value = objectRecord(record);
    const direct = included
      ? value.included_paths || value.included_files || value.approved_files
        || value.exact_paths || value.paths || value.files
      : value.excluded_paths || value.excluded_files || value.unrelated_paths;
    return Array.isArray(direct) ? direct : [];
  }

  function renderOwnerDeliverySequence(parts, commitState, pushState) {
    const proposalReady = Boolean(ownerDeliveryRecordId(parts.proposal));
    const commitApproved = canonicalApprovalState(parts.commitApproval, "PENDING") === "APPROVED";
    const committed = commitState === "LOCAL_COMMIT_CREATED";
    const pushPlanReady = Boolean(ownerDeliveryRecordId(parts.pushPlan));
    const pushApproved = canonicalApprovalState(parts.pushApproval, "PENDING") === "APPROVED";
    const pushStarted = Boolean(ownerDeliveryRecordId(parts.pushExecution));
    const delivered = ["DELIVERED", "ALREADY_DELIVERED"].indexOf(pushState) !== -1;
    const complete = {
      applied: true,
      commit_review: proposalReady,
      commit_approval: commitApproved,
      commit_confirmation: committed,
      committed: committed,
      push_review: pushPlanReady,
      push_approval: pushApproved,
      push_confirmation: pushStarted,
      delivered: delivered
    };
    let currentAssigned = false;
    document.querySelectorAll("#owner-delivery-sequence [data-delivery-step]").forEach(function (item) {
      const key = item.dataset.deliveryStep;
      item.dataset.state = complete[key] ? "complete" : "pending";
      item.removeAttribute("aria-current");
      if (!complete[key] && !currentAssigned) {
        item.dataset.state = "current";
        item.setAttribute("aria-current", "step");
        currentAssigned = true;
      }
    });
  }

  function renderCanonicalCommitAdvanced(parts) {
    const proposalAdvanced = objectRecord(parts.proposal.advanced);
    const approvalAdvanced = objectRecord(parts.commitApproval.advanced);
    const executionAdvanced = objectRecord(parts.commitExecution.advanced);
    elements.commitBuilderAdvancedCard.hidden = !ownerDeliveryRecordId(parts.proposal);
    if (elements.commitBuilderAdvancedCard.hidden) return;
    elements.commitPlanRecordId.textContent = boundedText(ownerDeliveryRecordId(parts.proposal), "None", 240);
    elements.commitProposalVersion.textContent = boundedText(
      parts.proposal.version || parts.proposal.proposal_version,
      "None",
      80
    );
    elements.commitProposalApprovalRecord.textContent = boundedText(
      ownerDeliveryRecordId(parts.commitApproval),
      "None",
      240
    );
    elements.commitProposalApprovalDigest.textContent = boundedText(
      ownerDeliveryDigest(parts.commitApproval),
      "None",
      500
    );
    elements.commitPlanDigest.textContent = boundedText(ownerDeliveryDigest(parts.proposal), "None", 500);
    elements.localCommitTreeSha.textContent = boundedText(
      parts.commitExecution.tree_sha || parts.commitExecution.tree_oid || executionAdvanced.tree_sha
        || executionAdvanced.tree_oid,
      "None",
      500
    );
    elements.commitProposalMessageBody.textContent = sanitizedApplyPlanText(
      parts.proposal.body || proposalAdvanced.body,
      "None",
      4000
    );
    elements.commitProposalAuthor.textContent = sanitizedApplyPlanText(
      parts.proposal.author || parts.proposal.author_identity || proposalAdvanced.author,
      "None",
      500
    );
    elements.localCommitArgv.textContent = sanitizedApplyPlanText(
      executionAdvanced.argv || executionAdvanced.command_argv,
      "None",
      1200
    );
    elements.localCommitProcessIdentity.textContent = boundedText(
      executionAdvanced.process_identity || parts.commitExecution.process_identity,
      "None",
      500
    );
    if (approvalAdvanced.approval_digest && !ownerDeliveryDigest(parts.commitApproval)) {
      elements.commitProposalApprovalDigest.textContent = boundedText(
        approvalAdvanced.approval_digest,
        "None",
        500
      );
    }
  }

  function renderCanonicalPushAdvanced(parts) {
    const planAdvanced = objectRecord(parts.pushPlan.advanced);
    const approvalAdvanced = objectRecord(parts.pushApproval.advanced);
    const executionAdvanced = objectRecord(parts.pushExecution.advanced);
    const receiptAdvanced = objectRecord(parts.receipt.advanced);
    elements.pushDeliveryAdvancedCard.hidden = !ownerDeliveryRecordId(parts.pushPlan)
      && !ownerDeliveryRecordId(parts.pushExecution);
    if (elements.pushDeliveryAdvancedCard.hidden) return;
    elements.pushPlanRecordId.textContent = boundedText(ownerDeliveryRecordId(parts.pushPlan), "None", 240);
    elements.pushPlanVersion.textContent = boundedText(
      parts.pushPlan.version || parts.pushPlan.plan_version,
      "None",
      80
    );
    elements.pushPlanDigest.textContent = boundedText(ownerDeliveryDigest(parts.pushPlan), "None", 500);
    elements.pushPlanApprovalRecord.textContent = boundedText(ownerDeliveryRecordId(parts.pushApproval), "None", 240);
    elements.pushPlanApprovalDigest.textContent = boundedText(
      ownerDeliveryDigest(parts.pushApproval) || approvalAdvanced.approval_digest,
      "None",
      500
    );
    elements.pushRemoteDescriptor.textContent = sanitizedApplyPlanText(
      parts.pushPlan.remote_descriptor || planAdvanced.remote_descriptor,
      "None",
      800
    );
    elements.pushExecutionArgv.textContent = sanitizedApplyPlanText(
      executionAdvanced.argv || executionAdvanced.command_argv,
      "None",
      1200
    );
    elements.pushProcessIdentity.textContent = boundedText(
      executionAdvanced.process_identity || parts.pushExecution.process_identity,
      "None",
      500
    );
    elements.pushRemoteReceipt.textContent = sanitizedApplyPlanText(
      parts.receipt.receipt || parts.receipt.summary || receiptAdvanced.receipt,
      "None",
      1600
    );
  }

  function renderOwnerCommitPushDelivery(run) {
    const canonical = canonicalOwnerDeliveryAvailable(run);
    elements.commitBuilderSection.dataset.ownerDelivery = canonical ? "canonical" : "legacy";
    elements.pushDeliverySection.dataset.ownerDelivery = canonical ? "canonical" : "legacy";
    elements.canonicalCommitBuilderControls.hidden = !canonical;
    elements.legacyCommitBuilderControls.hidden = canonical;
    elements.canonicalPushDeliveryControls.hidden = !canonical;
    elements.legacyPushDeliveryControls.hidden = canonical;
    if (!canonical) return;
    const parts = ownerDeliveryParts(run);
    const commitState = canonicalCommitState(parts);
    const pushState = canonicalPushState(parts);
    const proposalId = ownerDeliveryRecordId(parts.proposal);
    const commitId = ownerDeliveryRecordId(parts.commitExecution);
    const committed = commitState === "LOCAL_COMMIT_CREATED";
    const pushPlanId = ownerDeliveryRecordId(parts.pushPlan);
    const approved = ownerDeliveryPathEntries(parts.proposal, true);
    const excluded = ownerDeliveryPathEntries(parts.proposal, false);
    const commitBlockers = applyPlanTextList(parts.commitDelivery.blockers, "")
      .concat(applyPlanTextList(parts.proposal.blockers, ""))
      .concat(applyPlanTextList(parts.commitExecution.blockers, ""));
    const pushBlockers = applyPlanTextList(parts.pushDelivery.blockers, "")
      .concat(applyPlanTextList(parts.pushPlan.blockers, ""))
      .concat(applyPlanTextList(parts.pushExecution.blockers, ""));
    const pushConfirmationPhase = ownerPushConfirmationPhaseFor(parts);
    if (["blocked", "failed", "timed_out", "needs_review"].indexOf(pushConfirmationPhase) !== -1) {
      pushBlockers.unshift(
        ownerPushConfirmationReason(parts, "Push confirmation is blocked.")
      );
    }
    const commitApprovalState = canonicalApprovalState(parts.commitApproval, "PENDING");
    const pushApprovalState = canonicalApprovalState(parts.pushApproval, "PENDING");
    const proposalAdvanced = objectRecord(parts.proposal.advanced);
    const pushPlanAdvanced = objectRecord(parts.pushPlan.advanced);
    const commitAdvanced = objectRecord(parts.commitExecution.advanced);
    const pushAdvanced = objectRecord(parts.pushExecution.advanced);
    const authorReadiness = objectRecord(parts.commitDelivery.author_readiness);

    if (state.ownerCommitConfirmationContext) {
      const current = state.ownerCommitConfirmationContext;
      const stillCurrent = String(current.run_id) === String(run.id)
        && String(current.proposal_id) === String(proposalId || "")
        && String(current.proposal_digest) === String(ownerDeliveryDigest(parts.proposal))
        && String(current.approval_digest) === String(ownerDeliveryDigest(parts.commitApproval))
        && (parts.commitActions.can_confirm_commit === true
          || parts.commitActions.can_create_local_commit === true
          || parts.commitActions.can_commit === true);
      if (!stillCurrent) {
        state.ownerCommitConfirmationContext = null;
        if (elements.ownerLocalCommitConfirmationDialog.open) {
          elements.ownerLocalCommitConfirmationDialog.close();
        }
      }
    }
    if (state.ownerPushConfirmationContext) {
      const current = state.ownerPushConfirmationContext;
      const stillCurrent = String(current.run_id) === String(run.id)
        && String(current.plan_id) === String(pushPlanId || "")
        && String(current.plan_digest) === String(ownerDeliveryDigest(parts.pushPlan))
        && String(current.approval_digest) === String(ownerDeliveryDigest(parts.pushApproval));
      if (!stillCurrent) {
        state.ownerPushConfirmationContext = null;
        if (elements.ownerPushConfirmationDialog.open) {
          elements.ownerPushConfirmationDialog.close();
        }
      } else {
        const persistedPhase = ownerPushConfirmationPhaseFor(parts);
        const localRequestPending = state.pending.has("confirm-owner-push");
        if (!localRequestPending || persistedPhase !== "ready_for_confirmation") {
          setOwnerPushConfirmationPhase(
            persistedPhase,
            ownerPushConfirmationReason(
              parts,
              persistedPhase === "ready_for_confirmation"
                ? "The approved Push Plan is ready for one explicit confirmation."
                : "Review the current persisted Push confirmation state."
            ),
            { request_identity: current.request_identity }
          );
        }
      }
    }

    elements.commitBuilderSection.hidden = false;
    elements.pushDeliverySection.hidden = !committed;
    elements.ownerCommitApplyState.textContent = humanStatus(
      parts.applySession.apply_state || parts.applySession.state || (parts.projection.load_error ? "Unavailable" : "Not applied")
    );
    elements.ownerCommitPostApplyValidation.textContent = humanStatus(
      parts.postApply.status || parts.postApply.validation_result || (parts.projection.load_error ? "Unavailable" : "Not verified")
    );
    elements.commitBuilderStatus.textContent = OWNER_COMMIT_STATE_LABELS[commitState];
    setStatusLabel(elements.commitBuilderStatus, elements.commitBuilderStatus.textContent);
    elements.commitPlanSummary.textContent = proposalId
      ? "Proposal v" + String(parts.proposal.version || parts.proposal.proposal_version || "1")
      : "Not reviewed";
    elements.commitProposalApproval.textContent = humanStatus(commitApprovalState);
    setStatusLabel(elements.commitProposalApproval, elements.commitProposalApproval.textContent);
    elements.commitApprovedSummary.textContent = proposalId
      ? String(approved.length) + " approved path" + (approved.length === 1 ? "" : "s")
      : "Not reviewed";
    elements.commitIncludedCount.textContent = String(approved.length);
    elements.commitExcludedSummary.textContent = proposalId
      ? excluded.length
        ? String(excluded.length) + " excluded path" + (excluded.length === 1 ? "" : "s")
        : "None"
      : "Not reviewed";
    elements.commitUnrelatedWarning.textContent = excluded.length
      ? "Warning — " + String(excluded.length) + " unrelated path"
        + (excluded.length === 1 ? " is" : "s are") + " excluded and preserved."
      : "No unrelated path is included.";
    elements.commitBuilderBranch.textContent = sanitizedApplyPlanText(
      parts.proposal.branch || proposalAdvanced.branch,
      "Not reviewed",
      240
    );
    const parentSha = parts.proposal.expected_parent_sha || parts.proposal.parent_sha
      || parts.proposal.base_head || proposalAdvanced.expected_parent_sha
      || proposalAdvanced.base_head;
    elements.commitBuilderHead.textContent = boundedText(parentSha, "Not reviewed", 500);
    elements.commitExpectedParent.textContent = boundedText(parentSha, "Not reviewed", 500);
    elements.commitBuilderSubject.textContent = sanitizedApplyPlanText(
      parts.proposal.subject,
      "Not reviewed",
      200
    );
    elements.commitAuthorReadiness.textContent = humanStatus(
      parts.proposal.author_readiness || authorReadiness.status_label || authorReadiness.status
      || "not evaluated"
    );
    elements.commitBuilderValidation.textContent = pushDeliverySummary(
      parts.proposal.validation || parts.commitDelivery.validation,
      "Not reviewed",
      700
    );
    elements.commitStageSummary.textContent = proposalId
      ? "Internal exact-path staging occurs only after final Commit confirmation."
      : "Not started";
    const commitSha = parts.commitExecution.commit_sha || parts.commitExecution.commit_oid
      || commitAdvanced.commit_sha || commitAdvanced.commit_oid;
    elements.localCommitSummary.textContent = commitId
      ? OWNER_COMMIT_STATE_LABELS[commitState] + (commitSha ? " · " + boundedText(commitSha, "", 200) : "")
      : "Not created";
    elements.ownerLocalCommitSha.textContent = boundedText(commitSha, "Not created", 500);
    const projectionNext = objectRecord(parts.projection.next_action);
    elements.commitBuilderNextAction.textContent = sanitizedApplyPlanText(
      parts.commitPrerequisiteMessage || parts.commitDelivery.next_action || (committed ? "Review Push Plan." : projectionNext.message),
      commitState === "COMMIT_REVIEW_REQUIRED"
        ? "Select Review Commit."
        : commitState === "COMMIT_APPROVAL_REQUIRED"
          ? "Select Approve Commit."
          : commitState === "COMMIT_CONFIRMATION_REQUIRED"
            ? "Select Confirm Local Commit."
            : committed ? "Review Push Plan." : "Review Commit blockers.",
      700
    );
    renderCommitBuilderFiles(elements.commitApprovedFiles, approved, false);
    renderCommitBuilderFiles(elements.commitExcludedFiles, excluded, true);
    appendTextList(elements.commitBuilderBlockers, commitBlockers, "No Commit blocker is reported.");

    if (!proposalId && !elements.commitPlanSubject.value.trim()) {
      const task = selectedTask();
      const taskName = task ? task.title || task.development_task : "approved changes";
      elements.commitPlanSubject.value = "Apply " + String(taskName || "approved changes");
    }
    if (proposalId) {
      elements.commitPlanSubject.value = boundedText(parts.proposal.subject, elements.commitPlanSubject.value, 200);
      elements.commitPlanBody.value = boundedText(parts.proposal.body, elements.commitPlanBody.value, 4000);
    }
    const canRevise = parts.commitActions.can_create_proposal === true
      || parts.commitActions.can_edit === true
      || parts.commitActions.can_review_commit === true
      || parts.commitActions.can_review_commit_proposal === true;
    elements.commitMessageFields.hidden = commitApprovalState === "APPROVED" || Boolean(commitId);
    elements.commitPlanSubject.disabled = !canRevise;
    elements.commitPlanBody.disabled = !canRevise;
    elements.reviewOwnerCommit.hidden = false;
    elements.reviewOwnerCommit.disabled = !canRevise || state.pending.has("review-owner-commit");
    elements.approveCommitProposal.hidden = false;
    elements.approveCommitProposal.disabled = !(
      parts.commitActions.can_approve_commit === true
      || parts.commitActions.can_approve_commit_proposal === true
      || parts.commitActions.can_approve === true
    ) || state.pending.has("approve-commit-proposal");
    elements.confirmOwnerLocalCommit.hidden = false;
    elements.confirmOwnerLocalCommit.disabled = !(
      parts.commitActions.can_confirm_commit === true
      || parts.commitActions.can_create_local_commit === true
      || parts.commitActions.can_commit === true
    ) || state.pending.has("confirm-owner-local-commit");
    renderCanonicalCommitAdvanced(parts);

    if (committed) {
      elements.pushGateStatus.textContent = OWNER_PUSH_STATE_LABELS[pushState];
      setStatusLabel(elements.pushGateStatus, elements.pushGateStatus.textContent);
      elements.pushLocalCommit.textContent = boundedText(
        parts.pushPlan.local_commit_sha || parts.pushPlan.expected_new_sha || commitSha,
        "Not available",
        500
      );
      elements.pushCommitSubject.textContent = sanitizedApplyPlanText(
        parts.pushPlan.commit_subject || parts.proposal.subject,
        "Not available",
        300
      );
      elements.pushPlanApproval.textContent = humanStatus(pushApprovalState);
      setStatusLabel(elements.pushPlanApproval, elements.pushPlanApproval.textContent);
      elements.pushDestination.textContent = sanitizedApplyPlanText(
        parts.pushPlan.destination || parts.pushPlan.target_ref || pushPlanAdvanced.target_ref,
        "origin/main",
        300
      );
      const remoteOldSha = parts.pushPlan.remote_old_sha || parts.pushPlan.expected_remote_old_sha
        || parts.pushPlan.expected_remote_base_sha || pushPlanAdvanced.remote_old_sha;
      const remoteNewSha = parts.pushPlan.remote_new_sha || parts.pushPlan.expected_new_sha
        || parts.pushPlan.local_commit_sha || commitSha;
      elements.pushRemoteBase.textContent = boundedText(remoteOldSha, "Not evaluated", 500);
      elements.pushProposedNewSha.textContent = boundedText(remoteNewSha, "Not evaluated", 500);
      elements.pushFastForwardReadiness.textContent = humanStatus(
        parts.pushPlan.fast_forward_status || parts.pushPlan.fast_forward
        || parts.pushDelivery.fast_forward_status || "not evaluated"
      );
      elements.pushProgress.textContent = OWNER_PUSH_STATE_LABELS[pushState];
      const verifiedRemoteSha = ownerVerifiedRemoteSha(parts);
      elements.pushFinalRemoteSha.textContent = boundedText(
        verifiedRemoteSha,
        ["DELIVERED", "ALREADY_DELIVERED"].indexOf(pushState) !== -1
          ? "Verified receipt requires review"
          : "Not delivered",
        500
      );
      elements.pushReceiptSummary.textContent = sanitizedApplyPlanText(
        parts.receipt.summary || parts.receipt.classification || parts.receipt.status_label,
        ["DELIVERED", "ALREADY_DELIVERED"].indexOf(pushState) !== -1
          ? "Remote SHA verified."
          : "Not available",
        1000
      );
      elements.pushNextAction.textContent = sanitizedApplyPlanText(
        (ownerPushConfirmationProjectionRelevant(parts)
          || ownerPushConfirmationUncertaintyActive(parts))
          ? ownerPushConfirmationReason(parts, "Review the current Push confirmation state.")
          : parts.pushDelivery.next_action || projectionNext.message,
        pushState === "PUSH_REVIEW_REQUIRED"
          ? "Select Review Push Plan."
          : pushState === "PUSH_APPROVAL_REQUIRED"
            ? "Select Approve Push Plan."
            : pushState === "PUSH_CONFIRMATION_REQUIRED"
              ? "Select Confirm Push."
              : pushState === "DELIVERED" ? "Delivery is complete." : "Review Push blockers.",
        700
      );
      appendTextList(elements.pushBlockers, pushBlockers, "No Push blocker is reported.");
      elements.reviewPushPlan.hidden = false;
      elements.reviewPushPlan.disabled = !(
        parts.pushActions.can_review_push_plan === true
        || parts.pushActions.can_create_plan === true
      )
        || state.pending.has("review-push-plan");
      elements.approvePushPlan.hidden = false;
      elements.approvePushPlan.disabled = !(
        parts.pushActions.can_approve_push_plan === true
        || parts.pushActions.can_approve === true
      )
        || state.pending.has("approve-push-plan");
      elements.confirmOwnerPush.hidden = false;
      elements.confirmOwnerPush.disabled = !ownerPushConfirmationCanConfirm(parts)
        || state.pending.has("confirm-owner-push");
      elements.confirmOwnerPush.title = elements.confirmOwnerPush.disabled
        ? ownerPushConfirmationReason(parts, "Push confirmation is not currently eligible.")
        : "";
      renderCanonicalPushAdvanced(parts);
    }

    if (committed) {
      elements.revertAppliedChanges.hidden = true;
      elements.revertAppliedChanges.disabled = true;
      elements.revertAppliedChanges.title = "Working-tree Revert is unavailable after Local Commit.";
      elements.applySessionRevertAvailability.textContent = "Unavailable after Local Commit";
      elements.applySessionRecovery.textContent = "Committed history is preserved";
      elements.applySessionNextAction.textContent = "Review Push Plan. History-preserving Commit recovery belongs to a later flow.";
      elements.applySessionBoundaryNote.textContent = "The original working-tree Revert cannot erase or rewrite a local commit. No reset, amend, force, or branch rewrite is offered.";
    } else {
      elements.applySessionBoundaryNote.textContent = "Only INCLUDED Apply Plan paths are eligible. Apply and Revert do not stage, commit, or push.";
    }
    renderOwnerDeliverySequence(parts, commitState, pushState);
  }

  function confirmationListText(value, fallback) {
    const paths = applySessionPathsFrom(value);
    return paths.length ? paths.join(", ") : fallback;
  }

  function openApplyConfirmation() {
    const run = currentCodexRun();
    const parts = applySessionReviewParts(run);
    if (parts.actions.can_apply !== true || !parts.plan.id) return;
    const entries = Array.isArray(parts.plan.entries) ? parts.plan.entries : [];
    const counts = applySessionOperationCounts(entries, parts.applyConfirmation.operation_counts);
    const planAdvanced = objectRecord(parts.plan.advanced);
    const candidateReview = objectRecord(deliveryCandidateReviewForRun(run));
    const candidate = objectRecord(candidateReview.candidate);
    const planApproval = objectRecord(parts.plan.approval);
    const planApprovalAdvanced = objectRecord(planApproval.advanced);
    state.applyConfirmationContext = {
      plan_id: String(parts.plan.id),
      plan_digest: String(planAdvanced.plan_digest || ""),
      candidate_digest: String(
        planAdvanced.candidate_digest
        || objectRecord(candidate.advanced).candidate_digest
        || candidate.candidate_digest
        || ""
      ),
      plan_approval_digest: String(planApprovalAdvanced.approval_digest || ""),
      result_digest: String(planAdvanced.result_digest || ""),
      result_review_decision_digest: String(
        planAdvanced.result_review_decision_digest || ""
      )
    };
    elements.applyConfirmationPlan.textContent = "Plan " + String(parts.plan.id)
      + " · version " + String(parts.plan.version || "unknown");
    elements.applyConfirmationCandidate.textContent = candidate.id
      ? "Candidate " + String(candidate.id)
      : boundedText(planAdvanced.candidate_id, "Unavailable", 200);
    elements.applyConfirmationDrift.textContent = sanitizedApplyPlanText(
      parts.applyConfirmation.drift_status_label
      || parts.plan.drift_status_label,
      "Not evaluated",
      200
    );
    elements.applyConfirmationOperations.textContent = String(counts.CREATE)
      + " / " + String(counts.MODIFY)
      + " / " + String(counts.DELETE);
    elements.applyConfirmationIncluded.textContent = confirmationListText(
      parts.applyConfirmation.included_paths
      || entries.filter(function (entry) {
        return applyPlanDisposition(objectRecord(entry).disposition) === "INCLUDED";
      }),
      "None"
    );
    elements.applyConfirmationExcluded.textContent = confirmationListText(
      parts.applyConfirmation.excluded_paths
      || entries.filter(function (entry) {
        return applyPlanDisposition(objectRecord(entry).disposition) !== "INCLUDED";
      }),
      "None"
    );
    elements.applyConfirmationUnrelated.textContent = confirmationListText(
      parts.applyConfirmation.unrelated_paths,
      "None reported"
    );
    elements.applyConfirmationIndex.textContent = sanitizedApplyPlanText(
      parts.applyConfirmation.index_boundary,
      "Index must remain unchanged · staged paths 0",
      300
    );
    elements.applyConfirmationDialog.showModal();
    window.setTimeout(function () { elements.cancelApplyAcceptedChanges.focus(); }, 0);
  }

  function openRevertConfirmation() {
    const run = currentCodexRun();
    const parts = applySessionReviewParts(run);
    if (parts.actions.can_revert !== true || !parts.session.id) return;
    state.revertConfirmationContext = {
      session_id: String(parts.session.id),
      journal_digest: String(
        objectRecord(parts.session.advanced).journal_digest
        || parts.session.journal_digest
        || ""
      )
    };
    elements.revertConfirmationSession.textContent = "Apply session " + String(parts.session.id);
    elements.revertConfirmationPaths.textContent = confirmationListText(
      parts.revertConfirmation.paths,
      "No paths available"
    );
    elements.revertConfirmationOperations.textContent = applyPlanTextList(
      parts.revertConfirmation.reverse_operations,
      "Exact reverse operations will be derived from the durable journal."
    ).join(" · ");
    elements.revertConfirmationPreconditions.textContent = sanitizedApplyPlanText(
      parts.revertConfirmation.preconditions,
      "Every path must match its exact Apply after-state.",
      600
    );
    elements.revertConfirmationUnrelated.textContent = confirmationListText(
      parts.revertConfirmation.unrelated_paths,
      "Remain untouched"
    );
    elements.revertConfirmationIndex.textContent = sanitizedApplyPlanText(
      parts.revertConfirmation.index_boundary,
      "Index must remain unchanged · staged paths 0",
      300
    );
    elements.revertConfirmationDialog.showModal();
    window.setTimeout(function () { elements.cancelRevertAppliedChanges.focus(); }, 0);
  }

  function openStageConfirmation() {
    const parts = commitBuilderParts(currentCodexRun());
    const planId = commitBuilderRecordId(parts.plan);
    if (!planId || !(
      parts.actions.can_stage_approved_files === true
      || parts.actions.can_stage === true
    )) return;
    const advanced = objectRecord(parts.plan.advanced);
    const boundaryEvidence = objectRecord(advanced.boundary_evidence);
    const indexEvidence = objectRecord(boundaryEvidence.index);
    const approved = commitBuilderEntries(parts.plan, true);
    const excluded = commitBuilderEntries(parts.plan, false);
    state.stageConfirmationContext = {
      plan_id: String(planId),
      plan_digest: commitBuilderRecordDigest(parts.plan),
      verification_id: String(parts.verification.id || "")
    };
    elements.stageConfirmationPlan.textContent = postApplyVerificationBinding(
      planId,
      commitBuilderRecordDigest(parts.plan)
    );
    elements.stageConfirmationVerification.textContent = postApplyVerificationBinding(
      parts.verification.id,
      parts.verification.verification_digest
    );
    elements.stageConfirmationApproved.textContent = approved.length
      ? approved.map(commitBuilderPath).join(", ")
      : "None";
    elements.stageConfirmationExcluded.textContent = excluded.length
      ? excluded.map(commitBuilderPath).join(", ")
      : "None";
    elements.stageConfirmationHead.textContent = boundedText(
      advanced.base_head || boundaryEvidence.head,
      "Not evaluated",
      500
    );
    elements.stageConfirmationIndex.textContent = boundedText(
      advanced.index_fingerprint || indexEvidence.fingerprint,
      "Not evaluated",
      500
    );
    elements.stageConfirmationDialog.showModal();
    window.setTimeout(function () { elements.cancelStageApprovedFiles.focus(); }, 0);
  }

  function openLocalCommitConfirmation() {
    const parts = commitBuilderParts(currentCodexRun());
    const planId = commitBuilderRecordId(parts.plan);
    const stageId = commitBuilderRecordId(parts.stage);
    if (!planId || !stageId || !(
      parts.actions.can_create_local_commit === true
      || parts.actions.can_commit === true
    )) return;
    const planAdvanced = objectRecord(parts.plan.advanced);
    const stageAdvanced = objectRecord(parts.stage.advanced);
    const staged = commitBuilderEntries(parts.stage, true);
    state.localCommitConfirmationContext = {
      plan_id: String(planId),
      stage_id: String(stageId),
      plan_digest: commitBuilderRecordDigest(parts.plan),
      stage_digest: commitBuilderRecordDigest(parts.stage),
      verification_id: String(parts.verification.id || "")
    };
    elements.localCommitConfirmationStage.textContent = postApplyVerificationBinding(
      stageId,
      commitBuilderRecordDigest(parts.stage)
    );
    elements.localCommitConfirmationPaths.textContent = staged.length
      ? staged.map(commitBuilderPath).join(", ")
      : String(parts.stage.staged_path_count || 0) + " staged paths";
    elements.localCommitConfirmationSubject.textContent = sanitizedApplyPlanText(
      parts.plan.subject,
      "None",
      200
    );
    elements.localCommitConfirmationBody.textContent = sanitizedApplyPlanText(
      parts.plan.body,
      "None",
      1200
    );
    elements.localCommitConfirmationBranch.textContent = sanitizedApplyPlanText(
      planAdvanced.branch || stageAdvanced.branch,
      "Not evaluated",
      240
    );
    elements.localCommitConfirmationParent.textContent = boundedText(
      stageAdvanced.parent_sha || stageAdvanced.expected_head
        || planAdvanced.base_head,
      "Not evaluated",
      500
    );
    elements.localCommitConfirmationDialog.showModal();
    window.setTimeout(function () { elements.cancelCreateLocalCommit.focus(); }, 0);
  }

  function resultManifestEntries(envelope) {
    const record = objectRecord(envelope);
    const handoff = objectRecord(record.structured_handoff);
    const manifest = record.changed_file_manifest
      || record.changed_files
      || handoff.changed_file_manifest
      || handoff.changed_files;
    return Array.isArray(manifest) ? manifest : [];
  }

  function resultManifestLine(item) {
    const record = objectRecord(item);
    const path = repositoryRelativePath(record.path || record.repository_relative_path || item);
    const operation = humanStatus(record.operation || record.change_type || "changed");
    return operation + " · " + path;
  }

  function resultTestsSummary(envelope) {
    const record = objectRecord(envelope);
    const handoff = objectRecord(record.structured_handoff);
    return ownerSafeSummary(
      record.tests_summary || record.validation_summary || record.tests || handoff.tests,
      "No test result available.",
      500
    );
  }

  function resultCompletionClassification(envelope, lifecycleStatus, changedFileCount) {
    const record = objectRecord(envelope);
    const persisted = String(record.completion_classification || "").toLowerCase();
    const persistedLabels = {
      succeeded_with_changes: "Process succeeded with captured changes",
      succeeded_without_workspace_changes: "Process succeeded with no workspace change",
      failed: "Process failed",
      cancelled: "Process cancelled",
      timed_out: "Process timed out",
      interrupted: "Process interrupted",
      result_incomplete: "Result incomplete",
      workspace_evidence_conflict: "Workspace evidence conflict"
    };
    if (persistedLabels[persisted]) return persistedLabels[persisted];
    const terminal = String(record.terminal_status || lifecycleStatus || "waiting").toLowerCase();
    const integrity = String(record.integrity_state || record.result_integrity || "pending").toLowerCase();
    if (lifecycleIsActive(terminal) || lifecycleIsActive(lifecycleStatus)) return "In progress";
    if (/conflict/.test(integrity)) return "Workspace evidence conflict";
    if (/blocked|invalid|incomplete|unavailable/.test(integrity)) return "Result incomplete";
    if (["completed", "succeeded", "result_available"].indexOf(terminal) !== -1) {
      return changedFileCount > 0
        ? "Process succeeded with captured changes"
        : "Process succeeded with no workspace change";
    }
    if (terminal === "failed") return "Process failed";
    if (terminal === "cancelled") return "Process cancelled";
    if (terminal === "timed_out") return "Process timed out";
    if (["interrupted", "process_lost"].indexOf(terminal) !== -1) return "Process interrupted";
    return "Waiting for completion";
  }

  function renderResultIntake(run) {
    const envelope = resultEnvelopeForRun(run);
    const record = objectRecord(envelope);
    const handoff = objectRecord(record.structured_handoff);
    const activity = currentRunActivity();
    const terminalTruth = objectRecord(
      activity && activity.terminalTruth
      || run && (run.terminal_truth || run.terminalTruth)
    );
    const truthCoding = objectRecord(terminalTruth.coding);
    const truthVerification = objectRecord(terminalTruth.verification);
    const coding = objectRecord(
      record.coding_result || record.coding_evidence || handoff.coding_result
    );
    const verification = objectRecord(record.verification_evidence || handoff.verification_verdict);
    const lifecycleActive = Boolean(activity && lifecycleIsActive(activity.status));
    const status = String(
      activity
        ? activity.status
        : record.terminal_status || run && authoritativeRunStatus(run) || "waiting"
    ).toLowerCase();
    const integrity = String(
      activity && activity.lifecycleAvailable && activity.integrity
      || record.integrity_state
      || record.result_integrity
      || activity && activity.integrity
      || "pending"
    ).toLowerCase();
    const lifecycleBlocked = Boolean(
      activity
      && activity.lifecycleAvailable
      && activityResultIsBlocked(activity)
    );
    const valid = resultEnvelopeIsValid(record) && !lifecycleActive && !lifecycleBlocked;
    const requestedModel = record.requested_model || activity && activity.requestedModel;
    const effectiveModel = runLocalEffectiveModelView(record, {}, {});
    const effectiveModelDisplay = effectiveModel.available
      ? effectiveModel.display
      : activity && activity.runLocalEffectiveModelAvailable
        ? activity.runLocalEffectiveModel
        : RUN_LOCAL_MODEL_NOT_EXPOSED;
    const requestedAcceptance = requestedModelAcceptanceView(
      {
        requested_model_accepted: record.requested_model_accepted === true
          || Boolean(activity && activity.requestedModelAcceptedConfirmed)
      },
      coding,
      status
    );
    const startedAt = record.started_at || activity && activity.startedAt || run && run.started_at;
    const finishedAt = record.terminal_at || record.finished_at || activity && activity.finishedAt || run && run.finished_at;
    const timedOut = status === "timed_out";
    const changedFileCount = resultManifestEntries(record).length;

    elements.resultEnvelopeStatus.textContent = lifecycleActive
      ? "TWOS is monitoring this Run"
      : lifecycleBlocked
        ? "Result integrity blocked"
      : valid
      ? timedOut
        ? "Result available — Run timed out"
        : "Result available"
      : /blocked|invalid/.test(integrity)
        ? "Result integrity blocked"
        : status === "result_unavailable" || status === "process_lost"
          ? humanStatus(status)
          : lifecycleIsActive(status)
            ? "TWOS is monitoring this Run"
            : "Waiting for a valid terminal result";
    elements.resultEnvelopeRequestedModel.textContent = ownerSafeText(requestedModel, "Not recorded", 160);
    elements.resultEnvelopeRequestedModelAccepted.textContent = requestedAcceptance.display;
    elements.resultEnvelopeActualModel.textContent = effectiveModelDisplay;
    elements.resultEnvelopeDuration.textContent = formatDuration(
      record.execution_duration_seconds !== null && record.execution_duration_seconds !== undefined
        ? record.execution_duration_seconds
        : record.duration_ms !== null && record.duration_ms !== undefined
          ? Number(record.duration_ms) / 1000
          : record.execution_duration,
      startedAt,
      finishedAt
    );
    elements.resultEnvelopeClassification.textContent = resultCompletionClassification(
      record,
      status,
      changedFileCount
    );
    elements.resultEnvelopeFinalResponse.textContent = lifecycleActive
      ? "Available automatically after the process settles."
      : ownerSafeSummary(
          record.final_response || handoff.final_response || coding.safe_summary || coding.summary,
          valid ? "No final Codex response was captured." : "Not available",
          1200
        );
    elements.resultEnvelopeChangedCount.textContent = String(changedFileCount);
    elements.resultEnvelopeCoding.textContent = lifecycleActive
      ? "In progress — see Live Codex Activity"
      : timedOut
      ? "Run timed out — no verified model execution"
      : truthCoding.status
      ? humanStatus(truthCoding.status)
      : ownerWorkflowSummary(
          record.coding_result || coding,
          valid ? "Coding evidence was not summarized." : "Not available",
          400
        );
    elements.resultEnvelopeVerification.textContent = lifecycleActive
      ? status === "verifying"
        ? "Independent Verification is in progress"
        : "Waiting for Coding to settle"
      : timedOut
      ? "Unavailable — Coding did not complete"
      : truthVerification.status
      ? humanStatus(truthVerification.status)
      : ownerWorkflowSummary(
          record.verification_result || verification,
          valid ? "Verification evidence was not summarized." : "Not available",
          400
        );
    elements.resultEnvelopeTests.textContent = resultTestsSummary(record);
    elements.resultEnvelopeIntegrity.textContent = lifecycleActive
      ? "Pending authoritative lifecycle settlement"
      : timedOut && integrity === "verified"
      ? "Verified timeout envelope — not verified Coding output"
      : integrity === "verified"
      ? "Verified evidence envelope — independent Verification is shown separately"
      : humanStatus(integrity);
    setStatusLabel(elements.resultEnvelopeIntegrity, elements.resultEnvelopeIntegrity.textContent);
    elements.resultEnvelopeNextAction.textContent = ownerWorkflowText(
      activity && activity.nextAction
      || (timedOut
        ? "Review Handoff: BLOCKED. Verify Codex Connection before any new Owner-approved Run."
        : record.next_action || record.owner_action),
      valid
        ? "Select Review Handoff."
        : lifecycleBlocked || /blocked|invalid|unavailable/.test(integrity) || RESULT_BLOCKED_STATUSES.indexOf(status) !== -1
          ? "Review blocker evidence"
          : "TWOS will update this Run automatically.",
      400
    );

    elements.resultIntakeAdvancedCard.hidden = !run;
    elements.resultMonitorState.textContent = humanStatus(
      record.monitor_state || activity && activity.status || run && run.status || "none"
    );
    const monitor = objectRecord(record.monitor);
    const monitorAdvanced = objectRecord(monitor.advanced);
    const envelopeAdvanced = objectRecord(record.advanced);
    elements.resultRecoveryState.textContent = humanStatus(
      record.recovery_state || monitor.recovery_state || "none"
    );
    elements.resultSourceIdentity.textContent = ownerSafeText(
      record.result_source || monitor.result_source || envelopeAdvanced.result_source_identity,
      "None",
      240
    );
    elements.resultEnvelopeRecord.textContent = record.id === null || record.id === undefined
      ? "None"
      : "#" + String(record.id);
    elements.resultEnvelopeDigest.textContent = ownerSafeText(
      record.result_digest || envelopeAdvanced.result_digest,
      "None",
      200
    );
    elements.resultEnvelopeTaskBinding.textContent = record.task_id === null || record.task_id === undefined
      ? "None"
      : "Task #" + record.task_id + " · v" + String(record.task_version || envelopeAdvanced.task_version || "?");
    const packId = record.pack_id || envelopeAdvanced.pack_id;
    elements.resultEnvelopePackBinding.textContent = packId === null || packId === undefined
      ? "None"
      : "Pack #" + packId + " · v" + String(record.pack_version || envelopeAdvanced.pack_version || "?");
    elements.resultEnvelopeAssignmentBindings.textContent = [
      record.coding_assignment_id || envelopeAdvanced.coding_assignment_id
        ? "Coding #" + String(record.coding_assignment_id || envelopeAdvanced.coding_assignment_id)
          + " v" + String(record.coding_assignment_version || envelopeAdvanced.coding_assignment_version || "?")
        : "",
      record.verification_assignment_id || envelopeAdvanced.verification_assignment_id
        ? "Verification #" + String(record.verification_assignment_id || envelopeAdvanced.verification_assignment_id)
          + " v" + String(record.verification_assignment_version || envelopeAdvanced.verification_assignment_version || "?")
        : ""
    ].filter(Boolean).join(" · ") || "None";
    elements.resultEnvelopeRoutingBinding.textContent = ownerSafeText(
      record.routing_snapshot_identity
      || record.routing_snapshot
      || envelopeAdvanced.routing_snapshot_identity,
      "None",
      200
    );
    elements.resultProcessIdentity.textContent = ownerSafeText(
      record.process_identity
      || monitor.process_identity
      || monitorAdvanced.process_start_identity
      || envelopeAdvanced.process_evidence_identity,
      "None",
      220
    );
    elements.resultSessionIdentity.textContent = ownerSafeText(
      record.codex_session_identity
      || record.session_identity
      || monitorAdvanced.codex_session_identity,
      "None",
      220
    );
    elements.resultIngestedAt.textContent = formatTime(record.ingested_at);
    elements.resultIntakeDiagnostics.textContent = ownerSafeText(
      record.intake_message || record.sanitized_diagnostics,
      "No Result Envelope diagnostics are available.",
      900
    );
  }

  function renderHandoffReview(run) {
    const envelope = resultEnvelopeForRun(run);
    const activity = currentRunActivity();
    const validEnvelope = resultEnvelopeIsValid(envelope)
      && !(activity && lifecycleIsActive(activity.status));
    const review = objectRecord(handoffReviewForRun(run));
    const draft = objectRecord(instructionDraftForRun(run));
    const reviewed = Object.keys(review).length > 0;
    const reconciliation = String(
      review.recommended_reconciliation || review.reconciliation || "not reviewed"
    );

    elements.handoffReviewSection.hidden = !validEnvelope;
    elements.reviewHandoff.disabled = !validEnvelope || state.pending.has("review-handoff");
    elements.handoffReviewContent.hidden = !reviewed;
    elements.instructionDraftSection.hidden = !reviewed;
    if (!validEnvelope) return;

    elements.handoffRunOutcome.textContent = ownerSafeSummary(
      review.run_outcome || review.outcome,
      "No Run outcome reconciliation recorded.",
      500
    );
    elements.handoffTaskPack.textContent = ownerSafeSummary(
      review.task_pack_binding || review.task_and_pack,
      (function () {
        const advanced = objectRecord(objectRecord(envelope).advanced);
        const taskVersion = objectRecord(envelope).task_version || advanced.task_version;
        const packVersion = objectRecord(envelope).pack_version || advanced.pack_version;
        if (!taskVersion && !packVersion) return "Task and Pack binding not summarized.";
        return "Selected Task v" + String(taskVersion || "?")
          + " · approved Pack v" + String(packVersion || "?");
      }()),
      400
    );
    elements.handoffCodingResult.textContent = ownerSafeSummary(
      review.coding_result,
      "Coding result not summarized.",
      500
    );
    elements.handoffVerificationVerdict.textContent = ownerSafeSummary(
      review.verification_verdict || review.verification_result,
      "Verification verdict not summarized.",
      500
    );
    elements.handoffTests.textContent = ownerSafeSummary(
      review.tests || review.tests_summary,
      "No test summary recorded.",
      600
    );
    elements.handoffBoundary.textContent = ownerSafeSummary(
      review.boundary_confirmation,
      "No boundary confirmation recorded.",
      600
    );
    elements.handoffPhaseGate.textContent = ownerSafeSummary(
      review.current_phase_gate || review.phase_gate,
      "No phase gate recorded.",
      400
    );
    elements.handoffReconciliation.textContent = humanStatus(reconciliation);
    setStatusLabel(elements.handoffReconciliation, elements.handoffReconciliation.textContent);
    appendTextList(
      elements.handoffChangedFiles,
      (Array.isArray(review.changed_files) ? review.changed_files : resultManifestEntries(envelope))
        .map(resultManifestLine),
      "No changed-file summary is available."
    );
    appendTextList(
      elements.handoffWarnings,
      ownerSafeList(review.warnings, "No warnings reported."),
      "No warnings reported."
    );
    appendTextList(
      elements.handoffLimitations,
      ownerSafeList(review.limitations, "No limitations reported."),
      "No limitations reported."
    );
    appendTextList(
      elements.handoffBlockers,
      ownerSafeList(review.unresolved_blockers || review.blockers, "No unresolved blockers reported."),
      "No unresolved blockers reported."
    );

    const draftAvailable = Object.keys(draft).length > 0;
    const draftApproved = String(
      draft.status || draft.approval_status || draft.approval_state || ""
    ).toLowerCase() === "approved"
      || draft.approved === true;
    elements.instructionDraftStatus.textContent = draftApproved
      ? "Approved — activation remains a separate Owner action"
      : "Draft — Owner approval required";
    elements.instructionDraftStatus.classList.toggle("is-approved", draftApproved);
    elements.instructionDraftContent.textContent = draftAvailable
      ? ownerSafeText(
          draft.instruction_text || draft.content || draft.draft_text,
          "The persisted instruction draft has no displayable content.",
          24000
        )
      : "Select Review Instruction Draft to create or retrieve exactly one proposed next instruction.";
    elements.instructionDraftBoundary.textContent = draftApproved
      ? "Approved for future consideration. No new Codex Run was started."
      : "A draft cannot execute itself. Approval and any future Run remain separate explicit Owner actions.";
    elements.reviewInstructionDraft.disabled = state.pending.has("review-instruction-draft");
    elements.approveInstructionDraft.hidden = !draftAvailable;
    elements.approveInstructionDraft.disabled = draftApproved || state.pending.has("approve-instruction-draft");
  }

  function renderResult() {
    const task = selectedTask();
    const run = currentCodexRun();
    const legacyRun = currentLegacyRun();
    const hasPersistedRun = Boolean(run);
    elements.resultCard.hidden = !hasPersistedRun;
    elements.viewResult.hidden = !hasPersistedRun;

    if (run) {
      const authoritativeStatus = authoritativeRunStatus(run) || String(run.status || "").toLowerCase();
      const runView = Object.assign({}, run, { status: authoritativeStatus });
      const terminalTruth = objectRecord(run.terminal_truth || run.terminalTruth);
      const truthCoding = objectRecord(terminalTruth.coding);
      const truthVerification = objectRecord(terminalTruth.verification);
      const primaryLabel = terminalTruth.primary_label || humanStatus(authoritativeStatus);
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

      elements.resultStatus.textContent = lifecycleIsActive(authoritativeStatus)
        ? humanStatus(authoritativeStatus)
        : primaryLabel;
      elements.resultLifecycle.textContent = humanStatus(authoritativeStatus);
      elements.resultSummary.textContent = runStateSummary(
        authoritativeStatus,
        terminalTruth.primary_status ? terminalTruth : {
          verification: { started: run.lifecycle && run.lifecycle.verification_started }
        }
      );
      elements.resultReview.textContent = objectRecord(terminalTruth.owner_review).summary
        || resultReviewText(terminalTruth.primary_status || authoritativeStatus);

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

      elements.resultCodingProcess.textContent = humanStatus(
        truthCoding.status || evidenceStatus(codingProcess, codingStatusFallback(runView))
      );
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
            return repositoryRelativePath(record.path || record.repository_relative_path)
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
      elements.resultVerificationStatus.textContent = humanStatus(
        truthVerification.status || evidenceStatus(verificationProcess, "not_started")
      );
      elements.resultVerificationProcessStarted.textContent = typeof truthVerification.started === "boolean"
        ? truthVerification.started ? "Yes" : "No"
        : evidenceBoolean(verificationProcess, ["process_started", "process_spawned"])
          ? "Yes"
          : "No";
      elements.resultVerificationTurnTerminal.textContent = humanStatus(firstEvidenceValue(
        verificationProcess,
        ["turn_terminal_state", "terminal_turn_state", "final_turn_status"],
        "not_reached"
      ));
      elements.resultVerificationProcessExitCode.textContent = evidenceExitCode(verificationProcess);
      elements.resultVerificationSummary.textContent = truthVerification.reason
        || evidenceFailure(verificationProcess);
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

      if (authoritativeStatus === "timed_out") {
        elements.resultCodingProcess.textContent = "Timed out — no verified model execution";
        elements.resultCodingActualModel.textContent = "No verified actual model";
        elements.resultTaskAcceptance.textContent = "Not accepted — no accepted source result exists";
        elements.resultVerificationStatus.textContent = "Unavailable";
        elements.resultVerificationVerdict.textContent = "Unavailable — Coding did not complete";
      }

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
        && boundary.git_boundary_observed === true
        && boundary.git_boundary_unchanged === true
        && boundary.git_transport_protocols_allowed === false
        && boundary.codex_tool_network_access_allowed === false
        && boundary.automatic_merge === false
        && boundary.automatic_push === false
        && boundary.staged_changes_created === false
        && boundary.worktree_branch_unchanged === true
        && boundary.prohibited_git_mutation_observed === false
        && commits.length === 0;
      elements.resultBoundary.textContent = boundaryVerified
        ? "Verified isolated worktree; no local Commit; local Git refs and remote configuration/tracking refs remained unchanged; Git transport remained blocked."
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
      elements.runError.textContent = ["failed", "blocked", "timed_out", "cancelled"].indexOf(authoritativeStatus) !== -1
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
      elements.resultCodingActualModel.textContent = RUN_LOCAL_MODEL_NOT_EXPOSED;
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
      elements.resultVerificationActualModel.textContent = RUN_LOCAL_MODEL_NOT_EXPOSED;
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
    renderResultIntake(run);
    renderHandoffReview(run);
    renderDeliveryCandidateReview(run);
    renderApplyPlanReview(run);
    renderApplySessionReview(run);
    renderPostApplyVerification(run);
    renderCommitBuilder(run);
    renderPushDelivery(run);
    renderOwnerCommitPushDelivery(run);
    renderRunModelEvidence(run);
    setStatusLabel(elements.resultStatus, elements.resultStatus.textContent);
  }

  function ownerAcceptanceSignature(acceptance) {
    if (!acceptance) return "none";
    return JSON.stringify({
      id: acceptance.id,
      status: acceptance.status,
      review_state: acceptance.review_state,
      result_id: acceptance.result_id,
      candidate_id: acceptance.candidate_id,
      candidate_version: acceptance.candidate_version,
      items: (acceptance.items || []).map(function (item) {
        return [item.id, item.status, item.note];
      })
    });
  }

  function renderOwnerAcceptance() {
    const acceptance = state.ownerAcceptance;
    elements.acceptanceStatus.textContent = acceptance
      ? humanStatus(acceptance.review_state || acceptance.status)
      : "Waiting for result";
    setStatusLabel(elements.acceptanceStatus, elements.acceptanceStatus.textContent);
    const signature = ownerAcceptanceSignature(acceptance);
    if (signature !== state.renderedAcceptanceSignature) {
      clearChildren(elements.acceptanceItems);
      if (!acceptance) {
        const empty = document.createElement("p");
        empty.className = "empty-state";
        empty.textContent = "No Codex result is ready for review.";
        elements.acceptanceItems.appendChild(empty);
      } else if (acceptance.review_kind === "result_delivery") {
        const summary = document.createElement("p");
        summary.className = "result-section-copy";
        summary.textContent = "This captured Result is immutably bound to its versioned Candidate. "
          + "Coding, Verification, workspace evidence, and included files remain available in the Result and Candidate sections. "
          + "Exact Result, Candidate, and Run record identifiers remain under Advanced.";
        elements.acceptanceItems.appendChild(summary);
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
    const activeRun = codexRun && lifecycleIsActive(authoritativeRunStatus(codexRun));
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
    elements.confirmStartCodexRun.disabled = state.pending.has("run-codex");
    elements.cancelCodex.hidden = !activeRun;
    elements.cancelCodex.disabled = !activeRun || state.pending.has("cancel-codex");
    elements.reviewChangeCandidate.disabled = !authenticated
      || !isTerminalCodexRun(codexRun)
      || state.pending.has("review-change-candidate");
    elements.reviewApplyPlan.disabled = !authenticated
      || !isTerminalCodexRun(codexRun)
      || !deliveryCandidateReviewAvailable(codexRun)
      || state.pending.has("review-apply-plan");
    const currentPlan = currentApplyPlanForRun(codexRun);
    elements.approveApplyPlan.disabled = !authenticated
      || !currentPlan.id
      || currentPlan.approval_required !== true
      || String(currentPlan.approval_state || "").toUpperCase() !== "PENDING"
      || state.pending.has("approve-apply-plan");
    const applySessionParts = applySessionReviewParts(codexRun);
    elements.applyAcceptedChanges.disabled = !authenticated
      || applySessionParts.actions.can_apply !== true
      || state.pending.has("apply-accepted-changes");
    elements.revertAppliedChanges.disabled = !authenticated
      || applySessionParts.actions.can_revert !== true
      || state.pending.has("revert-applied-changes");
    const appliedSession = objectRecord(applySessionParts.session);
    const postApplyReview = objectRecord(
      postApplyVerificationReviewForSession(appliedSession)
    );
    const postApplyEligibility = objectRecord(postApplyReview.eligibility);
    const postApplyActions = objectRecord(postApplyReview.actions);
    const canVerifyAppliedChanges = postApplyActions.can_verify === true
      || postApplyEligibility.can_verify === true;
    elements.verifyAppliedChanges.disabled = !authenticated
      || !postApplyVerificationContextAvailable(appliedSession)
      || !canVerifyAppliedChanges
      || state.pending.has("verify-applied-changes");
    const commitParts = commitBuilderParts(codexRun);
    const commitPlanId = commitBuilderRecordId(commitParts.plan);
    const commitStageId = commitBuilderRecordId(commitParts.stage);
    const commitActions = objectRecord(commitParts.actions);
    elements.reviewCommitPlan.disabled = !authenticated
      || !commitParts.verification.id
      || !(commitParts.eligibility.can_review === true)
      || state.pending.has("review-commit-plan");
    elements.stageApprovedFiles.disabled = !authenticated
      || !commitPlanId
      || !(commitActions.can_stage_approved_files === true || commitActions.can_stage === true)
      || state.pending.has("stage-approved-files");
    elements.createLocalCommit.disabled = !authenticated
      || !commitPlanId
      || !commitStageId
      || !(commitActions.can_create_local_commit === true || commitActions.can_commit === true)
      || state.pending.has("create-local-commit");
    if (canonicalOwnerDeliveryAvailable(codexRun)) {
      const ownerDelivery = ownerDeliveryParts(codexRun);
      const canonicalCommitActions = objectRecord(ownerDelivery.commitActions);
      const canonicalPushActions = objectRecord(ownerDelivery.pushActions);
      const committed = canonicalCommitState(ownerDelivery) === "LOCAL_COMMIT_CREATED";
      elements.reviewOwnerCommit.disabled = !authenticated
        || !(canonicalCommitActions.can_create_proposal === true
          || canonicalCommitActions.can_edit === true
          || canonicalCommitActions.can_review_commit === true
          || canonicalCommitActions.can_review_commit_proposal === true)
        || state.pending.has("review-owner-commit");
      elements.approveCommitProposal.disabled = !authenticated
        || !(canonicalCommitActions.can_approve_commit === true
          || canonicalCommitActions.can_approve_commit_proposal === true
          || canonicalCommitActions.can_approve === true)
        || state.pending.has("approve-commit-proposal");
      elements.confirmOwnerLocalCommit.disabled = !authenticated
        || !(canonicalCommitActions.can_confirm_commit === true
          || canonicalCommitActions.can_create_local_commit === true
          || canonicalCommitActions.can_commit === true)
        || state.pending.has("confirm-owner-local-commit");
      elements.reviewPushPlan.disabled = !authenticated
        || !(canonicalPushActions.can_review_push_plan === true
          || canonicalPushActions.can_create_plan === true)
        || state.pending.has("review-push-plan");
      elements.approvePushPlan.disabled = !authenticated
        || !(canonicalPushActions.can_approve_push_plan === true
          || canonicalPushActions.can_approve === true)
        || state.pending.has("approve-push-plan");
      elements.confirmOwnerPush.disabled = !authenticated
        || !ownerPushConfirmationCanConfirm(ownerDelivery)
        || state.pending.has("confirm-owner-push");
      if (committed) elements.revertAppliedChanges.disabled = true;
    }
    const decisionPending = state.pending.has("acceptance-decision");
    elements.acceptResult.disabled = !acceptance || !acceptance.can_accept || acceptance.status !== "owner_review" || decisionPending;
    elements.rejectResult.disabled = !acceptance
      || acceptance.can_reject === false
      || acceptance.status !== "owner_review"
      || decisionPending;
    elements.runCompactSync.disabled = !authenticated || !task || task.action !== "Compact Sync" || state.pending.has("run-compact-sync");
    elements.runCompactSync.title = task && task.action === "Compact Sync"
      ? "Run the safe internal Compact Sync worker."
      : "Choose Compact Sync in Advanced task execution settings and save the task first.";
    elements.createSchedule.disabled = !authenticated || !task || task.action !== "Compact Sync" || state.pending.has("create-schedule");
    elements.pauseSchedule.disabled = !schedule || schedule.paused || state.pending.has("pause-schedule");
    elements.resumeSchedule.disabled = !schedule || !schedule.paused || state.pending.has("resume-schedule");
  }

  function taskPayload() {
    const firstTask = firstRunFirstTaskPending() && state.creatingTask;
    const payload = {
      project_id: Number(elements.taskProject.value),
      title: firstTask ? elements.taskName.value : undefined,
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
    if (firstTask) payload.objective = elements.taskTitle.value;
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
    const savingFirstRunFirstTask = firstRunFirstTaskPending() && state.creatingTask;
    await performAction("save-task", elements.saveTask, "Saving…", async function () {
      if (!elements.taskProject.value) throw new ApiError(400, "NO_PROJECT", "No project is available.", {}, "product");
      const task = await persistTask(selectedTask());
      state.creatingTask = false;
      state.newTaskInitialized = false;
      state.selectedTaskId = task.id;
      state.selectedActivityRunId = null;
      state.taskSelectionEpoch += 1;
      state.taskLoadState = "loading";
      state.taskLoadMessage = "Loading the saved Task.";
      state.renderedTaskId = null;
      await composeTeam(task);
      return savingFirstRunFirstTask
        ? "Task saved. No Run, Pack, or provider action started."
        : "Task saved. AI Team composed and routing evaluated.";
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

  function secureRequestIdentity(prefix) {
    const identityPrefix = String(prefix || "");
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return identityPrefix + window.crypto.randomUUID();
    }
    const bytes = new Uint8Array(16);
    if (window.crypto && typeof window.crypto.getRandomValues === "function") {
      window.crypto.getRandomValues(bytes);
      return identityPrefix + Array.from(bytes).map(function (value) {
        return value.toString(16).padStart(2, "0");
      }).join("");
    }
    throw new Error("Secure browser request identity generation is unavailable.");
  }

  function codexRunIdempotencyKey(task, pack) {
    const prefix = "twos-run-" + task.id + "-" + pack.id + "-";
    return secureRequestIdentity(prefix);
  }

  function openCodexRunConfirmation() {
    const task = selectedTask();
    const pack = currentPack();
    const eligibility = effectiveRunEligibility();
    if (!task || !pack || !pack.approved || !eligibility || eligibility.eligible !== true) {
      setFeedback("Resolve the current Run blocker before confirming Codex execution.", "error");
      return;
    }
    const existing = state.runConfirmationContext;
    let context = existing
      && String(existing.task_id) === String(task.id)
      && String(existing.pack_id) === String(pack.id)
      && String(existing.pack_version) === String(pack.version)
      ? existing
      : null;
    if (!context) {
      try {
        context = {
          task_id: task.id,
          pack_id: pack.id,
          pack_version: pack.version,
          idempotency_key: codexRunIdempotencyKey(task, pack)
        };
      } catch (error) {
        setFeedback("This browser cannot create a safe Run request identity.", "error");
        return;
      }
    }
    state.runConfirmationContext = context;
    const source = objectRecord(objectRecord(state.codexStatus).source);
    const sourceIdentity = task.repository_identity || source.identity || "Configured source repository";
    const sourceBoundary = [sourceIdentity, source.branch, source.commit]
      .filter(Boolean)
      .join(" · ");
    elements.startCodexConfirmationTask.textContent = ownerSafeText(
      task.development_task || task.title,
      "Untitled Development task",
      4000
    );
    elements.startCodexConfirmationPack.textContent = "Pack #" + pack.id + " · v" + pack.version + " · Approved";
    const approvedRouting = assignmentsForPack(pack).filter(function (assignment) {
      return assignment.capability === "coding" || assignment.capability === "verification";
    }).map(function (assignment) {
      const primary = modelStableIdentifier(assignment.assignedModel);
      const fallback = assignment.fallbackAllowed && assignment.fallbackModel
        ? " · configured alternate " + modelStableIdentifier(assignment.fallbackModel)
          + " (automatic fallback blocked)"
        : " · no fallback";
      return humanStatus(assignment.capability) + ": " + primary + fallback;
    });
    elements.startCodexConfirmationRouting.textContent = ownerSafeText(
      approvedRouting.join(" | "),
      "No executable model routing is bound — confirmation blocked.",
      2000
    );
    const codexStatus = objectRecord(state.codexStatus);
    const workspaceBoundary = [
      codexStatus.authorized_workspace,
      codexStatus.isolated_worktree_root
        ? "isolated Run root " + codexStatus.isolated_worktree_root
        : ""
    ].filter(Boolean).join(" · ");
    elements.startCodexConfirmationWorkspace.textContent = ownerSafeText(
      workspaceBoundary,
      "Configured authorized workspace for " + sourceIdentity,
      2000
    );
    elements.startCodexConfirmationSource.textContent = ownerSafeText(
      sourceBoundary,
      "Configured source identity unavailable — confirmation blocked.",
      1000
    );
    elements.startCodexConfirmationDialog.showModal();
    window.setTimeout(function () { elements.confirmStartCodexRun.focus(); }, 0);
  }

  async function runCodex() {
    await performAction("run-codex", elements.confirmStartCodexRun, "Checking eligibility…", async function () {
      const task = selectedTask();
      const context = state.runConfirmationContext;
      if (!task || !context || String(context.task_id) !== String(task.id)) {
        throw new ApiError(400, "RUN_CONFIRMATION_REQUIRED", "Confirm the exact Codex Run first.", {}, "product");
      }
      await api("/api/tasks/" + task.id + "/codex-runs", {
        method: "POST",
        body: {
          confirmation: "START_CODEX_RUN",
          idempotency_key: context.idempotency_key,
          pack_id: context.pack_id,
          pack_version: context.pack_version
        }
      });
      state.runConfirmationContext = null;
      elements.startCodexConfirmationDialog.close();
      return "Codex run queued. TWOS will verify the isolated worktree before process launch.";
    });
  }

  function currentRunIdForRecovery() {
    const activity = currentRunActivity();
    const run = currentCodexRun();
    return activity && activity.runId !== null && activity.runId !== undefined
      ? activity.runId
      : run && run.id !== null && run.id !== undefined ? run.id : null;
  }

  async function refreshRunStatus() {
    await performAction("refresh-run-status", elements.refreshRunStatus, "Refreshing…", async function () {
      const runId = currentRunIdForRecovery();
      if (runId === null) {
        throw new ApiError(400, "NO_RUN", "Select a Codex Run first.", {}, "product");
      }
      await api("/api/codex-runs/" + encodeURIComponent(runId) + "/refresh-status", {
        method: "POST",
        body: {}
      });
      return "Run status refreshed. Persisted monitor evidence remains authoritative.";
    });
  }

  async function reconnectCodexRun() {
    await performAction("reconnect-codex-run", elements.reconnectCodexRun, "Reconnecting…", async function () {
      const runId = currentRunIdForRecovery();
      if (runId === null) {
        throw new ApiError(400, "NO_RUN", "Select a Codex Run first.", {}, "product");
      }
      await api("/api/codex-runs/" + encodeURIComponent(runId) + "/reconnect", {
        method: "POST",
        body: {}
      });
      return "TWOS rechecked the persisted process and result identities. No duplicate Run was started.";
    });
  }

  async function importCodexResultFile(file) {
    if (!file) return;
    await performAction("import-codex-result", elements.importCodexResult, "Importing…", async function () {
      const runId = currentRunIdForRecovery();
      if (runId === null) {
        throw new ApiError(400, "NO_RUN", "Select the exact Codex Run before importing a result.", {}, "product");
      }
      if (file.size > MAX_IMPORT_BYTES) {
        throw new ApiError(
          413,
          "RESULT_TOO_LARGE",
          "The structured Result Envelope exceeds the 1 MiB import limit.",
          {},
          "product"
        );
      }
      let parsed;
      try {
        parsed = JSON.parse(await file.text());
      } catch (error) {
        throw new ApiError(
          400,
          "MALFORMED_RESULT",
          "Choose a valid structured JSON Result Envelope.",
          {},
          "product"
        );
      }
      if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
        throw new ApiError(
          400,
          "STRUCTURED_RESULT_REQUIRED",
          "Import requires one structured Result Envelope for the selected Run.",
          {},
          "product"
        );
      }
      await api("/api/codex-runs/" + encodeURIComponent(runId) + "/import-result", {
        method: "POST",
        body: { result: parsed }
      });
      return "Structured Codex Result imported and identity-checked for the selected Run.";
    });
    elements.importCodexResultFile.value = "";
  }

  async function reviewHandoff() {
    await performAction("review-handoff", elements.reviewHandoff, "Reviewing…", async function () {
      const run = currentCodexRun();
      if (!run || !resultEnvelopeIsValid(resultEnvelopeForRun(run))) {
        throw new ApiError(
          409,
          "RESULT_ENVELOPE_REQUIRED",
          "Review Handoff becomes available only after a valid Result Envelope exists.",
          {},
          "product"
        );
      }
      const payload = await api("/api/codex-runs/" + encodeURIComponent(run.id) + "/handoff-review", {
        method: "POST",
        body: {}
      });
      const review = handoffReviewRecord(payload);
      if (
        review.run_id !== null
        && review.run_id !== undefined
        && String(review.run_id) !== String(run.id)
      ) {
        throw new ApiError(
          200,
          "HANDOFF_BINDING_MISMATCH",
          "The handoff review did not match the selected Run.",
          {},
          "product"
        );
      }
      state.handoffReviews[String(run.id)] = review;
      const draft = instructionDraftRecord(payload);
      if (Object.keys(draft).length) state.instructionDrafts[String(run.id)] = draft;
      return "Handoff reconciled for Owner review. No result was accepted and no new Run was started.";
    });
  }

  async function reviewInstructionDraft() {
    await performAction(
      "review-instruction-draft",
      elements.reviewInstructionDraft,
      "Preparing…",
      async function () {
        const run = currentCodexRun();
        if (!run || !Object.keys(objectRecord(handoffReviewForRun(run))).length) {
          throw new ApiError(
            409,
            "HANDOFF_REVIEW_REQUIRED",
            "Review Handoff before preparing a next-instruction draft.",
            {},
            "product"
          );
        }
        const payload = await api(
          "/api/codex-runs/" + encodeURIComponent(run.id) + "/instruction-draft",
          { method: "POST", body: {} }
        );
        const draft = instructionDraftRecord(payload);
        if (!Object.keys(draft).length) {
          throw new ApiError(
            200,
            "INSTRUCTION_DRAFT_UNAVAILABLE",
            "No Owner-reviewable instruction draft was returned.",
            {},
            "product"
          );
        }
        state.instructionDrafts[String(run.id)] = draft;
        return "One next-instruction draft is ready for review. Owner approval is still required.";
      }
    );
  }

  async function approveInstructionDraft() {
    await performAction(
      "approve-instruction-draft",
      elements.approveInstructionDraft,
      "Approving…",
      async function () {
        const run = currentCodexRun();
        const draft = objectRecord(instructionDraftForRun(run));
        if (!run || !Object.keys(draft).length) {
          throw new ApiError(
            409,
            "INSTRUCTION_DRAFT_REQUIRED",
            "Review the instruction draft before approval.",
            {},
            "product"
          );
        }
        const payload = await api(
          "/api/codex-runs/" + encodeURIComponent(run.id) + "/instruction-draft",
          {
            method: "POST",
            body: {
              action: "approve",
              expected_digest: draft.draft_digest || draft.instruction_digest || draft.digest || ""
            }
          }
        );
        const approved = instructionDraftRecord(payload);
        state.instructionDrafts[String(run.id)] = Object.keys(approved).length ? approved : draft;
        return "Instruction draft approved. Starting another Codex Run remains a separate Owner action.";
      }
    );
  }

  async function reviewChangeCandidate() {
    await performAction(
      "review-change-candidate",
      elements.reviewChangeCandidate,
      "Reviewing…",
      async function () {
        const run = currentCodexRun();
        if (!isTerminalCodexRun(run)) {
          throw new ApiError(
            409,
            "TERMINAL_RUN_REQUIRED",
            "Review Change Candidate is available only for a terminal Codex Run result.",
            {},
            "product"
          );
        }
        const review = await api("/api/codex-runs/" + run.id + "/delivery-candidate", {
          method: "POST"
        });
        if (!review || Number(review.run_id) !== Number(run.id)) {
          throw new ApiError(
            200,
            "CANDIDATE_BINDING_MISMATCH",
            "Change Candidate review did not match the selected Run.",
            {},
            "product"
          );
        }
        const key = String(run.id);
        state.deliveryCandidateReviews[key] = review;
        state.deliveryCandidateReviewLoads.add(key);
        renderDeliveryCandidateReview(run);
        return "";
      }
    );
  }

  async function reviewApplyPlan() {
    await performAction(
      "review-apply-plan",
      elements.reviewApplyPlan,
      "Reviewing…",
      async function () {
        const run = currentCodexRun();
        if (!isTerminalCodexRun(run)) {
          throw new ApiError(
            409,
            "TERMINAL_RUN_REQUIRED",
            "Review Apply Plan is available only for a terminal Codex Run result.",
            {},
            "product"
          );
        }
        if (!deliveryCandidateReviewAvailable(run)) {
          throw new ApiError(
            409,
            "CANDIDATE_REVIEW_REQUIRED",
            "Review Change Candidate before reviewing an Apply Plan.",
            {},
            "product"
          );
        }
        const review = await api("/api/codex-runs/" + run.id + "/apply-plans", {
          method: "POST"
        });
        if (!review || Number(review.run_id) !== Number(run.id)) {
          throw new ApiError(
            200,
            "APPLY_PLAN_BINDING_MISMATCH",
            "Apply Plan review did not match the selected Run.",
            {},
            "product"
          );
        }
        const key = String(run.id);
        state.applyPlanReviews[key] = review;
        state.applyPlanReviewLoads.add(key);
        await loadApplySessionReview(run, true);
        await loadPostApplyVerification(run, true);
        renderApplyPlanReview(run);
        renderApplySessionReview(run);
        renderPostApplyVerification(run);
        return "";
      }
    );
  }

  async function approveApplyPlan() {
    await performAction(
      "approve-apply-plan",
      elements.approveApplyPlan,
      "Approving…",
      async function () {
        const run = currentCodexRun();
        const plan = currentApplyPlanForRun(run);
        const advanced = objectRecord(plan.advanced);
        if (!run || !plan.id || plan.approval_required !== true) {
          throw new ApiError(
            409,
            "APPLY_PLAN_APPROVAL_NOT_READY",
            "Review one current Result-bound Apply Plan before approval.",
            {},
            "product"
          );
        }
        const response = await api(
          "/api/apply-plans/" + encodeURIComponent(plan.id) + "/approve",
          {
            method: "POST",
            body: {
              confirmation: "APPROVE_APPLY_PLAN",
              expected_plan_digest: advanced.plan_digest || "",
              expected_candidate_digest: advanced.candidate_digest || "",
              expected_result_digest: advanced.result_digest || "",
              expected_result_review_decision_digest:
                advanced.result_review_decision_digest || ""
            }
          }
        );
        if (!response || Number(response.run_id) !== Number(run.id)) {
          throw new ApiError(
            200,
            "APPLY_PLAN_APPROVAL_BINDING_MISMATCH",
            "Apply Plan approval did not match the selected Run.",
            {},
            "product"
          );
        }
        const key = String(run.id);
        state.applyPlanReviews[key] = {
          run_id: run.id,
          plan: response.plan,
          history: objectRecord(state.applyPlanReviews[key]).history || []
        };
        await loadApplySessionReview(run, true);
        renderApplyPlanReview(run);
        renderApplySessionReview(run);
        return response.approval_replayed
          ? "This exact Apply Plan was already approved. No file action was repeated."
          : "Apply Plan approved. Apply remains a separate explicit Owner confirmation.";
      }
    );
  }

  async function loadHistoricalApplyPlan() {
    const run = currentCodexRun();
    const planId = elements.applyPlanHistory.value;
    if (!isTerminalCodexRun(run) || !planId || state.pending.has("apply-plan-history")) return;
    state.pending.add("apply-plan-history");
    elements.applyPlanHistory.disabled = true;
    try {
      const review = await api("/api/apply-plans/" + encodeURIComponent(planId));
      if (!review || Number(review.run_id) !== Number(run.id)) {
        throw new ApiError(
          200,
          "APPLY_PLAN_BINDING_MISMATCH",
          "Historical Apply Plan did not match the selected Run.",
          {},
          "product"
        );
      }
      const key = String(run.id);
      state.applyPlanReviews[key] = review;
      state.applyPlanReviewLoads.add(key);
      await loadApplySessionReview(run, true);
      await loadPostApplyVerification(run, true);
      renderApplyPlanReview(run);
      renderApplySessionReview(run);
      renderPostApplyVerification(run);
      setFeedback("Historical Apply Plan loaded for read-only review.", "neutral");
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleExpiredSession();
        return;
      }
      setFeedback(productActionMessage(error), "error");
    } finally {
      state.pending.delete("apply-plan-history");
      if (state.auth === AUTH_STATES.SIGNED_IN) {
        renderApplyPlanReview(currentCodexRun());
        renderApplySessionReview(currentCodexRun());
        renderPostApplyVerification(currentCodexRun());
      }
    }
  }

  async function verifyAppliedChanges() {
    await performAction(
      "verify-applied-changes",
      elements.verifyAppliedChanges,
      "Verifying…",
      async function () {
        const run = currentCodexRun();
        const parts = applySessionReviewParts(run);
        const applySession = objectRecord(parts.session);
        if (!applySession.id || !postApplyVerificationContextAvailable(applySession)) {
          throw new ApiError(
            409,
            "APPLIED_SESSION_REQUIRED",
            "Verify Applied Changes is available only for an applied, non-reverted session.",
            {},
            "product"
          );
        }
        const review = await api(
          "/api/apply-sessions/" + encodeURIComponent(applySession.id)
            + "/post-apply-verifications",
          {
            method: "POST",
            body: { expected_journal_digest: applySession.journal_digest || "" }
          }
        );
        if (!review || String(review.apply_session_id || "") !== String(applySession.id)) {
          throw new ApiError(
            200,
            "POST_APPLY_VERIFICATION_BINDING_MISMATCH",
            "Post-Apply Verification did not match the selected Apply session.",
            {},
            "product"
          );
        }
        const key = String(applySession.id);
        state.postApplyVerificationReviews[key] = review;
        state.postApplyVerificationReviewLoads.add(key);
        renderPostApplyVerification(run);
        const verification = objectRecord(review.verification);
        const status = normalizedPostApplyVerificationState(verification.status);
        return status === "PASSED"
          ? "Applied changes verified. Nothing was staged, committed, or pushed."
          : "Post-Apply Verification finished. Review the reported evidence.";
      }
    );
  }

  function postApplyVerificationDigest(verification) {
    const record = objectRecord(verification);
    const advanced = objectRecord(record.advanced);
    return String(record.verification_digest || advanced.verification_digest || "");
  }

  function utf8ByteLength(value) {
    return new TextEncoder().encode(String(value || "")).length;
  }

  function validCommitSubject(value) {
    return Boolean(value)
      && value === value.trim()
      && value.indexOf("\n") === -1
      && value.indexOf("\r") === -1
      && value.indexOf("\u0000") === -1
      && !Array.from(value).some(function (character) {
        return character.codePointAt(0) < 32;
      })
      && utf8ByteLength(value) <= 200;
  }

  function validCommitBody(value) {
    return value.indexOf("\r") === -1
      && value.indexOf("\u0000") === -1
      && !Array.from(value).some(function (character) {
        const code = character.codePointAt(0);
        return code < 32 && character !== "\n" && character !== "\t";
      })
      && utf8ByteLength(value) <= 4000;
  }

  function storeCommitBuilderReview(verificationId, review) {
    const key = String(verificationId || "");
    if (!key || !review || commitBuilderReviewBinding(review) !== key) {
      throw new ApiError(
        200,
        "COMMIT_BUILDER_BINDING_MISMATCH",
        "Commit workflow review did not match the verified Apply result.",
        {},
        "product"
      );
    }
    state.commitBuilderRequestSequences[key] =
      (state.commitBuilderRequestSequences[key] || 0) + 1;
    state.commitBuilderReviews[key] = review;
    state.commitBuilderReviewLoads.add(key);
  }

  function storePushDeliveryReview(commitId, review) {
    const key = String(commitId || "");
    if (!key || !review || pushDeliveryReviewBinding(review) !== key) {
      throw new ApiError(
        200,
        "PUSH_DELIVERY_BINDING_MISMATCH",
        "Push workflow review did not match the selected local Commit result.",
        {},
        "product"
      );
    }
    state.pushDeliveryRequestSequences[key] =
      (state.pushDeliveryRequestSequences[key] || 0) + 1;
    state.pushDeliveryReviews[key] = review;
    state.pushDeliveryReviewLoads.add(key);
  }

  function ownerDeliveryActionContext() {
    const run = currentCodexRun();
    if (!run || !canonicalOwnerDeliveryAvailable(run)) {
      throw new ApiError(
        409,
        "OWNER_DELIVERY_NOT_READY",
        "The Owner delivery workflow is not ready for this Run.",
        {},
        "product"
      );
    }
    return { run: run, parts: ownerDeliveryParts(run), epoch: state.taskSelectionEpoch };
  }

  function assertOwnerDeliveryActionCurrent(context) {
    if (context.epoch !== state.taskSelectionEpoch
        || String(objectRecord(currentCodexRun()).id || "") !== String(context.run.id)) {
      throw new ApiError(
        409,
        "STALE_OWNER_DELIVERY_RESPONSE",
        "The delivery response no longer matches the selected Task and Run.",
        {},
        "product"
      );
    }
  }

  async function reviewOwnerCommit() {
    await performAction(
      "review-owner-commit",
      elements.reviewOwnerCommit,
      "Reviewing…",
      async function () {
        const context = ownerDeliveryActionContext();
        const subject = elements.commitPlanSubject.value;
        const body = elements.commitPlanBody.value;
        const actions = context.parts.commitActions;
        if (!context.parts.commitPrerequisitesMet || !(actions.can_create_proposal === true
            || actions.can_edit === true || actions.can_review_commit === true || actions.can_review_commit_proposal === true)) {
          throw new ApiError(409, "COMMIT_PREREQUISITES_REQUIRED",
            context.parts.commitPrerequisiteMessage || context.parts.commitDelivery.next_action || "Resolve the Commit readiness blocker.", {}, "product");
        }
        if (!validCommitSubject(subject)) {
          elements.commitPlanSubject.focus();
          throw new ApiError(
            422,
            "COMMIT_SUBJECT_INVALID",
            "Enter one nonempty Commit subject line of at most 200 UTF-8 bytes.",
            {},
            "product"
          );
        }
        if (!validCommitBody(body)) {
          elements.commitPlanBody.focus();
          throw new ApiError(
            422,
            "COMMIT_BODY_INVALID",
            "Commit body must be at most 4000 UTF-8 bytes of plain text.",
            {},
            "product"
          );
        }
        const verificationId = ownerDeliveryRecordId(context.parts.postApply);
        const verificationDigest = context.parts.postApply.verification_digest
          || ownerDeliveryDigest(context.parts.postApply);
        if (!verificationId || !verificationDigest) {
          throw new ApiError(
            409,
            "PASSED_VERIFICATION_REQUIRED",
            "Review Commit requires the exact passed Post-Apply Verification.",
            {},
            "product"
          );
        }
        await api(
          "/api/post-apply-verifications/" + encodeURIComponent(verificationId)
            + "/commit-proposals",
          {
            method: "POST",
            body: {
              expected_verification_digest: verificationDigest,
              subject: subject,
              body: body
            }
          }
        );
        assertOwnerDeliveryActionCurrent(context);
        return "Commit proposal reviewed. Approval remains a separate explicit Owner action.";
      }
    );
  }

  async function approveOwnerCommitProposal() {
    await performAction(
      "approve-commit-proposal",
      elements.approveCommitProposal,
      "Approving…",
      async function () {
        const context = ownerDeliveryActionContext();
        const proposalId = ownerDeliveryRecordId(context.parts.proposal);
        const proposalDigest = ownerDeliveryDigest(context.parts.proposal);
        const proposalVersion = Number(
          context.parts.proposal.version || context.parts.proposal.proposal_version
        );
        if (!proposalId || !proposalDigest || !Number.isInteger(proposalVersion)) {
          throw new ApiError(
            409,
            "COMMIT_PROPOSAL_NOT_READY",
            "Review the current immutable Commit proposal before approval.",
            {},
            "product"
          );
        }
        await api(
          "/api/commit-proposals/" + encodeURIComponent(proposalId) + "/approvals",
          {
            method: "POST",
            body: {
              confirmation: "APPROVE_COMMIT_PROPOSAL",
              expected_proposal_digest: proposalDigest,
              expected_proposal_version: proposalVersion
            }
          }
        );
        assertOwnerDeliveryActionCurrent(context);
        return "Commit proposal approved. Local Commit still requires a separate final confirmation.";
      }
    );
  }

  function openOwnerLocalCommitConfirmation() {
    const context = ownerDeliveryActionContext();
    if (!(context.parts.commitActions.can_confirm_commit === true
        || context.parts.commitActions.can_create_local_commit === true
        || context.parts.commitActions.can_commit === true)) return;
    const proposalId = ownerDeliveryRecordId(context.parts.proposal);
    const proposalDigest = ownerDeliveryDigest(context.parts.proposal);
    const approvalDigest = ownerDeliveryDigest(context.parts.commitApproval);
    if (!proposalId || !proposalDigest || !approvalDigest) return;
    const approved = ownerDeliveryPathEntries(context.parts.proposal, true);
    const advanced = objectRecord(context.parts.proposal.advanced);
    state.ownerCommitConfirmationContext = {
      run_id: String(context.run.id),
      proposal_id: String(proposalId),
      proposal_digest: String(proposalDigest),
      approval_digest: String(approvalDigest),
      task_selection_epoch: context.epoch
    };
    elements.ownerCommitConfirmationProposal.textContent = "Proposal " + String(proposalId)
      + " · v" + String(context.parts.proposal.version || context.parts.proposal.proposal_version || "?");
    elements.ownerCommitConfirmationPaths.textContent = approved.length
      ? approved.map(commitBuilderPath).join(", ")
      : "None";
    elements.ownerCommitConfirmationSubject.textContent = sanitizedApplyPlanText(
      context.parts.proposal.subject,
      "None",
      200
    );
    elements.ownerCommitConfirmationBody.textContent = sanitizedApplyPlanText(
      context.parts.proposal.body,
      "None",
      1200
    );
    elements.ownerCommitConfirmationAuthor.textContent = sanitizedApplyPlanText(
      context.parts.proposal.author || context.parts.proposal.author_identity || advanced.author,
      "Not evaluated",
      500
    );
    elements.ownerCommitConfirmationBranch.textContent = sanitizedApplyPlanText(
      context.parts.proposal.branch || advanced.branch,
      "Not evaluated",
      240
    );
    elements.ownerCommitConfirmationParent.textContent = boundedText(
      context.parts.proposal.expected_parent_sha || context.parts.proposal.base_head
        || advanced.expected_parent_sha || advanced.base_head,
      "Not evaluated",
      500
    );
    elements.ownerLocalCommitConfirmationDialog.showModal();
    window.setTimeout(function () { elements.cancelApprovedLocalCommit.focus(); }, 0);
  }

  async function confirmApprovedLocalCommit() {
    const context = state.ownerCommitConfirmationContext;
    if (!context) return;
    await performAction(
      "confirm-owner-local-commit",
      elements.confirmApprovedLocalCommit,
      "Creating…",
      async function () {
        if (context.task_selection_epoch !== state.taskSelectionEpoch
            || String(objectRecord(currentCodexRun()).id || "") !== context.run_id) {
          throw new ApiError(
            409,
            "STALE_COMMIT_CONFIRMATION",
            "Commit confirmation no longer matches the selected Task and Run.",
            {},
            "product"
          );
        }
        await api(
          "/api/commit-proposals/" + encodeURIComponent(context.proposal_id)
            + "/local-commits",
          {
            method: "POST",
            body: {
              confirmation: "CREATE_LOCAL_COMMIT",
              expected_proposal_digest: context.proposal_digest,
              expected_approval_digest: context.approval_digest
            }
          }
        );
        state.ownerCommitConfirmationContext = null;
        elements.ownerLocalCommitConfirmationDialog.close();
        return "Local Commit created. Local Commit does not Push; review a separate Push Plan next.";
      }
    );
  }

  async function reviewOwnerPushPlan() {
    await performAction(
      "review-push-plan",
      elements.reviewPushPlan,
      "Reviewing…",
      async function () {
        const context = ownerDeliveryActionContext();
        const commitId = ownerDeliveryRecordId(context.parts.commitExecution);
        if (!commitId) {
          throw new ApiError(
            409,
            "LOCAL_COMMIT_REQUIRED",
            "Review Push Plan requires the exact successful local Commit.",
            {},
            "product"
          );
        }
        await api(
          "/api/local-commits/" + encodeURIComponent(commitId) + "/push-plans",
          { method: "POST" }
        );
        assertOwnerDeliveryActionCurrent(context);
        return "Push Plan reviewed. Push approval remains a separate explicit Owner action.";
      }
    );
  }

  async function approveOwnerPushPlan() {
    await performAction(
      "approve-push-plan",
      elements.approvePushPlan,
      "Approving…",
      async function () {
        const context = ownerDeliveryActionContext();
        const planId = ownerDeliveryRecordId(context.parts.pushPlan);
        const planDigest = ownerDeliveryDigest(context.parts.pushPlan);
        const planVersion = Number(
          context.parts.pushPlan.version || context.parts.pushPlan.plan_version
        );
        if (!planId || !planDigest || !Number.isInteger(planVersion)) {
          throw new ApiError(
            409,
            "PUSH_PLAN_NOT_READY",
            "Review the current immutable Push Plan before approval.",
            {},
            "product"
          );
        }
        await api(
          "/api/push-plans/" + encodeURIComponent(planId) + "/approvals",
          {
            method: "POST",
            body: {
              confirmation: "APPROVE_PUSH_PLAN",
              expected_plan_digest: planDigest,
              expected_plan_version: planVersion
            }
          }
        );
        assertOwnerDeliveryActionCurrent(context);
        return "Push Plan approved. Push still requires a separate final confirmation.";
      }
    );
  }

  function ownerPushConfirmationBusy() {
    const phase = String(state.ownerPushConfirmationState.phase || "");
    return state.pending.has("confirm-owner-push")
      || phase === "submitting"
      || phase === "running";
  }

  function setOwnerPushConfirmationPhase(phase, message, options) {
    const config = options || {};
    const normalized = Object.prototype.hasOwnProperty.call(
      OWNER_PUSH_CONFIRMATION_LABELS,
      phase
    ) ? phase : "needs_review";
    const safeMessage = sanitizedApplyPlanText(
      message,
      normalized === "ready_for_confirmation"
        ? "The approved Push Plan is ready for one explicit confirmation."
        : "Review the current persisted Push evidence before another action.",
      1000
    );
    state.ownerPushConfirmationState = {
      phase: normalized,
      message: safeMessage,
      request_identity: String(
        config.request_identity
        || state.ownerPushConfirmationState.request_identity
        || ""
      )
    };
    elements.ownerPushConfirmationStatus.dataset.state = normalized;
    elements.ownerPushConfirmationStatusLabel.textContent =
      OWNER_PUSH_CONFIRMATION_LABELS[normalized];
    elements.ownerPushConfirmationStatusMessage.textContent = safeMessage;
    const busy = normalized === "submitting" || normalized === "running";
    elements.confirmApprovedPush.disabled = normalized !== "ready_for_confirmation";
    elements.confirmApprovedPush.textContent = normalized === "submitting"
      ? "Submitting…"
      : normalized === "running"
        ? "Pushing…"
        : "Confirm Push";
    if (busy) {
      elements.confirmApprovedPush.setAttribute("aria-busy", "true");
    } else {
      elements.confirmApprovedPush.removeAttribute("aria-busy");
    }
    elements.cancelApprovedPush.textContent = busy ? "Hide" : normalized === "ready_for_confirmation" ? "Cancel" : "Close";
  }

  async function waitForOwnerPushRefresh() {
    let remainingWaits = Math.ceil(OWNER_PUSH_REFRESH_WAIT_MS / 50);
    while (state.refreshing && remainingWaits > 0) {
      await new Promise(function (resolve) { window.setTimeout(resolve, 50); });
      remainingWaits -= 1;
    }
    if (state.refreshing) {
      throw new ApiError(
        409,
        "WORKSPACE_REFRESH_ACTIVE",
        "TWOS is still reconciling read-only workspace evidence. No Push request was sent; wait for refresh to finish, then retry once.",
        {},
        "product"
      );
    }
  }

  function ownerPushConfirmationPhaseFor(parts) {
    if (ownerPushConfirmationRequestInFlight(parts)) return "running";
    if (ownerPushConfirmationUncertaintyActive(parts)) return "needs_review";
    const confirmation = objectRecord(parts.pushConfirmation);
    const projectedState = String(confirmation.state || "").toLowerCase();
    if (ownerPushConfirmationProjectionRelevant(parts)
        && Object.prototype.hasOwnProperty.call(
          OWNER_PUSH_CONFIRMATION_LABELS,
          projectedState
        )) {
      if (projectedState === "ready_for_confirmation"
          && !ownerPushConfirmationCanConfirm(parts)) {
        return "blocked";
      }
      return projectedState;
    }
    const stateValue = canonicalPushState(parts);
    if (stateValue === "DELIVERED") return "succeeded";
    if (stateValue === "ALREADY_DELIVERED") return "already_delivered";
    if (stateValue === "PUSHING") return "running";
    if (stateValue === "FAILED") return "failed";
    if (stateValue === "TIMED_OUT") return "timed_out";
    if (stateValue === "NEEDS_REVIEW") return "needs_review";
    if (stateValue === "BLOCKED" || stateValue === "NEEDS_SETUP") return "blocked";
    if (parts.pushActions.can_confirm_push === true || parts.pushActions.can_push === true) {
      return "ready_for_confirmation";
    }
    return "blocked";
  }

  function ownerPushConfirmationReason(parts, fallback) {
    if (ownerPushConfirmationRequestInFlight(parts)) {
      return "The Push request was sent and is awaiting canonical execution and remote evidence. Hiding this dialog does not cancel it.";
    }
    if (ownerPushConfirmationUncertaintyActive(parts)) {
      return sanitizedApplyPlanText(
        objectRecord(state.ownerPushConfirmationUncertainty).message,
        fallback,
        900
      );
    }
    const confirmation = objectRecord(parts.pushConfirmation);
    const projectedState = String(confirmation.state || "").toLowerCase();
    const localPhase = String(state.ownerPushConfirmationState.phase || "");
    if (state.pending.has("confirm-owner-push")
        && ["submitting", "running"].indexOf(localPhase) !== -1
        && [
          "succeeded",
          "already_delivered",
          "blocked",
          "failed",
          "timed_out",
          "needs_review"
        ].indexOf(projectedState) === -1) {
      return sanitizedApplyPlanText(
        state.ownerPushConfirmationState.message,
        localPhase === "submitting"
          ? "Submitting one bound Push request."
          : "The accepted Push request is running independently of this dialog.",
        900
      );
    }
    if (ownerPushConfirmationProjectionRelevant(parts)
        && projectedState === "ready_for_confirmation"
        && !ownerPushConfirmationCanConfirm(parts)) {
      if (confirmation.reason) {
        return sanitizedApplyPlanText(confirmation.reason, fallback, 900);
      }
      if (!/^[0-9a-f]{64}$/.test(String(confirmation.request_identity || ""))) {
        return "Push confirmation is blocked because its stable request identity is unavailable or malformed. Refresh the delivery state and review the approved Push Plan.";
      }
      if (confirmation.can_confirm !== true) {
        return "Push confirmation is blocked because the ready projection does not admit final confirmation. Refresh the delivery state and review the approved Push Plan.";
      }
      return sanitizedApplyPlanText(
        fallback,
        "Push confirmation is blocked by inconsistent persisted eligibility evidence.",
        900
      );
    }
    const canonicalReason = confirmation.reason || confirmation.progress;
    if (ownerPushConfirmationProjectionRelevant(parts) && canonicalReason) {
      return sanitizedApplyPlanText(canonicalReason, fallback, 900);
    }
    const blockers = applyPlanTextList(parts.pushDelivery.blockers, "")
      .concat(applyPlanTextList(parts.pushPlan.blockers, ""))
      .concat(applyPlanTextList(parts.pushExecution.blockers, ""));
    const projectionNext = objectRecord(parts.projection.next_action);
    return blockers[0]
      || sanitizedApplyPlanText(
        parts.pushDelivery.next_action || projectionNext.message,
        fallback,
        900
      );
  }

  async function reconcileOwnerPushConfirmation(context, requestError) {
    const allowNoExecutionReconciliation = ownerPushRejectionProvesNoEffect(requestError);
    const allowReadyReconciliation = ownerPushRejectionProvesSafeRetry(requestError);
    const reconciliationEvidence = {
      allow_no_execution_reconciliation: allowNoExecutionReconciliation,
      allow_ready_reconciliation: allowReadyReconciliation
    };
    markOwnerPushConfirmationUncertain(context, reconciliationEvidence);
    let pollCount = 0;
    try {
      while (true) {
        const projection = await api(
          "/api/codex-runs/" + encodeURIComponent(context.run_id) + "/delivery",
          { timeoutMs: 15 * 1000 }
        );
        if (context.task_selection_epoch !== state.taskSelectionEpoch
            || String(objectRecord(currentCodexRun()).id || "") !== context.run_id
            || !projection || String(projection.run_id || "") !== context.run_id) {
          throw new ApiError(
            409,
            "STALE_PUSH_RECONCILIATION",
            "Push reconciliation no longer matches the selected Task and Run.",
            {},
            "product"
          );
        }
        state.ownerDeliveryProjections[context.run_id] = projection;
        const localFence = objectRecord(state.ownerPushConfirmationUncertainty);
        if (!ownerPushConfirmationProjectionIsCanonical(projection)
            || (localFence.status
              && !resolveOwnerPushConfirmationUncertainty(
                context.run_id,
                projection,
                null
              ))) {
          throw new ApiError(
            200,
            "PUSH_CONFIRMATION_PROJECTION_MISSING",
            "Canonical Push confirmation evidence was not available after the request.",
            {},
            "product"
          );
        }
        const parts = ownerDeliveryParts(currentCodexRun());
        const phase = ownerPushConfirmationPhaseFor(parts);
        if (phase === "succeeded" || phase === "already_delivered") {
          setOwnerPushConfirmationPhase(
            phase,
            phase === "already_delivered"
              ? "The approved Commit was already present at the exact remote ref. No second Push was issued."
              : "The exact remote SHA is verified and the delivery receipt is persisted.",
            { request_identity: context.request_identity }
          );
          state.ownerPushConfirmationContext = null;
          if (elements.ownerPushConfirmationDialog.open) elements.ownerPushConfirmationDialog.close();
          setFeedback("Push delivery reconciled from persisted execution and remote evidence.", "success");
          return phase;
        }
        if (phase === "ready_for_confirmation") {
          const reason = productActionMessage(requestError);
          setOwnerPushConfirmationPhase(
            "ready_for_confirmation",
            reason + " Live evidence now shows the exact approved Plan is eligible for one explicit retry or idempotent settlement; TWOS did not retry automatically.",
            { request_identity: context.request_identity }
          );
          return phase;
        }
        setOwnerPushConfirmationPhase(
          phase,
          ownerPushConfirmationReason(
            parts,
            productActionMessage(requestError) + " Review persisted Push evidence before another action."
          ),
          { request_identity: context.request_identity }
        );
        if (["submitting", "running"].indexOf(phase) === -1) return phase;
        if (pollCount >= OWNER_PUSH_RECONCILIATION_MAX_POLLS) {
          setOwnerPushConfirmationPhase(
            phase,
            "Push execution is still in progress after bounded reconciliation. No retry was issued. Use Refresh Run Status to load the eventual persisted receipt.",
            { request_identity: context.request_identity }
          );
          return phase;
        }
        pollCount += 1;
        await new Promise(function (resolve) {
          window.setTimeout(resolve, OWNER_PUSH_RECONCILIATION_POLL_MS);
        });
      }
    } catch (reconciliationError) {
      markOwnerPushConfirmationUncertain(context, reconciliationEvidence);
      setOwnerPushConfirmationPhase(
        "needs_review",
        "The Push response could not be reconciled safely. No automatic retry will occur. Refresh the delivery view and review the persisted execution and remote SHA.",
        { request_identity: context.request_identity }
      );
      return "needs_review";
    }
  }

  function openOwnerPushConfirmation() {
    const context = ownerDeliveryActionContext();
    const initialPhase = ownerPushConfirmationPhaseFor(context.parts);
    const canConfirm = ownerPushConfirmationCanConfirm(context.parts);
    const planId = ownerDeliveryRecordId(context.parts.pushPlan);
    const planDigest = ownerDeliveryDigest(context.parts.pushPlan);
    const approvalDigest = ownerDeliveryDigest(context.parts.pushApproval);
    const requestIdentity = String(context.parts.pushConfirmation.request_identity || "");
    if (!planId || !planDigest || !approvalDigest
        || !/^[0-9a-f]{64}$/.test(requestIdentity)) {
      setFeedback(
        ownerPushConfirmationReason(
          context.parts,
          "Push confirmation is blocked because its approved Plan or request identity binding is unavailable."
        ),
        "error"
      );
      return;
    }
    const advanced = objectRecord(context.parts.pushPlan.advanced);
    state.ownerPushConfirmationContext = {
      run_id: String(context.run.id),
      plan_id: String(planId),
      plan_digest: String(planDigest),
      approval_digest: String(approvalDigest),
      request_identity: requestIdentity,
      task_selection_epoch: context.epoch
    };
    elements.ownerPushConfirmationPlan.textContent = "Push Plan " + String(planId)
      + " · v" + String(context.parts.pushPlan.version || context.parts.pushPlan.plan_version || "?");
    elements.ownerPushConfirmationRemote.textContent = sanitizedApplyPlanText(
      context.parts.pushPlan.remote_name || context.parts.pushPlan.remote || advanced.remote_name,
      "origin",
      200
    );
    elements.ownerPushConfirmationBranch.textContent = sanitizedApplyPlanText(
      context.parts.pushPlan.target_branch || context.parts.pushPlan.target_ref
        || advanced.target_ref,
      "refs/heads/main",
      320
    );
    elements.ownerPushConfirmationOldSha.textContent = boundedText(
      context.parts.pushPlan.remote_old_sha || context.parts.pushPlan.expected_remote_old_sha
        || context.parts.pushPlan.expected_remote_base_sha || advanced.remote_old_sha,
      "Not evaluated",
      500
    );
    elements.ownerPushConfirmationNewSha.textContent = boundedText(
      context.parts.pushPlan.remote_new_sha || context.parts.pushPlan.expected_new_sha
        || context.parts.pushPlan.local_commit_sha || advanced.expected_new_sha,
      "Not evaluated",
      500
    );
    elements.ownerPushConfirmationFastForward.textContent = humanStatus(
      context.parts.pushPlan.fast_forward_status || context.parts.pushPlan.fast_forward
      || "not evaluated"
    );
    setOwnerPushConfirmationPhase(
      canConfirm ? "ready_for_confirmation" : initialPhase,
      canConfirm
        ? "The approved Push Plan is current. Confirm Push authorizes one exact non-force attempt; no tag, other branch, or automatic retry is included."
        : ownerPushConfirmationReason(
          context.parts,
          "Push confirmation is blocked by the current persisted delivery state."
        ),
      { request_identity: state.ownerPushConfirmationContext.request_identity }
    );
    elements.ownerPushConfirmationDialog.showModal();
    window.setTimeout(function () { elements.cancelApprovedPush.focus(); }, 0);
  }

  async function reviewCommitPlan() {
    await performAction(
      "review-commit-plan",
      elements.reviewCommitPlan,
      "Reviewing…",
      async function () {
        const run = currentCodexRun();
        const verification = currentPassedPostApplyVerification(run);
        const subject = elements.commitPlanSubject.value;
        const body = elements.commitPlanBody.value;
        if (!verification || !verification.id) {
          throw new ApiError(
            409,
            "PASSED_VERIFICATION_REQUIRED",
            "Review Commit Plan requires the latest passed Post-Apply Verification.",
            {},
            "product"
          );
        }
        if (!validCommitSubject(subject)) {
          elements.commitPlanSubject.focus();
          throw new ApiError(
            422,
            "COMMIT_SUBJECT_INVALID",
            "Enter one nonempty Commit subject line of at most 200 UTF-8 bytes.",
            {},
            "product"
          );
        }
        if (!validCommitBody(body)) {
          elements.commitPlanBody.focus();
          throw new ApiError(
            422,
            "COMMIT_BODY_INVALID",
            "Commit body must be at most 4000 UTF-8 bytes of plain text.",
            {},
            "product"
          );
        }
        const selectionEpoch = state.taskSelectionEpoch;
        const review = await api(
          "/api/post-apply-verifications/" + encodeURIComponent(verification.id)
            + "/commit-plans",
          {
            method: "POST",
            body: {
              expected_verification_digest: postApplyVerificationDigest(verification),
              subject: subject,
              body: body
            }
          }
        );
        if (selectionEpoch !== state.taskSelectionEpoch
            || String(currentPassedPostApplyVerification(currentCodexRun()).id || "")
              !== String(verification.id)) {
          throw new ApiError(409, "STALE_COMMIT_PLAN_RESPONSE",
            "Commit Plan response no longer matches the selected Task. Review the current Task again.",
            {}, "product");
        }
        storeCommitBuilderReview(verification.id, review);
        renderCommitBuilder(run);
        return "Commit Plan reviewed. Stage remains a separate explicit Owner action.";
      }
    );
  }

  async function openPushConfirmation() {
    await performAction(
      "push-preflight",
      elements.pushToOriginMain,
      "Checking live remote…",
      async function () {
        const run = currentCodexRun();
        const commit = currentCommittedLocalCommit(run);
        const commitId = String(commitBuilderRecordId(commit) || "");
        if (!commitId) {
          throw new ApiError(
            409,
            "LOCAL_COMMIT_REQUIRED",
            "Push requires one approved, immutable local Commit result.",
            {},
            "product"
          );
        }
        const selectionEpoch = state.taskSelectionEpoch;
        const review = await api(
          "/api/local-commits/" + encodeURIComponent(commitId)
            + "/push-preflights",
          { method: "POST" }
        );
        const current = currentCommittedLocalCommit(currentCodexRun());
        if (selectionEpoch !== state.taskSelectionEpoch
            || String(commitBuilderRecordId(current) || "") !== commitId) {
          throw new ApiError(
            409,
            "STALE_PUSH_PREFLIGHT_RESPONSE",
            "Push preflight no longer matches the selected Task and local Commit result.",
            {},
            "product"
          );
        }
        storePushDeliveryReview(commitId, review);
        const parts = pushDeliveryParts(run);
        const executionId = String(parts.execution.id || "");
        const confirmationDigest = String(parts.execution.confirmation_digest || "");
        renderPushDelivery(run);
        if (parts.actions.can_confirm_push !== true
            || !executionId || !confirmationDigest) {
          state.pushConfirmationContext = null;
          if (elements.pushConfirmationDialog.open) elements.pushConfirmationDialog.close();
          setFeedback(
            pushDeliveryBlockers(parts)[0]
              || sanitizedApplyPlanText(
                parts.readiness.next_action || parts.execution.next_action,
                "Push is blocked by the current live preflight.",
                700
              ),
            "error"
          );
          return "";
        }
        state.pushConfirmationContext = {
          local_commit_execution_id: commitId,
          push_execution_id: executionId,
          confirmation_digest: confirmationDigest,
          task_selection_epoch: selectionEpoch
        };
        elements.confirmPushToOriginMain.disabled = false;
        elements.pushConfirmationRepository.textContent = sanitizedApplyPlanText(
          parts.readiness.repository || objectRecord(parts.execution.advanced).repository,
          "Bound repository",
          500
        );
        elements.pushConfirmationBranch.textContent = sanitizedApplyPlanText(
          parts.readiness.branch || parts.execution.branch,
          "main",
          240
        );
        elements.pushConfirmationCommit.textContent = boundedText(
          parts.execution.local_commit_sha || parts.readiness.local_commit_sha,
          "Not evaluated",
          500
        );
        elements.pushConfirmationSubject.textContent = sanitizedApplyPlanText(
          parts.execution.commit_subject || parts.readiness.commit_subject,
          "Not evaluated",
          300
        );
        elements.pushConfirmationRemoteBase.textContent = boundedText(
          parts.execution.expected_remote_base_sha
            || parts.readiness.expected_remote_base_sha,
          "Not evaluated",
          500
        );
        elements.pushConfirmationDestination.textContent = sanitizedApplyPlanText(
          parts.execution.destination || parts.readiness.destination,
          "origin/main",
          300
        );
        elements.pushConfirmationAheadBehind.textContent = pushAheadBehind(
          Object.assign({}, parts.readiness, parts.execution)
        );
        elements.pushConfirmationCleanliness.textContent = pushCleanliness(
          Object.assign({}, parts.readiness, parts.execution)
        );
        elements.pushConfirmationFastForward.textContent =
          "Standard fast-forward of the exact approved commit to refs/heads/main; no force, tag, or other branch.";
        elements.pushConfirmationDialog.showModal();
        window.setTimeout(function () { elements.cancelPushToOriginMain.focus(); }, 0);
        return "Live Push preflight passed. Review the exact remote base before confirming.";
      }
    );
  }

  async function confirmPushToOriginMain() {
    const context = state.pushConfirmationContext;
    if (!context || !context.push_execution_id || !context.confirmation_digest) return;
    await performAction(
      "confirm-push-to-origin-main",
      elements.confirmPushToOriginMain,
      "Pushing…",
      async function () {
        if (context.task_selection_epoch !== state.taskSelectionEpoch) {
          throw new ApiError(
            409,
            "STALE_PUSH_CONFIRMATION",
            "Push confirmation no longer matches the selected Task.",
            {},
            "product"
          );
        }
        const review = await api(
          "/api/push-preflights/" + encodeURIComponent(context.push_execution_id)
            + "/push-attempts",
          {
            method: "POST",
            body: {
              confirmation: "PUSH_TO_ORIGIN_MAIN",
              expected_confirmation_digest: context.confirmation_digest
            }
          }
        );
        const current = currentCommittedLocalCommit(currentCodexRun());
        if (context.task_selection_epoch !== state.taskSelectionEpoch
            || String(commitBuilderRecordId(current) || "")
              !== String(context.local_commit_execution_id)) {
          throw new ApiError(
            409,
            "STALE_PUSH_RESULT_RESPONSE",
            "Push result no longer matches the selected Task and local Commit result.",
            {},
            "product"
          );
        }
        storePushDeliveryReview(context.local_commit_execution_id, review);
        state.pushConfirmationContext = null;
        elements.pushConfirmationDialog.close();
        const parts = pushDeliveryParts(currentCodexRun());
        renderPushDelivery(currentCodexRun());
        if (pushDeliveryState(parts) !== "PUSHED") {
          setFeedback(
            pushDeliveryBlockers(parts)[0]
              || sanitizedApplyPlanText(
                parts.execution.next_action || parts.readiness.next_action,
                "Push did not complete. Review the persisted blocker evidence.",
                700
              ),
            "error"
          );
          return "";
        }
        return "The exact approved local commit was pushed once to origin/main. View the Delivery Result.";
      }
    );
  }

  async function viewDeliveryResult() {
    await performAction(
      "view-delivery-result",
      elements.viewDeliveryResult,
      "Loading result…",
      async function () {
        const run = currentCodexRun();
        const commit = currentCommittedLocalCommit(run);
        const commitId = String(commitBuilderRecordId(commit) || "");
        if (!commitId) {
          throw new ApiError(
            409,
            "LOCAL_COMMIT_REQUIRED",
            "Delivery Result requires one approved local Commit result.",
            {},
            "product"
          );
        }
        await loadPushDelivery(run, true);
        const review = objectRecord(state.pushDeliveryReviews[commitId]);
        if (objectRecord(review.actions).can_view_delivery_result !== true) {
          throw new ApiError(
            409,
            "DELIVERY_RESULT_NOT_READY",
            "Delivery Result is not available until the Push attempt reaches a durable result.",
            {},
            "product"
          );
        }
        state.pushDeliveryResultVisible.add(commitId);
        renderPushDelivery(run);
        return "Delivery Result refreshed from live local and origin/main reconciliation.";
      }
    );
  }

  async function confirmStageApprovedFiles() {
    const context = state.stageConfirmationContext;
    if (!context || !context.plan_id) return;
    await performAction(
      "stage-approved-files",
      elements.confirmStageApprovedFiles,
      "Staging…",
      async function () {
        const review = await api(
          "/api/commit-plans/" + encodeURIComponent(context.plan_id)
            + "/stage-sessions",
          {
            method: "POST",
            body: {
              confirmation: "STAGE_APPROVED_FILES",
              expected_plan_digest: context.plan_digest
            }
          }
        );
        storeCommitBuilderReview(context.verification_id, review);
        state.stageConfirmationContext = null;
        elements.stageConfirmationDialog.close();
        const run = currentCodexRun();
        await loadApplySessionReview(run, true);
        await loadPostApplyVerification(run, true);
        await loadCommitBuilder(run, true);
        renderApplySessionReview(run);
        renderPostApplyVerification(run);
        renderCommitBuilder(run);
        return "Only the approved files were staged. Local Commit requires a separate Owner action.";
      }
    );
  }

  async function confirmCreateLocalCommit() {
    const context = state.localCommitConfirmationContext;
    if (!context || !context.plan_id || !context.stage_id) return;
    await performAction(
      "create-local-commit",
      elements.confirmCreateLocalCommit,
      "Creating…",
      async function () {
        const review = await api(
          "/api/stage-sessions/" + encodeURIComponent(context.stage_id)
            + "/local-commits",
          {
            method: "POST",
            body: {
              confirmation: "CREATE_LOCAL_COMMIT",
              expected_plan_digest: context.plan_digest,
              expected_stage_digest: context.stage_digest
            }
          }
        );
        storeCommitBuilderReview(context.verification_id, review);
        state.localCommitConfirmationContext = null;
        elements.localCommitConfirmationDialog.close();
        const run = currentCodexRun();
        await loadApplySessionReview(run, true);
        await loadPostApplyVerification(run, true);
        await loadCommitBuilder(run, true);
        renderApplySessionReview(run);
        renderPostApplyVerification(run);
        renderCommitBuilder(run);
        return "Local Commit created. Review Push readiness before any separate remote action.";
      }
    );
  }

  async function confirmApplyAcceptedChanges() {
    const context = state.applyConfirmationContext;
    if (!context || !context.plan_id) return;
    await performAction(
      "apply-accepted-changes",
      elements.confirmApplyAcceptedChanges,
      "Applying…",
      async function () {
        const review = await api(
          "/api/apply-plans/" + encodeURIComponent(context.plan_id) + "/apply-sessions",
          {
            method: "POST",
            body: {
              confirmation: "APPLY_ACCEPTED_CHANGES",
              expected_plan_digest: context.plan_digest,
              expected_candidate_digest: context.candidate_digest,
              expected_plan_approval_digest: context.plan_approval_digest || null,
              expected_result_digest: context.result_digest || null,
              expected_result_review_decision_digest:
                context.result_review_decision_digest || null
            }
          }
        );
        if (!review || String(review.plan_id || "") !== String(context.plan_id)) {
          throw new ApiError(
            200,
            "APPLY_SESSION_BINDING_MISMATCH",
            "The Apply session did not match the confirmed Apply Plan.",
            {},
            "product"
          );
        }
        state.applySessionReviews[String(context.plan_id)] = review;
        state.applySessionReviewLoads.add(String(context.plan_id));
        state.applyConfirmationContext = null;
        elements.applyConfirmationDialog.close();
        renderApplySessionReview(currentCodexRun());
        await loadPostApplyVerification(currentCodexRun(), true);
        renderPostApplyVerification(currentCodexRun());
        return objectRecord(review.session).apply_state === "APPLIED"
          ? "Accepted changes applied. Nothing was staged, committed, or pushed."
          : "";
      }
    );
  }

  async function confirmRevertAppliedChanges() {
    const context = state.revertConfirmationContext;
    if (!context || !context.session_id) return;
    await performAction(
      "revert-applied-changes",
      elements.confirmRevertAppliedChanges,
      "Reverting…",
      async function () {
        const review = await api(
          "/api/apply-sessions/" + encodeURIComponent(context.session_id) + "/reverts",
          {
            method: "POST",
            body: {
              confirmation: "REVERT_APPLIED_CHANGES",
              expected_journal_digest: context.journal_digest
            }
          }
        );
        const planId = String(review && review.plan_id || "");
        if (!review || !planId) {
          throw new ApiError(
            200,
            "REVERT_SESSION_BINDING_MISMATCH",
            "The Revert result did not match the confirmed Apply session.",
            {},
            "product"
          );
        }
        state.applySessionReviews[planId] = review;
        state.applySessionReviewLoads.add(planId);
        state.revertConfirmationContext = null;
        elements.revertConfirmationDialog.close();
        renderApplySessionReview(currentCodexRun());
        delete state.postApplyVerificationReviews[String(context.session_id)];
        state.postApplyVerificationReviewLoads.delete(String(context.session_id));
        state.commitBuilderReviews = Object.create(null);
        state.commitBuilderReviewLoads = new Set();
        state.commitBuilderRequestSequences = Object.create(null);
        state.pushDeliveryReviews = Object.create(null);
        state.pushDeliveryReviewLoads = new Set();
        state.pushDeliveryRequestSequences = Object.create(null);
        state.pushDeliveryResultVisible = new Set();
        state.pushConfirmationContext = null;
        renderPostApplyVerification(currentCodexRun());
        renderCommitBuilder(currentCodexRun());
        renderPushDelivery(currentCodexRun());
        return objectRecord(review.session).revert_state === "REVERTED"
          ? "Applied changes reverted. Nothing was staged, committed, or pushed."
          : "";
      }
    );
  }

  async function cancelCodex() {
    await performAction("cancel-codex", elements.cancelCodex, "Cancelling…", async function () {
      const run = currentCodexRun();
      if (!run) throw new ApiError(400, "NO_RUN", "No active Codex run is available.", {}, "product");
      const result = await api("/api/codex-runs/" + run.id + "/cancel", { method: "POST" });
      return result.cancellation_request_replayed
        ? "Codex cancellation was already requested."
        : "Codex cancellation requested.";
    });
  }

  async function confirmApprovedPush() {
    const context = state.ownerPushConfirmationContext;
    if (!context) {
      setOwnerPushConfirmationPhase(
        "blocked",
        "Push confirmation is not bound to a current approved Push Plan. Close this dialog and review the current delivery state."
      );
      return;
    }
    if (state.pending.has("confirm-owner-push")) return;
    const currentParts = ownerDeliveryParts(currentCodexRun());
    const currentRequestIdentity = String(
      objectRecord(currentParts.pushConfirmation).request_identity || ""
    );
    const bindingsCurrent = String(ownerDeliveryRecordId(currentParts.pushPlan) || "")
        === String(context.plan_id)
      && String(ownerDeliveryDigest(currentParts.pushPlan)) === String(context.plan_digest)
      && String(ownerDeliveryDigest(currentParts.pushApproval)) === String(context.approval_digest)
      && currentRequestIdentity === String(context.request_identity);
    if (!bindingsCurrent) {
      setOwnerPushConfirmationPhase(
        "blocked",
        "The approved Push Plan or request identity changed. Close this dialog and review the current Push Plan before any new confirmation.",
        { request_identity: context.request_identity }
      );
      return;
    }
    if (!ownerPushConfirmationCanConfirm(currentParts)) {
      const persistedPhase = ownerPushConfirmationPhaseFor(currentParts);
      setOwnerPushConfirmationPhase(
        persistedPhase,
        ownerPushConfirmationReason(
          currentParts,
          "Push confirmation is no longer eligible. Review the current persisted delivery state."
        ),
        { request_identity: context.request_identity }
      );
      return;
    }
    state.pending.add("confirm-owner-push");
    setOwnerPushConfirmationPhase(
      "submitting",
      state.refreshing
        ? "Waiting for the current read-only evidence refresh to finish before sending one Push request. Hide does not cancel an accepted request."
        : "Submitting one bound Push request. Hide does not cancel it if the server accepts execution.",
      { request_identity: context.request_identity }
    );
    let requestDispatched = false;
    try {
      if (context.task_selection_epoch !== state.taskSelectionEpoch
          || String(objectRecord(currentCodexRun()).id || "") !== context.run_id) {
        throw new ApiError(
          409,
          "STALE_PUSH_CONFIRMATION",
          "Push confirmation no longer matches the selected Task and Run.",
          {},
          "product"
        );
      }
      await waitForOwnerPushRefresh();
      setOwnerPushConfirmationPhase(
        "running",
        "The server is processing the one approved Push request. Hiding this dialog does not cancel execution; refresh reconciles persisted execution and remote evidence.",
        { request_identity: context.request_identity }
      );
      requestDispatched = true;
      beginOwnerPushConfirmationReconciliation(context);
      const response = await api(
        "/api/push-plans/" + encodeURIComponent(context.plan_id) + "/push-attempts",
        {
          method: "POST",
          timeoutMs: OWNER_PUSH_RESPONSE_TIMEOUT_MS,
          body: {
            confirmation: "PUSH_TO_ORIGIN_MAIN",
            expected_plan_digest: context.plan_digest,
            expected_approval_digest: context.approval_digest,
            request_identity: context.request_identity
          }
        }
      );
      const execution = objectRecord(response.push_execution);
      const executionState = String(
        execution.canonical_state || execution.state || ""
      ).toUpperCase();
      const deliveryResult = objectRecord(response.delivery_result);
      const deliveryState = String(
        deliveryResult.status || deliveryResult.state || ""
      ).toUpperCase();
      if (["PUSHED", "SUCCEEDED", "DELIVERED", "ALREADY_DELIVERED"].indexOf(executionState) === -1
          && ["DELIVERED", "ALREADY_DELIVERED"].indexOf(deliveryState) === -1) {
        await reconcileOwnerPushConfirmation(
          context,
          new ApiError(
            200,
            "PUSH_NOT_TERMINAL",
            "The accepted Push request has not reached a verified delivery receipt yet.",
            {},
            "product"
          )
        );
        return;
      }
      const alreadyDelivered = executionState === "ALREADY_DELIVERED"
        || deliveryState === "ALREADY_DELIVERED";
      setOwnerPushConfirmationPhase(
        alreadyDelivered ? "already_delivered" : "succeeded",
        alreadyDelivered
          ? "The exact Commit was already present at the approved remote ref. No second Push was issued."
          : "The exact remote SHA was verified and the delivery receipt was persisted.",
        { request_identity: context.request_identity }
      );
      state.ownerPushConfirmationUncertainty = null;
      state.ownerPushConfirmationContext = null;
      if (elements.ownerPushConfirmationDialog.open) elements.ownerPushConfirmationDialog.close();
      await refreshWorkspace({ force: true });
      setFeedback(
        alreadyDelivered
          ? "The exact Commit was already delivered. No second Push was issued."
          : "Push delivered once. Review the verified remote SHA and persisted receipt.",
        "success"
      );
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        handleExpiredSession();
        return;
      }
      if (!requestDispatched) {
        const safeToRetry = error instanceof ApiError
          && error.code === "WORKSPACE_REFRESH_ACTIVE";
        setOwnerPushConfirmationPhase(
          safeToRetry ? "ready_for_confirmation" : "blocked",
          productActionMessage(error),
          { request_identity: context.request_identity }
        );
        setFeedback(productActionMessage(error), safeToRetry ? "neutral" : "error");
        return;
      }
      const phase = await reconcileOwnerPushConfirmation(context, error);
      setFeedback(
        phase === "ready_for_confirmation"
          ? productActionMessage(error) + " No automatic retry occurred."
          : "Push did not settle as delivered. Review the visible confirmation state and persisted evidence.",
        phase === "ready_for_confirmation" ? "neutral" : "error"
      );
    } finally {
      state.pending.delete("confirm-owner-push");
      if (state.auth === AUTH_STATES.SIGNED_IN
          && !elements.ownerPushConfirmationDialog.open) {
        renderWorkspace();
      }
    }
  }

  function closeOrHideOwnerPushConfirmation() {
    const hidingAcceptedRequest = ownerPushConfirmationBusy();
    if (!hidingAcceptedRequest) {
      state.ownerPushConfirmationContext = null;
    }
    if (elements.ownerPushConfirmationDialog.open) {
      elements.ownerPushConfirmationDialog.close();
    }
    if (hidingAcceptedRequest) {
      renderWorkspace();
      setFeedback(
        "Push submission remains active. Hiding the confirmation does not cancel an accepted request; refresh reconciles persisted execution and remote evidence.",
        "neutral"
      );
    }
  }

  async function decideAcceptance(decision) {
    const button = decision === "accept" ? elements.acceptResult : elements.rejectResult;
    const pending = decision === "accept" ? "Accepting…" : "Rejecting…";
    await performAction("acceptance-decision", button, pending, async function () {
      const acceptance = state.ownerAcceptance;
      if (!acceptance) throw new ApiError(400, "NO_ACCEPTANCE", "No acceptance session is ready.", {}, "product");
      if (acceptance.review_kind === "result_delivery") {
        const run = currentCodexRun();
        const envelope = resultEnvelopeForRun(run);
        const candidate = objectRecord(
          objectRecord(deliveryCandidateReviewForRun(run)).candidate
        );
        const advanced = objectRecord(candidate.advanced);
        if (!run || !envelope || !candidate.id) {
          throw new ApiError(
            409,
            "RESULT_DELIVERY_BINDING_UNAVAILABLE",
            "The exact Result and Candidate binding is unavailable.",
            {},
            "product"
          );
        }
        const routeDecision = decision === "accept" ? "accept" : "reject";
        const response = await api(
          "/api/codex-runs/" + encodeURIComponent(run.id)
            + "/delivery-review/" + routeDecision,
          {
            method: "POST",
            body: {
              confirmation: decision === "accept"
                ? "ACCEPT_RESULT_FOR_DELIVERY"
                : "REJECT_RESULT_FOR_DELIVERY",
              expected_result_id: envelope.id || acceptance.result_id || "",
              expected_result_digest:
                advanced.result_digest || objectRecord(acceptance.advanced).result_digest || "",
              expected_candidate_id: candidate.id,
              expected_candidate_version: Number(candidate.candidate_version || 1),
              expected_candidate_digest:
                advanced.candidate_digest || objectRecord(acceptance.advanced).candidate_digest || "",
              note: elements.acceptanceNote.value
            }
          }
        );
        state.ownerAcceptance = response.review;
        state.deliveryCandidateReviewLoads.delete(String(run.id));
        await loadDeliveryCandidateReview(run);
        return decision === "accept"
          ? "Result accepted for delivery. No Apply, Stage, Commit, Push, or new Run started."
          : "Result rejected for delivery. The captured Result remains available.";
      }
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

  function browserRunObserverActive() {
    const run = currentCodexRun();
    if (run && lifecycleIsActive(authoritativeRunStatus(run))) return true;
    return state.runActivity.map(activityView).some(activityNeedsBrowserObservation);
  }

  async function loadFirstDeliveryGuide(task, epoch) {
    state.firstDeliveryGuide = null;
    if (!task || !state.firstRun || state.firstRun.enabled !== true) return;
    const guide = await api("/api/tasks/" + task.id + "/first-delivery");
    if (epoch === state.taskSelectionEpoch && String(state.selectedTaskId) === String(task.id)) state.firstDeliveryGuide = guide;
  }

  function renderFirstDeliveryGuide() {
    const guide = state.firstDeliveryGuide;
    const task = selectedTask();
    const run = guide && guide.stage_index >= 4 ? currentCodexRun() : null;
    const panel = byId("first-delivery-guide");
    panel.hidden = !guide || !task || String(guide.task_id) !== String(task.id)
      || guide.stage_index >= 4 && (!run || String(guide.run_id) !== String(run.id));
    if (panel.hidden) return;
    byId("first-delivery-title").textContent = String(guide.stage_index + 1) + ". " + guide.stage;
    byId("first-delivery-message").textContent = guide.message;
    byId("first-delivery-action").textContent = guide.action_label;
    const location = guide.location || {};
    byId("first-delivery-workspace").textContent = location.authorized_workspace || "Unavailable";
    byId("first-delivery-source").textContent = location.source_repository || "Unavailable";
    byId("first-delivery-targets").textContent = (location.targets || []).map(function (target) {
      return target.source_target_path + (target.apply_result ? " — " + target.apply_result : "");
    }).join("\n") || "Review the Task scope and Candidate for exact target paths.";
    byId("first-delivery-target-basis").textContent = location.target_basis || "";
    byId("first-delivery-applied-evidence").textContent = "Apply: " + (location.apply_state || "Not applied")
      + ". Post-Apply validation: " + (location.post_apply_validation || "Not verified") + ".";
    const stages = byId("first-delivery-stages");
    stages.replaceChildren();
    guide.stages.forEach(function (label, index) {
      const item = document.createElement("li");
      item.textContent = label;
      if (index === guide.stage_index) item.setAttribute("aria-current", "step");
      stages.appendChild(item);
    });
  }

  function guidedToolSelectionsChanged() {
    const config = state.guidedToolChecked;
    if (config && config.model === byId("guided-model").value && config.reasoning_effort === byId("guided-effort").value) return;
    state.guidedToolChecked = null;
    renderGuidedToolControls();
    byId("guided-auth").textContent = "Not checked for this configuration";
    byId("guided-tool-state").textContent = "Not checked for this configuration. Select Check Codex Readiness explicitly.";
  }

  function renderGuidedToolControls() {
    const config = state.guidedToolChecked;
    const checking = state.guidedToolChecking === true;
    const matches = config && config.model === byId("guided-model").value && config.reasoning_effort === byId("guided-effort").value;
    const ready = Boolean(matches && config.ready);
    const button = byId("guided-tool-check");
    button.disabled = checking || ready || !state.guidedToolDiscovery || state.guidedToolDiscovery.status !== "Not checked" || !byId("guided-model").value || !byId("guided-effort").value;
    button.className = "button " + (ready ? "button-quiet" : "button-primary");
    button.textContent = checking ? "Checking Codex Readiness…" : ready ? "Codex Readiness checked" : "Check Codex Readiness";
    byId("guided-tool-save").disabled = checking || !ready || config.confirmed === true;
    byId("guided-model").disabled = checking;
    byId("guided-effort").disabled = checking;
    byId("guided-tool-close").disabled = checking;
  }

  function populateGuidedEfforts(preferred) {
    const model = (state.guidedToolDiscovery.models || []).find(function (item) { return item.model === byId("guided-model").value; });
    const select = byId("guided-effort");
    select.replaceChildren();
    (model ? model.reasoning_efforts : []).forEach(function (effort) {
      const option = document.createElement("option");
      option.value = effort;
      option.textContent = effort === "xhigh" ? "Extra high (xhigh)" : effort === "max" ? "Maximum (max)" : effort;
      select.appendChild(option);
    });
    if (Array.from(select.options).some(function (option) { return option.value === preferred; })) select.value = preferred;
  }

  function showGuidedConfiguration(config) {
    state.guidedToolChecked = config;
    byId("guided-tool-state").textContent = config ? config.status + ". " + config.next_action : "Not checked. Select Check Codex Readiness explicitly.";
    byId("guided-auth").textContent = config ? config.authentication : "Not checked";
    byId("guided-last-check").textContent = config && config.last_successful_readiness_check || "Never";
    renderGuidedToolControls();
  }

  async function openGuidedToolSetup() {
    const dialog = byId("guided-tool-dialog");
    if (state.guidedToolChecking) return;
    state.guidedToolChecked = null;
    byId("guided-auth").textContent = "Not checked";
    byId("guided-last-check").textContent = "Never";
    byId("guided-tool-state").textContent = "Reading local CLI metadata…";
    byId("guided-tool-check").disabled = true;
    byId("guided-tool-save").disabled = true;
    if (!dialog.open) dialog.showModal();
    try {
      const response = await api("/api/guided-tool-setup");
      const found = response.discovery;
      state.guidedToolDiscovery = found;
      byId("guided-executable").textContent = found.executable || "Not found";
      byId("guided-version").textContent = found.cli_version || "Unavailable";
      byId("guided-minimum").textContent = found.minimum_supported_version;
      byId("guided-tool-evidence").textContent = JSON.stringify({ executable_identity: found.executable_identity, catalogue_source: found.catalogue_source, provider_request_performed: false }, null, 2);
      const select = byId("guided-model");
      select.replaceChildren();
      (found.models || []).forEach(function (entry) {
        const option = document.createElement("option");
        option.value = entry.model;
        option.textContent = entry.model;
        select.appendChild(option);
      });
      const wanted = response.configuration ? response.configuration.model : "gpt-6-astra";
      select.value = wanted;
      populateGuidedEfforts(response.configuration ? response.configuration.reasoning_effort : "xhigh");
      showGuidedConfiguration(response.configuration);
      if (found.status !== "Not checked" || !select.value) byId("guided-tool-state").textContent = found.status + ". " + found.next_action;
    } catch (error) { byId("guided-tool-state").textContent = productActionMessage(error); }
  }

  async function checkGuidedTool() {
    const button = byId("guided-tool-check");
    if (button.disabled || state.guidedToolChecking) return;
    state.guidedToolChecking = true;
    renderGuidedToolControls();
    byId("guided-tool-state").textContent = "Checking the exact selected Codex configuration after your explicit action…";
    try {
      const result = await api("/api/guided-tool-setup/check", { method: "POST", body: { model_identifier: byId("guided-model").value, reasoning_effort: byId("guided-effort").value } });
      showGuidedConfiguration(result.configuration);
    } catch (error) { state.guidedToolChecked = null; byId("guided-tool-state").textContent = productActionMessage(error); }
    finally { state.guidedToolChecking = false; renderGuidedToolControls(); }
  }

  async function saveGuidedTool() {
    const config = state.guidedToolChecked;
    if (!config || byId("guided-tool-save").disabled) return;
    await performAction("save-guided-tool", byId("guided-tool-save"), "Saving…", async function () {
      await api("/api/guided-tool-setup/save", { method: "POST", body: { configuration_id: config.id } });
      byId("guided-tool-dialog").close();
      return "Tool Setup saved. Prepare First Delivery when you are ready.";
    });
  }

  async function firstDeliveryAction() {
    const guide = state.firstDeliveryGuide;
    const task = selectedTask();
    if (!guide || !task || String(guide.task_id) !== String(task.id)) return;
    if (guide.stage_index >= 4) {
      const run = currentCodexRun();
      if (!run || String(guide.run_id) !== String(run.id)) return;
    }
    if (guide.next_action === "tool_setup") return openGuidedToolSetup();
    if (guide.next_action === "prepare") {
      return performAction("prepare-first-delivery", byId("first-delivery-action"), "Preparing…", async function () {
        const pack = await api("/api/tasks/" + task.id + "/first-delivery/prepare", { method: "POST" });
        state.selectedPackId = pack.id;
        return "Instruction Pack prepared. Review and approve it explicitly; no Run has started.";
      });
    }
    if (guide.next_action === "review_pack") {
      const pack = currentPack();
      if (!pack || String(pack.id) !== String(guide.pack_id)) return;
      byId("guided-pack-summary").textContent = "Task: " + task.title + ". Version: " + pack.task_version + ". Model: " + guide.configuration.model + ". Reasoning: " + guide.configuration.reasoning_effort + ". Verification: independent local exact-content check. Coding may only change the isolated Run workspace; no Commit or Push is authorized.";
      byId("guided-pack-deliverable").textContent = task.required_output || pack.acceptance_target || task.objective;
      byId("guided-pack-workspace").textContent = guide.configuration.workspace;
      byId("guided-pack-source").textContent = pack.source_snapshot_digest ? "Source snapshot captured and bound to this Pack. Approval and Start recheck it for changes." : "Source snapshot unavailable; preparation must be repeated.";
      byId("guided-pack-content").textContent = (pack.content || "") + "\n\nBound source and tool evidence:\n" + JSON.stringify(pack.generation_metadata || {}, null, 2);
      byId("guided-pack-dialog").showModal();
      return;
    }
    if (guide.next_action === "start_run") return openCodexRunConfirmation();
    if (guide.next_action === "validate_applied") return verifyAppliedChanges();
    if (guide.next_action === "review_candidate") return reviewChangeCandidate();
    if (guide.next_action === "approve_apply_plan") return approveApplyPlan();
    if (guide.next_action === "apply") return openApplyConfirmation();
    if (guide.next_action === "delivery") {
      const code = guide.delivery && guide.delivery.next_action && guide.delivery.next_action.primary && guide.delivery.next_action.primary.code;
      if (code === "review_commit") return reviewOwnerCommit();
      if (code === "approve_commit") return approveOwnerCommitProposal();
      if (code === "confirm_local_commit") return openOwnerLocalCommitConfirmation();
      if (code === "review_push_plan") return reviewOwnerPushPlan();
      if (code === "approve_push_plan") return approveOwnerPushPlan();
      if (code === "confirm_push") return openOwnerPushConfirmation();
    }
    const target = byId(guide.next_action === "view_run" ? "run-card" : guide.stage_index >= 8 ? "commit-builder-section" : "result-card");
    if (target) target.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function bindEvents() {
    byId("guided-tool-open").addEventListener("click", openGuidedToolSetup);
    byId("first-delivery-action").addEventListener("click", firstDeliveryAction);
    byId("guided-tool-check").addEventListener("click", checkGuidedTool);
    byId("guided-tool-save").addEventListener("click", saveGuidedTool);
    byId("guided-tool-close").addEventListener("click", function () { byId("guided-tool-dialog").close(); });
    byId("guided-model").addEventListener("change", function () { populateGuidedEfforts("xhigh"); guidedToolSelectionsChanged(); });
    byId("guided-effort").addEventListener("change", guidedToolSelectionsChanged);
    byId("guided-pack-close").addEventListener("click", function () { byId("guided-pack-dialog").close(); });
    byId("guided-pack-approve").addEventListener("click", async function () { await approvePack(); byId("guided-pack-dialog").close(); });
    elements.firstRunStart.addEventListener("click", startFirstRun);
    elements.firstRunConfirmInstallation.addEventListener("click", confirmFirstRunInstallation);
    elements.firstRunOwnerForm.addEventListener("submit", function (event) {
      event.preventDefault();
      createFirstRunOwner();
    });
    elements.firstRunWorkspaceForm.addEventListener("submit", function (event) {
      event.preventDefault();
      authorizeFirstRunWorkspace();
    });
    elements.firstRunReviewTools.addEventListener("click", function () {
      completeOptionalToolReview("review", elements.firstRunReviewTools);
    });
    elements.firstRunSkipTools.addEventListener("click", function () {
      completeOptionalToolReview("skip", elements.firstRunSkipTools);
    });
    elements.firstRunFinishSetup.addEventListener("click", finishFirstRunSetup);
    elements.firstRunRefreshStatus.addEventListener("click", refreshFirstRunStatus);
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
      elements.verifyCodexConnection.disabled = true;
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
        elements.verifyCodexConnection.disabled = true;
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
    elements.verifyCodexConnection.addEventListener("click", verifyCodexConnection);
    elements.saveAssignCodex.addEventListener("click", saveAndAssignCodex);
    elements.cancelCodexSetup.addEventListener("click", function () { elements.codexSetupDialog.close(); });
    elements.codexSetupDialog.addEventListener("close", resetCodexSetupDialog);
    elements.generatePack.addEventListener("click", generatePack);
    elements.approvePack.addEventListener("click", approvePack);
    elements.runCodex.addEventListener("click", openCodexRunConfirmation);
    elements.confirmStartCodexRun.addEventListener("click", runCodex);
    elements.cancelStartCodexRun.addEventListener("click", function () {
      state.runConfirmationContext = null;
      elements.startCodexConfirmationDialog.close();
    });
    elements.startCodexConfirmationDialog.addEventListener("cancel", function () {
      state.runConfirmationContext = null;
    });
    elements.refreshRunStatus.addEventListener("click", refreshRunStatus);
    elements.reconnectCodexRun.addEventListener("click", reconnectCodexRun);
    elements.importCodexResult.addEventListener("click", function () {
      elements.importCodexResultFile.click();
    });
    elements.importCodexResultFile.addEventListener("change", function () {
      importCodexResultFile(elements.importCodexResultFile.files[0]).catch(function (error) {
        elements.importCodexResultFile.value = "";
        setFeedback(productActionMessage(error), "error");
      });
    });
    elements.reviewHandoff.addEventListener("click", reviewHandoff);
    elements.reviewInstructionDraft.addEventListener("click", reviewInstructionDraft);
    elements.approveInstructionDraft.addEventListener("click", approveInstructionDraft);
    elements.reviewChangeCandidate.addEventListener("click", reviewChangeCandidate);
    elements.reviewApplyPlan.addEventListener("click", reviewApplyPlan);
    elements.approveApplyPlan.addEventListener("click", approveApplyPlan);
    elements.applyPlanHistory.addEventListener("change", loadHistoricalApplyPlan);
    elements.applyAcceptedChanges.addEventListener("click", openApplyConfirmation);
    elements.revertAppliedChanges.addEventListener("click", openRevertConfirmation);
    elements.verifyAppliedChanges.addEventListener("click", verifyAppliedChanges);
    elements.reviewOwnerCommit.addEventListener("click", reviewOwnerCommit);
    elements.approveCommitProposal.addEventListener("click", approveOwnerCommitProposal);
    elements.confirmOwnerLocalCommit.addEventListener("click", openOwnerLocalCommitConfirmation);
    elements.reviewCommitPlan.addEventListener("click", reviewCommitPlan);
    elements.stageApprovedFiles.addEventListener("click", openStageConfirmation);
    elements.createLocalCommit.addEventListener("click", openLocalCommitConfirmation);
    elements.pushToOriginMain.addEventListener("click", openPushConfirmation);
    elements.reviewPushPlan.addEventListener("click", reviewOwnerPushPlan);
    elements.approvePushPlan.addEventListener("click", approveOwnerPushPlan);
    elements.confirmOwnerPush.addEventListener("click", openOwnerPushConfirmation);
    elements.viewDeliveryResult.addEventListener("click", viewDeliveryResult);
    elements.confirmApplyAcceptedChanges.addEventListener("click", confirmApplyAcceptedChanges);
    elements.cancelApplyAcceptedChanges.addEventListener("click", function () {
      state.applyConfirmationContext = null;
      elements.applyConfirmationDialog.close();
    });
    elements.confirmRevertAppliedChanges.addEventListener("click", confirmRevertAppliedChanges);
    elements.cancelRevertAppliedChanges.addEventListener("click", function () {
      state.revertConfirmationContext = null;
      elements.revertConfirmationDialog.close();
    });
    elements.applyConfirmationDialog.addEventListener("cancel", function () {
      state.applyConfirmationContext = null;
    });
    elements.revertConfirmationDialog.addEventListener("cancel", function () {
      state.revertConfirmationContext = null;
    });
    elements.confirmStageApprovedFiles.addEventListener("click", confirmStageApprovedFiles);
    elements.cancelStageApprovedFiles.addEventListener("click", function () {
      state.stageConfirmationContext = null;
      elements.stageConfirmationDialog.close();
    });
    elements.confirmCreateLocalCommit.addEventListener("click", confirmCreateLocalCommit);
    elements.cancelCreateLocalCommit.addEventListener("click", function () {
      state.localCommitConfirmationContext = null;
      elements.localCommitConfirmationDialog.close();
    });
    elements.confirmPushToOriginMain.addEventListener("click", confirmPushToOriginMain);
    elements.cancelPushToOriginMain.addEventListener("click", function () {
      state.pushConfirmationContext = null;
      elements.pushConfirmationDialog.close();
    });
    elements.stageConfirmationDialog.addEventListener("cancel", function () {
      state.stageConfirmationContext = null;
    });
    elements.localCommitConfirmationDialog.addEventListener("cancel", function () {
      state.localCommitConfirmationContext = null;
    });
    elements.pushConfirmationDialog.addEventListener("cancel", function () {
      state.pushConfirmationContext = null;
    });
    elements.confirmApprovedLocalCommit.addEventListener("click", confirmApprovedLocalCommit);
    elements.cancelApprovedLocalCommit.addEventListener("click", function () {
      state.ownerCommitConfirmationContext = null;
      elements.ownerLocalCommitConfirmationDialog.close();
    });
    elements.ownerLocalCommitConfirmationDialog.addEventListener("cancel", function () {
      state.ownerCommitConfirmationContext = null;
    });
    elements.confirmApprovedPush.addEventListener("click", confirmApprovedPush);
    elements.cancelApprovedPush.addEventListener("click", closeOrHideOwnerPushConfirmation);
    elements.ownerPushConfirmationDialog.addEventListener("cancel", function (event) {
      event.preventDefault();
      closeOrHideOwnerPushConfirmation();
    });
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
    if (
      state.auth === AUTH_STATES.SIGNED_IN
      && !document.hidden
      && state.pending.size === 0
      && browserRunObserverActive()
    ) refreshWorkspace();
  }, ACTIVE_RUN_POLL_INTERVAL_MS);
}());
