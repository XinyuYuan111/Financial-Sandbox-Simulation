export type NarrativeLine = {
  title: string
  text: string
}

export type DecisionNarrative = {
  kind: 'action' | 'planning' | 'waiting-plan' | 'plan-wait' | 'cognition' | 'no-op'
  label: string
  summary: string
  actions: string[]
}

const integer = new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 0 })

const triggerLabels: Record<string, string> = {
  initial_observation: '初始观察',
  market_change: '市场变化',
  information: '收到信息',
  private_message: '收到私信',
  own_action_outcome: '自身动作回执',
  planning_result: '规划结果返回',
  directive_wakeup: '计划指令到期',
  risk: '风险条件触发',
}

const reasonLabels: Record<string, string> = {
  world_execution_succeeded: '市场已成功执行',
  accepted: '已接受',
  queued: '已进入执行队列',
  plan_activated: '计划已激活',
  world_admission_pending: '已通过校验，等待市场执行',
  dependency_or_capability_rejected: '依赖条件或能力校验未通过',
  stale_strategy_revision: '计划版本已经过期',
  planning_request_rejected: '规划请求未被接受',
  insufficient_balance: '可用余额不足',
  insufficient_available_balance: '可用余额不足',
  invalid_price: '价格不合法',
  invalid_quantity: '数量不合法',
  order_not_found: '未找到目标订单',
  self_trade_prevented: '为避免自成交而拒绝',
  action_expired: '动作已超过有效期',
}

export function observationNarrative(observation: Record<string, unknown>): NarrativeLine[] {
  const market = asRecord(observation.market_view)
  const bids = asRecords(market.bids)
  const asks = asRecords(market.asks)
  const bestBid = bids[0]
  const bestAsk = asks[0]
  const base = text(market.base_asset, 'TOKEN')
  const quote = text(market.quote_asset, 'USDX')
  const lines: NarrativeLine[] = []

  if (bestBid || bestAsk) {
    const bidText = bestBid ? `${formatNumber(bestBid.price)}（${formatNumber(bestBid.remaining ?? bestBid.quantity)} ${base}）` : '暂无买单'
    const askText = bestAsk ? `${formatNumber(bestAsk.price)}（${formatNumber(bestAsk.remaining ?? bestAsk.quantity)} ${base}）` : '暂无卖单'
    let spread = ''
    const bidPrice = number(bestBid?.price)
    const askPrice = number(bestAsk?.price)
    if (bidPrice !== null && askPrice !== null) spread = `，价差 ${formatNumber(askPrice - bidPrice)} ${quote}`
    lines.push({ title: '盘口', text: `最优买价 ${bidText}，最优卖价 ${askText}${spread}。` })
  } else {
    lines.push({ title: '盘口', text: '当前盘口没有可见挂单。' })
  }

  const lastTrade = asRecord(market.last_trade)
  if (Object.keys(lastTrade).length) {
    lines.push({ title: '最近成交', text: `${formatNumber(lastTrade.quantity)} ${base} 成交于 ${formatNumber(lastTrade.price)} ${quote}。` })
  }

  const account = asRecord(observation.account_snapshot)
  const balances = asRecord(account.balances)
  const balanceParts = Object.entries(balances).map(([asset, raw]) => {
    const balance = asRecord(raw)
    const locked = number(balance.locked) ?? 0
    return `${asset} 可用 ${formatNumber(balance.free)}${locked ? `、锁定 ${formatNumber(locked)}` : ''}`
  })
  if (balanceParts.length) {
    const orders = asArray(account.open_orders).length
    lines.push({ title: '账户', text: `${balanceParts.join('；')}。当前有 ${orders} 笔未完成订单。` })
  }

  const information = [...asRecords(observation.information_items), ...asRecords(observation.private_messages)]
  if (information.length) {
    const latest = information[information.length - 1]
    const signal = signalText(latest)
    const content = text(latest.rendered_content, '收到一条没有正文的信息')
    lines.push({ title: '最新信息', text: `${content}${signal ? `（${signal}）` : ''}` })
  }

  const receipts = asRecords(observation.action_receipts)
  if (receipts.length) {
    const latest = receipts[receipts.length - 1]
    lines.push({ title: '自身动作', text: `最近动作${outcomeText(latest.outcome)}，原因：${reasonText(latest.reason_code)}。` })
  }

  return lines
}

export function triggerText(trigger: unknown): string {
  const item = asRecord(trigger)
  const label = triggerLabels[text(item.type)] ?? text(item.type, '观察更新')
  const severity = number(item.severity)
  return severity === null ? label : `${label} · 强度 ${severity}`
}

