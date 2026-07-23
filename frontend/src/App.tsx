import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import {
  Activity, Archive, Box, Boxes, ChevronRight, CirclePause, CirclePlay,
  Database, Download, GitFork, Info, LayoutDashboard, Pause, Play,
  RefreshCw, Save, Settings2, StepForward, Upload, Users, X,
} from 'lucide-react'
import { api } from './api'
import type { EventEnvelope, Projection, ResolvedPreview, Run, Trade } from './types'

type View = 'market' | 'timeline' | 'information' | 'agents' | 'worlds' | 'replay' | 'scenario' | 'archive'

const navItems: Array<{ id: View; label: string; icon: typeof Activity }> = [
  { id: 'market', label: '市场工作台', icon: LayoutDashboard },
  { id: 'timeline', label: '事件时间线', icon: Activity },
  { id: 'information', label: '信息流', icon: Info },
  { id: 'agents', label: 'Agent 视图', icon: Users },
  { id: 'worlds', label: '平行世界', icon: GitFork },
  { id: 'replay', label: '回放', icon: CirclePlay },
  { id: 'scenario', label: 'Scenario', icon: Settings2 },
  { id: 'archive', label: 'Archive', icon: Archive },
]

const eventLabels: Record<string, string> = {
  RunCreated: '运行创建', InitialStateResolved: '初始状态解析', BranchCreated: '分支创建',
  BranchResumed: '分支运行', BranchPaused: '分支暂停', BranchQuiescing: '静默保存',
  CheckpointCreated: '检查点创建', ActionAccepted: '动作接受', ActionRejected: '动作拒绝',
  OrderSubmitted: '订单提交', OrderCancelled: '订单撤销', TradeMatched: '撮合完成',
  OrderReplaced: '订单替换',
  TradeSettled: '成交结算', FeeCharged: '费用记账', ObservationCreated: '观察生成',
  InformationPublished: '信息发布', PrivateMessageDelivered: '私信送达',
  InformationDelivered: '信息送达', InformationViewed: '信息阅读',
}

const formatNumber = (value: number | undefined | null) => new Intl.NumberFormat('zh-CN').format(value ?? 0)
const shortId = (value: string | null | undefined) => value ? `${value.slice(0, 8)}...${value.slice(-4)}` : '-'
const simTime = (value: number) => `${(value / 1_000_000).toFixed(1)}s`

function IconButton({ title, onClick, disabled, children }: { title: string; onClick: () => void; disabled?: boolean; children: ReactNode }) {
  return <button type="button" className="icon-button" title={title} aria-label={title} onClick={onClick} disabled={disabled}>{children}</button>
}

function StatusMark({ status }: { status: string }) {
  const running = status === 'Running'
  return <span className={`status-mark status-${status.toLowerCase()}`}><span className="status-dot" />{running ? '运行中' : status}</span>
}

