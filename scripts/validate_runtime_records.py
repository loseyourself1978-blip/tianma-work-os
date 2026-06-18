#!/usr/bin/env python3
"""Validate Vol.3 runtime JSON examples and records against local schemas.

This validator intentionally uses only the Python standard library. It supports
the small JSON Schema subset used by this repository: type, required,
properties, additionalProperties, enum, and items.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_DIRS = [
    REPO_ROOT / "examples" / "ldd",
    REPO_ROOT / "examples" / "runtime"
]
RECORD_DIRS = [
    REPO_ROOT / "records" / "ldd"
]
COCKPIT_DIRS = [
    REPO_ROOT / "cockpit" / "ldd"
]
MOCK_CONSUMER_MATRIX = REPO_ROOT / "mock_consumers" / "ldd" / "consumer_contract_test_matrix.json"
PRIVACY_BOUNDARY_SAMPLE = REPO_ROOT / "mock_consumers" / "ldd" / "privacy_boundary_sample.json"
READ_ONLY_API_CONTRACT = REPO_ROOT / "mock_consumers" / "ldd" / "read_only_api_contract.json"
READ_ONLY_API_RESPONSES = REPO_ROOT / "mock_consumers" / "ldd" / "read_only_api_response_examples.json"
VOL7_STATIC_UI_SHELL_BOUNDARY_MAP = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_static_ui_shell_boundary_map.json"
VOL7_STATIC_FIXTURE_CONSUMER_CONTRACT = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_static_fixture_consumer_contract.json"
VOL7_READ_ONLY_PANEL_LAYOUT = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_read_only_panel_layout.json"
VOL7_STATIC_FIXTURE_CONSUMER_DRY_RUN = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_static_fixture_consumer_dry_run_result.json"
VOL7_STATIC_FIXTURE_CONSUMER_DRIFT_REPORT = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_static_fixture_consumer_drift_report.json"
VOL7_STATIC_SHELL_IMPLEMENTATION_READINESS_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_static_shell_implementation_readiness_gate.json"
VOL7_LOCAL_STATIC_SHELL_SKELETON_MANIFEST = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_local_static_shell_skeleton_manifest.json"
VOL7_LOCAL_STATIC_SHELL_REVIEW_REPORT = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_local_static_shell_review_report.json"
VOL7_LOCAL_STATIC_SHELL_DEMO_PACK = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_local_static_shell_demo_pack.json"
VOL7_LOCAL_STATIC_SHELL_SNAPSHOT_QA = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_local_static_shell_snapshot_qa.json"
VOL7_COMPLETION_READINESS_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_completion_readiness_gate.json"
VOL7_HANDOFF_SUMMARY = REPO_ROOT / "mock_consumers" / "ldd" / "vol7_handoff_summary.json"
VOL8_ENTRY_READINESS_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_entry_readiness_gate.json"
VOL8_STATIC_SHELL_QA_HANDOFF_INTAKE = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_static_shell_qa_handoff_intake.json"
VOL8_BOUNDARY_FREEZE = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_boundary_freeze.json"
IMPLEMENTED_FUNCTION_FRAMEWORK_INDEX = REPO_ROOT / "mock_consumers" / "ldd" / "implemented_function_framework_index.json"
VOL8_OPERATOR_FEEDBACK_REVIEW_SAMPLE = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_operator_feedback_review_sample.json"
VOL8_OPERATOR_FEEDBACK_ROLLUP = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_operator_feedback_rollup.json"
VOL8_FEEDBACK_TO_ROADMAP_MAPPING_SAMPLE = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_feedback_to_roadmap_mapping_sample.json"
VOL8_FEEDBACK_TO_ROADMAP_BOUNDARY_MAP = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_feedback_to_roadmap_boundary_map.json"
VOL8_FUTURE_IMPLEMENTATION_READINESS_ITEMS = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_future_implementation_readiness_items.json"
VOL8_FUTURE_IMPLEMENTATION_READINESS_LADDER = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_future_implementation_readiness_ladder.json"
VOL8_HANDOFF_SUMMARY = REPO_ROOT / "mock_consumers" / "ldd" / "vol8_handoff_summary.json"
VOL9_ENTRY_READINESS_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "vol9_entry_readiness_gate.json"
VOL9_PHASE9_1_RUNTIME_STATUS_BACKFEED_PROTOCOL = REPO_ROOT / "mock_consumers" / "ldd" / "twos_ldd_runtime_status_backfeed_protocol.json"
VOL9_PHASE9_1_DRIFT_RESOLUTION_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "cross_workspace_baseline_drift_resolution_gate.json"
VOL9_PHASE9_2_LDD_CONSUMER_ACKNOWLEDGEMENT = REPO_ROOT / "mock_consumers" / "ldd" / "ldd_consumer_acknowledgement_packet.json"
VOL9_PHASE9_2_STRICT_BASELINE_SYNC_READY_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "strict_baseline_sync_ready_gate.json"
VOL9_PHASE9_3_FUTURE_IMPLEMENTATION_BOUNDARY_MATRIX = REPO_ROOT / "mock_consumers" / "ldd" / "future_implementation_boundary_matrix.json"
VOL9_PHASE9_3_STATIC_PROTOTYPE_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "static_prototype_gate.json"
VOL9_PHASE9_4_STATIC_PROTOTYPE_EVIDENCE_PACK = REPO_ROOT / "mock_consumers" / "ldd" / "static_prototype_evidence_pack.json"
VOL9_PHASE9_4_FUTURE_GATE_READINESS_CHECKLIST = REPO_ROOT / "mock_consumers" / "ldd" / "future_gate_readiness_checklist.json"
VOL9_PHASE9_5_FORBIDDEN_SCOPE_REGRESSION_GUARD = REPO_ROOT / "mock_consumers" / "ldd" / "forbidden_scope_regression_guard.json"
VOL9_PHASE9_5_FUTURE_GATE_NON_ACTIVATION_AUDIT = REPO_ROOT / "mock_consumers" / "ldd" / "future_gate_non_activation_audit.json"
VOL9_PHASE9_6_STATIC_SHELL_FIXTURE_COVERAGE_MATRIX = REPO_ROOT / "mock_consumers" / "ldd" / "static_shell_fixture_coverage_matrix.json"
VOL9_PHASE9_6_PROTOTYPE_TO_GATE_TRACEABILITY_MAP = REPO_ROOT / "mock_consumers" / "ldd" / "prototype_to_gate_traceability_map.json"
VOL9_PHASE9_7_LDD_FULL_REPORT_SCOPE_REQUIREMENTS = REPO_ROOT / "mock_consumers" / "ldd" / "ldd_full_report_scope_requirements.json"
VOL9_PHASE9_7_LDD_ORDER_RECONCILIATION = REPO_ROOT / "mock_consumers" / "ldd" / "ldd_order_reconciliation_and_zero_fill_separation.json"
VOL9_PHASE9_7_LDD_STATIC_COCKPIT_PANEL_GATE = REPO_ROOT / "mock_consumers" / "ldd" / "ldd_static_cockpit_panel_requirement_gate.json"
VOL9_PHASE9_8_IMPLEMENTED_FEATURE_INVENTORY_TREE = REPO_ROOT / "mock_consumers" / "ldd" / "implemented_feature_inventory_tree.json"
VOL9_PHASE9_8_IMPLEMENTED_FEATURE_TIMELINE_CATALOG = REPO_ROOT / "mock_consumers" / "ldd" / "implemented_feature_timeline_catalog.json"
SCHEMAS_DIR = REPO_ROOT / "schemas"


@dataclass(frozen=True)
class ValidationTarget:
    path: Path
    bucket: str
    schema_name: str
    schema_key: str


SCHEMA_FILES = {
    "trigger_execution_rule": "trigger_execution_rule.schema.json",
    "strategy_state": "strategy_state.schema.json",
    "portfolio_state": "portfolio_state.schema.json",
    "account_structure_review": "account_structure_review.schema.json",
    "pending_command": "pending_command.schema.json",
    "command_intelligence_check": "command_intelligence_check.schema.json",
    "smart_execution_plan": "smart_execution_plan.schema.json",
    "command_execution_feedback": "command_execution_feedback.schema.json",
    "rule_based_execution_review": "rule_based_execution_review.schema.json",
    "volatility_execution_split": "volatility_execution_split.schema.json",
    "sync_delta_update": "sync_delta_update.schema.json",
    "rule_ledger_snapshot": "rule_ledger_snapshot.schema.json",
    "execution_event": "execution_event.schema.json",
    "memory_retention_policy": "memory_retention_policy.schema.json",
    "memory_cleanup_recommendation": "memory_cleanup_recommendation.schema.json",
    "active_memory_checkpoint": "active_memory_checkpoint.schema.json",
    "cockpit_manifest": "cockpit_manifest.schema.json",
    "cockpit_summary": "cockpit_summary.schema.json",
    "cockpit_consistency_review": "cockpit_consistency_review.schema.json",
    "cockpit_view_model_contract": "cockpit_view_model_contract.schema.json",
    "cockpit_view_model": "cockpit_view_model.schema.json",
    "cockpit_view_model_generation": "cockpit_view_model_generation.schema.json",
    "view_model_quality_gate_review": "view_model_quality_gate_review.schema.json",
    "cockpit_consumer_readiness_review": "cockpit_consumer_readiness_review.schema.json",
    "mock_consumer_package_review": "mock_consumer_package_review.schema.json",
    "consumer_contract_test_matrix": "consumer_contract_test_matrix.schema.json",
    "read_only_consumer_fixture_validation": "read_only_consumer_fixture_validation.schema.json",
    "executed_order_writeback": "executed_order_writeback.schema.json",
    "runtime_status_arbitration": "runtime_status_arbitration.schema.json",
    "ui_boundary_architecture_review": "ui_boundary_architecture_review.schema.json",
    "permission_privacy_masking_review": "permission_privacy_masking_review.schema.json",
    "governance_runtime_sync": "governance_runtime_sync.schema.json",
    "read_only_api_contract": "read_only_api_contract.schema.json",
    "read_only_api_response_envelope": "read_only_api_response_envelope.schema.json",
    "read_only_api_contract_review": "read_only_api_contract_review.schema.json",
    "runtime_execution_reconciliation": "runtime_execution_reconciliation.schema.json",
    "ldd_residual_core_checkpoint_update": "ldd_residual_core_checkpoint_update.schema.json",
    "ldd_premarket_governance_sync": "ldd_premarket_governance_sync.schema.json",
    "ldd_full_market_scope_governance_sync": "ldd_full_market_scope_governance_sync.schema.json",
    "vol6_handoff_readiness_gate": "vol6_handoff_readiness_gate.schema.json",
    "vol7_static_ui_shell_boundary_map": "vol7_static_ui_shell_boundary_map.schema.json",
    "vol7_static_fixture_consumer_contract": "vol7_static_fixture_consumer_contract.schema.json",
    "vol7_read_only_panel_layout": "vol7_read_only_panel_layout.schema.json",
    "vol7_static_fixture_consumer_dry_run": "vol7_static_fixture_consumer_dry_run.schema.json",
    "vol7_static_fixture_consumer_drift_report": "vol7_static_fixture_consumer_drift_report.schema.json",
    "vol7_static_shell_implementation_readiness_gate": "vol7_static_shell_implementation_readiness_gate.schema.json",
    "vol7_local_static_shell_skeleton_manifest": "vol7_local_static_shell_skeleton_manifest.schema.json",
    "vol7_local_static_shell_review_report": "vol7_local_static_shell_review_report.schema.json",
    "vol7_local_static_shell_demo_pack": "vol7_local_static_shell_demo_pack.schema.json",
    "vol7_local_static_shell_snapshot_qa": "vol7_local_static_shell_snapshot_qa.schema.json",
    "vol7_completion_readiness_gate": "vol7_completion_readiness_gate.schema.json",
    "vol7_handoff_summary": "vol7_handoff_summary.schema.json",
    "vol8_entry_readiness_gate": "vol8_entry_readiness_gate.schema.json",
    "vol8_static_shell_qa_handoff_intake": "vol8_static_shell_qa_handoff_intake.schema.json",
    "vol8_boundary_freeze": "vol8_boundary_freeze.schema.json",
    "implemented_function_framework_index": "implemented_function_framework_index.schema.json",
    "vol8_operator_feedback_review": "vol8_operator_feedback_review.schema.json",
    "vol8_operator_feedback_rollup": "vol8_operator_feedback_rollup.schema.json",
    "vol8_feedback_to_roadmap_mapping": "vol8_feedback_to_roadmap_mapping.schema.json",
    "vol8_feedback_to_roadmap_boundary_map": "vol8_feedback_to_roadmap_boundary_map.schema.json",
    "vol8_future_implementation_readiness_item": "vol8_future_implementation_readiness_item.schema.json",
    "vol8_future_implementation_readiness_ladder": "vol8_future_implementation_readiness_ladder.schema.json",
    "vol8_handoff_summary": "vol8_handoff_summary.schema.json",
    "vol9_entry_readiness_gate": "vol9_entry_readiness_gate.schema.json",
    "twos_ldd_runtime_status_backfeed_protocol": "twos_ldd_runtime_status_backfeed_protocol.schema.json",
    "cross_workspace_baseline_drift_state": "cross_workspace_baseline_drift_state.schema.json",
    "ldd_consumer_acknowledgement": "ldd_consumer_acknowledgement.schema.json",
    "strict_baseline_sync_ready_gate": "strict_baseline_sync_ready_gate.schema.json",
    "future_implementation_boundary_matrix": "future_implementation_boundary_matrix.schema.json",
    "static_prototype_gate": "static_prototype_gate.schema.json",
    "static_prototype_evidence_pack": "static_prototype_evidence_pack.schema.json",
    "future_gate_readiness_checklist": "future_gate_readiness_checklist.schema.json",
    "forbidden_scope_regression_guard": "forbidden_scope_regression_guard.schema.json",
    "future_gate_non_activation_audit": "future_gate_non_activation_audit.schema.json",
    "static_shell_fixture_coverage_matrix": "static_shell_fixture_coverage_matrix.schema.json",
    "prototype_to_gate_traceability_map": "prototype_to_gate_traceability_map.schema.json",
    "ldd_full_report_scope_requirements": "ldd_full_report_scope_requirements.schema.json",
    "ldd_order_reconciliation_and_zero_fill_separation": "ldd_order_reconciliation_and_zero_fill_separation.schema.json",
    "ldd_static_cockpit_panel_requirement_gate": "ldd_static_cockpit_panel_requirement_gate.schema.json",
    "implemented_feature_inventory_tree": "implemented_feature_inventory_tree.schema.json",
    "implemented_feature_timeline_catalog": "implemented_feature_timeline_catalog.schema.json",
    "static_cockpit_prototype_review": "static_cockpit_prototype_review.schema.json",
    "internal_operator_cockpit_static_spec_review": "internal_operator_cockpit_static_spec_review.schema.json",
    "ai_board_cockpit_static_spec_review": "ai_board_cockpit_static_spec_review.schema.json",
    "cockpit_static_spec_integration_review": "cockpit_static_spec_integration_review.schema.json",
    "static_consumer_fixture_handoff": "static_consumer_fixture_handoff.schema.json"
}


COCKPIT_SUMMARY_FILES = {
    "latest_state.json",
    "active_rules.json",
    "strategy_states.json",
    "account_structure.json",
    "pending_commands.json",
    "memory_checkpoint.json"
}


def schema_for_filename(filename: str) -> tuple[str, str] | None:
    if filename == "view_model.json":
        return "cockpit_view_model", SCHEMA_FILES["cockpit_view_model"]
    if "cockpit_view_model_generation" in filename:
        return "cockpit_view_model_generation", SCHEMA_FILES["cockpit_view_model_generation"]
    if "view_model_quality_gate_review" in filename:
        return "view_model_quality_gate_review", SCHEMA_FILES["view_model_quality_gate_review"]
    if "cockpit_consumer_readiness_review" in filename:
        return "cockpit_consumer_readiness_review", SCHEMA_FILES["cockpit_consumer_readiness_review"]
    if "mock_consumer_package_review" in filename:
        return "mock_consumer_package_review", SCHEMA_FILES["mock_consumer_package_review"]
    if "consumer_contract_test_matrix" in filename:
        return "consumer_contract_test_matrix", SCHEMA_FILES["consumer_contract_test_matrix"]
    if "read_only_consumer_fixture_validation" in filename:
        return "read_only_consumer_fixture_validation", SCHEMA_FILES["read_only_consumer_fixture_validation"]
    if "executed_order_writeback" in filename:
        return "executed_order_writeback", SCHEMA_FILES["executed_order_writeback"]
    if "runtime_status_conflict_arbitration" in filename:
        return "runtime_status_arbitration", SCHEMA_FILES["runtime_status_arbitration"]
    if "ui_boundary_architecture_review" in filename:
        return "ui_boundary_architecture_review", SCHEMA_FILES["ui_boundary_architecture_review"]
    if "permission_privacy_masking_review" in filename:
        return "permission_privacy_masking_review", SCHEMA_FILES["permission_privacy_masking_review"]
    if "ldd_premarket_runtime_sync_governance_patch" in filename:
        return "governance_runtime_sync", SCHEMA_FILES["governance_runtime_sync"]
    if "read_only_api_contract_review" in filename:
        return "read_only_api_contract_review", SCHEMA_FILES["read_only_api_contract_review"]
    if "vol6_phase6_3a_ldd_post_close_execution_reconciliation" in filename:
        return "runtime_execution_reconciliation", SCHEMA_FILES["runtime_execution_reconciliation"]
    if "vol6_phase6_5a_ldd_post_close_residual_core_checkpoint_update" in filename:
        return "ldd_residual_core_checkpoint_update", SCHEMA_FILES["ldd_residual_core_checkpoint_update"]
    if "vol6_phase6_7a_ldd_premarket_rebound_confirmation_governance_sync" in filename:
        return "ldd_premarket_governance_sync", SCHEMA_FILES["ldd_premarket_governance_sync"]
    if "vol6_phase6_8a_ldd_full_market_scope_correction_and_ipo_radar_governance_sync" in filename:
        return "ldd_full_market_scope_governance_sync", SCHEMA_FILES["ldd_full_market_scope_governance_sync"]
    if "vol6_phase6_9_handoff_summary_and_vol7_readiness_gate" in filename:
        return "vol6_handoff_readiness_gate", SCHEMA_FILES["vol6_handoff_readiness_gate"]
    if "vol7_phase7_0_static_ui_shell_boundary_map" in filename:
        return "vol7_static_ui_shell_boundary_map", SCHEMA_FILES["vol7_static_ui_shell_boundary_map"]
    if "vol7_phase7_1_static_fixture_consumer_contract_and_panel_layout" in filename:
        return "vol7_static_fixture_consumer_contract", SCHEMA_FILES["vol7_static_fixture_consumer_contract"]
    if "vol7_phase7_2_static_fixture_consumer_dry_run_and_drift_detector" in filename:
        return "vol7_static_fixture_consumer_dry_run", SCHEMA_FILES["vol7_static_fixture_consumer_dry_run"]
    if "vol7_phase7_3_static_shell_implementation_readiness_gate" in filename:
        return "vol7_static_shell_implementation_readiness_gate", SCHEMA_FILES["vol7_static_shell_implementation_readiness_gate"]
    if "vol7_phase7_4_local_static_shell_skeleton_permissioned_implementation" in filename:
        return "vol7_local_static_shell_skeleton_manifest", SCHEMA_FILES["vol7_local_static_shell_skeleton_manifest"]
    if "vol7_phase7_5_local_static_shell_review_accessibility_guardrail_hardening_and_ldd_backfeed" in filename:
        return "vol7_local_static_shell_review_report", SCHEMA_FILES["vol7_local_static_shell_review_report"]
    if "vol7_phase7_6_local_static_shell_demo_pack_and_operator_walkthrough" in filename:
        return "vol7_local_static_shell_demo_pack", SCHEMA_FILES["vol7_local_static_shell_demo_pack"]
    if "vol7_phase7_7_local_static_shell_snapshot_qa_and_completion_readiness" in filename:
        return "vol7_local_static_shell_snapshot_qa", SCHEMA_FILES["vol7_local_static_shell_snapshot_qa"]
    if "vol7_phase7_8_handoff_summary_and_vol8_readiness_gate" in filename:
        return "vol7_handoff_summary", SCHEMA_FILES["vol7_handoff_summary"]
    if "vol8_phase8_1_static_shell_qa_handoff_intake_and_boundary_freeze" in filename:
        return "vol8_static_shell_qa_handoff_intake", SCHEMA_FILES["vol8_static_shell_qa_handoff_intake"]
    if "vol8_phase8_2_implemented_function_framework_index_output_module" in filename:
        return "implemented_function_framework_index", SCHEMA_FILES["implemented_function_framework_index"]
    if "vol8_phase8_3_local_operator_feedback_review_model" in filename:
        return "vol8_operator_feedback_rollup", SCHEMA_FILES["vol8_operator_feedback_rollup"]
    if "vol8_phase8_4_feedback_to_roadmap_product_boundary_mapping" in filename:
        return "vol8_feedback_to_roadmap_boundary_map", SCHEMA_FILES["vol8_feedback_to_roadmap_boundary_map"]
    if "vol8_phase8_5_future_implementation_readiness_ladder" in filename:
        return "vol8_future_implementation_readiness_ladder", SCHEMA_FILES["vol8_future_implementation_readiness_ladder"]
    if "vol8_phase8_6_handoff_summary_and_vol9_readiness_gate" in filename:
        return "vol8_handoff_summary", SCHEMA_FILES["vol8_handoff_summary"]
    if "vol9_phase9_1_cross_workspace_baseline_drift_resolution_and_backfeed_protocol" in filename:
        return "cross_workspace_baseline_drift_state", SCHEMA_FILES["cross_workspace_baseline_drift_state"]
    if "vol9_phase9_2_ldd_consumer_acknowledgement_and_strict_baseline_sync_ready_gate" in filename:
        return "strict_baseline_sync_ready_gate", SCHEMA_FILES["strict_baseline_sync_ready_gate"]
    if "vol9_phase9_3_future_implementation_boundary_matrix_and_static_prototype_gate" in filename:
        return "static_prototype_gate", SCHEMA_FILES["static_prototype_gate"]
    if "vol9_phase9_4_static_prototype_evidence_pack_and_future_gate_readiness_checklist" in filename:
        return "future_gate_readiness_checklist", SCHEMA_FILES["future_gate_readiness_checklist"]
    if "vol9_phase9_5_forbidden_scope_regression_guard_and_non_activation_audit_harness" in filename:
        return "future_gate_non_activation_audit", SCHEMA_FILES["future_gate_non_activation_audit"]
    if "vol9_phase9_6_static_shell_fixture_coverage_matrix_and_prototype_to_gate_traceability_map" in filename:
        return "prototype_to_gate_traceability_map", SCHEMA_FILES["prototype_to_gate_traceability_map"]
    if "vol9_phase9_7_ldd_full_report_scope_regression_guard_order_reconciliation_and_static_cockpit_panel_requirements" in filename:
        return "ldd_static_cockpit_panel_requirement_gate", SCHEMA_FILES["ldd_static_cockpit_panel_requirement_gate"]
    if "vol9_phase9_8_implemented_feature_inventory_tree_and_volume_timeline_catalog_refresh" in filename:
        return "implemented_feature_timeline_catalog", SCHEMA_FILES["implemented_feature_timeline_catalog"]
    if "static_cockpit_prototype_boundary_review" in filename:
        return "static_cockpit_prototype_review", SCHEMA_FILES["static_cockpit_prototype_review"]
    if "internal_operator_cockpit_static_spec_review" in filename:
        return "internal_operator_cockpit_static_spec_review", SCHEMA_FILES["internal_operator_cockpit_static_spec_review"]
    if "ai_board_cockpit_static_spec_review" in filename:
        return "ai_board_cockpit_static_spec_review", SCHEMA_FILES["ai_board_cockpit_static_spec_review"]
    if "cockpit_static_spec_integration_review" in filename:
        return "cockpit_static_spec_integration_review", SCHEMA_FILES["cockpit_static_spec_integration_review"]
    if "static_consumer_fixture_integration_and_handoff" in filename:
        return "static_consumer_fixture_handoff", SCHEMA_FILES["static_consumer_fixture_handoff"]
    if "phase5_final_pressure_test_result" in filename:
        return "cockpit_consistency_review", SCHEMA_FILES["cockpit_consistency_review"]
    if "ldd_post_close_execution_review" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "rule_compliance_vs_price_outcome_review" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "gld_rule_execution_review" in filename or "nvda_rule_execution_review" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "post_sale_cost_basis_interpretation" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "us_cash_ratio_quality_score" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "hk_high_profit_protection_escalation" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "closed_position_discipline_validation" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "ldd_post_close_review" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "premarket_trigger_to_post_close_outcome_reconciliation" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "active_risk_non_execution_review" in filename:
        return "rule_ledger_snapshot", SCHEMA_FILES["rule_ledger_snapshot"]
    if "gld_active_risk_rule_update" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "nvda_core_risk_trigger_update" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "goog_ggll_risk_valve_update" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "closed_position_opportunity_cost_requirement" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "hk_high_profit_protection_requirement" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "crypto_defense_state_delta" in filename:
        return "strategy_state", SCHEMA_FILES["strategy_state"]
    if "pending_instruction_supersession" in filename:
        return "pending_command", SCHEMA_FILES["pending_command"]
    if "cockpit_view_model_contract" in filename:
        return "cockpit_view_model_contract", SCHEMA_FILES["cockpit_view_model_contract"]
    if "cockpit_consistency_review" in filename:
        return "cockpit_consistency_review", SCHEMA_FILES["cockpit_consistency_review"]
    if "ldd_core_position_defense_checkpoint" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "core_position_defense_monitor" in filename:
        return "strategy_state", SCHEMA_FILES["strategy_state"]
    if "remaining_leveraged_risk_monitor" in filename:
        return "rule_ledger_snapshot", SCHEMA_FILES["rule_ledger_snapshot"]
    if "gld_concentration_risk_rule_update" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "quote_type_tagging_reinforcement" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "ldd_premarket_checkpoint" in filename or "ldd_post_close_cleanup_review" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "soxl_residual_risk_monitor" in filename or "portfolio_mode_transition" in filename:
        return "strategy_state", SCHEMA_FILES["strategy_state"]
    if "cleanup_effectiveness_review" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "remaining_risk_concentration_monitor" in filename:
        return "rule_ledger_snapshot", SCHEMA_FILES["rule_ledger_snapshot"]
    if "full_cleanup_reconciliation" in filename or "closure_reconciliation" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "cleanup_execution" in filename or "residual_closure_execution" in filename:
        return "execution_event", SCHEMA_FILES["execution_event"]
    if "soxl_execution_filled" in filename:
        return "execution_event", SCHEMA_FILES["execution_event"]
    if "ldd_post_close_checkpoint" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "soxl_execution_reconciliation" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "execution_feedback_loop_requirement" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "residual_risk_valve_state" in filename:
        return "rule_ledger_snapshot", SCHEMA_FILES["rule_ledger_snapshot"]
    if filename == "manifest.json":
        return "cockpit_manifest", SCHEMA_FILES["cockpit_manifest"]
    if filename in COCKPIT_SUMMARY_FILES:
        return "cockpit_summary", SCHEMA_FILES["cockpit_summary"]
    if "post_close_runtime_delta" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "account_state_delta" in filename:
        return "portfolio_state", SCHEMA_FILES["portfolio_state"]
    if "rule_trigger_monitor" in filename:
        return "rule_ledger_snapshot", SCHEMA_FILES["rule_ledger_snapshot"]
    if "quote_source_conflict" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "section_level_account_structure_requirement" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "memory_retention_policy" in filename:
        return "memory_retention_policy", SCHEMA_FILES["memory_retention_policy"]
    if "memory_cleanup_recommendation" in filename:
        return "memory_cleanup_recommendation", SCHEMA_FILES["memory_cleanup_recommendation"]
    if "active_memory_checkpoint" in filename:
        return "active_memory_checkpoint", SCHEMA_FILES["active_memory_checkpoint"]
    if "command_intelligence_check" in filename or "superseded_check" in filename:
        return "command_intelligence_check", SCHEMA_FILES["command_intelligence_check"]
    if "smart_execution_plan" in filename:
        return "smart_execution_plan", SCHEMA_FILES["smart_execution_plan"]
    if "execution_feedback" in filename:
        return "command_execution_feedback", SCHEMA_FILES["command_execution_feedback"]
    if "rule_based_execution_review" in filename:
        return "rule_based_execution_review", SCHEMA_FILES["rule_based_execution_review"]
    if "volatility_execution_split" in filename:
        return "volatility_execution_split", SCHEMA_FILES["volatility_execution_split"]
    if "sync_block_delta" in filename or "sync_delta" in filename or "delta_protocol" in filename:
        return "sync_delta_update", SCHEMA_FILES["sync_delta_update"]
    if "rule_ledger_snapshot" in filename:
        return "rule_ledger_snapshot", SCHEMA_FILES["rule_ledger_snapshot"]
    if "closure_execution" in filename:
        return "execution_event", SCHEMA_FILES["execution_event"]
    if "trigger_rule" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "trigger_execution" in filename:
        return "trigger_execution_rule", SCHEMA_FILES["trigger_execution_rule"]
    if "strategy_state" in filename:
        return "strategy_state", SCHEMA_FILES["strategy_state"]
    if "portfolio_state" in filename:
        return "portfolio_state", SCHEMA_FILES["portfolio_state"]
    if "account_structure_review" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if "account_structure_score" in filename or "account_structure_update" in filename:
        return "account_structure_review", SCHEMA_FILES["account_structure_review"]
    if filename.startswith("pending_") or "pending_command" in filename:
        return "pending_command", SCHEMA_FILES["pending_command"]
    return None


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def matches_type(value: Any, expected: str) -> bool:
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    if expected == "null":
        return value is None
    return False


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    errors: list[str] = []

    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(matches_type(value, item) for item in expected_types):
            errors.append(f"{path}: expected type {expected_types}, got {type_name(value)}")
            return errors

    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: value {value!r} is not in enum {schema['enum']!r}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required:
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    errors.append(f"{path}: unexpected property {key!r}")

        for key, child_schema in properties.items():
            if key in value:
                errors.extend(validate(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and "items" in schema:
        item_schema = schema["items"]
        for index, item in enumerate(value):
            errors.extend(validate(item, item_schema, f"{path}[{index}]"))

    return errors


def collect_targets() -> tuple[list[ValidationTarget], list[Path]]:
    targets: list[ValidationTarget] = []
    unmapped: list[Path] = []

    roots = [(root, "examples") for root in EXAMPLE_DIRS]
    roots.extend((root, "records") for root in RECORD_DIRS)

    for root, bucket in roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            schema_match = schema_for_filename(path.name)
            if schema_match is None:
                unmapped.append(path)
                continue
            schema_key, schema_name = schema_match
            targets.append(ValidationTarget(path, bucket, schema_name, schema_key))

    for root in COCKPIT_DIRS:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.json")):
            schema_match = schema_for_filename(path.name)
            if schema_match is None:
                continue
            schema_key, schema_name = schema_match
            targets.append(ValidationTarget(path, "cockpit", schema_name, schema_key))

    if MOCK_CONSUMER_MATRIX.exists():
        targets.append(
            ValidationTarget(
                MOCK_CONSUMER_MATRIX,
                "mock_consumers",
                SCHEMA_FILES["consumer_contract_test_matrix"],
                "consumer_contract_test_matrix",
            )
        )

    if READ_ONLY_API_CONTRACT.exists():
        targets.append(
            ValidationTarget(
                READ_ONLY_API_CONTRACT,
                "mock_consumers",
                SCHEMA_FILES["read_only_api_contract"],
                "read_only_api_contract",
            )
        )

    if READ_ONLY_API_RESPONSES.exists():
        targets.append(
            ValidationTarget(
                READ_ONLY_API_RESPONSES,
                "mock_consumers",
                SCHEMA_FILES["read_only_api_response_envelope"],
                "read_only_api_response_envelope",
            )
        )

    if VOL7_STATIC_UI_SHELL_BOUNDARY_MAP.exists():
        targets.append(
            ValidationTarget(
                VOL7_STATIC_UI_SHELL_BOUNDARY_MAP,
                "mock_consumers",
                SCHEMA_FILES["vol7_static_ui_shell_boundary_map"],
                "vol7_static_ui_shell_boundary_map",
            )
        )

    if VOL7_STATIC_FIXTURE_CONSUMER_CONTRACT.exists():
        targets.append(
            ValidationTarget(
                VOL7_STATIC_FIXTURE_CONSUMER_CONTRACT,
                "mock_consumers",
                SCHEMA_FILES["vol7_static_fixture_consumer_contract"],
                "vol7_static_fixture_consumer_contract",
            )
        )

    if VOL7_READ_ONLY_PANEL_LAYOUT.exists():
        targets.append(
            ValidationTarget(
                VOL7_READ_ONLY_PANEL_LAYOUT,
                "mock_consumers",
                SCHEMA_FILES["vol7_read_only_panel_layout"],
                "vol7_read_only_panel_layout",
            )
        )

    if VOL7_STATIC_FIXTURE_CONSUMER_DRY_RUN.exists():
        targets.append(
            ValidationTarget(
                VOL7_STATIC_FIXTURE_CONSUMER_DRY_RUN,
                "mock_consumers",
                SCHEMA_FILES["vol7_static_fixture_consumer_dry_run"],
                "vol7_static_fixture_consumer_dry_run",
            )
        )

    if VOL7_STATIC_FIXTURE_CONSUMER_DRIFT_REPORT.exists():
        targets.append(
            ValidationTarget(
                VOL7_STATIC_FIXTURE_CONSUMER_DRIFT_REPORT,
                "mock_consumers",
                SCHEMA_FILES["vol7_static_fixture_consumer_drift_report"],
                "vol7_static_fixture_consumer_drift_report",
            )
        )

    if VOL7_STATIC_SHELL_IMPLEMENTATION_READINESS_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL7_STATIC_SHELL_IMPLEMENTATION_READINESS_GATE,
                "mock_consumers",
                SCHEMA_FILES["vol7_static_shell_implementation_readiness_gate"],
                "vol7_static_shell_implementation_readiness_gate",
            )
        )

    if VOL7_LOCAL_STATIC_SHELL_SKELETON_MANIFEST.exists():
        targets.append(
            ValidationTarget(
                VOL7_LOCAL_STATIC_SHELL_SKELETON_MANIFEST,
                "mock_consumers",
                SCHEMA_FILES["vol7_local_static_shell_skeleton_manifest"],
                "vol7_local_static_shell_skeleton_manifest",
            )
        )

    if VOL7_LOCAL_STATIC_SHELL_REVIEW_REPORT.exists():
        targets.append(
            ValidationTarget(
                VOL7_LOCAL_STATIC_SHELL_REVIEW_REPORT,
                "mock_consumers",
                SCHEMA_FILES["vol7_local_static_shell_review_report"],
                "vol7_local_static_shell_review_report",
            )
        )

    if VOL7_LOCAL_STATIC_SHELL_DEMO_PACK.exists():
        targets.append(
            ValidationTarget(
                VOL7_LOCAL_STATIC_SHELL_DEMO_PACK,
                "mock_consumers",
                SCHEMA_FILES["vol7_local_static_shell_demo_pack"],
                "vol7_local_static_shell_demo_pack",
            )
        )

    if VOL7_LOCAL_STATIC_SHELL_SNAPSHOT_QA.exists():
        targets.append(
            ValidationTarget(
                VOL7_LOCAL_STATIC_SHELL_SNAPSHOT_QA,
                "mock_consumers",
                SCHEMA_FILES["vol7_local_static_shell_snapshot_qa"],
                "vol7_local_static_shell_snapshot_qa",
            )
        )

    if VOL7_COMPLETION_READINESS_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL7_COMPLETION_READINESS_GATE,
                "mock_consumers",
                SCHEMA_FILES["vol7_completion_readiness_gate"],
                "vol7_completion_readiness_gate",
            )
        )

    if VOL7_HANDOFF_SUMMARY.exists():
        targets.append(
            ValidationTarget(
                VOL7_HANDOFF_SUMMARY,
                "mock_consumers",
                SCHEMA_FILES["vol7_handoff_summary"],
                "vol7_handoff_summary",
            )
        )

    if VOL8_ENTRY_READINESS_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL8_ENTRY_READINESS_GATE,
                "mock_consumers",
                SCHEMA_FILES["vol8_entry_readiness_gate"],
                "vol8_entry_readiness_gate",
            )
        )

    if VOL8_STATIC_SHELL_QA_HANDOFF_INTAKE.exists():
        targets.append(
            ValidationTarget(
                VOL8_STATIC_SHELL_QA_HANDOFF_INTAKE,
                "mock_consumers",
                SCHEMA_FILES["vol8_static_shell_qa_handoff_intake"],
                "vol8_static_shell_qa_handoff_intake",
            )
        )

    if VOL8_BOUNDARY_FREEZE.exists():
        targets.append(
            ValidationTarget(
                VOL8_BOUNDARY_FREEZE,
                "mock_consumers",
                SCHEMA_FILES["vol8_boundary_freeze"],
                "vol8_boundary_freeze",
            )
        )

    if IMPLEMENTED_FUNCTION_FRAMEWORK_INDEX.exists():
        targets.append(
            ValidationTarget(
                IMPLEMENTED_FUNCTION_FRAMEWORK_INDEX,
                "mock_consumers",
                SCHEMA_FILES["implemented_function_framework_index"],
                "implemented_function_framework_index",
            )
        )

    if VOL8_OPERATOR_FEEDBACK_REVIEW_SAMPLE.exists():
        targets.append(
            ValidationTarget(
                VOL8_OPERATOR_FEEDBACK_REVIEW_SAMPLE,
                "mock_consumers",
                SCHEMA_FILES["vol8_operator_feedback_review"],
                "vol8_operator_feedback_review",
            )
        )

    if VOL8_OPERATOR_FEEDBACK_ROLLUP.exists():
        targets.append(
            ValidationTarget(
                VOL8_OPERATOR_FEEDBACK_ROLLUP,
                "mock_consumers",
                SCHEMA_FILES["vol8_operator_feedback_rollup"],
                "vol8_operator_feedback_rollup",
            )
        )

    if VOL8_FEEDBACK_TO_ROADMAP_MAPPING_SAMPLE.exists():
        targets.append(
            ValidationTarget(
                VOL8_FEEDBACK_TO_ROADMAP_MAPPING_SAMPLE,
                "mock_consumers",
                SCHEMA_FILES["vol8_feedback_to_roadmap_mapping"],
                "vol8_feedback_to_roadmap_mapping",
            )
        )

    if VOL8_FEEDBACK_TO_ROADMAP_BOUNDARY_MAP.exists():
        targets.append(
            ValidationTarget(
                VOL8_FEEDBACK_TO_ROADMAP_BOUNDARY_MAP,
                "mock_consumers",
                SCHEMA_FILES["vol8_feedback_to_roadmap_boundary_map"],
                "vol8_feedback_to_roadmap_boundary_map",
            )
        )

    if VOL8_FUTURE_IMPLEMENTATION_READINESS_ITEMS.exists():
        targets.append(
            ValidationTarget(
                VOL8_FUTURE_IMPLEMENTATION_READINESS_ITEMS,
                "mock_consumers",
                SCHEMA_FILES["vol8_future_implementation_readiness_item"],
                "vol8_future_implementation_readiness_item",
            )
        )

    if VOL8_FUTURE_IMPLEMENTATION_READINESS_LADDER.exists():
        targets.append(
            ValidationTarget(
                VOL8_FUTURE_IMPLEMENTATION_READINESS_LADDER,
                "mock_consumers",
                SCHEMA_FILES["vol8_future_implementation_readiness_ladder"],
                "vol8_future_implementation_readiness_ladder",
            )
        )

    if VOL8_HANDOFF_SUMMARY.exists():
        targets.append(
            ValidationTarget(
                VOL8_HANDOFF_SUMMARY,
                "mock_consumers",
                SCHEMA_FILES["vol8_handoff_summary"],
                "vol8_handoff_summary",
            )
        )

    if VOL9_ENTRY_READINESS_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL9_ENTRY_READINESS_GATE,
                "mock_consumers",
                SCHEMA_FILES["vol9_entry_readiness_gate"],
                "vol9_entry_readiness_gate",
            )
        )

    if VOL9_PHASE9_1_RUNTIME_STATUS_BACKFEED_PROTOCOL.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_1_RUNTIME_STATUS_BACKFEED_PROTOCOL,
                "mock_consumers",
                SCHEMA_FILES["twos_ldd_runtime_status_backfeed_protocol"],
                "twos_ldd_runtime_status_backfeed_protocol",
            )
        )

    if VOL9_PHASE9_1_DRIFT_RESOLUTION_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_1_DRIFT_RESOLUTION_GATE,
                "mock_consumers",
                SCHEMA_FILES["cross_workspace_baseline_drift_state"],
                "cross_workspace_baseline_drift_state",
            )
        )

    if VOL9_PHASE9_2_LDD_CONSUMER_ACKNOWLEDGEMENT.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_2_LDD_CONSUMER_ACKNOWLEDGEMENT,
                "mock_consumers",
                SCHEMA_FILES["ldd_consumer_acknowledgement"],
                "ldd_consumer_acknowledgement",
            )
        )

    if VOL9_PHASE9_2_STRICT_BASELINE_SYNC_READY_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_2_STRICT_BASELINE_SYNC_READY_GATE,
                "mock_consumers",
                SCHEMA_FILES["strict_baseline_sync_ready_gate"],
                "strict_baseline_sync_ready_gate",
            )
        )

    if VOL9_PHASE9_3_FUTURE_IMPLEMENTATION_BOUNDARY_MATRIX.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_3_FUTURE_IMPLEMENTATION_BOUNDARY_MATRIX,
                "mock_consumers",
                SCHEMA_FILES["future_implementation_boundary_matrix"],
                "future_implementation_boundary_matrix",
            )
        )

    if VOL9_PHASE9_3_STATIC_PROTOTYPE_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_3_STATIC_PROTOTYPE_GATE,
                "mock_consumers",
                SCHEMA_FILES["static_prototype_gate"],
                "static_prototype_gate",
            )
        )

    if VOL9_PHASE9_4_STATIC_PROTOTYPE_EVIDENCE_PACK.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_4_STATIC_PROTOTYPE_EVIDENCE_PACK,
                "mock_consumers",
                SCHEMA_FILES["static_prototype_evidence_pack"],
                "static_prototype_evidence_pack",
            )
        )

    if VOL9_PHASE9_4_FUTURE_GATE_READINESS_CHECKLIST.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_4_FUTURE_GATE_READINESS_CHECKLIST,
                "mock_consumers",
                SCHEMA_FILES["future_gate_readiness_checklist"],
                "future_gate_readiness_checklist",
            )
        )

    if VOL9_PHASE9_5_FORBIDDEN_SCOPE_REGRESSION_GUARD.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_5_FORBIDDEN_SCOPE_REGRESSION_GUARD,
                "mock_consumers",
                SCHEMA_FILES["forbidden_scope_regression_guard"],
                "forbidden_scope_regression_guard",
            )
        )

    if VOL9_PHASE9_5_FUTURE_GATE_NON_ACTIVATION_AUDIT.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_5_FUTURE_GATE_NON_ACTIVATION_AUDIT,
                "mock_consumers",
                SCHEMA_FILES["future_gate_non_activation_audit"],
                "future_gate_non_activation_audit",
            )
        )

    if VOL9_PHASE9_6_STATIC_SHELL_FIXTURE_COVERAGE_MATRIX.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_6_STATIC_SHELL_FIXTURE_COVERAGE_MATRIX,
                "mock_consumers",
                SCHEMA_FILES["static_shell_fixture_coverage_matrix"],
                "static_shell_fixture_coverage_matrix",
            )
        )

    if VOL9_PHASE9_6_PROTOTYPE_TO_GATE_TRACEABILITY_MAP.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_6_PROTOTYPE_TO_GATE_TRACEABILITY_MAP,
                "mock_consumers",
                SCHEMA_FILES["prototype_to_gate_traceability_map"],
                "prototype_to_gate_traceability_map",
            )
        )

    if VOL9_PHASE9_7_LDD_FULL_REPORT_SCOPE_REQUIREMENTS.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_7_LDD_FULL_REPORT_SCOPE_REQUIREMENTS,
                "mock_consumers",
                SCHEMA_FILES["ldd_full_report_scope_requirements"],
                "ldd_full_report_scope_requirements",
            )
        )

    if VOL9_PHASE9_7_LDD_ORDER_RECONCILIATION.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_7_LDD_ORDER_RECONCILIATION,
                "mock_consumers",
                SCHEMA_FILES["ldd_order_reconciliation_and_zero_fill_separation"],
                "ldd_order_reconciliation_and_zero_fill_separation",
            )
        )

    if VOL9_PHASE9_7_LDD_STATIC_COCKPIT_PANEL_GATE.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_7_LDD_STATIC_COCKPIT_PANEL_GATE,
                "mock_consumers",
                SCHEMA_FILES["ldd_static_cockpit_panel_requirement_gate"],
                "ldd_static_cockpit_panel_requirement_gate",
            )
        )

    if VOL9_PHASE9_8_IMPLEMENTED_FEATURE_INVENTORY_TREE.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_8_IMPLEMENTED_FEATURE_INVENTORY_TREE,
                "mock_consumers",
                SCHEMA_FILES["implemented_feature_inventory_tree"],
                "implemented_feature_inventory_tree",
            )
        )

    if VOL9_PHASE9_8_IMPLEMENTED_FEATURE_TIMELINE_CATALOG.exists():
        targets.append(
            ValidationTarget(
                VOL9_PHASE9_8_IMPLEMENTED_FEATURE_TIMELINE_CATALOG,
                "mock_consumers",
                SCHEMA_FILES["implemented_feature_timeline_catalog"],
                "implemented_feature_timeline_catalog",
            )
        )

    return targets, unmapped


def validate_privacy_boundary_sample() -> list[str]:
    try:
        document = load_json(PRIVACY_BOUNDARY_SAMPLE)
    except (json.JSONDecodeError, OSError) as exc:
        return [f"cannot load privacy boundary sample: {exc}"]

    if not isinstance(document, dict):
        return ["privacy boundary sample must be a JSON object"]

    errors: list[str] = []
    categories = document.get("categories")
    required_categories = {
        "public_safe_fields",
        "internal_only_fields",
        "sensitive_account_fields",
        "execution_sensitive_fields",
        "never_expose_fields",
    }
    if not isinstance(categories, dict):
        errors.append("$.categories must be an object")
    else:
        missing = sorted(required_categories - set(categories))
        if missing:
            errors.append(f"$.categories missing: {', '.join(missing)}")

    status = document.get("safety_status")
    if not isinstance(status, dict):
        errors.append("$.safety_status must be an object")
    else:
        if status.get("customer_facing_ready") is not False:
            errors.append("$.safety_status.customer_facing_ready must be false")
        if status.get("external_api_connected") is not False:
            errors.append("$.safety_status.external_api_connected must be false")
        if status.get("trading_automation_enabled") is not False:
            errors.append("$.safety_status.trading_automation_enabled must be false")

    return errors


def main() -> int:
    targets, unmapped = collect_targets()
    failures = 0
    examples_checked = 0
    records_checked = 0
    cockpit_checked = 0
    mock_consumers_checked = 0
    coverage: Counter[str] = Counter()

    if unmapped:
        for path in unmapped:
            print(f"FAIL {path.relative_to(REPO_ROOT)} has no schema mapping")
        failures += len(unmapped)

    for target in targets:
        schema_path = SCHEMAS_DIR / target.schema_name
        try:
            document = load_json(target.path)
            schema = load_json(schema_path)
        except json.JSONDecodeError as exc:
            print(f"FAIL {target.path.relative_to(REPO_ROOT)} invalid JSON: {exc}")
            failures += 1
            continue
        except OSError as exc:
            print(f"FAIL {target.path.relative_to(REPO_ROOT)} cannot load file: {exc}")
            failures += 1
            continue

        errors = validate(document, schema)
        coverage[target.schema_key] += 1

        if target.bucket == "examples":
            examples_checked += 1
        elif target.bucket == "records":
            records_checked += 1
        elif target.bucket == "cockpit":
            cockpit_checked += 1
        elif target.bucket == "mock_consumers":
            mock_consumers_checked += 1

        if errors:
            print(f"FAIL {target.path.relative_to(REPO_ROOT)} against {target.schema_name}")
            for error in errors:
                print(f"  - {error}")
            failures += 1
        else:
            print(f"PASS {target.path.relative_to(REPO_ROOT)} against {target.schema_name}")

    privacy_errors = validate_privacy_boundary_sample()
    mock_consumers_checked += 1
    if privacy_errors:
        print(f"FAIL {PRIVACY_BOUNDARY_SAMPLE.relative_to(REPO_ROOT)} against privacy boundary contract")
        for error in privacy_errors:
            print(f"  - {error}")
        failures += 1
    else:
        print(f"PASS {PRIVACY_BOUNDARY_SAMPLE.relative_to(REPO_ROOT)} against privacy boundary contract")

    total_checked = examples_checked + records_checked + cockpit_checked + mock_consumers_checked

    print()
    if failures:
        print("Runtime validation failed.")
    else:
        print("Runtime validation passed.")

    print(f"Examples checked: {examples_checked}")
    print(f"Records checked: {records_checked}")
    print(f"Cockpit files checked: {cockpit_checked}")
    print(f"Mock consumer files checked: {mock_consumers_checked}")
    print(f"Total JSON files checked: {total_checked}")
    print("Schema coverage:")
    for schema_key in sorted(SCHEMA_FILES):
        print(f"- {schema_key}: {coverage.get(schema_key, 0)}")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
