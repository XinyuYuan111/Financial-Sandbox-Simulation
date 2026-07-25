import { FormEvent, ReactNode, useMemo, useState } from 'react'
import { Archive, ChevronRight, GitFork, Radio, Send, SlidersHorizontal, Users, X } from 'lucide-react'
import type { EventEnvelope, Projection, Run } from '../types'
import { formatTime, shortId, StatusBadge } from '../components/ui'
import { channelText, informationNarrative } from '../features/agents/auditNarrative'

const channels = [
  ['PublicFeed', '公开快讯'],
  ['OfficialAnnouncement', '官方公告'],
  ['TradingTerminal', '终端数据'],
  ['PrivateChannel', '定向私信'],
] as const

const channelTagClass: Record<string, string> = {
  PublicFeed: 'ch-public',
  OfficialAnnouncement: 'ch-official',
  TradingTerminal: 'ch-terminal',
  PrivateChannel: 'ch-private',
}

const effectCatalog: Array<[string, string]> = [
  ['◇', '发布信息'], ['▽', '市场状态'], ['△', '账户冻结'], ['○', '资产转移'],
  ['☰', '创建实体'], ['✕', '创建关系'], ['⌘', '钱包访问'],
]

const roleLabels: Record<string, string> = {
  market_participant: '普通参与者', capital_holder: '资本持有者',
  liquidity_provider: '流动性提供者', asset_issuer: '资产发行方', information_participant: '信息参与者',
}

export function ControlRail({ projection, branchStatus, onPrepareInformation, onOpenInformation, onOpenInterventions, onOpenAgent }: {
  projection: Projection
  branchStatus: string
  onPrepareInformation: (draft: { intent: string; content: string; channel: typeof channels[number][0]; targetIds: string }) => void
  onOpenInformation: () => void
  onOpenInterventions: () => void
  onOpenAgent: (agentId: string) => void
}) {
  const [tab, setTab] = useState<'information' | 'intervention'>('information')
  const [content, setContent] = useState('')
  const [channel, setChannel] = useState<typeof channels[number][0]>('OfficialAnnouncement')
  const [targetIds, setTargetIds] = useState('')
  const paused = branchStatus === 'Paused'

  const submitInformation = (event: FormEvent) => {
    event.preventDefault()
    if (!content.trim() || !paused) return
    onPrepareInformation({
      intent: `在 ${channel} 发布信息`,
      content: content.trim(),
      channel,
      targetIds,
    })
  }

  const tradeCount = projection.market.trades.length
  const temperature = tradeCount >= 12 ? '躁动' : tradeCount >= 3 ? '温和' : '平静'
  const simMinutes = (projection.sim_time_us / 1_000_000).toFixed(2)

  return <aside className="control-rail">
    <div className="rail-heading"><div><span>CONTROL</span><strong>信息注入台</strong></div><Radio size={16} /></div>
    <div className="rail-tabs" role="tablist" aria-label="控制台视图">
      <button role="tab" aria-selected={tab === 'information'} className={tab === 'information' ? 'selected' : ''} onClick={() => setTab('information')}>信息注入</button>
      <button role="tab" aria-selected={tab === 'intervention'} className={tab === 'intervention' ? 'selected' : ''} onClick={() => setTab('intervention')}>干预效果</button>
    </div>

    {tab === 'information' ? <>
      <form className="information-composer" onSubmit={submitInformation}>
        <label htmlFor="information-content">外生信息</label>
        <textarea id="information-content" rows={4} value={content} onChange={event => setContent(event.target.value)} placeholder="写一条你想放进世界的消息……" maxLength={4000} />
        <div className="channel-grid">
          {channels.map(([value, label]) => <label key={value}><input type="radio" name="information-channel" value={value} checked={channel === value} onChange={() => setChannel(value)} /><span>{label}</span></label>)}
        </div>
        {channel === 'PrivateChannel' ? <label className="target-field">接收 Agent ID<input value={targetIds} onChange={event => setTargetIds(event.target.value)} placeholder="多个 ID 用逗号分隔" /></label> : null}
        <button className="intervention-button" type="submit" disabled={!paused || !content.trim()}><Send size={15} />进入确认流程</button>
        {!paused ? <p className="control-note">先暂停当前分支，干预才能在确定事件边界起草并确认。</p> : null}
      </form>
      <div className="watch-strip">模拟第 {simMinutes} 分钟 · 成交 {tradeCount} · 信息 {projection.information.length} · 温度 {temperature}</div>
      <div className="rail-subheading"><span>传播链</span><button onClick={onOpenInformation}>完整视图 <ChevronRight size={13} /></button></div>
      <div className="compact-information-list">
        {[...projection.information].reverse().slice(0, 5).map((item, index) => {
          const narrative = informationNarrative(item)
          const channelKey = String(item.channel ?? '')
          return <article className="info-entry" key={String(item.information_id ?? index)}>
            <header><span className={`ie-tag ${channelTagClass[channelKey] ?? ''}`}>{channelText(item.channel)}</span><time>{formatTime(Number(item.sim_time_us ?? 0))}</time></header>
            <p>{String(item.rendered_content ?? '')}</p>
            <small>{narrative.scope} · {narrative.claim}</small>
          </article>
        })}
        {!projection.information.length ? <p className="rail-empty">尚无信息进入传播链</p> : null}
      </div>
    </> : <>
      <div className="effect-catalog">
        {effectCatalog.map(([glyph, label]) => <div key={label}><i>{glyph}</i><span>{label}</span><small>受控效果</small></div>)}
      </div>
      <button className="intervention-button" onClick={onOpenInterventions}><SlidersHorizontal size={15} />打开干预工作舱</button>
      <dl className="control-facts"><div><dt>分支状态</dt><dd><StatusBadge status={branchStatus} /></dd></div><div><dt>规划 Provider</dt><dd>{projection.planning?.provider ?? '规则 / 回放'}</dd></div><div><dt>待处理请求</dt><dd>{projection.planning?.pending ?? 0}</dd></div><div><dt>活动计划</dt><dd>{projection.planning?.active_plans ?? 0}</dd></div></dl>
    </>}

    <div className="rail-subheading roster-heading"><span>Agent 名录</span><Users size={13} /></div>
    <div className="compact-roster">
      {projection.agents.slice(0, 24).map((agent, index) => <button className="ro-row" key={agent.agent_id} onClick={() => onOpenAgent(agent.agent_id)}>
        <i className="ro-dot" style={{ background: `var(--agent-${index % 6})` }} />
        <span className="ro-name">{agent.display_name ?? shortId(agent.agent_id)}</span>
        <span className="ro-persona">{roleLabels[agent.role_tags?.[0] ?? ''] ?? '参与者'}</span>
        <span className="ro-state">{agent.planning_request_id ? '规划中' : agent.portfolio.open_orders.length ? `${agent.portfolio.open_orders.length} 挂单` : '观望'}</span>
      </button>)}
    </div>
  </aside>
}

