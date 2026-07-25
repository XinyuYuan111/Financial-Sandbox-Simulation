import { useMemo, useState } from 'react'
import { Filter, Search } from 'lucide-react'
import type { EventEnvelope } from '../../types'
import { EmptyState, formatTime, shortId, StatusBadge } from '../../components/ui'

export function EventExplorer({ events }: { events: EventEnvelope[] }) {
  const [query, setQuery] = useState('')
  const [visibility, setVisibility] = useState('all')
  const filtered = useMemo(() => events.filter(event => {
    const match = !query || `${event.event_type} ${event.source_id} ${JSON.stringify(event.payload)}`.toLowerCase().includes(query.toLowerCase())
    return match && (visibility === 'all' || event.visibility === visibility)
  }), [events, query, visibility])
  return <section className="workspace-panel full-panel event-explorer">
    <div className="panel-heading"><div><h2>事件浏览器</h2><p>当前显示 {filtered.length} / {events.length} 条记录</p></div><div className="event-filters"><label><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索事件或主体" /></label><label><Filter size={15} /><select value={visibility} onChange={event => setVisibility(event.target.value)}><option value="all">全部可见范围</option><option value="analyst_only">仅分析端</option><option value="participants">参与者可见</option><option value="agent_private">Agent 私有</option><option value="public">公开</option></select></label></div></div>
    {filtered.length ? <div className="table-scroll event-table"><table><thead><tr><th>序号</th><th>时间</th><th>发生了什么</th><th>发起方</th><th>可见范围</th><th>自然语言摘要</th></tr></thead><tbody>{[...filtered].reverse().map(event => <tr key={event.event_id}><td>{event.branch_seq}</td><td>{formatTime(event.sim_time_us)}</td><td><strong>{eventTitle(event.event_type)}</strong><small>{shortId(event.event_id)}</small></td><td title={event.source_id}>{shortId(event.source_id)}</td><td><StatusBadge status={event.visibility} /></td><td className="payload-cell">{eventSummary(event)}</td></tr>)}</tbody></table></div> : <EmptyState title="没有匹配事件" />}
  </section>
}

const eventLabels: Record<string, string> = {
  RunCreated: '创建运行', BranchCreated: '创建分支', BranchPaused: '暂停分支', BranchResumed: '恢复分支',
  BranchStopped: '停止分支', CheckpointCreated: '建立保存点', ArchiveExported: '导出存档', ArchiveImported: '导入存档',
  ActionAccepted: '动作通过校验', ActionRejected: '动作被拒绝', PendingActionScheduled: '动作进入执行队列',
  PendingActionResolved: '动作执行完毕', OrderSubmitted: '提交订单', OrderCancelled: '撤销订单', OrderReplaced: '修改订单',
  TradeMatched: '订单完成撮合', TradeSettled: '成交完成结算', FeeCharged: '收取交易费用',
  InformationPublished: '发布一条信息', InformationDelivered: '信息已经送达', PrivateMessageDelivered: '私信已经送达',
  InformationViewed: 'Agent 查看信息', InformationWithheld: 'Agent 选择不披露', CommunicationIntentRecorded: '记录交流意图',
  ObservationCreated: '形成一次局部观察', AgentDecisionRecorded: 'Agent 作出决策', AgentDecisionOutcomeRecorded: '决策完成校验',
  MemoryWritten: '形成一条记忆', BeliefUpdated: '更新一条信念',
  PlanningRequestStateChanged: '规划请求更新', StrategyPlanActivated: '新计划开始生效', PlanningResultRecorded: '规划结果已保存',
  BackgroundOrderFlowImpactApplied: '外部事件开始影响背景订单流', BackgroundOrderFlowSampled: '背景订单流完成采样', AgentNoOpFallbackSampled: '演示活动策略完成采样',
  InterventionStageApplied: '外部干预阶段已应用', ControlInterventionApplied: '外部干预已生效',
}

function eventTitle(eventType: string): string {
  return eventLabels[eventType] ?? '系统状态发生变化'
}

