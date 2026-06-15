window.TIANMA_LDD_STATIC_SHELL_DATA = Object.freeze({
  phase: "Vol.7 Phase 7.4 - Local Static Shell Skeleton Permissioned Implementation",
  baseline_commit: "80e02ba076f191fc02e48cf7d159a66451aa8ff9",
  implementation_timestamp: "2026-06-15T18:12:39+08:00",
  active_checkpoint: "2026-06-12T09:18:00+08:00",
  latest_timeline_event: "2026-06-15T17:07:00+08:00",
  runtime_records_count: 103,
  timeline_event_count: 103,
  timeline_warning_count: 0,
  active_rules_count: 11,
  strategy_states_count: 16,
  customer_facing_readiness: false,
  static_shell_implementation_readiness: "ready_with_limits",
  operating_mode: "cash_defense_core_position_survival_mode",
  portfolio_mode: "residual_core_position_mode",
  dry_run_status: "passed",
  drift_status: "no_drift_detected",
  ldd_scope_reminder: "LDD scope is the entire U.S. equity market, not only existing or former positions.",
  fixture_only: true,
  read_only: true,
  local_static_preview_only: true,
  network_allowed: false,
  api_allowed: false,
  mutation_allowed: false,
  execution_allowed: false,
  credential_handling_allowed: false,
  live_data_allowed: false,
  production_deployment_allowed: false,
  required_labels: [
    "LOCAL STATIC PREVIEW ONLY",
    "STATIC FIXTURE",
    "READ ONLY",
    "NOT EXECUTABLE",
    "NO LIVE DATA",
    "NO BROKER CONNECTION",
    "NO BINANCE CONNECTION",
    "NO CREDENTIAL HANDLING",
    "NO RUNTIME MUTATION",
    "CUSTOMER-FACING READINESS: FALSE"
  ],
  allowed_panels: [
    "runtime_status_panel",
    "readiness_gate_panel",
    "timeline_health_panel",
    "active_rules_panel",
    "strategy_states_panel",
    "static_fixture_source_panel",
    "ldd_scope_reminder_panel",
    "quote_drift_display_panel",
    "holdings_candidate_forbidden_radar_separation_panel",
    "cash_defense_split_panel",
    "transfer_pnl_separation_panel",
    "forbidden_actions_panel",
    "non_executable_guardrail_panel"
  ],
  forbidden_actions: [
    "buy_button",
    "sell_button",
    "rebalance_button",
    "connect_broker_button",
    "connect_binance_button",
    "sync_broker_button",
    "sync_binance_button",
    "live_refresh_button",
    "api_key_input",
    "credential_form",
    "login_auth_form",
    "auto_trade_toggle",
    "runtime_edit_form",
    "rule_mutation_editor",
    "portfolio_edit_form",
    "alert_dispatch_toggle",
    "scheduler_toggle",
    "background_worker_trigger",
    "production_publish_button",
    "customer_facing_publish_flag"
  ],
  forbidden_integrations: [
    "production_ui",
    "customer_facing_ui",
    "hosted_app",
    "api_server",
    "live_endpoint",
    "external_api",
    "broker_connection",
    "binance_connection",
    "live_market_data",
    "trading_automation",
    "credential_handling",
    "runtime_mutation_ui",
    "execution_trigger",
    "order_placement",
    "portfolio_modification",
    "background_worker",
    "scheduler",
    "notification_dispatcher"
  ],
  quote_drift_requirements: {
    quote_drift_display_layer_required: true,
    quote_type_tagging_required: true,
    execution_source_of_truth_label: "Execution source of truth remains broker/Binance order page and final filled order records.",
    non_executable_quote_warning: "Watchlist, premarket, and holding valuation prices are not executable prices.",
    quote_types: [
      "broker_watchlist_latest_price",
      "premarket_price",
      "holding_valuation_price",
      "executable_order_page_price",
      "final_filled_order_price"
    ]
  },
  position_separation: {
    holdings_candidate_forbidden_radar_separation_required: true,
    categories: [
      "current_holdings",
      "watchlist_candidates",
      "forbidden_chase_list",
      "ipo_new_listing_radar",
      "zero_position_former_holdings",
      "residual_tiny_positions"
    ],
    current_holdings: ["GOOG 9", "NVDA 10"],
    watchlist_candidates: ["SPCX", "MU", "DRAM", "ASML", "TSM", "AMD", "ORCL"],
    forbidden_chase_list: ["SOXL", "GDXU", "GLD", "UGL", "SPCX", "SPCH", "SSPC"],
    ipo_new_listing_radar: ["SPCX", "SPCH", "SSPC"],
    zero_position_former_holdings: ["GGLL", "GLD", "SOXL", "UGL", "INTC", "SOXS", "TSLQ", "GDXU"],
    residual_tiny_positions: ["TSLA 0.0116"],
    ggll_current_state: "zero_position_not_residual_risk_valve",
    zec_grid_state: "closed_no_reopen"
  },
  cash_defense_split: {
    cash_defense_ratio_split_required: true,
    fixture_only: true,
    timestamped: true,
    non_live: true,
    non_executable: true,
    us_cash_ratio_approx: "77.8%",
    binance_usdt_defense_ratio_approx: "71.2%",
    total_cross_account_defense_ratio: "placeholder_fixture_only",
    usdt_defense_floor_required: true,
    usdt_defense_floor: "70%"
  },
  transfer_pnl_separation: {
    transfer_pnl_separation_required: true,
    account_movement_events: [
      {
        event_type: "crypto_withdrawal",
        amount: "49.99 USDT",
        status: "completed",
        classification: "account_movement_not_trading_pnl"
      }
    ]
  },
  panels: [
    {
      panel_id: "runtime_status_panel",
      title: "Runtime Status Panel",
      purpose: "Show static runtime baseline and operating mode.",
      fields: ["phase", "baseline_commit", "active_checkpoint", "operating_mode", "portfolio_mode"]
    },
    {
      panel_id: "readiness_gate_panel",
      title: "Readiness Gate Panel",
      purpose: "Show local static shell readiness and customer-facing blocked state.",
      fields: ["static_shell_implementation_readiness", "customer_facing_readiness", "local_static_preview_only"]
    },
    {
      panel_id: "timeline_health_panel",
      title: "Timeline Health Panel",
      purpose: "Show static timeline health with zero-warning expectation.",
      fields: ["latest_timeline_event", "timeline_event_count", "timeline_warning_count"]
    },
    {
      panel_id: "active_rules_panel",
      title: "Active Rules Panel",
      purpose: "Show active rule count as non-executable context.",
      fields: ["active_rules_count", "execution_allowed"]
    },
    {
      panel_id: "strategy_states_panel",
      title: "Strategy States Panel",
      purpose: "Show strategy state count and residual core mode context.",
      fields: ["strategy_states_count", "operating_mode", "portfolio_mode"]
    },
    {
      panel_id: "static_fixture_source_panel",
      title: "Static Fixture Source Panel",
      purpose: "Show fixture-only source state.",
      fields: ["fixture_only", "read_only", "live_data_allowed", "network_allowed"]
    },
    {
      panel_id: "ldd_scope_reminder_panel",
      title: "LDD Scope Reminder Panel",
      purpose: "Preserve full-market LDD scope.",
      fields: ["ldd_scope_reminder"]
    },
    {
      panel_id: "quote_drift_display_panel",
      title: "Quote Drift Display Panel",
      purpose: "Separate quote types and executable source-of-truth labels.",
      fields: ["quote_drift_requirements"]
    },
    {
      panel_id: "holdings_candidate_forbidden_radar_separation_panel",
      title: "Holdings / Candidate / Forbidden / Radar Separation Panel",
      purpose: "Separate active holdings, candidates, forbidden chase names, radar names, zero positions, and residual tiny positions.",
      fields: ["position_separation"]
    },
    {
      panel_id: "cash_defense_split_panel",
      title: "Cash Defense Split Panel",
      purpose: "Show U.S. and Binance defense ratios as separate static non-live values.",
      fields: ["cash_defense_split"]
    },
    {
      panel_id: "transfer_pnl_separation_panel",
      title: "Transfer / P&L Separation Panel",
      purpose: "Separate account movement events from trading performance.",
      fields: ["transfer_pnl_separation"]
    },
    {
      panel_id: "forbidden_actions_panel",
      title: "Forbidden Actions Panel",
      purpose: "List blocked actions and integrations as non-interactive text.",
      fields: ["forbidden_actions", "forbidden_integrations"]
    },
    {
      panel_id: "non_executable_guardrail_panel",
      title: "Non-Executable Guardrail Panel",
      purpose: "Show hard guardrail flags.",
      fields: ["fixture_only", "read_only", "mutation_allowed", "execution_allowed", "credential_handling_allowed", "live_data_allowed", "production_deployment_allowed"]
    }
  ]
});
