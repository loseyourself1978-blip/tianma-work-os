from __future__ import annotations

import json
import re
from contextlib import contextmanager
from typing import Iterator

from sqlalchemy import Engine, MetaData, create_engine, inspect, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.schema import CreateTable

from .models import (
    AICapability,
    AIModel,
    AIModelAvailabilityEvidence,
    Base,
    Project,
    Provider,
    SchemaVersion,
    Tool,
    stable_model_identifier,
)


VOL17_SCHEMA_VERSION = "vol17.001"
VOL17_MODEL_SETUP_SCHEMA_VERSION = "vol17.002"
VOL17_END_TO_END_SCHEMA_VERSION = "vol17.003"
VOL17_REAL_EVIDENCE_SCHEMA_VERSION = "vol17.004"
VOL18_DELIVERY_CANDIDATE_SCHEMA_VERSION = "vol18.001"
VOL18_REVIEW_APPLY_PLAN_SCHEMA_VERSION = "vol18.002"
VOL18_APPLY_REVERT_SCHEMA_VERSION = "vol18.003"
VOL18_RESULT_INTAKE_SCHEMA_VERSION = "vol18.004"
VOL18_CODEX_CONNECTIVITY_SCHEMA_VERSION = "vol18.005"
VOL18_EXEC_LIFECYCLE_SCHEMA_VERSION = "vol18.006"
VOL18_POST_APPLY_VERIFICATION_SCHEMA_VERSION = "vol18.007"
VOL18_LOCAL_COMMIT_BUILDER_SCHEMA_VERSION = "vol18.008"
VOL18_PUSH_DELIVERY_SCHEMA_VERSION = "vol18.009"
VOL19_CODEX_RUN_RESULT_SCHEMA_VERSION = "vol19.001"
VOL19_RESULT_DELIVERY_LOOP_SCHEMA_VERSION = "vol19.002"
VOL19_OWNER_COMMIT_PUSH_SCHEMA_VERSION = "vol19.003"


DEFAULT_PROJECTS = [
    ("ldd", "LDD"),
    ("wc", "2026WC"),
    ("twos", "TWOS Product Development"),
]

# Vol.17 does not invent vendor configuration. Model providers are created only
# from explicit runtime/persisted configuration; upgraded Vol.16 placeholders
# remain preserved in the database but are not treated as configured records.
DEFAULT_PROVIDERS: list[tuple[str, str, str, str]] = []

DEFAULT_AI_CAPABILITIES = [
    ("reasoning", "Frame decisions and resolve multi-step ambiguity.", "high", "medium", False, True),
    ("coding", "Design and implement product or software changes.", "high", "medium", True, True),
    ("research", "Gather and synthesize evidence for a task.", "high", "low", True, True),
    ("verification", "Check boundaries, evidence, and acceptance conditions.", "high", "medium", False, False),
    ("summarization", "Compress source material without losing decisions or boundaries.", "medium", "high", False, True),
    ("planning", "Turn goals into an ordered, reviewable execution plan.", "high", "medium", False, True),
    ("risk_analysis", "Identify downside, uncovered tails, and policy boundaries.", "high", "medium", False, True),
    ("data_analysis", "Interpret structured evidence and quantitative outputs.", "high", "medium", True, True),
]

DEFAULT_AI_MODELS: list[tuple[str, str, list[str], int]] = []

DEFAULT_TOOLS = [
    ("Calendar", "calendar", "unconfigured", "Required slot; no event creation configured."),
    ("Outlook / Email", "email", "unconfigured", "Required slot; no auto-send configured."),
    ("IM / Chat", "messaging", "unconfigured", "Required slot; no auto-post configured."),
    ("Task tracker", "task_tool", "unconfigured", "Required slot; no task write adapter configured."),
    ("File / document workspace", "workspace", "unconfigured", "Required slot; no document adapter configured."),
    ("Trading execution", "live_trade", "blocked", "Hard policy denial."),
    ("Betting execution", "live_bet", "blocked", "Hard policy denial."),
]