export function ObservationRail({ events, run, projection, onOpenEvents, onOpenBranches }: {
  events: EventEnvelope[]
  run: Run
  projection: Projection
  onOpenEvents: () => void
  onOpenBranches: () => void
}) {
  const [tab, setTab] = useState<'ledger' | 'events' | 'archive'>('ledger')
  const [query, setQuery] = useState('')
  const [visibility, setVisibility] = useState('all')
  const filtered = useMemo(() => events.filter(event => {
    const matchesQuery = !query || `${event.event_type} ${event.source_id} ${JSON.stringify(event.payload)}`.toLowerCase().includes(query.toLowerCase())
    return matchesQuery && (visibility === 'all' || event.visibility === visibility)
  }), [events, query, visibility])

  return <aside className="observation-rail">
    <div className="rail-heading"><div><span>OBSERVE</span><strong>世界账本</strong></div><Archive size={16} /></div>
    <div className="rail-tabs three" role="tablist" aria-label="观测台视图">
      {(['ledger', 'events', 'archive'] as const).map(item => <button role="tab" aria-selected={tab === item} key={item} className={tab === item ? 'selected' : ''} onClick={() => setTab(item)}>{item === 'ledger' ? '账本' : item === 'events' ? '事件' : '归档'}</button>)}
    </div>

    {tab === 'ledger' ? <div className="ledger-list">
      {[...events].reverse().slice(0, 80).map(event => <LedgerEntry key={event.event_id} event={event} />)}
      {!events.length ? <p className="rail-empty">等待不可变事件写入</p> : null}
    </div> : null}

    {tab === 'events' ? <div className="compact-events">
      <label>搜索事件<input value={query} onChange={event => setQuery(event.target.value)} placeholder="类型、主体或字段" /></label>
      <label>可见范围<select value={visibility} onChange={event => setVisibility(event.target.value)}><option value="all">全部</option><option value="analyst_only">仅分析端</option><option value="participants">参与者</option><option value="agent_private">Agent 私有</option><option value="public">公开</option></select></label>
      <button className="text-command" onClick={onOpenEvents}>打开事件浏览器 <ChevronRight size={13} /></button>
      <div>{[...filtered].reverse().slice(0, 30).map(event => <article className="event-row" key={event.event_id}>
        <i className="evt-dot" style={{ background: eventKindColor(event.event_type) }} />
        <span className="evt-type">{eventLabel(event.event_type)}</span>
        <span className="evt-source">{shortId(event.source_id)}</span>
        <span className="evt-sum">seq {event.branch_seq}</span>
        <span className="evt-vis"><StatusBadge status={event.visibility} /></span>
      </article>)}</div>
    </div> : null}

    {tab === 'archive' ? <div className="archive-summary">
      <div className="archive-mark"><GitFork size={22} /><strong>{run.branches.length}</strong><span>平行分支</span></div>
      <dl><div><dt>当前分支</dt><dd>{shortId(projection.branch_id)}</dd></div><div><dt>状态游标</dt><dd>{projection.cursor}</dd></div><div><dt>父分支</dt><dd>{shortId(projection.parent_branch_id)}</dd></div><div><dt>当前时间</dt><dd>{formatTime(projection.sim_time_us)}</dd></div></dl>
      <button className="intervention-button quiet" onClick={onOpenBranches}><Archive size={15} />分支、回放与归档</button>
    </div> : null}

    <footer className="ledger-foot">{run.name} · {shortId(projection.branch_id)} · SERVER PROJECTION</footer>
  </aside>
}