export function directiveNarrative(directive: unknown): NarrativeLine {
  const item = asRecord(directive)
  const type = text(item.type)
  const emission = emissionText(item.emission)
  if (type === 'trade') {
    const side = sideText(item.side)
    const style = tradeStyleText(item.style)
    const offset = number(item.price_offset_bps) ?? 0
    const offsetText = offset ? `，相对参考价偏移 ${offset > 0 ? '+' : ''}${offset} bps` : ''
    return { title: `${style}${side}`, text: `最多${side}${formatNumber(item.max_quantity)} 单位${offsetText}；${emission}。` }
  }
  if (type === 'quote') {
    const side = text(item.side) === 'both' ? '双边' : `${sideText(item.side)}单边`
    return { title: `${side}报价`, text: `目标价差 ${formatNumber(item.target_spread_bps)} bps，每侧最多 ${formatNumber(item.max_quantity_per_side)} 单位；${emission}。` }
  }
  if (type === 'cancel') {
    const selector = item.order_id ? `订单 ${short(text(item.order_id))}` : item.side ? `${sideText(item.side)}方向订单` : `计划版本 ${formatNumber(item.plan_revision)} 的订单`
    return { title: '撤销订单', text: `撤销${selector}；${emission}。` }
  }
  if (type === 'communication') {
    const targets = asArray(item.target_ids).length ? `，发送给 ${asArray(item.target_ids).length} 个指定 Agent` : ''
    const signal = signalText(item)
    return { title: '发布信息', text: `通过${channelText(item.channel)}发布“${text(item.message_payload)}”${targets}${signal ? `；信号为${signal}` : ''}；${emission}。` }
  }
  return { title: type || '未知指令', text: `执行计划指令 ${text(item.directive_key, '未命名')}；${emission}。` }
}

export function goalText(goal: unknown): string {
  const item = asRecord(goal)
  const labels: Record<string, string> = {
    preserve_capital: '保护本金并控制新增风险',
    share_market_information: '发布市场观点并影响其他参与者',
    provide_liquidity: '向盘口提供双边流动性',
    seek_risk_adjusted_return: '在风险约束内争取交易收益',
  }
  const goalKey = text(item.goal_key, '未命名目标')
  return `${labels[goalKey] ?? goalKey.replaceAll('_', ' ')}（优先级 ${formatNumber(item.priority)}）`
}

export function constraintText(constraint: unknown): string {
  const item = asRecord(constraint)
  const labels: Record<string, string> = {
    max_order_notional: '单笔最大名义金额',
    max_position_base: '最大基础资产头寸',
    min_free_quote: '最低可用计价资产',
    allowed_action_count: '允许动作数量',
  }
  return `${labels[text(item.kind)] ?? text(item.kind, '约束')} ${formatNumber(item.amount)}`
}

