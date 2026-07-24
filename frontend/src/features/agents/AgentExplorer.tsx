import { useEffect, useMemo, useState } from 'react'
import { BrainCircuit, ChevronRight, CircleDot, ClipboardList, Eye, MemoryStick, ReceiptText, Target, Users } from 'lucide-react'
import { api } from '../../api'
import type { AgentAudit, AgentDetail, AgentProjection } from '../../types'
import { EmptyState, ErrorBanner, formatInteger, formatTime, JsonBlock, shortId, StatusBadge } from '../../components/ui'

type Tab = 'overview' | 'observations' | 'memory' | 'plans' | 'decisions' | 'actions'
const tabs: Array<{ id: Tab; label: string; icon: typeof Eye }> = [
  { id: 'overview', label: '概览', icon: Users },
  { id: 'observations', label: '观察', icon: Eye },
  { id: 'memory', label: '记忆与信念', icon: MemoryStick },
  { id: 'plans', label: '计划', icon: Target },
  { id: 'decisions', label: '决策', icon: BrainCircuit },
  { id: 'actions', label: '动作回执', icon: ReceiptText },
]

type ObservationResponse = { observations: Array<Record<string, unknown>> }
type DecisionResponse = { decisions: AgentAudit['decisions'] }
type PlanResponse = { plans: AgentAudit['plans'] }
type ReceiptResponse = { receipts: AgentAudit['receipts'] }

export function AgentExplorer({ branchId }: { branchId: string }) {
  const [agents, setAgents] = useState<AgentProjection[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [detail, setDetail] = useState<AgentDetail | null>(null)
  const [audit, setAudit] = useState<AgentAudit>({ observations: [], decisions: [], plans: [], receipts: [] })
  const [tab, setTab] = useState<Tab>('overview')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    setSelectedId(''); setDetail(null); setAudit({ observations: [], decisions: [], plans: [], receipts: [] })
    api.agents<{ agents: AgentProjection[] }>(branchId).then(response => {
      if (!active) return
      setAgents(response.agents)
      setSelectedId(response.agents[0]?.agent_id ?? '')
    }).catch(reason => active && setError(reason instanceof Error ? reason.message : 'Agent 列表加载失败'))
    return () => { active = false }
  }, [branchId])

  useEffect(() => {
    if (!selectedId) return
    let active = true
    Promise.all([
      api.agent<AgentDetail>(branchId, selectedId),
      api.observations<ObservationResponse>(branchId, selectedId),
      api.decisions<DecisionResponse>(branchId, selectedId),
      api.plans<PlanResponse>(branchId, selectedId),
      api.receipts<ReceiptResponse>(branchId, selectedId),
    ]).then(([agent, observations, decisions, plans, receipts]) => {
      if (!active) return
      setDetail(agent)
      setAudit({ observations: observations.observations, decisions: decisions.decisions, plans: plans.plans, receipts: receipts.receipts })
    }).catch(reason => active && setError(reason instanceof Error ? reason.message : 'Agent 审计数据加载失败'))
    return () => { active = false }
  }, [branchId, selectedId])

  return <div className="agent-explorer">
    {error ? <ErrorBanner message={error} onClose={() => setError(null)} /> : null}
    <aside className="agent-list">
      <div className="panel-heading"><div><h2>Agent</h2><p>{agents.length} 个显式主体</p></div><Users size={18} /></div>
      <div className="agent-list-scroll">{agents.map(agent => <button key={agent.agent_id} className={selectedId === agent.agent_id ? 'selected' : ''} onClick={() => setSelectedId(agent.agent_id)}><span className={`agent-avatar profile-${agent.funding_profile ?? 'ordinary'}`}>{(agent.display_name ?? agent.agent_id).slice(0, 1).toUpperCase()}</span><span><strong>{agent.display_name ?? agent.agent_id}</strong><small>{agent.funding_profile ?? '-'} · rev {agent.agent_revision ?? 0}</small></span><ChevronRight size={16} /></button>)}</div>
    </aside>
    <section className="agent-detail">
      {detail ? <>
        <header className="agent-header"><div><span className={`agent-avatar large profile-${detail.funding_profile ?? 'ordinary'}`}>{(detail.display_name ?? detail.agent_id).slice(0, 1).toUpperCase()}</span><div><h1>{detail.display_name ?? detail.agent_id}</h1><p>{detail.agent_id}</p></div></div><div className="agent-header-state"><StatusBadge status={detail.planning_request_id ? 'Queued' : 'Ready'} /><span>Agent rev {detail.agent_revision}</span><span>Strategy rev {detail.active_strategy_revision}</span></div></header>
        <nav className="detail-tabs">{tabs.map(item => { const Icon = item.icon; return <button key={item.id} className={tab === item.id ? 'selected' : ''} onClick={() => setTab(item.id)}><Icon size={15} />{item.label}</button> })}</nav>
        <div className="detail-content">
          {tab === 'overview' ? <Overview detail={detail} audit={audit} /> : null}
          {tab === 'observations' ? <Observations observations={audit.observations} /> : null}
          {tab === 'memory' ? <MemoryBeliefs detail={detail} /> : null}
          {tab === 'plans' ? <Plans plans={audit.plans} /> : null}
          {tab === 'decisions' ? <Decisions decisions={audit.decisions} receipts={audit.receipts} /> : null}
          {tab === 'actions' ? <Receipts receipts={audit.receipts} /> : null}
        </div>
      </> : <EmptyState title="选择一个 Agent" />}
    </section>
  </div>
}

