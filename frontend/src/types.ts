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
  funding_profile?: string
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
  key_present?: boolean
  timeout_seconds?: number
  max_in_flight?: number
}

export type ResolvedPreview = {
  scenario_id: string
  name: string
  preset_version: string
  mode: 'test_fixture' | 'live_llm_smoke' | 'live'
  provider_report: Record<string, unknown>
  chain_snapshot: Record<string, unknown>
  total_supply: Record<string, number>
  agents: Array<{ agent_id: string; display_name: string; strategy: string; token_balance: number; usdx_balance: number }>
  agent_definitions: Array<{ agent_id: string; display_name: string; funding_profile: string; role_tags: string[]; planner_profile_id: string }>
  background_market_sector: { sector_id: string; token_balance: number; usdx_balance: number }
  preview: {
    preset?: string
    agent_count?: number
    funding_profile_counts?: Record<string, number>
    assets?: Record<string, number | boolean>
  }
  warnings: string[]
}

export type AgentAudit = {
  observations: Array<Record<string, unknown>>
  decisions: Array<{ decision: Record<string, unknown>; outcome: Record<string, unknown> }>
  plans: Array<{ plan: Record<string, unknown>; active: boolean }>
  receipts: Array<Record<string, unknown>>
}