export function decisionNarrative(decision: Record<string, unknown>, outcome: Record<string, unknown>): DecisionNarrative {
  const actionProposals = asRecords(decision.action_proposals)
  const actions = actionProposals.map(actionProposalText)
  const memoryCount = asArray(decision.memory_proposals).length
  const beliefCount = asArray(decision.belief_proposals).length
  const planning = asRecord(decision.planning_request_proposal)
  const planActivation = asRecord(decision.strategy_plan_proposal)
  const rationale = asRecord(decision.rationale)
  const strategyRevision = number(rationale.strategy_revision) ?? 0
  const riskFlags = new Set(asArray(rationale.risk_flags).map(String))

  if (actions.length) {
    const actionIds = new Set(actionProposals.map(proposal => text(proposal.proposal_id)).filter(Boolean))
    const accepted = asRecords(outcome.proposal_results).filter(result => actionIds.has(text(result.proposal_id)) && result.accepted === true).length
    return {
      kind: 'action',
      label: `${actions.length} 个市场动作`,
      summary: accepted ? `本轮提出 ${actions.length} 个市场动作，其中 ${accepted} 个已通过决策校验。` : `本轮提出 ${actions.length} 个市场动作，等待或未通过后续校验。`,
      actions,
    }
  }
  if (Object.keys(planning).length) {
    const reasons = asArray(planning.reason_keys).map(item => triggerSemanticText(String(item)))
    return {
      kind: 'planning',
      label: '请求新计划',
      summary: `当前没有可执行计划，已请求 ${text(planning.requested_planner_profile_id, '规划器')} 生成新计划${reasons.length ? `；触发原因：${reasons.join('、')}` : ''}。`,
      actions: [],
    }
  }
  if (Object.keys(planActivation).length) {
    return {
      kind: 'planning',
      label: '激活新计划',
      summary: `规划结果已经返回，本轮激活计划 ${short(text(planActivation.plan_id))}，尚未产生市场动作。`,
      actions: [],
    }
  }
  if (memoryCount || beliefCount) {
    const details = [memoryCount ? `更新 ${memoryCount} 条记忆` : '', beliefCount ? `修订 ${beliefCount} 条信念` : ''].filter(Boolean)
    return {
      kind: 'cognition',
      label: '仅更新认知',
      summary: `本轮没有市场动作，Agent 只${details.join('并')}，为后续决策积累证据。`,
      actions: [],
    }
  }
  if (decision.planning_request_id) {
    return {
      kind: 'waiting-plan',
      label: '等待规划结果',
      summary: `规划请求 ${short(text(decision.planning_request_id))} 仍在处理中，本轮保持等待，不重复提交请求或市场动作。`,
      actions: [],
    }
  }
  if (riskFlags.has('activity_cooldown')) {
    return {
      kind: 'plan-wait',
      label: '活动冷却中',
      summary: `策略版本 ${strategyRevision} 的指令已执行完毕；为避免连续随机交易，本轮等待活动冷却结束后再请求新计划。`,
      actions: [],
    }
  }
  if (riskFlags.has('cognitive_budget_exhausted')) {
    return {
      kind: 'plan-wait',
      label: '等待规划额度',
      summary: '当前计划已无法继续产生动作，但本周期的规划额度已经用完；Agent 将在预算窗口重置后重新规划。',
      actions: [],
    }
  }
  if (riskFlags.has('no_directive_eligible')) {
    return {
      kind: 'plan-wait',
      label: '等待指令条件',
      summary: `策略版本 ${strategyRevision} 仍然有效，但本轮守卫条件或执行间隔尚未满足，因此不提交市场动作。`,
      actions: [],
    }
  }
  if (strategyRevision > 0) {
    return {
      kind: 'plan-wait',
      label: '按计划等待',
      summary: `策略版本 ${strategyRevision} 仍在生效，但本轮没有指令满足执行或重复发射条件，因此不提交市场动作。`,
      actions: [],
    }
  }
  return {
    kind: 'no-op',
    label: '评估后不行动',
    summary: '本轮已完成观察评估，但没有计划请求、认知更新或合法市场动作被提出。',
    actions: [],
  }
}

export function rationaleLines(decision: Record<string, unknown>): NarrativeLine[] {
  const rationale = asRecord(decision.rationale)
  const lines: NarrativeLine[] = []
  const goal = text(rationale.goal_summary)
  const statedReason = text(rationale.stated_reason)
  if (goal) lines.push({ title: '决策目标', text: translatePipelineText(goal) })
  if (statedReason) lines.push({ title: '记录理由', text: translatePipelineText(statedReason) })
  const uncertainty = number(rationale.uncertainty_milli)
  if (uncertainty !== null) lines.push({ title: '不确定度', text: `${uncertainty} / 1000` })
  const flags = asArray(rationale.risk_flags).map(item => riskText(String(item)))
  if (flags.length) lines.push({ title: '风险标记', text: flags.join('、') })
  return lines
}

export function actionProposalText(proposal: Record<string, unknown>): string {
  const actionType = text(proposal.action_type)
  const payload = asRecord(proposal.payload)
  const side = sideText(payload.side)
  const quantity = formatNumber(payload.quantity)
  if (actionType === 'SubmitProtectedMarketOrder') {
    return `提交保护市价${side}单：${quantity} 单位，最差可接受价格 ${formatNumber(payload.worst_price)}。`
  }
  if (actionType === 'SubmitLimitOrder') {
    return `提交${side}限价单：${quantity} 单位，价格 ${formatNumber(payload.price)}。`
  }
  if (actionType === 'CancelOrder') return `撤销订单 ${short(text(payload.order_id))}。`
  if (actionType === 'ReplaceOrder') {
    const price = payload.price === undefined ? '' : `，新价格 ${formatNumber(payload.price)}`
    const qty = payload.quantity === undefined ? '' : `，新数量 ${formatNumber(payload.quantity)}`
    return `修改订单 ${short(text(payload.order_id))}${price}${qty}。`
  }
  if (actionType === 'PublishInformation') {
    const targets = asArray(payload.target_ids).length ? `，定向发送给 ${asArray(payload.target_ids).length} 个 Agent` : ''
    return `通过${channelText(payload.channel)}发布“${text(payload.content, '无正文')}”${targets}。`
  }
  return `提交动作 ${actionType || '未知类型'}。`
}