function ScenarioBuilder({ onRun }: { onRun: (run: Run) => void }) {
  const [mode, setMode] = useState<'test_fixture' | 'live'>('test_fixture')
  const [name, setName] = useState('Framework Alpha 实验')
  const [token, setToken] = useState('TOKEN')
  const [chain, setChain] = useState('ethereum')
  const [provider, setProvider] = useState('openai')
  const [preview, setPreview] = useState<ResolvedPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const resolve = async () => {
    setBusy(true); setError(null)
    try {
      const scenario = await api.createScenario<{ scenario_id: string }>({
        name, mode, seed: 20260723, target_token: token,
        chain_id: mode === 'live' ? chain : null,
        llm_provider: mode === 'live' ? provider : null,
      })
      setPreview(await api.resolveScenario<ResolvedPreview>(scenario.scenario_id))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '解析失败')
    } finally { setBusy(false) }
  }

  const createRun = async () => {
    if (!preview) return
    setBusy(true); setError(null)
    try { onRun(await api.createRun<Run>(preview.scenario_id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '创建失败') }
    finally { setBusy(false) }
  }

  return <div className="scenario-layout">
    <section className="form-surface">
      <div className="section-heading"><div><h2>Scenario Builder</h2><p>framework-alpha.default.v0.2</p></div><Database size={20} /></div>
      <label>运行名称<input value={name} onChange={(event) => setName(event.target.value)} /></label>
      <div className="segmented" role="group" aria-label="运行模式">
        <button className={mode === 'test_fixture' ? 'selected' : ''} onClick={() => { setMode('test_fixture'); setPreview(null) }}>测试 Fixture</button>
        <button className={mode === 'live' ? 'selected' : ''} onClick={() => { setMode('live'); setPreview(null) }}>Live</button>
      </div>
      <label>目标 Token<input value={token} onChange={(event) => setToken(event.target.value.toUpperCase())} /></label>
      {mode === 'live' ? <>
        <label>外部链<select value={chain} onChange={(event) => setChain(event.target.value)}><option value="ethereum">Ethereum</option><option value="solana">Solana</option></select></label>
        <label>LLM Provider<select value={provider} onChange={(event) => setProvider(event.target.value)}><option value="openai">OpenAI</option><option value="anthropic">Anthropic</option></select></label>
      </> : null}
      {error ? <div className="inline-error"><X size={16} />{error}</div> : null}
      <button className="primary-button" onClick={resolve} disabled={busy}><RefreshCw size={16} />{busy ? '解析中' : '解析初始状态'}</button>
    </section>
    <section className="preview-surface">
      <div className="section-heading"><div><h2>Resolved Initial State</h2><p>{preview?.mode ?? '等待解析'}</p></div><Box size={20} /></div>
      {preview ? <>
        <dl className="preview-facts">
          <div><dt>最终区块</dt><dd>{String(preview.chain_snapshot.block_height ?? '-')}</dd></div>
          <div><dt>Provider</dt><dd>{String(preview.provider_report.provider ?? '-')}</dd></div>
          <div><dt>Agent</dt><dd>{preview.agents.length}</dd></div>
          <div><dt>资产</dt><dd>{Object.keys(preview.total_supply).join(' / ')}</dd></div>
        </dl>
        <div className="allocation-table"><div className="table-head"><span>主体</span><span>策略</span><span>Token</span><span>USDx</span></div>
          {preview.agents.map(agent => <div className="table-row" key={agent.agent_id}><span>{agent.display_name}</span><span>{agent.strategy}</span><span>{formatNumber(agent.token_balance)}</span><span>{formatNumber(agent.usdx_balance)}</span></div>)}
        </div>
        {preview.warnings.map(warning => <div className="warning-line" key={warning}>{warning}</div>)}
        <button className="primary-button" onClick={createRun} disabled={busy}><Play size={16} />创建运行</button>
      </> : <div className="empty-state"><Database size={28} /><span>无已解析状态</span></div>}
    </section>
  </div>
}

function PriceChart({ trades }: { trades: Trade[] }) {
  const points = useMemo(() => {
    if (!trades.length) return ''
    const prices = trades.map(trade => trade.price)
    const min = Math.min(...prices) - 1
    const max = Math.max(...prices) + 1
    return prices.map((price, index) => `${16 + index * (448 / Math.max(prices.length - 1, 1))},${142 - ((price - min) / Math.max(max - min, 1)) * 110}`).join(' ')
  }, [trades])
  return <div className="chart-wrap">
    <svg viewBox="0 0 480 160" role="img" aria-label="成交价格走势">
      {[32, 72, 112, 152].map(y => <line key={y} x1="8" x2="472" y1={y} y2={y} className="chart-grid" />)}
      {points ? <polyline points={points} className="price-line" /> : null}
    </svg>
    {trades.length === 0 ? <span className="chart-empty">等待成交</span> : null}
  </div>
}

function OrderBook({ projection }: { projection: Projection }) {
  const rows = Math.max(projection.market.asks.length, projection.market.bids.length, 5)
  return <section className="tool-panel orderbook-panel">
    <div className="panel-title"><h3>订单簿</h3><span>{projection.market.market_id}</span></div>
    <div className="book-header"><span>买量</span><span>买价</span><span>卖价</span><span>卖量</span></div>
    {Array.from({ length: rows }, (_, index) => {
      const bid = projection.market.bids[index]
      const ask = projection.market.asks[index]
      return <div className="book-row" key={index}>
        <span>{bid ? formatNumber(bid.remaining) : '-'}</span><span className="positive">{bid?.price ?? '-'}</span>
        <span className="negative">{ask?.price ?? '-'}</span><span>{ask ? formatNumber(ask.remaining) : '-'}</span>
      </div>
    })}
  </section>
}