function eventSummary(event: EventEnvelope): string {
  const payload = event.payload
  if (event.event_type === 'InformationPublished') {
    return `${event.source_id} 发布：“${String(payload.rendered_content ?? '无正文')}”。`
  }
  if (event.event_type === 'CommunicationIntentRecorded') {
    const scope = payload.disclosure_scope === 'selective' ? '定向披露' : '公开表达'
    if (payload.claim_intent === 'strategic_deception') {
      return `${event.source_id} 选择${scope}；其公开方向与私有判断相反。此意图只对分析端可见。`
    }
    return `${event.source_id} 选择${scope}，公开说法与记录的私有判断一致。`
  }
  if (event.event_type === 'InformationWithheld') {
    return `${event.source_id} 保留了当前${directionText(payload.private_assessment_direction)}判断，没有向其他 Agent 发送。`
  }
  if (event.event_type === 'PrivateMessageDelivered') return `一条定向消息已送达 ${String(payload.target_id ?? '目标 Agent')}。`
  if (event.event_type === 'InformationDelivered') return `一条公开信息已送达 ${String(payload.target_id ?? '目标 Agent')}。`
  if (event.event_type === 'InformationViewed') return `${String(payload.agent_id ?? '目标 Agent')} 已实际查看这条信息，之后才可能形成记忆和信念。`
  if (event.event_type === 'ObservationCreated') return `${String(payload.agent_id ?? event.source_id)} 保存了当时实际可见的市场、账户和信息快照。`
  if (event.event_type === 'MemoryWritten') {
    return payload.source_kind === 'market_observation'
      ? `${event.source_id} 把当时的盘口与成交状态写入私有记忆。`
      : `${event.source_id} 把实际查看过的信息写入私有记忆。`
  }
  if (event.event_type === 'BeliefUpdated') {
    return `${event.source_id} 根据可访问记忆更新了对 ${String(payload.subject ?? '相关对象')} 的主观判断，确信程度为 ${String(payload.confidence_milli ?? '未知')} / 1000。`
  }
  if (event.event_type === 'TradeMatched' || event.event_type === 'TradeSettled') {
    return `${String(payload.quantity ?? '未知数量')} 单位资产以 ${String(payload.price ?? '未知价格')} 成交。`
  }
  if (event.event_type === 'OrderSubmitted' || event.event_type === 'OrderReplaced') {
    const side = payload.side === 'buy' ? '买入' : payload.side === 'sell' ? '卖出' : '交易'
    return `${String(payload.agent_id ?? event.source_id)} 提交${side}意向，数量 ${String(payload.quantity ?? '未知')}，价格 ${String(payload.price ?? '按保护价格执行')}。`
  }
  if (event.event_type === 'ActionRejected') return `动作未通过执行边界，原因是 ${reasonText(payload.reason_code ?? payload.reason)}。`
  if (event.event_type === 'PlanningRequestStateChanged') return `Agent 的策略规划从${stateText(payload.from)}进入${stateText(payload.to)}。`
  if (event.event_type === 'AgentDecisionOutcomeRecorded') return `决策完成校验，产生 ${String(payload.accepted_actions ?? 0)} 个可进入世界执行的动作。`
  if (event.event_type === 'BackgroundOrderFlowImpactApplied') {
    const impact = numericValue(payload.signed_impact_milli)
    if (impact === 0) return '本阶段对背景订单流的影响为中性，未来买卖采样倾向保持不变。'
    const action = impact > 0 ? '提高背景买入概率' : '降低背景买入概率并增加卖出倾向'
    return `外部事件开始产生${marketImpactText(impact)}影响，未来采样将${action}。`
  }
  if (event.event_type === 'BackgroundOrderFlowSampled') {
    const baseProbability = optionalNumericValue(payload.base_buy_probability_milli)
    const effectiveProbability = optionalNumericValue(payload.effective_buy_probability_milli)
    const impact = numericValue(payload.net_impact_milli)
    const sampledSide = payload.side === 'buy' ? '买入' : payload.side === 'sell' ? '卖出' : '方向未知'
    if (baseProbability === null || effectiveProbability === null) {
      return `背景订单流本次采样方向为${sampledSide}；这条历史记录没有保存冲击前后的买入概率。`
    }
    return `背景订单流原本有 ${probabilityText(baseProbability)} 的买入概率；受到${marketImpactText(impact)}影响后，实际买入概率为 ${probabilityText(effectiveProbability)}，本次采样方向为${sampledSide}。`
  }
  if (event.event_type === 'CheckpointCreated') return `分支在完整事件边界建立了可回看、可分叉的保存点。`
  if (payload.message) return String(payload.message)
  if (payload.reason || payload.reason_code) return `系统记录的原因是 ${reasonText(payload.reason ?? payload.reason_code)}。`
  return '系统已把这次变化写入不可变事件历史，详细字段可通过审计数据查询。'
}

function numericValue(value: unknown): number {
  return optionalNumericValue(value) ?? 0
}

function optionalNumericValue(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function probabilityText(value: number): string {
  const percentage = Math.max(0, Math.min(100, value / 10))
  return `${Number.isInteger(percentage) ? percentage.toFixed(0) : percentage.toFixed(1)}%`
}

function marketImpactText(value: number): string {
  const degree = Math.abs(value) >= 700 ? '强烈' : Math.abs(value) >= 350 ? '明显' : Math.abs(value) > 0 ? '轻微' : ''
  if (value > 0) return `${degree}利多`
  if (value < 0) return `${degree}利空`
  return '中性'
}

function directionText(value: unknown): string {
  return ({ bullish: '偏多', bearish: '偏空', neutral: '中性' } as Record<string, string>)[String(value)] ?? '方向未知'
}

function stateText(value: unknown): string {
  return ({ Queued: '“等待规划”', Running: '“正在规划”', Ready: '“结果就绪”', Terminal: '“已经完成”' } as Record<string, string>)[String(value)] ?? '“初始状态”'
}

function reasonText(value: unknown): string {
  const raw = String(value ?? '未提供原因')
  const labels: Record<string, string> = {
    insufficient_balance: '可用余额不足', insufficient_available_balance: '可用余额不足',
    dependency_or_capability_rejected: '依赖条件或能力边界不允许', action_expired: '动作已经过期',
    world_execution_succeeded: '市场已成功执行',
  }
  return labels[raw] ?? '已记录的执行边界未满足'
}