export function receiptNarrative(receipt: Record<string, unknown>, proposal?: Record<string, unknown>): NarrativeLine[] {
  const outcome = outcomeText(receipt.outcome)
  const lines: NarrativeLine[] = [{ title: '执行结果', text: `动作${outcome}，${reasonText(receipt.reason_code)}。` }]
  if (proposal) lines.unshift({ title: '提交动作', text: actionProposalText(proposal) })
  const refs = asRecord(receipt.result_state_refs)
  if (refs.portfolio_revision !== undefined) lines.push({ title: '账户状态', text: `执行后账户版本为 ${formatNumber(refs.portfolio_revision)}。` })
  const events = asArray(receipt.authoritative_event_ids).length
  if (events) lines.push({ title: '审计事件', text: `关联 ${events} 条权威事件。` })
  return lines
}

export function reasonText(value: unknown): string {
  const reason = text(value, '未提供原因')
  return reasonLabels[reason] ?? reason.replaceAll('_', ' ')
}

export function outcomeText(value: unknown): string {
  const labels: Record<string, string> = {
    accepted: '已接受', rejected: '被拒绝', queued: '已排队', executed: '已执行', partial: '部分执行',
    failed: '执行失败', expired: '已过期', canceled: '已取消',
  }
  return labels[text(value)] ?? text(value, '状态未知')
}

export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

export function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}

function asRecords(value: unknown): Array<Record<string, unknown>> {
  return asArray(value).map(asRecord)
}

function text(value: unknown, fallback = ''): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  return fallback
}