COLUMN_MIGRATIONS = {
    "tasks": [
        ("development_task", "TEXT NOT NULL DEFAULT ''"),
        ("workflow_type", "VARCHAR(80) NOT NULL DEFAULT 'general'"),
        ("objective", "TEXT NOT NULL DEFAULT ''"),
        ("implementation_scope", "TEXT NOT NULL DEFAULT ''"),
        ("forbidden_scope", "TEXT NOT NULL DEFAULT ''"),
        ("acceptance_target", "TEXT NOT NULL DEFAULT ''"),
        ("repository_identity", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("source_baseline_commit", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("objective_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("source_context_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("required_output_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("acceptance_target_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
        ("implementation_scope_provenance", "VARCHAR(40) NOT NULL DEFAULT 'derived'"),
    ],
    "ai_models": [
        ("stable_id", "VARCHAR(160)"),
        ("display_name", "VARCHAR(160) NOT NULL DEFAULT ''"),
        ("provider_model_id", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("execution_adapter", "VARCHAR(40) NOT NULL DEFAULT ''"),
        ("configuration_status", "VARCHAR(40) NOT NULL DEFAULT 'needs_setup'"),
        ("availability_status", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("invocation_mode", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("last_invocation_outcome", "VARCHAR(40) NOT NULL DEFAULT 'not_invoked'"),
        ("evidence_status", "VARCHAR(40) NOT NULL DEFAULT 'unverified'"),
        ("evidence_source", "VARCHAR(80) NOT NULL DEFAULT 'none'"),
        ("last_verified_at", "DATETIME"),
        ("safe_diagnostic", "TEXT NOT NULL DEFAULT ''"),
    ],
    "ai_team_plans": [
        ("omitted_capabilities", "TEXT NOT NULL DEFAULT '[]'"),
        ("omission_explanation", "TEXT NOT NULL DEFAULT ''"),
        ("assignment_version", "INTEGER NOT NULL DEFAULT 0"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("routing_snapshot_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "ai_team_plan_items": [
        ("selection_reason", "TEXT NOT NULL DEFAULT ''"),
    ],
    "routing_decisions": [
        ("requested_capabilities", "TEXT NOT NULL DEFAULT '[]'"),
        ("fallback_status", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("fallback_reason", "TEXT NOT NULL DEFAULT ''"),
        ("next_action", "TEXT NOT NULL DEFAULT ''"),
    ],
    "codex_instruction_packs": [
        ("development_task", "TEXT NOT NULL DEFAULT ''"),
        ("development_task_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("assignment_version", "INTEGER NOT NULL DEFAULT 0"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("routing_snapshot_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_snapshot_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_snapshot_json", "TEXT NOT NULL DEFAULT '{}'"),
    ],
    "codex_runs": [
        ("development_task", "TEXT NOT NULL DEFAULT ''"),
        ("development_task_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("assignment_version", "INTEGER NOT NULL DEFAULT 0"),
        ("task_version", "INTEGER NOT NULL DEFAULT 1"),
        ("routing_snapshot_hash", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_snapshot_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("approved_instruction_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("start_idempotency_digest", "VARCHAR(64)"),
        ("start_request_digest", "VARCHAR(64)"),
        ("owner_start_confirmed_at", "DATETIME"),
        ("cancellation_requested_at", "DATETIME"),
        ("execution_assignment_id", "INTEGER"),
        ("execution_model_id", "INTEGER"),
        ("execution_provider_id", "INTEGER"),
        ("execution_connectivity_evidence_id", "INTEGER"),
        ("requested_model_identifier", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("fallback_selected", "BOOLEAN NOT NULL DEFAULT 0"),
        ("launch_intent_at", "DATETIME"),
        ("process_spawned", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_assignment_id", "INTEGER"),
        ("verification_model_id", "INTEGER"),
        ("verification_provider_id", "INTEGER"),
        ("verification_connectivity_evidence_id", "INTEGER"),
        ("verification_model_identifier", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("verification_status", "VARCHAR(40) NOT NULL DEFAULT 'not_started'"),
        ("verification_summary", "TEXT NOT NULL DEFAULT ''"),
        ("verification_process_spawned", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_stdout", "TEXT NOT NULL DEFAULT ''"),
        ("verification_stderr", "TEXT NOT NULL DEFAULT ''"),
        ("verification_exit_code", "INTEGER"),
        ("verification_duration_ms", "INTEGER"),
        ("verification_timed_out", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_cancelled", "BOOLEAN NOT NULL DEFAULT 0"),
        ("verification_output_truncated", "BOOLEAN NOT NULL DEFAULT 0"),
    ],
    "codex_result_envelopes": [
        ("approved_instruction_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("authorized_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("workspace_baseline_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("structured_handoff_status", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("task_acceptance_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("process_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("workspace_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("completion_classification", "VARCHAR(40) NOT NULL DEFAULT 'result_incomplete'"),
        ("execution_started_at", "DATETIME"),
        ("execution_finished_at", "DATETIME"),
    ],
    "owner_acceptance_sessions": [
        ("owner_id", "INTEGER REFERENCES users(id)"),
        ("result_envelope_id", "INTEGER REFERENCES codex_result_envelopes(id)"),
        ("result_envelope_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("result_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("result_task_version", "INTEGER"),
        ("result_pack_id", "INTEGER REFERENCES codex_instruction_packs(id)"),
        ("result_pack_version", "INTEGER"),
        ("approved_instruction_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("delivery_candidate_id", "INTEGER REFERENCES delivery_candidates(id)"),
        ("candidate_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("candidate_version", "INTEGER"),
        ("candidate_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        (
            "review_policy_version",
            "VARCHAR(80) NOT NULL DEFAULT 'twos.result_delivery_review.v1'",
        ),
        ("decision_version", "INTEGER NOT NULL DEFAULT 1"),
        ("decision_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "delivery_candidates": [
        ("candidate_version", "INTEGER NOT NULL DEFAULT 1"),
        (
            "derivation_version",
            "VARCHAR(80) NOT NULL DEFAULT 'twos.delivery_candidate.v1'",
        ),
        ("result_envelope_id", "INTEGER REFERENCES codex_result_envelopes(id)"),
        ("result_envelope_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("result_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("approved_instruction_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("coding_attempt_id", "INTEGER REFERENCES codex_execution_attempts(id)"),
        ("coding_attempt_identity", "VARCHAR(96) NOT NULL DEFAULT ''"),
        ("coding_outcome", "VARCHAR(40) NOT NULL DEFAULT 'unknown'"),
        ("verification_policy", "VARCHAR(40) NOT NULL DEFAULT 'required'"),
        ("verification_attempt_id", "INTEGER REFERENCES codex_execution_attempts(id)"),
        ("verification_attempt_identity", "VARCHAR(96) NOT NULL DEFAULT ''"),
        ("verification_receipt_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("result_integrity_state", "VARCHAR(24) NOT NULL DEFAULT 'unverified'"),
        ("source_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_baseline_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_post_state_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("excluded_manifest_json", "TEXT NOT NULL DEFAULT '[]'"),
        ("attribution_summary_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("readiness_state", "VARCHAR(48) NOT NULL DEFAULT 'blocked'"),
        ("readiness_reason", "TEXT NOT NULL DEFAULT ''"),
        ("readiness_blockers_json", "TEXT NOT NULL DEFAULT '[]'"),
    ],
    "apply_plans": [
        ("candidate_version", "INTEGER NOT NULL DEFAULT 1"),
        ("result_envelope_id", "INTEGER REFERENCES codex_result_envelopes(id)"),
        ("result_envelope_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("result_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("owner_acceptance_id", "INTEGER REFERENCES owner_acceptance_sessions(id)"),
        ("result_review_decision_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("approved_instruction_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_baseline_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_post_state_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("verification_policy", "VARCHAR(40) NOT NULL DEFAULT 'required'"),
        ("verification_verdict", "VARCHAR(40) NOT NULL DEFAULT 'unavailable'"),
        ("verification_receipt_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "apply_sessions": [
        ("candidate_version", "INTEGER NOT NULL DEFAULT 1"),
        ("result_envelope_id", "INTEGER REFERENCES codex_result_envelopes(id)"),
        ("result_envelope_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("result_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("owner_acceptance_id", "INTEGER REFERENCES owner_acceptance_sessions(id)"),
        ("result_review_decision_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("apply_plan_approval_id", "INTEGER REFERENCES apply_plan_approvals(id)"),
        ("apply_plan_approval_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("apply_plan_approval_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_baseline_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_post_state_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "apply_plan_approvals": [
        ("run_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_baseline_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_post_state_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "local_commit_executions": [
        ("commit_proposal_id", "INTEGER REFERENCES commit_proposals(id)"),
        (
            "commit_proposal_approval_id",
            "INTEGER REFERENCES commit_proposal_approvals(id)",
        ),
        ("proposal_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("proposal_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("proposal_approval_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("proposal_approval_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("owner_commit_confirmation_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("owner_commit_confirmed_at", "DATETIME"),
        ("result_envelope_id", "INTEGER REFERENCES codex_result_envelopes(id)"),
        ("result_envelope_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("result_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("owner_acceptance_id", "INTEGER REFERENCES owner_acceptance_sessions(id)"),
        ("result_review_decision_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("candidate_version", "INTEGER"),
        ("apply_plan_approval_id", "INTEGER REFERENCES apply_plan_approvals(id)"),
        ("apply_plan_approval_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("apply_plan_approval_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("source_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("run_workspace_identity", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("author_identity_sanitized", "VARCHAR(240) NOT NULL DEFAULT ''"),
        ("author_identity_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("command_started_at", "DATETIME"),
        ("command_finished_at", "DATETIME"),
        ("command_exit_code", "INTEGER"),
        ("command_output_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("command_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("command_evidence_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("hooks_evidence_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("hooks_evidence_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
    ],
    "push_executions": [
        ("push_plan_id", "INTEGER REFERENCES push_plans(id)"),
        ("push_plan_approval_id", "INTEGER REFERENCES push_plan_approvals(id)"),
        ("push_plan_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("push_plan_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("push_plan_approval_public_id", "VARCHAR(80) NOT NULL DEFAULT ''"),
        ("push_plan_approval_digest", "VARCHAR(64) NOT NULL DEFAULT ''"),
        ("command_output_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("recovery_reconciliation_json", "TEXT NOT NULL DEFAULT '{}'"),
        ("recovery_reconciliation_digest", "VARCHAR(64)"),
        ("recovered_at", "DATETIME"),
    ],
}


def make_engine(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def make_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False, future=True)


def initialize_database(engine: Engine) -> None:
    # Reconcile the one SQLite shape that requires a table rebuild before
    # creating any new Vol.19 tables.  This keeps an unsafe legacy schema from
    # being partially advanced merely by ``create_all``.
    _ensure_vol19_delivery_candidate_schema(engine)
    Base.metadata.create_all(engine)
    ensure_runtime_columns(engine)
    _ensure_vol18_immutable_triggers(engine)
    factory = make_session_factory(engine)
    with factory() as session:
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "mvp14.001")):
            session.add(SchemaVersion(version="mvp14.001"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "mvp15.001")):
            session.add(SchemaVersion(version="mvp15.001"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "mvp15.002")):
            session.add(SchemaVersion(version="mvp15.002"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == "vol16.001")):
            session.add(SchemaVersion(version="vol16.001"))
        if not session.scalar(select(SchemaVersion).where(SchemaVersion.version == VOL17_SCHEMA_VERSION)):
            session.add(SchemaVersion(version=VOL17_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_MODEL_SETUP_SCHEMA_VERSION)
        ):
            session.add(SchemaVersion(version=VOL17_MODEL_SETUP_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_END_TO_END_SCHEMA_VERSION)
        ):
            session.add(SchemaVersion(version=VOL17_END_TO_END_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(SchemaVersion.version == VOL17_REAL_EVIDENCE_SCHEMA_VERSION)
        ):
            session.add(SchemaVersion(version=VOL17_REAL_EVIDENCE_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL18_DELIVERY_CANDIDATE_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(version=VOL18_DELIVERY_CANDIDATE_SCHEMA_VERSION)
            )
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL18_REVIEW_APPLY_PLAN_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(version=VOL18_REVIEW_APPLY_PLAN_SCHEMA_VERSION)
            )
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL18_APPLY_REVERT_SCHEMA_VERSION
            )
        ):
            session.add(SchemaVersion(version=VOL18_APPLY_REVERT_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL18_RESULT_INTAKE_SCHEMA_VERSION
            )
        ):
            session.add(SchemaVersion(version=VOL18_RESULT_INTAKE_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL18_CODEX_CONNECTIVITY_SCHEMA_VERSION
            )
        ):
            session.add(SchemaVersion(version=VOL18_CODEX_CONNECTIVITY_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL18_EXEC_LIFECYCLE_SCHEMA_VERSION
            )
        ):
            session.add(SchemaVersion(version=VOL18_EXEC_LIFECYCLE_SCHEMA_VERSION))
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version
                == VOL18_POST_APPLY_VERIFICATION_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(
                    version=VOL18_POST_APPLY_VERIFICATION_SCHEMA_VERSION
                )
            )
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version
                == VOL18_LOCAL_COMMIT_BUILDER_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(
                    version=VOL18_LOCAL_COMMIT_BUILDER_SCHEMA_VERSION
                )
            )
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL18_PUSH_DELIVERY_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(version=VOL18_PUSH_DELIVERY_SCHEMA_VERSION)
            )
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL19_CODEX_RUN_RESULT_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(version=VOL19_CODEX_RUN_RESULT_SCHEMA_VERSION)
            )
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL19_RESULT_DELIVERY_LOOP_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(version=VOL19_RESULT_DELIVERY_LOOP_SCHEMA_VERSION)
            )
        if not session.scalar(
            select(SchemaVersion).where(
                SchemaVersion.version == VOL19_OWNER_COMMIT_PUSH_SCHEMA_VERSION
            )
        ):
            session.add(
                SchemaVersion(version=VOL19_OWNER_COMMIT_PUSH_SCHEMA_VERSION)
            )
        seed_projects(session)
        seed_registry(session)
        session.flush()
        seed_ai_registry(session)
        session.commit()


def ensure_runtime_columns(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    added_columns: dict[str, set[str]] = {}
    with engine.begin() as connection:
        for table_name, definitions in COLUMN_MIGRATIONS.items():
            if table_name not in tables:
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in definitions:
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))
                    added_columns.setdefault(table_name, set()).add(column_name)
        if "ai_models" in tables:
            added_model_columns = added_columns.get("ai_models", set())
            _backfill_ai_model_registry(
                connection,
                promote_configuration_state="configuration_status" in added_model_columns,
                promote_availability_state="availability_status" in added_model_columns,
            )
    if "ai_models" in tables:
        _ensure_ai_model_stable_id_index(engine)
        _ensure_vol17_ai_model_indexes(engine)
    if "codex_runs" in tables:
        _ensure_vol17_codex_run_indexes(engine)
        _ensure_vol19_codex_run_indexes(engine)
    if "codex_result_envelopes" in tables:
        _ensure_vol19_result_envelope_indexes(engine)
    if "codex_instruction_packs" in tables:
        _ensure_vol17_pack_indexes(engine)
    _ensure_vol19_result_delivery_indexes(engine)


def _ensure_vol19_delivery_candidate_schema(engine: Engine) -> None:
    """Relax legacy evidence bindings without losing an existing Candidate.

    SQLite cannot remove a ``NOT NULL`` constraint with ``ALTER TABLE``.  The
    Vol.18 table required model-assignment and model-invocation evidence for
    both phases, while the canonical local Verification path introduced in
    Vol.19 can truthfully have only a ``CodexExecutionAttempt`` and receipt.
    Rebuild only the legacy shape, copy every historical column, and give new
    lineage/readiness columns conservative blocked defaults.  Fresh databases
    already have the nullable mapped shape and take no rebuild path.
    """
    if engine.dialect.name != "sqlite":
        return
    inspector = inspect(engine)
    if "delivery_candidates" not in set(inspector.get_table_names()):
        return
    columns = {item["name"]: item for item in inspector.get_columns("delivery_candidates")}
    relaxed_columns = (
        "coding_assignment_id",
        "verification_assignment_id",
        "coding_evidence_id",
        "verification_evidence_id",
    )
    required_legacy_columns = {
        "id",
        "candidate_id",
        "owner_id",
        "task_id",
        "task_version",
        "pack_id",
        "pack_version",
        "coding_assignment_id",
        "coding_assignment_version",
        "verification_assignment_id",
        "verification_assignment_version",
        "routing_snapshot_identity",
        "source_snapshot_identity",
        "source_baseline_commit",
        "run_id",
        "coding_evidence_id",
        "coding_evidence_identity",
        "coding_evidence_digest",
        "verification_evidence_id",
        "verification_evidence_identity",
        "verification_evidence_digest",
        "verification_verdict",
        "acceptance_id",
        "acceptance_status",
        "file_manifest_json",
        "patch_identity",
        "candidate_digest",
        "created_at",
    }
    missing = sorted(required_legacy_columns.difference(columns))
    if missing:
        raise RuntimeError(
            "The legacy Delivery Candidate schema cannot be reconciled safely; "
            f"required columns are missing: {', '.join(missing)}."
        )
    if all(bool(columns[name].get("nullable")) for name in relaxed_columns):
        return

    temporary_name = "delivery_candidates_vol19_002"
    migration_metadata = MetaData()
    # Cloning is name-based only; no DDL ordering is needed here.  Iterating
    # insertion order also avoids treating the intentional Acceptance ↔
    # Candidate lineage cycle as a table-creation ordering problem.
    for table in Base.metadata.tables.values():
        table.to_metadata(migration_metadata)
    target_table = Base.metadata.tables["delivery_candidates"].to_metadata(
        migration_metadata,
        name=temporary_name,
    )
    conservative_defaults: dict[str, object] = {
        "candidate_version": 1,
        "derivation_version": "twos.delivery_candidate.v1",
        "result_envelope_public_id": "",
        "result_digest": "",
        "approved_instruction_digest": "",
        "coding_attempt_identity": "",
        "coding_outcome": "legacy_unbound",
        "verification_policy": "required",
        "verification_attempt_identity": "",
        "verification_receipt_identity": "",
        "result_integrity_state": "unverified",
        "source_workspace_identity": "",
        "run_workspace_identity": "",
        "run_workspace_baseline_identity": "",
        "run_workspace_post_state_identity": "",
        "excluded_manifest_json": "[]",
        "attribution_summary_json": "{}",
        "readiness_state": "blocked",
        "readiness_reason": (
            "Legacy Candidate lacks immutable Result-envelope lineage."
        ),
        "readiness_blockers_json": '["LEGACY_RESULT_LINEAGE_MISSING"]',
    }

    with engine.connect() as connection:
        existing_violations = list(
            connection.execute(text("PRAGMA foreign_key_check"))
        )
        if existing_violations:
            raise RuntimeError(
                "The Delivery Candidate schema cannot be rebuilt while the "
                "existing database has foreign-key violations."
            )
        connection.commit()
        connection.execute(text("PRAGMA foreign_keys=OFF"))
        connection.commit()
        try:
            with connection.begin():
                connection.execute(
                    text("DROP TABLE IF EXISTS delivery_candidates_vol19_002")
                )
                connection.execute(CreateTable(target_table))
                destination_columns: list[str] = []
                select_expressions: list[str] = []
                parameters: dict[str, object] = {}
                quote = connection.dialect.identifier_preparer.quote
                for column in target_table.columns:
                    name = column.name
                    destination_columns.append(quote(name))
                    if name in columns:
                        select_expressions.append(quote(name))
                    elif name in conservative_defaults:
                        parameter_name = f"default_{name}"
                        select_expressions.append(f":{parameter_name}")
                        parameters[parameter_name] = conservative_defaults[name]
                    elif column.nullable:
                        select_expressions.append("NULL")
                    else:
                        raise RuntimeError(
                            "The Delivery Candidate migration has no safe value for "
                            f"the required column {name}."
                        )
                connection.execute(
                    text(
                        f"INSERT INTO {quote(temporary_name)} "
                        f"({', '.join(destination_columns)}) "
                        f"SELECT {', '.join(select_expressions)} "
                        "FROM delivery_candidates"
                    ),
                    parameters,
                )
                old_count = int(
                    connection.scalar(text("SELECT COUNT(*) FROM delivery_candidates"))
                    or 0
                )
                new_count = int(
                    connection.scalar(
                        text(
                            "SELECT COUNT(*) FROM delivery_candidates_vol19_002"
                        )
                    )
                    or 0
                )
                if old_count != new_count:
                    raise RuntimeError(
                        "The Delivery Candidate migration row-count check failed."
                    )
                copied_violations = list(
                    connection.execute(
                        text(
                            "PRAGMA foreign_key_check("
                            "delivery_candidates_vol19_002)"
                        )
                    )
                )
                if copied_violations:
                    raise RuntimeError(
                        "The copied Delivery Candidate rows failed their "
                        "foreign-key check."
                    )
                connection.execute(text("DROP TABLE delivery_candidates"))
                connection.execute(
                    text(
                        "ALTER TABLE delivery_candidates_vol19_002 "
                        "RENAME TO delivery_candidates"
                    )
                )
            connection.execute(text("PRAGMA foreign_keys=ON"))
            violations = list(connection.execute(text("PRAGMA foreign_key_check")))
            if violations:
                raise RuntimeError(
                    "The Delivery Candidate migration failed its foreign-key check."
                )
        except Exception:
            if connection.in_transaction():
                connection.rollback()
            connection.execute(text("PRAGMA foreign_keys=ON"))
            raise


def _ensure_vol19_result_delivery_indexes(engine: Engine) -> None:
    """Create indexes/uniqueness omitted by additive SQLite column upgrades."""
    tables = set(inspect(engine).get_table_names())
    specifications: dict[str, tuple[tuple[str, tuple[str, ...], bool], ...]] = {
        "owner_acceptance_sessions": (
            ("ix_owner_acceptance_sessions_owner_id", ("owner_id",), False),
            (
                "ix_owner_acceptance_sessions_result_envelope_id",
                ("result_envelope_id",),
                True,
            ),
            ("ix_owner_acceptance_sessions_result_digest", ("result_digest",), False),
            ("ix_owner_acceptance_sessions_result_pack_id", ("result_pack_id",), False),
            (
                "ix_owner_acceptance_sessions_delivery_candidate_id",
                ("delivery_candidate_id",),
                True,
            ),
            ("ix_owner_acceptance_sessions_candidate_digest", ("candidate_digest",), False),
            (
                "ix_owner_acceptance_sessions_review_policy_version",
                ("review_policy_version",),
                False,
            ),
            ("ix_owner_acceptance_sessions_decision_digest", ("decision_digest",), False),
        ),
        "delivery_candidates": (
            ("ix_delivery_candidates_candidate_id", ("candidate_id",), True),
            ("ix_delivery_candidates_owner_id", ("owner_id",), False),
            ("ix_delivery_candidates_task_id", ("task_id",), False),
            ("ix_delivery_candidates_pack_id", ("pack_id",), False),
            (
                "ux_delivery_candidate_owner_result_version",
                ("owner_id", "result_envelope_id", "candidate_version"),
                True,
            ),
            ("ix_delivery_candidates_derivation_version", ("derivation_version",), False),
            (
                "ix_delivery_candidates_source_snapshot_identity",
                ("source_snapshot_identity",),
                False,
            ),
            ("ix_delivery_candidates_run_id", ("run_id",), True),
            (
                "ix_delivery_candidates_result_envelope_id",
                ("result_envelope_id",),
                True,
            ),
            ("ix_delivery_candidates_result_digest", ("result_digest",), False),
            ("ix_delivery_candidates_coding_attempt_id", ("coding_attempt_id",), False),
            ("ix_delivery_candidates_coding_outcome", ("coding_outcome",), False),
            ("ix_delivery_candidates_verification_policy", ("verification_policy",), False),
            (
                "ix_delivery_candidates_verification_attempt_id",
                ("verification_attempt_id",),
                False,
            ),
            (
                "ix_delivery_candidates_result_integrity_state",
                ("result_integrity_state",),
                False,
            ),
            ("ix_delivery_candidates_readiness_state", ("readiness_state",), False),
            (
                "ix_delivery_candidates_candidate_digest",
                ("candidate_digest",),
                True,
            ),
        ),
        "apply_plans": (
            ("ix_apply_plans_result_envelope_id", ("result_envelope_id",), False),
            ("ix_apply_plans_result_digest", ("result_digest",), False),
            ("ix_apply_plans_owner_acceptance_id", ("owner_acceptance_id",), False),
            (
                "ix_apply_plans_result_review_decision_digest",
                ("result_review_decision_digest",),
                False,
            ),
            ("ix_apply_plans_verification_policy", ("verification_policy",), False),
        ),
        "apply_sessions": (
            ("ix_apply_sessions_result_envelope_id", ("result_envelope_id",), False),
            ("ix_apply_sessions_result_digest", ("result_digest",), False),
            ("ix_apply_sessions_owner_acceptance_id", ("owner_acceptance_id",), False),
            (
                "ix_apply_sessions_result_review_decision_digest",
                ("result_review_decision_digest",),
                False,
            ),
            (
                "ix_apply_sessions_apply_plan_approval_id",
                ("apply_plan_approval_id",),
                True,
            ),
            (
                "ix_apply_sessions_apply_plan_approval_digest",
                ("apply_plan_approval_digest",),
                False,
            ),
        ),
        "local_commit_executions": (
            (
                "ix_local_commit_executions_commit_proposal_id",
                ("commit_proposal_id",),
                False,
            ),
            (
                "ux_local_commit_executions_commit_proposal_approval_id",
                ("commit_proposal_approval_id",),
                True,
            ),
            (
                "ix_local_commit_executions_proposal_digest",
                ("proposal_digest",),
                False,
            ),
            (
                "ix_local_commit_executions_proposal_approval_digest",
                ("proposal_approval_digest",),
                False,
            ),
        ),
        "push_executions": (
            ("ix_push_executions_push_plan_id", ("push_plan_id",), False),
            (
                "ix_push_executions_push_plan_approval_id",
                ("push_plan_approval_id",),
                False,
            ),
            ("ix_push_executions_push_plan_digest", ("push_plan_digest",), False),
        ),
    }
    with engine.begin() as connection:
        for table_name, table_specs in specifications.items():
            if table_name not in tables:
                continue
            table_inspector = inspect(connection)
            column_names = {
                item["name"] for item in table_inspector.get_columns(table_name)
            }
            existing_indexes = {
                (
                    tuple(item.get("column_names") or ()),
                    bool(item.get("unique")),
                )
                for item in table_inspector.get_indexes(table_name)
            }
            existing_indexes.update(
                (
                    tuple(item.get("column_names") or ()),
                    True,
                )
                for item in table_inspector.get_unique_constraints(table_name)
            )
            for index_name, indexed_columns, unique in table_specs:
                if not set(indexed_columns).issubset(column_names):
                    continue
                if (indexed_columns, unique) in existing_indexes:
                    continue
                uniqueness = "UNIQUE " if unique else ""
                columns_sql = ", ".join(indexed_columns)
                connection.execute(
                    text(
                        f"CREATE {uniqueness}INDEX IF NOT EXISTS {index_name} "
                        f"ON {table_name} ({columns_sql})"
                    )
                )
                existing_indexes.add((indexed_columns, unique))
        if "local_commit_executions" in tables:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS "
                    "ux_local_commit_owner_confirmation "
                    "ON local_commit_executions (owner_commit_confirmation_digest) "
                    "WHERE owner_commit_confirmation_digest != ''"
                )
            )


def _ensure_vol18_immutable_triggers(engine: Engine) -> None:
    """Enforce Phase 18 immutable history below the ORM boundary on SQLite."""
    if engine.dialect.name != "sqlite":
        return
    statements = (
        (
            "trg_delivery_candidates_no_update",
            "delivery_candidates",
            "UPDATE",
            "Delivery Candidate records are immutable.",
        ),
        (
            "trg_delivery_candidates_no_delete",
            "delivery_candidates",
            "DELETE",
            "Delivery Candidate records are immutable.",
        ),
        (
            "trg_source_drift_evaluations_no_update",
            "source_drift_evaluations",
            "UPDATE",
            "Source Drift evaluations are append-only.",
        ),
        (
            "trg_source_drift_evaluations_no_delete",
            "source_drift_evaluations",
            "DELETE",
            "Source Drift evaluations are append-only.",
        ),
        (
            "trg_apply_plans_no_update",
            "apply_plans",
            "UPDATE",
            "Apply Plan records are immutable.",
        ),
        (
            "trg_apply_plans_no_delete",
            "apply_plans",
            "DELETE",
            "Apply Plan records are immutable.",
        ),
        (
            "trg_apply_plan_entries_no_update",
            "apply_plan_entries",
            "UPDATE",
            "Apply Plan entries are immutable.",
        ),
        (
            "trg_apply_plan_entries_no_delete",
            "apply_plan_entries",
            "DELETE",
            "Apply Plan entries are immutable.",
        ),
        (
            "trg_apply_plan_approvals_no_update",
            "apply_plan_approvals",
            "UPDATE",
            "Apply Plan approvals are immutable.",
        ),
        (
            "trg_apply_plan_approvals_no_delete",
            "apply_plan_approvals",
            "DELETE",
            "Apply Plan approvals are immutable.",
        ),
        (
            "trg_owner_acceptance_sessions_no_delete",
            "owner_acceptance_sessions",
            "DELETE",
            "Owner Result-review decisions cannot be deleted.",
        ),
        (
            "trg_apply_session_audits_no_update",
            "apply_session_audits",
            "UPDATE",
            "Apply session audits are append-only.",
        ),
        (
            "trg_apply_session_audits_no_delete",
            "apply_session_audits",
            "DELETE",
            "Apply session audits are append-only.",
        ),
        (
            "trg_apply_sessions_no_delete",
            "apply_sessions",
            "DELETE",
            "Apply sessions cannot be deleted.",
        ),
        (
            "trg_apply_session_entries_no_delete",
            "apply_session_entries",
            "DELETE",
            "Apply session entries cannot be deleted.",
        ),
        (
            "trg_post_apply_verifications_no_update",
            "post_apply_verifications",
            "UPDATE",
            "Post-Apply Verification records are append-only.",
        ),
        (
            "trg_post_apply_verifications_no_delete",
            "post_apply_verifications",
            "DELETE",
            "Post-Apply Verification records are append-only.",
        ),
        (
            "trg_commit_plans_no_update",
            "commit_plans",
            "UPDATE",
            "Commit Plan records are immutable.",
        ),
        (
            "trg_commit_plans_no_delete",
            "commit_plans",
            "DELETE",
            "Commit Plan records are immutable.",
        ),
        (
            "trg_commit_proposals_no_update",
            "commit_proposals",
            "UPDATE",
            "Commit Proposal records are immutable.",
        ),
        (
            "trg_commit_proposals_no_delete",
            "commit_proposals",
            "DELETE",
            "Commit Proposal records are immutable.",
        ),
        (
            "trg_commit_proposal_approvals_no_update",
            "commit_proposal_approvals",
            "UPDATE",
            "Commit Proposal approvals are immutable.",
        ),
        (
            "trg_commit_proposal_approvals_no_delete",
            "commit_proposal_approvals",
            "DELETE",
            "Commit Proposal approvals are immutable.",
        ),
        (
            "trg_stage_executions_no_delete",
            "stage_executions",
            "DELETE",
            "Stage execution records cannot be deleted.",
        ),
        (
            "trg_local_commit_executions_no_delete",
            "local_commit_executions",
            "DELETE",
            "Local Commit execution records cannot be deleted.",
        ),
        (
            "trg_push_executions_no_delete",
            "push_executions",
            "DELETE",
            "Push execution records cannot be deleted.",
        ),
        (
            "trg_push_plans_no_update",
            "push_plans",
            "UPDATE",
            "Push Plan records are immutable.",
        ),
        (
            "trg_push_plans_no_delete",
            "push_plans",
            "DELETE",
            "Push Plan records are immutable.",
        ),
        (
            "trg_push_plan_approvals_no_update",
            "push_plan_approvals",
            "UPDATE",
            "Push Plan approvals are immutable.",
        ),
        (
            "trg_push_plan_approvals_no_delete",
            "push_plan_approvals",
            "DELETE",
            "Push Plan approvals are immutable.",
        ),
        (
            "trg_codex_run_monitors_no_delete",
            "codex_run_monitors",
            "DELETE",
            "Codex Run monitors cannot be deleted.",
        ),
        (
            "trg_codex_result_envelopes_no_update",
            "codex_result_envelopes",
            "UPDATE",
            "Codex Result Envelopes are immutable.",
        ),
        (
            "trg_codex_result_envelopes_no_delete",
            "codex_result_envelopes",
            "DELETE",
            "Codex Result Envelopes are immutable.",
        ),
        (
            "trg_codex_result_artifacts_no_update",
            "codex_result_artifacts",
            "UPDATE",
            "Codex Result artifacts are immutable.",
        ),
        (
            "trg_codex_result_artifacts_no_delete",
            "codex_result_artifacts",
            "DELETE",
            "Codex Result artifacts are immutable.",
        ),
        (
            "trg_codex_connectivity_evidence_no_update",
            "codex_connectivity_evidence",
            "UPDATE",
            "Codex connectivity evidence is append-only.",
        ),
        (
            "trg_codex_connectivity_evidence_no_delete",
            "codex_connectivity_evidence",
            "DELETE",
            "Codex connectivity evidence is append-only.",
        ),
        (
            "trg_handoff_reviews_no_update",
            "handoff_reviews",
            "UPDATE",
            "Handoff Reviews are immutable.",
        ),
        (
            "trg_handoff_reviews_no_delete",
            "handoff_reviews",
            "DELETE",
            "Handoff Reviews are immutable.",
        ),
        (
            "trg_handoff_instruction_drafts_no_delete",
            "handoff_instruction_drafts",
            "DELETE",
            "Handoff instruction drafts cannot be deleted.",
        ),
    )
    with engine.begin() as connection:
        # These Phase 18.4B triggers are still evolving inside the same
        # schema delivery; rebuild them so an already-initialized local DB
        # receives the exact recovery semantics and set-once columns.
        for trigger_name in (
            "trg_apply_sessions_core_no_update",
            "trg_owner_acceptance_sessions_set_once",
            "trg_owner_acceptance_sessions_terminal_no_update",
            "trg_local_commit_executions_core_no_update",
            "trg_local_commit_executions_set_once",
            "trg_push_executions_core_no_update",
            "trg_push_executions_set_once",
            "trg_push_executions_terminal_no_update",
            "trg_push_executions_state_transition",
        ):
            connection.execute(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))
        for trigger_name, table_name, operation, message in statements:
            connection.execute(
                text(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger_name} "
                    f"BEFORE {operation} ON {table_name} "
                    f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
                )
            )
        apply_session_core_columns = (
            "session_id",
            "owner_id",
            "apply_plan_id",
            "apply_plan_public_id",
            "apply_plan_digest",
            "delivery_candidate_id",
            "candidate_public_id",
            "candidate_digest",
            "candidate_version",
            "result_envelope_id",
            "result_envelope_public_id",
            "result_digest",
            "owner_acceptance_id",
            "result_review_decision_digest",
            "apply_plan_approval_id",
            "apply_plan_approval_public_id",
            "apply_plan_approval_digest",
            "run_id",
            "task_id",
            "task_version",
            "pack_id",
            "pack_version",
            "source_snapshot_identity",
            "source_workspace_identity",
            "run_workspace_identity",
            "run_workspace_baseline_identity",
            "run_workspace_post_state_identity",
            "source_drift_evaluation_id",
            "repository_locator_fingerprint",
            "repository_fingerprint",
            "sanitized_repository_identity",
            "branch",
            "pre_apply_head",
            "pre_apply_index_fingerprint",
            "pre_apply_worktree_fingerprint",
            "included_path_count",
            "excluded_path_count",
            "blocked_path_count",
            "included_paths_json",
            "excluded_paths_json",
            "blocked_paths_json",
            "ordered_operations_json",
            "apply_confirmation_digest",
            "journal_digest",
            "before_evidence_json",
            "created_at",
            "started_at",
        )
        apply_entry_core_columns = (
            "apply_session_id",
            "apply_plan_entry_id",
            "operation_ordinal",
            "repository_path",
            "path_identity",
            "operation",
            "reverse_operation",
            "before_present",
            "before_hash",
            "before_size",
            "before_mode",
            "before_file_type",
            "before_atime_ns",
            "before_mtime_ns",
            "before_material",
            "after_present",
            "after_hash",
            "after_size",
            "after_mode",
            "after_file_type",
            "after_atime_ns",
            "after_mtime_ns",
            "after_material",
            "temporary_material_identity",
            "parent_chain_json",
            "created_parent_dirs_json",
        )
        monitor_core_columns = (
            "monitor_id",
            "owner_id",
            "task_id",
            "task_version",
            "pack_id",
            "pack_version",
            "coding_assignment_id",
            "coding_assignment_version",
            "verification_assignment_id",
            "verification_assignment_version",
            "routing_snapshot_identity",
            "source_snapshot_identity",
            "run_id",
            "requested_model_identifier",
            "verification_model_identifier",
            "monitor_digest",
            "created_at",
        )
        instruction_draft_core_columns = (
            "draft_id",
            "owner_id",
            "handoff_review_id",
            "result_envelope_id",
            "run_id",
            "instruction_id",
            "revision",
            "scope",
            "supersession",
            "completion_gate_json",
            "required_handoff_json",
            "instruction_text",
            "draft_digest",
            "created_at",
        )
        stage_execution_core_columns = (
            "stage_execution_id",
            "owner_id",
            "commit_plan_id",
            "commit_plan_public_id",
            "commit_plan_digest",
            "verification_digest",
            "repository_locator_fingerprint",
            "branch",
            "branch_ref",
            "base_head",
            "planned_entries_json",
            "planned_entries_digest",
            "pre_stage_evidence_json",
            "pre_stage_evidence_digest",
            "created_at",
            "started_at",
        )
        local_commit_execution_core_columns = (
            "commit_execution_id",
            "owner_id",
            "commit_proposal_id",
            "commit_proposal_approval_id",
            "commit_plan_id",
            "stage_execution_id",
            "commit_plan_public_id",
            "commit_plan_digest",
            "stage_execution_public_id",
            "stage_digest",
            "repository_locator_fingerprint",
            "branch",
            "branch_ref",
            "base_head",
            "staged_entries_json",
            "staged_entries_digest",
            "subject_digest",
            "body_digest",
            "message_digest",
            "intent_digest",
            "pre_commit_evidence_json",
            "pre_commit_evidence_digest",
            "proposal_public_id",
            "proposal_digest",
            "proposal_approval_public_id",
            "proposal_approval_digest",
            "owner_commit_confirmation_digest",
            "owner_commit_confirmed_at",
            "result_envelope_id",
            "result_envelope_public_id",
            "result_digest",
            "owner_acceptance_id",
            "result_review_decision_digest",
            "candidate_version",
            "apply_plan_approval_id",
            "apply_plan_approval_public_id",
            "apply_plan_approval_digest",
            "source_workspace_identity",
            "run_workspace_identity",
            "author_identity_sanitized",
            "author_identity_digest",
            "created_at",
            "started_at",
        )
        push_execution_core_columns = (
            "push_execution_id",
            "owner_id",
            "push_plan_id",
            "push_plan_approval_id",
            "local_commit_execution_id",
            "stage_execution_id",
            "commit_plan_id",
            "post_apply_verification_id",
            "apply_session_id",
            "delivery_candidate_id",
            "run_id",
            "task_id",
            "push_plan_public_id",
            "push_plan_digest",
            "push_plan_approval_public_id",
            "push_plan_approval_digest",
            "local_commit_public_id",
            "local_commit_receipt_digest",
            "commit_plan_digest",
            "stage_digest",
            "verification_digest",
            "candidate_digest",
            "journal_digest",
            "repository_locator_fingerprint",
            "sanitized_repository_identity",
            "branch",
            "branch_ref",
            "remote_name",
            "destination_ref",
            "approved_commit_oid",
            "expected_parent_oid",
            "subject",
            "subject_digest",
            "remote_fetch_url_digest",
            "remote_push_url_digest",
            "remote_config_fingerprint",
            "observed_remote_base_oid",
            "preflight_evidence_json",
            "preflight_evidence_digest",
            "confirmation_digest",
            "refspec",
            "command_evidence_json",
            "command_evidence_digest",
            "created_at",
        )
        for trigger_name, table_name, columns, message in (
            (
                "trg_apply_sessions_core_no_update",
                "apply_sessions",
                apply_session_core_columns,
                "Apply session binding and journal fields are immutable.",
            ),
            (
                "trg_apply_session_entries_core_no_update",
                "apply_session_entries",
                apply_entry_core_columns,
                "Apply session entry journal and material fields are immutable.",
            ),
            (
                "trg_codex_run_monitors_core_no_update",
                "codex_run_monitors",
                monitor_core_columns,
                "Codex Run monitor binding fields are immutable.",
            ),
            (
                "trg_handoff_instruction_drafts_core_no_update",
                "handoff_instruction_drafts",
                instruction_draft_core_columns,
                "Handoff instruction draft content and bindings are immutable.",
            ),
            (
                "trg_stage_executions_core_no_update",
                "stage_executions",
                stage_execution_core_columns,
                "Stage execution binding and intent fields are immutable.",
            ),
            (
                "trg_local_commit_executions_core_no_update",
                "local_commit_executions",
                local_commit_execution_core_columns,
                "Local Commit execution binding and intent fields are immutable.",
            ),
            (
                "trg_push_executions_core_no_update",
                "push_executions",
                push_execution_core_columns,
                "Push execution binding and intent fields are immutable.",
            ),
        ):
            predicate = " OR ".join(
                f"OLD.{column_name} IS NOT NEW.{column_name}"
                for column_name in columns
            )
            connection.execute(
                text(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger_name} "
                    f"BEFORE UPDATE ON {table_name} WHEN {predicate} "
                    f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
                )
            )
        owner_acceptance_set_once_columns = (
            "owner_id",
            "result_envelope_id",
            "result_envelope_public_id",
            "result_digest",
            "result_task_version",
            "result_pack_id",
            "result_pack_version",
            "approved_instruction_digest",
            "delivery_candidate_id",
            "candidate_public_id",
            "candidate_version",
            "candidate_digest",
            "review_policy_version",
            "decision_version",
            "decision_digest",
        )
        owner_acceptance_set_once_predicate = " OR ".join(
            f"(OLD.{column_name} IS NOT NULL "
            f"AND CAST(OLD.{column_name} AS TEXT) != '' "
            f"AND OLD.{column_name} IS NOT NEW.{column_name})"
            for column_name in owner_acceptance_set_once_columns
        )
        connection.execute(
            text(
                "CREATE TRIGGER trg_owner_acceptance_sessions_set_once "
                "BEFORE UPDATE ON owner_acceptance_sessions "
                f"WHEN {owner_acceptance_set_once_predicate} "
                "BEGIN SELECT RAISE(ABORT, "
                "'Owner Result and Candidate bindings may be set only once.'"
                "); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER trg_owner_acceptance_sessions_terminal_no_update "
                "BEFORE UPDATE ON owner_acceptance_sessions "
                "WHEN OLD.status IN ('accepted','rejected') "
                "AND (OLD.result_envelope_id IS NOT NULL "
                "OR OLD.decision_digest != '') "
                "BEGIN SELECT RAISE(ABORT, "
                "'Terminal Owner Result-review decisions are immutable.'"
                "); END"
            )
        )
        monitor_set_once_columns = (
            "process_id",
            "process_start_identity",
            "verification_process_id",
            "verification_process_start_identity",
            "codex_session_identity",
            "executable_fingerprint",
            "isolated_worktree_identity",
            "execution_location_identity",
            "result_locator_identity",
            "protected_result_locator",
        )
        monitor_set_once_predicate = " OR ".join(
            f"((OLD.{column_name} IS NOT NULL AND OLD.{column_name} != '') "
            f"AND OLD.{column_name} IS NOT NEW.{column_name})"
            for column_name in monitor_set_once_columns
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS trg_codex_run_monitors_set_once "
                "BEFORE UPDATE ON codex_run_monitors "
                f"WHEN {monitor_set_once_predicate} "
                "BEGIN SELECT RAISE(ABORT, "
                "'Codex Run monitor process and location bindings may be set only once.'"
                "); END"
            )
        )
        codex_run_start_set_once_columns = (
            "approved_instruction_digest",
            "start_idempotency_digest",
            "start_request_digest",
            "owner_start_confirmed_at",
        )
        codex_run_start_set_once_predicate = " OR ".join(
            f"((OLD.{column_name} IS NOT NULL AND OLD.{column_name} != '') "
            f"AND OLD.{column_name} IS NOT NEW.{column_name})"
            for column_name in codex_run_start_set_once_columns
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS trg_codex_runs_owner_start_set_once "
                "BEFORE UPDATE ON codex_runs "
                f"WHEN {codex_run_start_set_once_predicate} "
                "BEGIN SELECT RAISE(ABORT, "
                "'Codex Run Owner-confirmed start bindings may be set only once.'"
                "); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS "
                "trg_codex_runs_cancellation_requested_set_once "
                "BEFORE UPDATE ON codex_runs "
                "WHEN OLD.cancellation_requested_at IS NOT NULL "
                "AND OLD.cancellation_requested_at IS NOT NEW.cancellation_requested_at "
                "BEGIN SELECT RAISE(ABORT, "
                "'Codex Run cancellation request time may be set only once.'"
                "); END"
            )
        )
        for trigger_name, table_name, columns, message in (
            (
                "trg_stage_executions_set_once",
                "stage_executions",
                (
                    "post_stage_evidence_json",
                    "staged_entries_json",
                    "staged_entries_digest",
                    "stage_digest",
                    "finished_at",
                ),
                "Stage execution transition evidence may be set only once.",
            ),
            (
                "trg_local_commit_executions_set_once",
                "local_commit_executions",
                (
                    "tree_oid",
                    "commit_oid",
                    "parent_oid",
                    "post_commit_evidence_json",
                    "receipt_digest",
                    "command_started_at",
                    "command_finished_at",
                    "command_exit_code",
                    "command_output_json",
                    "command_evidence_json",
                    "command_evidence_digest",
                    "hooks_evidence_json",
                    "hooks_evidence_digest",
                    "finished_at",
                ),
                "Local Commit transition evidence may be set only once.",
            ),
            (
                "trg_push_executions_set_once",
                "push_executions",
                (
                    "command_started_at",
                    "command_finished_at",
                    "execution_remote_base_oid",
                    "command_exit_code",
                    "command_output_json",
                    "failure_category",
                    "failure_evidence_json",
                    "post_push_evidence_json",
                    "recovery_reconciliation_json",
                    "recovery_reconciliation_digest",
                    "recovered_at",
                    "receipt_digest",
                    "finished_at",
                ),
                "Push execution transition evidence may be set only once.",
            ),
        ):
            predicate = " OR ".join(
                f"(OLD.{column_name} IS NOT NULL "
                f"AND CAST(OLD.{column_name} AS TEXT) NOT IN ('','{{}}','[]') "
                f"AND OLD.{column_name} IS NOT NEW.{column_name})"
                for column_name in columns
            )
            connection.execute(
                text(
                    f"CREATE TRIGGER IF NOT EXISTS {trigger_name} "
                    f"BEFORE UPDATE ON {table_name} WHEN {predicate} "
                    f"BEGIN SELECT RAISE(ABORT, '{message}'); END"
                )
            )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS trg_push_executions_terminal_no_update "
                "BEFORE UPDATE ON push_executions "
                "WHEN OLD.state IN ("
                "'PUSHED','PUSH_BLOCKED','REMOTE_MOVED','PUSH_FAILED'"
                ") "
                "BEGIN SELECT RAISE(ABORT, "
                "'Terminal Push execution records are immutable.'"
                "); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS trg_push_executions_state_transition "
                "BEFORE UPDATE OF state ON push_executions "
                "WHEN NOT ("
                "(OLD.state = 'READY_TO_PUSH' AND NEW.state IN ("
                "'PUSHING','PUSH_BLOCKED','REMOTE_MOVED')) OR "
                "(OLD.state = 'PUSHING' AND NEW.state IN ("
                "'PUSHED','REMOTE_MOVED','PUSH_FAILED','RECONCILIATION_BLOCKED')) OR "
                "(OLD.state = 'RECONCILIATION_BLOCKED' AND NEW.state = 'PUSHED')"
                ") "
                "BEGIN SELECT RAISE(ABORT, "
                "'The Push execution state transition is invalid.'"
                "); END"
            )
        )
        connection.execute(
            text(
                "CREATE TRIGGER IF NOT EXISTS trg_push_executions_single_attempt "
                "BEFORE UPDATE OF command_attempt_count ON push_executions "
                "WHEN NOT (OLD.command_attempt_count = 0 "
                "AND NEW.command_attempt_count = 1) "
                "BEGIN SELECT RAISE(ABORT, "
                "'A Push confirmation authorizes one attempt only.'"
                "); END"
            )
        )
        connection.execute(
            text("DROP INDEX IF EXISTS ux_push_execution_local_commit_active")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ux_push_execution_local_commit_active "
                "ON push_executions (local_commit_execution_id) "
                "WHERE state IN ("
                "'READY_TO_PUSH','PUSHING','RECONCILIATION_BLOCKED'"
                ")"
            )
        )
        # Partial/incomplete source state owns the repository mutation boundary
        # until an explicit recovery phase resolves it. Rebuild the partial
        # index because an earlier vol18.003 development schema covered only
        # the two actively executing states.
        connection.execute(
            text("DROP INDEX IF EXISTS ux_apply_sessions_repository_active")
        )
        connection.execute(
            text(
                "CREATE UNIQUE INDEX ux_apply_sessions_repository_active "
                "ON apply_sessions (repository_locator_fingerprint) "
                "WHERE state IN ("
                "'APPLYING','REVERTING',"
                "'APPLY_FAILED_PARTIAL','REVERT_FAILED_PARTIAL'"
                ")"
            )
        )


def _backfill_ai_model_registry(
    connection: Connection,
    *,
    promote_configuration_state: bool,
    promote_availability_state: bool,
) -> None:
    """Populate additive registry fields and translate legacy state exactly once."""
    rows = list(
        connection.execute(
            text(
                "SELECT m.id, m.provider_id, m.model_name, m.stable_id, m.display_name, m.status, "
                "m.configuration_status, m.availability_status, p.enabled AS provider_enabled, "
                "p.status AS provider_status FROM ai_models AS m "
                "LEFT JOIN providers AS p ON p.id = m.provider_id ORDER BY m.id"
            )
        ).mappings()
    )
    reserved_ids = {
        str(row["stable_id"])
        for row in rows
        if row["stable_id"]
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", str(row["stable_id"]))
    }
    used_ids: set[str] = set()
    for row in rows:
        stable_id = str(row["stable_id"] or "")
        stable_id_is_safe = bool(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", stable_id)
        )
        if not stable_id_is_safe or stable_id in used_ids:
            base = stable_model_identifier(int(row["provider_id"]), str(row["model_name"]))
            candidate = base
            suffix = 0
            while candidate in reserved_ids or candidate in used_ids:
                suffix += 1
                available = max(1, 158 - len(str(row["id"])) - len(str(suffix)))
                candidate = f"{base[:available]}.{int(row['id'])}.{suffix}"
            stable_id = candidate
        used_ids.add(stable_id)
        legacy_status = str(row["status"] or "unconfigured")
        provider_status = str(row["provider_status"] or "unconfigured")
        provider_eligible = bool(row["provider_enabled"]) and provider_status in {"healthy", "degraded"}
        configuration_status = str(row["configuration_status"] or "needs_setup")
        if configuration_status not in {"configured", "needs_setup", "disabled"}:
            configuration_status = "needs_setup"
        if (
            promote_configuration_state
            and configuration_status == "needs_setup"
            and legacy_status in {"healthy", "degraded"}
            and provider_eligible
        ):
            configuration_status = "configured"
        if promote_configuration_state and (
            legacy_status in {"blocked", "disabled"}
            or provider_status in {"blocked", "disabled"}
        ):
            configuration_status = "disabled"
        availability_status = str(row["availability_status"] or "unavailable")
        if availability_status not in {"available", "unavailable", "disabled"}:
            availability_status = "unavailable"
        if promote_availability_state and legacy_status in {"healthy", "degraded"} and provider_eligible:
            availability_status = "available"
        elif promote_availability_state and (
            legacy_status in {"blocked", "disabled"}
            or provider_status in {"blocked", "disabled"}
        ):
            availability_status = "disabled"
        connection.execute(
            text(
                "UPDATE ai_models SET stable_id = :stable_id, display_name = :display_name, "
                "configuration_status = :configuration_status, availability_status = :availability_status "
                "WHERE id = :model_id"
            ),
            {
                "stable_id": stable_id,
                "display_name": str(row["display_name"] or row["model_name"]),
                "configuration_status": configuration_status,
                "availability_status": availability_status,
                "model_id": int(row["id"]),
            },
        )


def _ensure_ai_model_stable_id_index(engine: Engine) -> None:
    inspector = inspect(engine)
    unique_indexes = [
        item
        for item in inspector.get_indexes("ai_models")
        if item.get("unique") and item.get("column_names") == ["stable_id"]
    ]
    unique_constraints = [
        item
        for item in inspector.get_unique_constraints("ai_models")
        if item.get("column_names") == ["stable_id"]
    ]
    if unique_indexes or unique_constraints:
        return
    with engine.begin() as connection:
        connection.execute(text("CREATE UNIQUE INDEX ux_ai_models_stable_id ON ai_models (stable_id)"))


def _ensure_vol17_ai_model_indexes(engine: Engine) -> None:
    """Give upgraded databases the indexes that fresh mapped tables receive."""
    required = {
        "ix_ai_models_configuration_status": "configuration_status",
        "ix_ai_models_availability_status": "availability_status",
        "ix_ai_models_invocation_mode": "invocation_mode",
        "ix_ai_models_last_invocation_outcome": "last_invocation_outcome",
        "ix_ai_models_evidence_status": "evidence_status",
    }
    inspector = inspect(engine)
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("ai_models")
    }
    missing = [
        (index_name, column_name)
        for index_name, column_name in required.items()
        if (column_name,) not in indexed_columns
    ]
    if not missing:
        return
    with engine.begin() as connection:
        for index_name, column_name in missing:
            connection.execute(text(f"CREATE INDEX {index_name} ON ai_models ({column_name})"))


def _ensure_vol17_codex_run_indexes(engine: Engine) -> None:
    """Align additive-upgrade execution-target lookup indexes with fresh databases."""
    required = {
        "ix_codex_runs_execution_assignment_id": "execution_assignment_id",
        "ix_codex_runs_execution_model_id": "execution_model_id",
        "ix_codex_runs_execution_provider_id": "execution_provider_id",
        "ix_codex_runs_verification_assignment_id": "verification_assignment_id",
        "ix_codex_runs_verification_model_id": "verification_model_id",
        "ix_codex_runs_verification_provider_id": "verification_provider_id",
        "ix_codex_runs_source_snapshot_digest": "source_snapshot_digest",
        "ix_codex_runs_verification_status": "verification_status",
    }
    inspector = inspect(engine)
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("codex_runs")
    }
    missing = [
        (index_name, column_name)
        for index_name, column_name in required.items()
        if (column_name,) not in indexed_columns
    ]
    if not missing:
        return
    with engine.begin() as connection:
        for index_name, column_name in missing:
            connection.execute(text(f"CREATE INDEX {index_name} ON codex_runs ({column_name})"))


def _ensure_vol19_codex_run_indexes(engine: Engine) -> None:
    """Enforce one accepted start identity while preserving legacy NULL rows."""
    inspector = inspect(engine)
    indexes = inspector.get_indexes("codex_runs")
    indexed_columns = {
        tuple(item.get("column_names") or []): item for item in indexes
    }
    with engine.begin() as connection:
        if ("start_idempotency_digest",) not in indexed_columns:
            connection.execute(
                text(
                    "CREATE UNIQUE INDEX ix_codex_runs_start_idempotency_digest "
                    "ON codex_runs (start_idempotency_digest)"
                )
            )
        if ("start_request_digest",) not in indexed_columns:
            connection.execute(
                text(
                    "CREATE INDEX ix_codex_runs_start_request_digest "
                    "ON codex_runs (start_request_digest)"
                )
            )


def _ensure_vol19_result_envelope_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("codex_result_envelopes")
    }
    if ("completion_classification",) in indexed_columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE INDEX ix_codex_result_envelopes_completion_classification "
                "ON codex_result_envelopes (completion_classification)"
            )
        )


def _ensure_vol17_pack_indexes(engine: Engine) -> None:
    inspector = inspect(engine)
    indexed_columns = {
        tuple(item.get("column_names") or [])
        for item in inspector.get_indexes("codex_instruction_packs")
    }
    if ("source_snapshot_digest",) in indexed_columns:
        return
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE INDEX ix_codex_instruction_packs_source_snapshot_digest "
                "ON codex_instruction_packs (source_snapshot_digest)"
            )
        )


def seed_projects(session: Session) -> None:
    for key, name in DEFAULT_PROJECTS:
        if not session.scalar(select(Project).where(Project.key == key)):
            session.add(Project(key=key, name=name, status="active"))


def seed_registry(session: Session) -> None:
    for name, kind, status, details in DEFAULT_PROVIDERS:
        existing = session.scalar(select(Provider).where(Provider.name == name, Provider.kind == kind))
        if not existing:
            session.add(Provider(name=name, kind=kind, status=status, enabled=False, details=details))
    for name, kind, status, details in DEFAULT_TOOLS:
        existing = session.scalar(select(Tool).where(Tool.name == name, Tool.kind == kind))
        if not existing:
            session.add(Tool(name=name, kind=kind, status=status, enabled=False, details=details))


def seed_ai_registry(session: Session) -> None:
    for name, description, quality, latency, requires_tool, requires_verification in DEFAULT_AI_CAPABILITIES:
        if not session.scalar(select(AICapability).where(AICapability.name == name)):
            session.add(
                AICapability(
                    name=name,
                    description=description,
                    quality_requirement=quality,
                    latency_sensitivity=latency,
                    requires_tool_capability=requires_tool,
                    requires_verification=requires_verification,
                    enabled=True,
                )
            )

    providers = {item.name: item for item in session.scalars(select(Provider).where(Provider.kind == "model")).all()}
    for provider_name, model_name, capability_tags, priority in DEFAULT_AI_MODELS:
        provider = providers.get(provider_name)
        if not provider:
            continue
        existing = session.scalar(
            select(AIModel).where(AIModel.provider_id == provider.id, AIModel.model_name == model_name)
        )
        if not existing:
            session.add(
                AIModel(
                    provider_id=provider.id,
                    model_name=model_name,
                    stable_id=stable_model_identifier(provider.id, model_name),
                    display_name=model_name,
                    provider_model_id="",
                    execution_adapter="",
                    capability_tags=json.dumps(capability_tags, separators=(",", ":")),
                    context_limit=None,
                    cost_metadata="unknown",
                    latency_metadata="unknown",
                    status="unconfigured",
                    configuration_status="needs_setup",
                    availability_status="unavailable",
                    invocation_mode="unavailable",
                    last_invocation_outcome="not_invoked",
                    evidence_status="unverified",
                    evidence_source="seeded_registry",
                    routing_priority=priority,
                )
            )


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
