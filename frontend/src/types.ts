export type Branch = {
  branch_id: string
  run_id: string
  parent_branch_id: string | null
  fork_checkpoint_id: string | null
  status: string
  sim_time_us: number
  state_version: number
  last_event_hash: string
}

export type Run = {
  run_id: string
  scenario_id: string
  name: string
  status: string
  runtime_version: string
  branches: Branch[]
}

export type Balance = { free: number; locked: number }

export type Order = {
  order_id: string
  agent_id: string
  side: 'buy' | 'sell'
  order_type: string
  price: number | null
  quantity: number
  remaining: number
  status: string
  submitted_seq: number
}

export type Trade = {
  trade_id: string
  buyer_id: string
  seller_id: string
  quantity: number
  price: number
  buyer_fee: number
  seller_fee: number
}

export type AgentProjection = {
  agent_id: string
  display_name?: string
  strategy?: string
  role_tags?: string[]
  planner_profile_id?: string
  agent_revision?: number
  active_strategy_revision?: number
  planning_request_id?: string | null
  portfolio: { balances: Record<string, Balance>; open_orders: Order[] }
}

export type AgentDetail = AgentProjection & {
  capabilities: string[]
  definition: Record<string, unknown> | null
  runtime_state: {
    agent_revision: number
    component_revisions: Record<string, number>
    active_strategy_revision: number
    planning_request_id: string | null
    cognitive_budget_state: Record<string, number>
    attention_budget_state: Record<string, number>
    memory_entries: Array<Record<string, unknown>>
    beliefs: Array<Record<string, unknown>>
    directive_cursors: Record<string, Record<string, unknown>>
  } | null
}

export type Projection = {
  branch_id: string
  cursor: number
  status: string
  sim_time_us: number
  parent_branch_id?: string | null
  fork_checkpoint_id?: string | null
  fixture_step?: number
  world_revision?: number
  market_status?: 'active' | 'halted'
  deferred_observation_count?: number
  terminal_reason?: string | null
  planning?: {
    total: number
    pending: number
    applied: number
    failed: number
    active_plans: number
    last_failure_code: string | null
    last_failure_message: string | null
    provider: 'openai' | 'deepseek' | null
  }
  market: {
    market_id: string
    bids: Order[]
    asks: Order[]
    last_trade: Trade | null
    trades: Trade[]
  }
  agents: AgentProjection[]
  information: Array<Record<string, unknown>>
  historical?: boolean
}

export type InterventionEffect = {
  effect_id: string
  effect_type: string
  [key: string]: unknown
}

export type InterventionStage = {
  stage_id: string
  effective_sim_time_us: number
  background_order_flow_impact_milli: number
  effects: InterventionEffect[]
  status: 'pending' | 'applied' | 'failed' | 'canceled'
  failure_reason?: string | null
}

export type InterventionPlan = {
  plan_id: string
  branch_id: string
  status: 'draft' | 'confirmed' | 'rejected' | 'canceled' | 'completed' | 'failed'
  base_world_revision: number
  plan_revision: number
  director_record: { submitted_intent: string }
  stages: InterventionStage[]
  preview: Array<{ effect_id: string; effect_type: string; target_refs: string[]; summary: string; warnings: string[] }>
}

export type EventEnvelope = {
  event_id: string
  branch_seq: number
  sim_time_us: number
  event_type: string
  source_id: string
  payload: Record<string, unknown>
  visibility: string
  event_hash: string
}

export type ProviderProfile = {
  provider: string
  model?: string
  endpoint_class?: 'responses' | 'chat_completions'
  key_present?: boolean
  timeout_seconds?: number
  max_in_flight?: number
}

export type ChainOption = {
  chain_id: string
  label: string
  holder_source_configured: boolean
}

export type ConfigurationProvenance = {
  source: 'default' | 'archetype' | 'random' | 'user' | 'llm_interpreted'
  source_ref: string | null
  distribution_version: string | null
  seed: number | null
  interpreter_request_id: string | null
  user_confirmed: boolean
}

