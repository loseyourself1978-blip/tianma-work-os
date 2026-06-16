window.TIANMA_LDD_STATIC_SHELL_DATA = Object.freeze({
  phase: "Vol.7 Phase 7.5 - Local Static Shell Review, Accessibility, Guardrail Hardening, and LDD Post-Close DUXD Backfeed",
  baseline_commit: "9de6673708ca2449701e52f41f9e2bca3787a879",
  review_timestamp: "2026-06-16T09:03:34+08:00",
  ldd_post_close_backfeed_window: "2026-06-15 U.S. regular-session post-close; screenshots 08:37-08:38 SGT/BJT",
  active_checkpoint: "2026-06-12T09:18:00+08:00",
  latest_timeline_event: "2026-06-15T18:12:39+08:00",
  runtime_records_count: 104,
  timeline_event_count: 104,
  timeline_warning_count: 0,
  active_rules_count: 11,
  strategy_states_count: 16,
  customer_facing_readiness: false,
  static_shell_implementation_readiness: "ready_with_limits",
  operating_mode: "cash_defense_core_position_survival_mode",
  portfolio_mode: "residual_core_position_mode",
  dry_run_status: "passed",
  drift_status: "no_drift_detected",
  review_status: "passed",
  accessibility_review_status: "passed",
  guardrail_visibility_status: "passed",
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
  static_safety_copy: {
    not_production: "This is not production and is not customer-facing.",
    not_live_data: "All displayed values are timestamped fixture context and are not live data.",
    cannot_trade: "This static shell cannot trade, rebalance, place orders, or modify a portfolio.",
    cannot_connect_accounts: "This static shell cannot connect to broker, Binance, market-data, or account systems.",
    cannot_accept_credentials: "This static shell cannot accept credentials, passwords, tokens, account numbers, or API keys.",
    execution_sot: "Execution source remains broker/Binance order page and final filled order records."
  },
  accessibility_review: {
    semantic_headings: true,
    panel_landmarks: true,
    keyboard_friendly_static_navigation: true,
    clear_link_text: true,
    no_hidden_critical_warnings: true,
    no_color_only_safety_signaling: true,
    no_hover_only_information: true,
    readable_contrast_reviewed: true
  },
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
    "hk_exposure_display_panel",
    "opportunity_cost_tracker_panel",
    "rule_compliance_opportunity_capture_panel",
    "zero_position_candidate_radar_panel",
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
  ldd_post_close_backfeed_snapshot: {
    fixture_only: true,
    read_only: true,
    timestamped: true,
    non_live: true,
    non_executable: true,
    source_of_truth: [
      "user_longbridge_screenshots",
      "user_binance_screenshots",
      "broker_binance_order_page_and_final_filled_order_records"
    ],
    external_market_data_usage: "cross_check_only",
    longbridge: {
      total_assets_usd: 42813.57,
      us_section_assets_usd: 24219.34,
      us_holding_value_usd: 5425.79,
      implied_us_cash_usd: 18793.55,
      us_cash_ratio_approx: "77.6%",
      us_holding_pl_usd: "+2342.34",
      us_day_pl_usd: "+145.73",
      current_day_orders_visible: "0/0"
    },
    us_holdings: {
      GOOG: "9 shares",
      NVDA: "10 shares",
      TSLA: "0.0116 residual shares",
      GGLL: "0",
      GLD: "0",
      GDXU: "0",
      SOXL: "0",
      UGL: "0",
      INTC: "0",
      SOXS: "0",
      TSLQ: "0"
    },
    hk_holding: {
      symbol: "02513 Zhipu",
      shares: 100,
      market_value_hkd: 145700,
      holding_quote_hkd: 1457.000,
      cost_hkd: 116.200,
      holding_pl_hkd: "+134080",
      day_pl_hkd: "+36000",
      day_pl_pct: "+32.81%"
    },
    binance: {
      estimated_total_assets_usdt: 8335.46,
      day_pl_usdt: "-1.08",
      day_pl_pct: "-0.01%",
      usdt_balance: "5886.00171992",
      usdt_defense_ratio_approx: "70.6%",
      ETH: "0.8070416",
      DOGE: "8400.535",
      SOL: "2.931163",
      BTC: "0.00055762",
      ZEC: "0.012974",
      withdrawal_note: "49.99 USDT completed transfer / withdrawal, not trading loss",
      zec_grid_status: "closed_no_reopen"
    }
  },
  quote_drift_requirements: {
    quote_drift_display_layer_required: true,
    quote_type_tagging_required: true,
    execution_source_of_truth_label: "Execution source remains broker/Binance order page and final filled order records.",
    non_executable_quote_warning: "Holding, watchlist, night-session, and premarket quotes are not executable prices.",
    quote_types: [
      "holding_quote",
      "watchlist_quote",
      "night_session_quote",
      "premarket_quote",
      "executable_order_book_quote",
      "final_filled_order_price"
    ]
  },
  position_separation: {
    holdings_candidate_forbidden_radar_separation_required: true,
    zero_position_candidate_radar_required: true,
    forbidden_chase_list_required: true,
    ipo_new_listing_radar_required: true,
    categories: [
      "current_holdings",
      "zero_position_former_holdings",
      "zero_position_candidate_radar",
      "forbidden_chase_list",
      "ipo_new_listing_radar",
      "residual_tiny_positions"
    ],
    current_holdings: ["GOOG 9", "NVDA 10"],
    zero_position_former_holdings: ["GGLL", "GLD", "GDXU", "SOXL", "UGL", "INTC", "SOXS", "TSLQ"],
    zero_position_candidate_radar: ["SPCX", "MU", "DRAM", "AMD", "TSM"],
    forbidden_chase_list: ["SOXL", "GDXU", "GLD", "UGL", "SPCX", "SPCH", "SSPC"],
    ipo_new_listing_radar: [
      "SPCX: IPO radar only; max 1 share limit order if considered later; no chase; no SPCH/SSPC; do not sell GOOG/NVDA to fund it"
    ],
    residual_tiny_positions: ["TSLA 0.0116"],
    ggll_current_state: "zero_position_not_residual_risk_valve",
    zec_grid_state: "closed_no_reopen"
  },
  cash_defense_split: {
    cash_defense_ratio_split_required: true,
    cash_defense_split_extended_to_hk_required: true,
    fixture_only: true,
    timestamped: true,
    non_live: true,
    non_executable: true,
    us_cash_ratio_approx: "77.6%",
    binance_usdt_defense_ratio_approx: "70.6%",
    hk_02513_holding_value_hkd: "145700",
    total_cross_account_risk_placeholder: "placeholder_fixture_only",
    usdt_defense_floor_required: true,
    usdt_defense_floor: "70%"
  },
  transfer_pnl_separation: {
    transfer_pnl_separation_required: true,
    transfer_withdrawal_pnl_separation_required: true,
    required_copy: "completed transfer / withdrawal, not trading loss",
    account_movement_events: [
      {
        event_type: "crypto_withdrawal",
        amount: "49.99 USDT",
        status: "completed",
        classification: "account_movement_not_trading_pnl",
        display_copy: "49.99 USDT completed transfer / withdrawal, not trading loss"
      }
    ]
  },
  opportunity_cost_tracker: {
    opportunity_cost_tracker_required: true,
    fixture_only: true,
    read_only: true,
    non_live: true,
    non_executable: true,
    purpose: "Track zero-position opportunity cost without marking prior risk-control decisions as wrong.",
    candidates: ["SOXL", "GDXU", "GGLL", "GLD", "UGL", "INTC", "SPCX", "MU", "DRAM"],
    rules: [
      "Opportunity cost is hindsight/context only.",
      "Opportunity cost is separate from rule compliance score.",
      "Opportunity cost must not trigger buy or re-entry actions.",
      "Opportunity cost must not override cash-defense mode.",
      "Opportunity cost is not execution advice."
    ]
  },
  rule_compliance_opportunity_capture: {
    rule_compliance_opportunity_capture_separation_required: true,
    fixture_only: true,
    read_only: true,
    non_live: true,
    non_executable: true,
    scores: {
      rule_compliance: "9.5/10",
      risk_control: "9/10",
      return_capture: "7/10",
      account_structure: "9/10",
      emotional_discipline: "9/10",
      duxd_feedback_value: "10/10",
      overall_review_score: "8.9/10"
    },
    boundary: "Scores are post-close review context only, not execution logic."
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
      fields: ["static_shell_implementation_readiness", "review_status", "customer_facing_readiness", "local_static_preview_only"]
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
      fields: ["active_rules_count", "execution_allowed", "static_safety_copy.cannot_trade"]
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
      purpose: "Show fixture-only source state and execution source-of-truth boundary.",
      fields: ["fixture_only", "read_only", "live_data_allowed", "network_allowed", "static_safety_copy.execution_sot"]
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
      purpose: "Separate current holdings, zero positions, candidates, forbidden chase names, IPO radar, and tiny residuals.",
      fields: ["position_separation"]
    },
    {
      panel_id: "cash_defense_split_panel",
      title: "Cash Defense Split Panel",
      purpose: "Show U.S., Binance, HK exposure, and total cross-account placeholder separately as static non-live values.",
      fields: ["cash_defense_split"]
    },
    {
      panel_id: "transfer_pnl_separation_panel",
      title: "Transfer / P&L Separation Panel",
      purpose: "Separate account movement events from trading performance.",
      fields: ["transfer_pnl_separation"]
    },
    {
      panel_id: "hk_exposure_display_panel",
      title: "HK Exposure Display Panel",
      purpose: "Represent HK 02513 exposure separately from U.S. cash-defense and U.S. rule scoring.",
      fields: ["ldd_post_close_backfeed_snapshot.hk_holding"]
    },
    {
      panel_id: "opportunity_cost_tracker_panel",
      title: "Opportunity Cost Tracker Panel",
      purpose: "Track zero-position opportunity cost as context only, separate from rule compliance.",
      fields: ["opportunity_cost_tracker"]
    },
    {
      panel_id: "rule_compliance_opportunity_capture_panel",
      title: "Rule Compliance / Opportunity Capture Panel",
      purpose: "Separate rule compliance, risk control, return capture, emotional discipline, and DUXD feedback value.",
      fields: ["rule_compliance_opportunity_capture"]
    },
    {
      panel_id: "zero_position_candidate_radar_panel",
      title: "Zero-Position Candidate Radar Panel",
      purpose: "Show former holdings, candidate radar, forbidden chase list, IPO/new-listing radar, and residual tiny positions.",
      fields: ["position_separation.zero_position_candidate_radar", "position_separation.forbidden_chase_list", "position_separation.ipo_new_listing_radar", "position_separation.ggll_current_state", "position_separation.zec_grid_state"]
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
      purpose: "Show hard guardrail flags and safety copy.",
      fields: ["fixture_only", "read_only", "mutation_allowed", "execution_allowed", "credential_handling_allowed", "live_data_allowed", "production_deployment_allowed", "static_safety_copy"]
    }
  ]
});