function MarketView({ projection }: { projection: Projection }) {
  const last = projection.market.last_trade
  const volume = projection.market.trades.reduce((sum, trade) => sum + trade.quantity, 0)
  return <div className="market-layout">
    <section className="market-main">
      <div className="market-stats">
        <div><span>最新价</span><strong>{last?.price ?? '---'}</strong><small>USDx ticks</small></div>
        <div><span>成交量</span><strong>{formatNumber(volume)}</strong><small>Token units</small></div>
        <div><span>事件游标</span><strong>{projection.cursor}</strong><small>{simTime(projection.sim_time_us)}</small></div>
        <div><span>盘口</span><strong>{projection.market.bids.length + projection.market.asks.length}</strong><small>open orders</small></div>
      </div>
      <div className="chart-panel"><div className="panel-title"><h3>价格路径</h3><span>虚拟时间</span></div><PriceChart trades={projection.market.trades} /></div>
      <section className="trade-tape"><div className="panel-title"><h3>成交记录</h3><span>{projection.market.trades.length} trades</span></div>
        <div className="trade-header"><span>成交</span><span>买方</span><span>卖方</span><span>价格</span><span>数量</span></div>
        {projection.market.trades.slice().reverse().map(trade => <div className="trade-row" key={trade.trade_id}><span>{shortId(trade.trade_id)}</span><span>{trade.buyer_id}</span><span>{trade.seller_id}</span><span>{trade.price}</span><span>{formatNumber(trade.quantity)}</span></div>)}
        {projection.market.trades.length === 0 ? <div className="empty-row">暂无成交</div> : null}
      </section>
    </section>
    <OrderBook projection={projection} />
  </div>
}

function Timeline({ events }: { events: EventEnvelope[] }) {
  return <section className="timeline-surface">
    <div className="table-toolbar"><h2>权威事件</h2><span>{events.length} events</span></div>
    <div className="event-table">
      <div className="event-head"><span>Seq</span><span>虚拟时间</span><span>事件</span><span>来源</span><span>摘要</span><span>Hash</span></div>
      {events.slice().reverse().map(event => <div className="event-row" key={event.event_id}>
        <span>{event.branch_seq}</span><span>{simTime(event.sim_time_us)}</span><span><i className={`event-kind kind-${event.event_type.toLowerCase()}`} />{eventLabels[event.event_type] ?? event.event_type}</span><span>{event.source_id}</span><span>{eventSummary(event)}</span><span className="mono">{shortId(event.event_hash)}</span>
      </div>)}
    </div>
  </section>
}

function eventSummary(event: EventEnvelope) {
  const payload = event.payload
  if (event.event_type === 'TradeSettled') return `${payload.quantity} @ ${payload.price}`
  if (event.event_type === 'OrderSubmitted') return `${payload.side} ${payload.quantity} @ ${payload.price ?? 'MKT'}`
  if (event.event_type === 'ObservationCreated') return String(payload.agent_id ?? '')
  if (event.event_type === 'ActionRejected') return String(payload.reason ?? '')
  return Object.keys(payload).slice(0, 2).map(key => `${key}: ${String(payload[key])}`).join(' · ') || '-'
}