export type ConfigurationSuggestion = {
  suggestion_id: string
  kind: 'archetype' | 'role_tag' | 'capability'
  value: string
  reason: string
  confidence_milli: number
  ambiguity: string
}

export type AgentConfigurationDraft = {
  draft_id: string
  input_mode: 'preset' | 'random' | 'natural_language' | 'detailed'
  agent_id: string | null
  display_name: string | null
  public_identity: string | null
  strategy: 'rule' | 'replay' | 'openai' | 'deepseek' | null
  archetype_ids: string[]
  role_tags: string[] | null
  capability_set: string[] | null
  base_persona: Record<string, unknown>
  cognitive_profile: Record<string, unknown>
  attention_profile: Record<string, unknown>
  latency_profile: Record<string, unknown>
  planner_profile_id: string | null
  portfolio: { token_amount: number | null; usdx_amount: number | null }
  random_fields: string[]
  provenance: Record<string, ConfigurationProvenance>
  suggestions: ConfigurationSuggestion[]
  accepted_suggestion_ids: string[]
  declined_suggestion_ids: string[]
  ambiguities: string[]
  schema_version: string
}

export type ParticipantArchetype = {
  archetype_id: string
  label: string
  suggested_role_tags: string[]
  suggested_capabilities: string[]
  suggested_persona: Record<string, number | string>
  schema_version: string
}

export type ResolvedPreview = {
  scenario_id: string
  name: string
  preset_version: string
  mode: 'test_fixture' | 'live_llm_smoke' | 'live'
  provider_report: Record<string, unknown>
  chain_snapshot: {
    schema_version: string
    provider: string
    chain_id: string
    target_token: string
    total_supply: number
    eligible_active_supply: number
    covered_eligible_supply: number
    source_buckets: Array<{ bucket_id: string; category: string; amount: number; eligible_for_active_market: boolean }>
    holder_distribution: Record<string, number | string>
  }
  market: { base_asset: string; quote_asset: string; initial_mid_price: number; price_tick: number }
  portfolio: { quote_coverage_ratio_ppm: number; token_usdx_correlation_milli: number; token_distribution: string }
  total_supply: Record<string, number>
  agents: Array<{ agent_id: string; display_name: string; strategy: string; token_balance: number; usdx_balance: number; role_tags: string[]; configuration_provenance: Record<string, ConfigurationProvenance> }>
  agent_definitions: Array<{
    agent_id: string
    display_name: string
    role_tags: string[]
    planner_profile_id: string
    capability_set: string[]
    base_persona: { risk_tolerance_milli: number; time_horizon: 'short' | 'medium' | 'long'; skepticism_milli: number }
    cognitive_profile: { max_plans_per_window: number; memory_search_limit: number }
    attention_profile: { information_capacity: number; minimum_salience: number }
    latency_profile: { planning_latency_us: number; action_latency_us: number }
    configuration_provenance: Record<string, ConfigurationProvenance>
  }>
  background_market_sector: { sector_id: string; token_balance: number; usdx_balance: number; enabled: boolean; two_sided_ready: boolean }
  preview: {
    preset?: string
    agent_count?: number
    archetype_counts?: Record<string, number>
    assets?: Record<string, number | boolean | string>
    source_buckets?: Array<{ bucket_id: string; category: string; amount: number; eligible: boolean }>
    portfolio_distribution?: Record<string, unknown>
    configuration?: { compiler_version: string; input_modes: string[]; ambiguities: string[] }
    market?: {
      initial_mid_price: number
      price_tick: number
      target_spread_bps: number
      impact_target_bps: number
      quote_levels: number
      background_participation_policy_id: string
    }
  }
  warnings: string[]
  resolution_hash: string
  schema_version: string
}

export type AgentAudit = {
  observations: Array<Record<string, unknown>>
  decisions: Array<{ decision: Record<string, unknown>; outcome: Record<string, unknown> }>
  plans: Array<{ plan: Record<string, unknown>; active: boolean }>
  receipts: Array<Record<string, unknown>>
}