function LedgerEntry({ event }: { event: EventEnvelope }) {
  return <>
    {event.event_type === 'CheckpointCreated' ? <div className="seal-line" aria-hidden="true" /> : null}
    <article className="ledger-entry">
      <i className="blk" style={{ background: eventKindColor(event.event_type), color: eventKindColor(event.event_type) }} />
      <time>t+{(event.sim_time_us / 1_000_000).toFixed(2)}</time>
      <span>{eventLabel(event.event_type)}</span>
      <small>{shortId(event.source_id)}</small>
    </article>
  </>
}

export function WorkspaceOverlay({ title, side, onClose, children }: { title: string; side: 'left' | 'right' | 'bottom'; onClose: () => void; children: ReactNode }) {
  return <div className="workspace-backdrop" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <section className={`workspace-overlay workspace-${side}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} autoFocus>
      <header><div><span>WORKSPACE</span><h2>{title}</h2></div><button className="overlay-close" type="button" onClick={onClose} title="关闭工作舱" aria-label="关闭工作舱"><X size={18} /></button></header>
      <div className="workspace-overlay-content">{children}</div>
    </section>
  </div>
}

function eventKindColor(eventType: string): string {
  if (eventType.startsWith('Trade') || eventType.startsWith('Order') || eventType === 'FeeCharged') return '#5B8DBE'
  if (eventType.startsWith('Information') || eventType.startsWith('PrivateMessage') || eventType === 'CommunicationIntentRecorded') return '#C9922A'
  if (eventType === 'CheckpointCreated' || eventType.startsWith('Archive')) return '#C8432B'
  if (eventType.startsWith('Intervention') || eventType === 'ControlInterventionApplied' || eventType.startsWith('Background')) return '#8B7F9E'
  if (eventType.startsWith('Branch') || eventType === 'RunCreated') return '#6FA287'
  return '#7A8B8F'
}

function eventLabel(value: string): string {
  const labels: Record<string, string> = {
    RunCreated: '运行创建', BranchCreated: '分支创建', BranchPaused: '分支暂停', BranchResumed: '分支恢复', BranchStopped: '分支停止',
    CheckpointCreated: '检查点封存', ActionAccepted: '动作通过', ActionRejected: '动作拒绝', OrderSubmitted: '订单提交', TradeMatched: '订单撮合', TradeSettled: '成交结算',
    InformationPublished: '信息发布', InformationDelivered: '信息送达', PrivateMessageDelivered: '私信送达', ObservationCreated: '形成观察', AgentDecisionRecorded: 'Agent 决策',
    MemoryWritten: '写入记忆', BeliefUpdated: '信念更新', PlanningRequestStateChanged: '规划状态', StrategyPlanActivated: '策略生效', InterventionStageApplied: '干预应用',
  }
  return labels[value] ?? value
}