function AgentView({ projection, branchId }: { projection: Projection; branchId: string }) {
  const [selected, setSelected] = useState(projection.agents[0]?.agent_id ?? '')
  const [observations, setObservations] = useState<Array<Record<string, unknown>>>([])
  const agent = projection.agents.find(item => item.agent_id === selected) ?? projection.agents[0]
  useEffect(() => {
    if (!agent) return
    api.observations<{ observations: Array<Record<string, unknown>> }>(branchId, agent.agent_id, projection.cursor).then(body => setObservations(body.observations)).catch(() => setObservations([]))
  }, [agent?.agent_id, branchId, projection.cursor])
  if (!agent) return <div className="empty-state">无 Agent</div>
  return <div className="agent-layout">
    <aside className="agent-list"><div className="list-title">Agents</div>{projection.agents.map(item => <button key={item.agent_id} className={item.agent_id === agent.agent_id ? 'selected' : ''} onClick={() => setSelected(item.agent_id)}><span className="avatar">{(item.display_name ?? item.agent_id).slice(0, 1)}</span><span><strong>{item.display_name ?? item.agent_id}</strong><small>{item.strategy ?? 'historical'}</small></span><ChevronRight size={15} /></button>)}</aside>
    <section className="agent-detail">
      <div className="agent-title"><div><h2>{agent.display_name ?? agent.agent_id}</h2><p>{agent.agent_id} · {(agent.role_tags ?? []).join(', ')}</p></div><Users size={22} /></div>
      <div className="balance-strip">{Object.entries(agent.portfolio.balances ?? {}).map(([asset, balance]) => <div key={asset}><span>{asset}</span><strong>{formatNumber(balance.free)}</strong><small>{formatNumber(balance.locked)} locked</small></div>)}</div>
      <div className="agent-columns">
        <section><div className="panel-title"><h3>实际观察</h3><span>{observations.length}</span></div>{observations.slice(0, 8).map(item => <div className="observation-row" key={String(item.observation_id)}><span>{simTime(Number(item.sim_time_us))}</span><strong>{shortId(String(item.observation_id))}</strong><small>world v{String(item.world_version)}</small></div>)}</section>
        <section><div className="panel-title"><h3>未结订单</h3><span>{agent.portfolio.open_orders?.length ?? 0}</span></div>{(agent.portfolio.open_orders ?? []).map(order => <div className="observation-row" key={order.order_id}><span className={order.side === 'buy' ? 'positive' : 'negative'}>{order.side}</span><strong>{order.remaining} @ {order.price}</strong><small>{order.status}</small></div>)}</section>
      </div>
    </section>
  </div>
}

function WorldsView({ run, activeBranchId, onSelect, onFork, checkpointId }: { run: Run; activeBranchId: string; onSelect: (id: string) => void; onFork: () => void; checkpointId: string | null }) {
  return <section className="worlds-surface"><div className="table-toolbar"><h2>Parallel Worlds</h2><button className="secondary-button" onClick={onFork} disabled={!checkpointId}><GitFork size={16} />从检查点分叉</button></div>
    <div className="branch-tree">{run.branches.map((branch, index) => <button key={branch.branch_id} className={branch.branch_id === activeBranchId ? 'branch-row selected' : 'branch-row'} onClick={() => onSelect(branch.branch_id)}>
      <span className="branch-rail"><i />{index > 0 ? <b /> : null}</span><GitFork size={17} /><span><strong>{index === 0 ? 'Root world' : `Branch ${index}`}</strong><small>{shortId(branch.branch_id)}</small></span><StatusMark status={branch.status} /><span className="branch-cursor">v{branch.state_version}</span>
    </button>)}</div>
  </section>
}

function InformationView({ items }: { items: Array<Record<string, unknown>> }) {
  return <section className="information-surface"><div className="table-toolbar"><h2>Information Map</h2><span>{items.length} items</span></div>
    <div className="information-list">{items.slice().reverse().map(item => <article key={String(item.information_id)}><div className="source-mark">{String(item.source_id ?? '?').slice(0, 1).toUpperCase()}</div><div><div className="info-meta"><strong>{String(item.source_id)}</strong><span>{String(item.channel)}</span><time>{simTime(Number(item.sim_time_us))}</time></div><p>{String(item.rendered_content)}</p></div></article>)}{items.length === 0 ? <div className="empty-state"><Info size={26} /><span>暂无信息事件</span></div> : null}</div>
  </section>
}