function number(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatNumber(value: unknown): string {
  const numeric = number(value)
  return numeric === null ? '未知' : integer.format(numeric)
}

function sideText(value: unknown): string {
  return text(value) === 'sell' ? '卖出' : text(value) === 'buy' ? '买入' : '交易'
}

function tradeStyleText(value: unknown): string {
  const labels: Record<string, string> = { passive: '被动限价', aggressive: '进取限价', protected_market: '保护市价' }
  return labels[text(value)] ?? '交易'
}

function channelText(value: unknown): string {
  const labels: Record<string, string> = {
    PublicFeed: '公开信息流', OfficialAnnouncement: '官方公告', TradingTerminal: '交易终端', PrivateChannel: '私有频道',
  }
  return labels[text(value)] ?? text(value, '指定频道')
}

function emissionText(value: unknown): string {
  const emission = asRecord(value)
  const mode = text(emission.mode)
  if (mode === 'once') return '仅执行一次'
  if (mode === 'periodic') return `每 ${durationText(emission.interval_us)}执行一次，最多 ${formatNumber(emission.max_emissions)} 次`
  if (mode === 'while_guarded') return `条件成立时执行，冷却 ${durationText(emission.cooldown_us)}`
  if (mode === 'on_guard_transition') return '条件从不成立变为成立时执行'
  return '按计划发射策略执行'
}

function durationText(value: unknown): string {
  const microseconds = number(value)
  if (microseconds === null) return '未知时长'
  if (microseconds >= 60_000_000) return `${integer.format(microseconds / 60_000_000)} 分钟`
  if (microseconds >= 1_000_000) return `${integer.format(microseconds / 1_000_000)} 秒`
  return `${integer.format(microseconds)} 微秒`
}

function signalText(item: Record<string, unknown>): string {
  const direction = text(item.signal_direction)
  const labels: Record<string, string> = { bullish: '偏多', bearish: '偏空', neutral: '中性' }
  if (!direction) return ''
  const confidence = number(item.signal_confidence_milli)
  return `${labels[direction] ?? direction}${confidence === null ? '' : `，置信度 ${confidence} / 1000`}`
}

function short(value: string): string {
  if (!value) return '未知'
  return value.length <= 14 ? value : `${value.slice(0, 8)}…${value.slice(-4)}`
}

function triggerSemanticText(value: string): string {
  if (value === 'no_active_plan') return '当前没有有效计划'
  if (value === 'plan_directives_exhausted') return '当前计划的动作次数已经用完'
  if (value === 'activity_cooldown_elapsed') return '活动冷却已经结束'
  if (value === 'plan_expired') return '当前计划已经过期'
  if (value === 'plan_replan_condition_met') return '计划的重规划条件已经触发'
  if (value.startsWith('information:')) return '收到新信息'
  if (value.startsWith('market_change:')) return '市场状态变化'
  if (value.startsWith('receipt:')) return '自身动作返回结果'
  return value.replaceAll('_', ' ')
}

function riskText(value: string): string {
  const labels: Record<string, string> = {
    hold_and_protect: '等待并保护资产',
    activity_floor_sampled: '演示活动底线已触发',
    no_op_fallback: '原计划未提供动作',
    activity_sampled: '已触发有界动作采样',
    exploratory_direction_sample: '缺少方向信号，使用探索性方向',
    evidence_directed_action: '动作方向由观察或记忆证据支持',
    plan_directives_exhausted: '计划指令次数已用完',
    activity_cooldown: '活动冷却尚未结束',
    activity_cooldown_elapsed: '活动冷却已经结束',
    cognitive_budget_exhausted: '本周期规划额度已用完',
    no_directive_eligible: '本轮没有满足条件的指令',
    plan_expired: '计划已经过期',
  }
  return labels[value] ?? value.replaceAll('_', ' ')
}

function translatePipelineText(value: string): string {
  const labels: Record<string, string> = {
    'Activate a validated plan and interpret its directives': '激活已验证的计划，并解释其中可执行的指令。',
    'Update cognition and request planning': '根据最新观察更新认知，并在需要时请求新计划。',
    'All proposals were produced by the fixed Agent Decision Pipeline.': '所有提议均由固定的 Agent 决策管线根据当前观察、记忆和计划生成。',
    'Execute eligible directives from the active bounded plan.': '执行当前有界计划中已经满足条件的指令。',
    'Request a new plan because the current strategy cannot produce another action.': '当前策略已经无法继续产生动作，因此请求新计划。',
    'Wait until the activity cooldown permits another bounded plan.': '等待活动冷却结束，再生成下一份有界计划。',
    'Wait for the cognitive planning budget to reset.': '等待认知规划额度重置。',
    'Monitor the active plan until a directive becomes eligible.': '继续观察市场，直到计划中的指令满足执行条件。',
    'Update cognition while preserving current risk.': '更新认知，同时保持当前风险敞口。',
    'Participate through a bounded, capability-safe demo directive.': '通过有次数上限、符合自身能力的演示指令参与市场。',
    'Preserve capital because no capability-safe demo directive is available.': '当前没有符合能力和风险约束的演示指令，因此保护本金。',
  }
  if (labels[value]) return labels[value]
  if (value.startsWith('The local rule planner used the saved observation')) {
    return '本地规则规划器综合了当前观察、可访问记忆与信念、Persona、能力和可用余额。'
  }
  if (value.startsWith('The no-op fallback used the saved observation')) {
    const directed = value.includes('direction was supported')
    return directed
      ? '原计划没有动作；系统依据当前观察、可访问记忆与信念及可用余额生成有界动作，方向由结构化证据支持。'
      : '原计划没有动作；系统依据当前观察、可访问记忆与信念及可用余额生成有界探索动作，当前没有可靠的结构化方向信号。'
  }
  const actionMatch = value.match(/^The active plan produced (\d+) capability-checked action proposal/)
  if (actionMatch) return `当前计划根据最新盘口和账户快照生成了 ${actionMatch[1]} 个通过能力检查的动作提议。`
  const exhaustedMatch = value.match(/^Every directive in strategy revision (\d+) spent its emission budget/)
  if (exhaustedMatch && value.includes('cooldown elapsed')) {
    return `策略版本 ${exhaustedMatch[1]} 的指令次数已经用完，活动冷却已结束，因此请求重新规划。`
  }
  if (exhaustedMatch && value.includes('Replanning is held until simulation time')) {
    return `策略版本 ${exhaustedMatch[1]} 的指令次数已经用完；当前仍在活动冷却期，暂不重复规划。`
  }
  if (value === 'The plan cannot produce another action, but no planning slot remains in the current simulation-time budget window.') {
    return '当前计划无法继续产生动作，而且本周期的规划额度已经用完；预算窗口重置后将重新规划。'
  }
  if (value === 'The active plan remains valid, but no guarded or scheduled directive was eligible on this observation.') {
    return '当前计划仍然有效，但本轮没有守卫条件或执行间隔满足要求的指令。'
  }
  if (value === 'No capability-safe action or planning request was eligible on this observation.') {
    return '本轮没有符合能力与风险约束的动作，也不满足新建规划请求的条件。'
  }
  return value
}