function Overview({ detail, audit }: { detail: AgentDetail; audit: AgentAudit }) {
  const balances = detail.portfolio.balances
  const definition = asRecord(detail.definition)
  const persona = asRecord(definition.base_persona)
  return <div className="agent-overview">
    <section className="fact-grid agent-facts"><div><span>资金画像</span><strong>{detail.funding_profile ?? '-'}</strong></div><div><span>规划器</span><strong>{detail.planner_profile_id ?? '-'}</strong></div><div><span>开放订单</span><strong>{detail.portfolio.open_orders.length}</strong></div><div><span>审计决策</span><strong>{audit.decisions.length}</strong></div></section>
    <div className="overview-grid"><section><h3>账户</h3><table><thead><tr><th>资产</th><th>可用</th><th>锁定</th></tr></thead><tbody>{Object.entries(balances).map(([asset, balance]) => <tr key={asset}><td><strong>{asset}</strong></td><td>{formatInteger(balance.free)}</td><td>{formatInteger(balance.locked)}</td></tr>)}</tbody></table></section><section><h3>身份与能力</h3><dl className="detail-list"><div><dt>公开身份</dt><dd>{String(definition.public_identity ?? '-')}</dd></div><div><dt>风险偏好</dt><dd>{String(persona.risk_appetite_milli ?? '-')} / 1000</dd></div><div><dt>时间偏好</dt><dd>{String(persona.time_preference_milli ?? '-')} / 1000</dd></div><div><dt>能力</dt><dd>{detail.capabilities?.join(', ') || '-'}</dd></div><div><dt>角色</dt><dd>{detail.role_tags?.join(', ') || '-'}</dd></div></dl></section></div>
  </div>
}

function Observations({ observations }: { observations: Array<Record<string, unknown>> }) {
  if (!observations.length) return <EmptyState title="暂无观察" />
  return <div className="audit-list">{observations.map(observation => <article key={String(observation.observation_id)}><header><div><strong>{shortId(String(observation.observation_id))}</strong><span>{formatTime(Number(observation.sim_time_us))}</span></div><span>world v{String(observation.world_version)}</span></header><div className="trigger-row">{asArray(observation.decision_triggers).map((trigger, index) => { const item = asRecord(trigger); return <StatusBadge key={index} status={String(item.type ?? 'observation')} /> })}{!asArray(observation.decision_triggers).length ? <span className="muted">无决策触发</span> : null}</div><details><summary>观察快照</summary><JsonBlock value={observation} /></details></article>)}</div>
}

function MemoryBeliefs({ detail }: { detail: AgentDetail }) {
  const runtime = detail.runtime_state
  if (!runtime) return <EmptyState title="暂无运行时状态" />
  return <div className="memory-grid"><section><h3>记忆 <span>{runtime.memory_entries.length}</span></h3>{runtime.memory_entries.length ? <div className="audit-list compact">{runtime.memory_entries.map((entry, index) => <article key={String(entry.memory_id ?? index)}><header><strong>{String(entry.summary ?? '-')}</strong><StatusBadge status={entry.accessible === false ? 'forgotten' : 'active'} /></header><p>置信度 {String(entry.confidence_milli ?? 0)} · 显著性 {String(entry.salience ?? 0)}</p></article>)}</div> : <EmptyState title="暂无记忆" />}</section><section><h3>信念 <span>{runtime.beliefs.length}</span></h3>{runtime.beliefs.length ? <div className="audit-list compact">{runtime.beliefs.map((belief, index) => <article key={String(belief.belief_id ?? index)}><header><strong>{String(belief.subject ?? '-')} · {String(belief.predicate ?? '-')}</strong><span>{String(belief.confidence_milli ?? 0)} / 1000</span></header><p>{String(belief.value ?? '-')}</p></article>)}</div> : <EmptyState title="暂无信念" />}</section></div>
}