function ReplayView({ projection, minCursor, maxCursor, onCursor }: { projection: Projection; minCursor: number; maxCursor: number; onCursor: (cursor?: number) => void }) {
  const [cursor, setCursor] = useState(projection.cursor)
  useEffect(() => setCursor(projection.cursor), [projection.cursor])
  return <section className="replay-surface">
    <div className="replay-head"><div><h2>Replay</h2><p>{projection.historical ? 'Historical projection' : 'Live edge'}</p></div><StatusMark status={projection.historical ? 'Historical' : projection.status} /></div>
    <div className="replay-controls"><IconButton title="回到首个投影" onClick={() => { setCursor(minCursor); onCursor(minCursor) }}><CirclePause size={18} /></IconButton><input type="range" min={minCursor} max={Math.max(maxCursor, minCursor)} value={Math.max(cursor, minCursor)} onChange={event => setCursor(Number(event.target.value))} onMouseUp={() => onCursor(cursor)} onTouchEnd={() => onCursor(cursor)} /><span>{cursor} / {maxCursor}</span><IconButton title="跟随最新" onClick={() => onCursor()}><Play size={18} /></IconButton></div>
    <MarketView projection={projection} />
  </section>
}

function ArchiveView({ run, onRefresh }: { run: Run; onRefresh: () => void }) {
  const [message, setMessage] = useState<string | null>(null)
  const input = useRef<HTMLInputElement>(null)
  const exportRun = async () => {
    const result = await api.exportArchive<{ path: string }>(run.run_id)
    setMessage(result.path)
    onRefresh()
  }
  const importRun = async (file?: File) => {
    if (!file) return
    const result = await api.importArchive<{ run_id: string }>(file)
    setMessage(`Imported ${result.run_id}`)
    onRefresh()
  }
  return <section className="archive-surface"><div className="archive-hero"><Archive size={32} /><div><h2>Sandbox Archive</h2><p>{run.name}</p></div></div>
    <div className="archive-actions"><button className="primary-button" onClick={exportRun}><Download size={17} />导出完整根树</button><button className="secondary-button" onClick={() => input.current?.click()}><Upload size={17} />导入并校验</button><input ref={input} hidden type="file" accept=".sandbox,application/zip" onChange={event => importRun(event.target.files?.[0])} /></div>
    <dl className="archive-facts"><div><dt>Runtime</dt><dd>{run.runtime_version}</dd></div><div><dt>Branches</dt><dd>{run.branches.length}</dd></div><div><dt>Run ID</dt><dd>{run.run_id}</dd></div></dl>
    {message ? <div className="archive-result"><Database size={17} />{message}</div> : null}
  </section>
}

