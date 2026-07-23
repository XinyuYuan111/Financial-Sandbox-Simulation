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
  portfolio: {
    balances: Record<string, Balance>
    open_orders: Order[]
  }
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

export type ResolvedPreview = {
  scenario_id: string
  name: string
  mode: 'test_fixture' | 'live'
  provider_report: Record<string, unknown>
  chain_snapshot: Record<string, unknown>
  total_supply: Record<string, number>
  agents: Array<{ agent_id: string; display_name: string; strategy: string; token_balance: number; usdx_balance: number }>
  warnings: string[]
}