function Plans({ plans }: { plans: AgentAudit['plans'] }) {
  if (!plans.length) return <EmptyState title="暂无策略计划" />
  return <div className="audit-list">{plans.map(({ plan, active }) => <article key={String(plan.plan_id)}><header><div><strong>Strategy rev {String(plan.strategy_revision)}</strong><span>{shortId(String(plan.plan_id))}</span></div><StatusBadge status={active ? 'active' : 'inactive'} /></header><div className="plan-summary"><span>有效期 {formatTime(Number(plan.valid_from_sim_time_us))} - {formatTime(Number(plan.valid_until_sim_time_us))}</span><span>{asArray(plan.directives).length} 条指令</span><span>{asArray(plan.constraints).length} 项约束</span></div><div className="directive-list">{asArray(plan.directives).map((directive, index) => { const item = asRecord(directive); return <div key={index}><CircleDot size={13} /><b>{String(item.type)}</b><span>{String(item.directive_key)}</span></div> })}</div><details><summary>完整计划</summary><JsonBlock value={plan} /></details></article>)}</div>
}

function Decisions({ decisions, receipts }: { decisions: AgentAudit['decisions']; receipts: AgentAudit['receipts'] }) {
  if (!decisions.length) return <EmptyState title="暂无决策" />
  return <div className="audit-list decision-list">{decisions.map(({ decision, outcome }) => {
    const rationale = asRecord(decision.rationale)
    const receipt = receipts.find(item => item.decision_id === decision.decision_id)
    return <article key={String(decision.decision_id)}><header><div><strong>{formatTime(Number(decision.sim_time_us))}</strong><span>{shortId(String(decision.decision_id))}</span></div><StatusBadge status={outcome.accepted ? 'accepted' : 'rejected'} /></header><div className="decision-chain"><div><Eye size={15} /><span>观察</span><b>{shortId(String(decision.observation_id))}</b></div><ChevronRight size={15} /><div><BrainCircuit size={15} /><span>决策</span><b>{asArray(decision.action_proposals).length} 动作</b></div><ChevronRight size={15} /><div><ClipboardList size={15} /><span>结果</span><b>Agent rev {String(outcome.resulting_agent_revision)}</b></div>{receipt ? <><ChevronRight size={15} /><div><ReceiptText size={15} /><span>回执</span><b>{String(receipt.outcome)}</b></div></> : null}</div><dl className="detail-list"><div><dt>目标</dt><dd>{String(rationale.goal_summary ?? '-')}</dd></div><div><dt>理由</dt><dd>{String(rationale.stated_reason ?? '-')}</dd></div><div><dt>不确定度</dt><dd>{String(rationale.uncertainty_milli ?? 0)} / 1000</dd></div><div><dt>风险标记</dt><dd>{asArray(rationale.risk_flags).join(', ') || '-'}</dd></div></dl><details><summary>决策与结果</summary><JsonBlock value={{ decision, outcome }} /></details></article>
  })}</div>
}

function Receipts({ receipts }: { receipts: AgentAudit['receipts'] }) {
  if (!receipts.length) return <EmptyState title="暂无动作回执" />
  return <div className="table-scroll"><table><thead><tr><th>时间</th><th>结果</th><th>原因</th><th>动作</th><th>决策</th><th>权威事件</th></tr></thead><tbody>{receipts.map(receipt => <tr key={String(receipt.receipt_id)}><td>{formatTime(Number(receipt.resolved_sim_time_us))}</td><td><StatusBadge status={String(receipt.outcome)} /></td><td>{String(receipt.reason_code)}</td><td title={String(receipt.action_id)}>{shortId(String(receipt.action_id))}</td><td title={String(receipt.decision_id ?? '')}>{shortId(receipt.decision_id as string | undefined)}</td><td>{asArray(receipt.authoritative_event_ids).length}</td></tr>)}</tbody></table></div>
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : []
}