export default function App() {
  const [view, setView] = useState<View>('market')
  const [runs, setRuns] = useState<Run[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [branchId, setBranchId] = useState<string | null>(null)
  const [projection, setProjection] = useState<Projection | null>(null)
  const [events, setEvents] = useState<EventEnvelope[]>([])
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const refreshRuns = useCallback(async (preferredRunId?: string, preferredBranchId?: string) => {
    const list = await api.listRuns<Run[]>()
    setRuns(list)
    const chosen = list.find(item => item.run_id === (preferredRunId ?? run?.run_id)) ?? list[0] ?? null
    setRun(chosen)
    if (chosen) {
      const branch = chosen.branches.find(item => item.branch_id === (preferredBranchId ?? branchId)) ?? chosen.branches.at(-1)
      setBranchId(branch?.branch_id ?? null)
    }
  }, [run?.run_id, branchId])

  const loadBranch = useCallback(async (id: string, cursor?: number) => {
    const [state, eventPage] = await Promise.all([
      api.state<Projection>(id, cursor),
      api.events<{ events: EventEnvelope[] }>(id),
    ])
    setProjection(state); setEvents(eventPage.events)
  }, [])

  useEffect(() => { refreshRuns().catch(reason => setError(reason.message)) }, [])
  useEffect(() => { if (branchId) loadBranch(branchId).catch(reason => setError(reason.message)) }, [branchId, loadBranch])
  useEffect(() => {
    if (!branchId || projection?.historical) return
    const source = new EventSource(`/api/v1/branches/${branchId}/stream?cursor=${projection?.cursor ?? 0}`)
    source.addEventListener('projection', event => {
      const body = JSON.parse((event as MessageEvent).data)
      setProjection(body.projection)
      api.events<{ events: EventEnvelope[] }>(branchId).then(page => setEvents(page.events))
    })
    return () => source.close()
  }, [branchId, projection?.historical])

  const onRun = (created: Run) => {
    setRun(created); setRuns(current => [created, ...current]); setBranchId(created.branches[0].branch_id); setView('market')
  }
  const command = async (type: string) => {
    if (!branchId || !run) return
    setBusy(true); setError(null)
    try { await api.command(branchId, type); await refreshRuns(run.run_id, branchId); await loadBranch(branchId) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '命令失败') }
    finally { setBusy(false) }
  }
  const checkpointId = useMemo(() => {
    const event = events.slice().reverse().find(item => item.event_type === 'CheckpointCreated')
    return event ? String(event.payload.checkpoint_id) : null
  }, [events])
  const firstProjectionCursor = useMemo(() => events.find(item => item.event_type === 'ObservationCreated')?.branch_seq ?? 1, [events])
  const fork = async () => {
    if (!branchId || !checkpointId || !run) return
    setBusy(true)
    try { const result = await api.fork<{ branch_id: string }>(branchId, checkpointId); await refreshRuns(run.run_id, result.branch_id); setBranchId(result.branch_id) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '分叉失败') }
    finally { setBusy(false) }
  }

  if (!run || !branchId || !projection) return <main className="onboarding-shell"><header className="onboarding-header"><div className="brand-mark">PM</div><div><strong>Parallel Market Sandbox</strong><span>Framework Alpha · v0.2</span></div></header><ScenarioBuilder onRun={onRun} />{error ? <div className="toast-error"><X size={17} />{error}</div> : null}</main>

  const activeBranch = run.branches.find(item => item.branch_id === branchId)
  return <div className="app-shell">
    <header className="topbar"><div className="brand"><div className="brand-mark">PM</div><div><strong>Parallel Market Sandbox</strong><span>Framework Alpha · v0.2</span></div></div><div className="run-context"><span>{run.name}</span><b>{shortId(branchId)}</b><StatusMark status={projection.status} /></div><div className="command-bar">
      {projection.status === 'Ready' || projection.status === 'Paused' ? <IconButton title="启动分支" onClick={() => command('start')} disabled={busy}><Play size={18} /></IconButton> : null}
      {projection.status === 'Running' ? <><IconButton title="暂停分支" onClick={() => command('pause')} disabled={busy}><Pause size={18} /></IconButton><button className="step-button" onClick={() => command('step_fixture')} disabled={busy}><StepForward size={17} />单步</button></> : null}
      {['Ready', 'Running', 'Paused', 'Completed'].includes(projection.status) ? <IconButton title="创建检查点" onClick={() => command('save')} disabled={busy}><Save size={18} /></IconButton> : null}
      <IconButton title="刷新投影" onClick={() => loadBranch(branchId)} disabled={busy}><RefreshCw size={18} /></IconButton>
    </div></header>
    <aside className="sidebar"><nav>{navItems.map(item => { const NavIcon = item.icon; return <button key={item.id} className={view === item.id ? 'selected' : ''} onClick={() => setView(item.id)}><NavIcon size={18} /><span>{item.label}</span></button> })}</nav><div className="sidebar-foot"><Boxes size={16} /><span>{run.branches.length} worlds</span><b>cursor {projection.cursor}</b></div></aside>
    <main className="workspace">
      {error ? <div className="workspace-error"><X size={16} />{error}<button onClick={() => setError(null)} aria-label="关闭错误"><X size={15} /></button></div> : null}
      {view === 'market' ? <MarketView projection={projection} /> : null}
      {view === 'timeline' ? <Timeline events={events} /> : null}
      {view === 'information' ? <InformationView items={projection.information} /> : null}
      {view === 'agents' ? <AgentView projection={projection} branchId={branchId} /> : null}
      {view === 'worlds' ? <WorldsView run={run} activeBranchId={branchId} onSelect={setBranchId} onFork={fork} checkpointId={checkpointId} /> : null}
      {view === 'replay' ? <ReplayView projection={projection} minCursor={firstProjectionCursor} maxCursor={activeBranch?.state_version ?? projection.cursor} onCursor={cursor => loadBranch(branchId, cursor)} /> : null}
      {view === 'scenario' ? <ScenarioBuilder onRun={onRun} /> : null}
      {view === 'archive' ? <ArchiveView run={run} onRefresh={() => refreshRuns(run.run_id, branchId)} /> : null}
    </main>
  </div>
}
