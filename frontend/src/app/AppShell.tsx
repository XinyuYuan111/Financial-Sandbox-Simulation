import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive,
  BookOpenText,
  Boxes,
  CirclePause,
  CirclePlay,
  GitFork,
  PanelRightOpen,
  RefreshCw,
  Save,
  Settings2,
  Square,
  StepForward,
  TimerReset,
  Users,
} from 'lucide-react'
import { api } from '../api'
import type { EventEnvelope, Projection, Run } from '../types'
import { ErrorBanner, formatInteger, formatTime, IconButton, shortId, StatusBadge } from '../components/ui'
import { QuickStartPage } from '../features/quickstart/QuickStartPage'
import { AgentExplorer } from '../features/agents/AgentExplorer'
import { BranchExplorer } from '../features/branches/BranchExplorer'
import { EventExplorer } from '../features/run/EventExplorer'
import { InformationWorkspace, MarketWorkspace } from '../features/run/MarketWorkspace'
import { InterventionWorkspace } from '../features/interventions/InterventionWorkspace'
import { ControlRail, ObservationRail, WorkspaceOverlay } from './TheatreWorkspace'
import { SimulationStage } from '../features/stage/SimulationStage'

type WorkspaceView = 'market' | 'agents' | 'events' | 'information' | 'interventions' | 'branches' | 'scenario'
type InformationDraft = { key: string; intent: string; content: string; channel: 'PublicFeed' | 'OfficialAnnouncement' | 'TradingTerminal' | 'PrivateChannel'; targetIds: string }

export function AppShell() {
  const [runs, setRuns] = useState<Run[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [branchId, setBranchId] = useState('')
  const [projection, setProjection] = useState<Projection | null>(null)
  const [events, setEvents] = useState<EventEnvelope[]>([])
  const [workspace, setWorkspace] = useState<WorkspaceView | null>(null)
  const [focusedAgentId, setFocusedAgentId] = useState<string | null>(null)
  const [informationDraft, setInformationDraft] = useState<InformationDraft | null>(null)
  const [checkpointId, setCheckpointId] = useState<string | null>(null)
  const [historicalCursor, setHistoricalCursor] = useState<number | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const previousPrice = useRef<number | null>(null)
  const [priceTone, setPriceTone] = useState('')

  const activeBranch = useMemo(() => run?.branches.find(branch => branch.branch_id === branchId) ?? null, [branchId, run])
  const activeLlmProvider = projection?.planning?.provider ?? null

  const loadBranch = useCallback(async (targetRun: Run, targetBranchId: string, cursor?: number) => {
    setBusy(true)
    setError(null)
    try {
      const [nextProjection, eventResponse] = await Promise.all([
        api.state<Projection>(targetBranchId, cursor),
        api.events<{ events: EventEnvelope[] }>(targetBranchId),
      ])
      const branch = targetRun.branches.find(item => item.branch_id === targetBranchId)
      const historical = cursor !== undefined && branch !== undefined && cursor < branch.state_version
      setHistoricalCursor(historical ? cursor : null)
      previousPrice.current = null
      setPriceTone('')
      setRun(targetRun)
      setBranchId(targetBranchId)
      setProjection(nextProjection)
      setEvents(historical ? eventResponse.events.filter(event => event.branch_seq <= cursor) : eventResponse.events)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '运行数据加载失败')
    } finally {
      setBusy(false)
    }
  }, [])

  const refresh = useCallback(async () => {
    if (!run || !branchId || historicalCursor !== null) return
    setBusy(true)
    try {
      const fresh = await api.getRun<Run>(run.run_id)
      setRuns(current => current.map(item => item.run_id === fresh.run_id ? fresh : item))
      await loadBranch(fresh, branchId)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '刷新失败')
      setBusy(false)
    }
  }, [branchId, historicalCursor, loadBranch, run])

  useEffect(() => {
    let active = true
    api.listRuns<Run[]>().then(async list => {
      if (!active) return
      setRuns(list)
      const first = list[0]
      const branch = first?.branches[0]
      if (first && branch) await loadBranch(first, branch.branch_id)
      else setBusy(false)
    }).catch(reason => {
      if (active) {
        setError(reason instanceof Error ? reason.message : '服务连接失败')
        setBusy(false)
      }
    })
    return () => { active = false }
  }, [loadBranch])

  useEffect(() => {
    if (!activeBranch || activeBranch.status !== 'Running' || historicalCursor !== null) return
    const timer = window.setInterval(() => { void refresh() }, 3000)
    return () => window.clearInterval(timer)
  }, [activeBranch, historicalCursor, refresh])

  useEffect(() => {
    if (!workspace) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setWorkspace(null)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [workspace])

  useEffect(() => {
    if (!workspace && informationDraft) setInformationDraft(null)
  }, [informationDraft, workspace])

  useEffect(() => {
    const price = projection?.market.last_trade?.price
    if (price == null) return
    if (previousPrice.current != null && price !== previousPrice.current) {
      setPriceTone(price > previousPrice.current ? 'metric-price-up' : 'metric-price-down')
    }
    previousPrice.current = price
  }, [projection])

  const acceptRun = async (created: Run) => {
    const branch = created.branches[0]
    setRuns(current => [created, ...current.filter(item => item.run_id !== created.run_id)])
    setWorkspace(null)
    setCheckpointId(null)
    if (branch) await loadBranch(created, branch.branch_id)
  }

  const command = async (commandType: 'start' | 'pause' | 'stop' | 'step_fixture' | 'run_for' | 'save') => {
    if (!branchId || historicalCursor !== null) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.command<Record<string, unknown>>(branchId, commandType, commandType === 'run_for' ? { max_requests: 1 } : {})
      if (typeof result.checkpoint_id === 'string') setCheckpointId(result.checkpoint_id)
      const fresh = await api.getRun<Run>(run!.run_id)
      setRuns(current => current.map(item => item.run_id === fresh.run_id ? fresh : item))
      await loadBranch(fresh, branchId)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '命令执行失败')
      setBusy(false)
    }
  }

  const selectRun = async (runId: string) => {
    const selected = runs.find(item => item.run_id === runId)
    const branch = selected?.branches[0]
    if (selected && branch) {
      setCheckpointId(null)
      setWorkspace(null)
      await loadBranch(selected, branch.branch_id)
    }
  }

  const fork = async () => {
    if (!checkpointId || !run) return
    setBusy(true)
    setError(null)
    try {
      const result = await api.fork<{ branch_id: string }>(branchId, checkpointId)
      const fresh = await api.getRun<Run>(run.run_id)
      setRuns(current => current.map(item => item.run_id === fresh.run_id ? fresh : item))
      setCheckpointId(null)
      await loadBranch(fresh, result.branch_id)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '分叉失败')
      setBusy(false)
    }
  }

  const exportArchive = async () => {
    if (!run) return
    setBusy(true)
    setError(null)
    try {
      await api.exportArchive(run.run_id)
      window.location.assign(`/api/v1/archives/${run.run_id}/download`)
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '归档导出失败')
    } finally {
      setBusy(false)
    }
  }

  const importArchive = async (file: File) => {
    setBusy(true)
    setError(null)
    try {
      await api.importArchive(file)
      setRuns(await api.listRuns<Run[]>())
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '归档导入失败')
    } finally {
      setBusy(false)
    }
  }

  if (!run || !projection || !activeBranch) {
    return <main className="entry-screen">
      <div className="entry-brand"><strong>EPOCH ONE</strong><span>金融平行市场沙盒</span></div>
      {error ? <ErrorBanner message={error} onClose={() => setError(null)} /> : null}
      {busy ? <div className="app-loading"><span />正在连接本地运行时</div> : <QuickStartPage onRun={acceptRun} />}
    </main>
  }

  const branchStatus = historicalCursor === null ? activeBranch.status : 'Historical'
  const running = branchStatus === 'Running'
  const hasLivePlanner = projection.agents.some(agent => agent.planner_profile_id && !/^(rule|replay)\./.test(agent.planner_profile_id))
  const pending = projection.planning?.pending ?? projection.agents.filter(agent => agent.planning_request_id).length
  const activePlans = projection.planning?.active_plans ?? projection.agents.filter(agent => (agent.active_strategy_revision ?? 0) > 0).length
  const failedPlans = projection.planning?.failed ?? 0
  const planningFailure = projection.planning?.last_failure_code
    ? `${projection.planning.last_failure_code}${projection.planning.last_failure_message ? ` · ${projection.planning.last_failure_message}` : ''}`
    : undefined
  const lastTrade = projection.market.last_trade
  const bestBid = projection.market.bids[0]?.price
  const bestAsk = projection.market.asks[0]?.price
  const volume = projection.market.trades.reduce((sum, trade) => sum + trade.quantity, 0)
  const spread = bestBid != null && bestAsk != null ? bestAsk - bestBid : null
  const spreadBps = spread !== null && bestBid != null && bestAsk != null && (bestBid + bestAsk) > 0
    ? spread * 20_000 / (bestBid + bestAsk)
    : null
  const openWorkspace = (next: WorkspaceView) => setWorkspace(next)

  const prepareInformation = (draft: Omit<InformationDraft, 'key'>) => {
    setInformationDraft({ ...draft, key: crypto.randomUUID() })
    setWorkspace('interventions')
  }

  return <div className="epoch-shell">
    <header className="epoch-topbar">
      <div className="epoch-brand"><strong>EPOCH ONE</strong><span>{run.name}</span></div>
      <div className="epoch-metrics" aria-label="市场实时指标">
        <span>最新成交 <b className={priceTone}>{lastTrade?.price ?? '--'}</b></span>
        <span>最优买卖 <b className="metric-bid">{bestBid ?? '--'}</b> / <b className="metric-ask">{bestAsk ?? '--'}</b></span>
        <span>累计成交 <b>{formatInteger(volume)}</b></span>
        {spreadBps !== null ? <span>价差 <b className="metric-spread">{spreadBps.toFixed(1)}</b> bps</span> : null}
      </div>
      <div className="epoch-status">
        <span className={`epoch-mode ${running ? 'live' : ''}`}><i />{running ? 'LIVE' : historicalCursor !== null ? '历史投影' : projection.market_status === 'halted' ? '停牌' : '待机'}</span>
        <StatusBadge status={branchStatus} />
        <span>{formatTime(projection.sim_time_us)}</span>
        <span>CURSOR {projection.cursor}</span>
        <span>AGENTS {projection.agents.length}</span>
        <span>PLANS {activePlans}</span>
        <span className={failedPlans ? 'status-warning' : ''} title={planningFailure}>PENDING {pending}{failedPlans ? ` / FAILED ${failedPlans}` : ''}</span>
      </div>
      <div className="epoch-controls">
        <label className="run-select" title="切换实验"><Boxes size={15} /><select aria-label="当前实验" value={run.run_id} onChange={event => { void selectRun(event.target.value) }}>{runs.map(item => <option value={item.run_id} key={item.run_id}>{item.name}</option>)}</select></label>
        <IconButton title="订单簿与成交" onClick={() => openWorkspace('market')}><PanelRightOpen size={17} /></IconButton>
        <IconButton title="Agent 审计" onClick={() => openWorkspace('agents')}><Users size={17} /></IconButton>
        <IconButton title="平行世界与归档" onClick={() => openWorkspace('branches')}><GitFork size={17} /></IconButton>
        <IconButton title="新建场景" onClick={() => openWorkspace('scenario')}><Settings2 size={17} /></IconButton>
        <span className="control-divider" />
        {running
          ? <IconButton title="暂停" onClick={() => void command('pause')} disabled={busy}><CirclePause size={18} /></IconButton>
          : <IconButton title="运行" onClick={() => void command('start')} disabled={busy || !['Ready', 'Paused', 'Checkpointed'].includes(branchStatus)}><CirclePlay size={18} /></IconButton>}
        <IconButton title="停止运行" onClick={() => void command('stop')} disabled={busy || !['Running', 'Paused', 'Ready', 'Checkpointed'].includes(branchStatus)}><Square size={16} /></IconButton>
        <IconButton title="执行 Fixture 步进" onClick={() => void command('step_fixture')} disabled={busy || !running}><StepForward size={18} /></IconButton>
        <IconButton title="处理一个规划请求" onClick={() => void command('run_for')} disabled={busy || !running || !hasLivePlanner}><TimerReset size={18} /></IconButton>
        <IconButton title="创建检查点" onClick={() => void command('save')} disabled={busy || !['Running', 'Paused', 'Ready', 'Completed'].includes(branchStatus)}><Save size={17} /></IconButton>
        <IconButton title="刷新" onClick={() => void refresh()} disabled={busy || historicalCursor !== null}><RefreshCw size={17} /></IconButton>
      </div>
    </header>

    <main className="epoch-main">
      <ControlRail
        projection={projection}
        branchStatus={branchStatus}
        onPrepareInformation={prepareInformation}
        onOpenInformation={() => openWorkspace('information')}
        onOpenInterventions={() => { setInformationDraft(null); openWorkspace('interventions') }}
        onOpenAgent={agentId => { setFocusedAgentId(agentId); openWorkspace('agents') }}
      />
      <SimulationStage
        projection={projection}
        events={events}
        branchStatus={branchStatus}
        onOpenAgent={agentId => { setFocusedAgentId(agentId); openWorkspace('agents') }}
        onOpenMarket={() => openWorkspace('market')}
        onStart={() => void command('start')}
      />
      <ObservationRail
        events={events}
        run={run}
        projection={projection}
        onOpenEvents={() => openWorkspace('events')}
        onOpenBranches={() => openWorkspace('branches')}
      />
    </main>

    {busy ? <div className="loading-bar" /> : null}
    {error ? <div className="shell-error"><ErrorBanner message={error} onClose={() => setError(null)} /></div> : null}

    {workspace ? <WorkspaceOverlay title={workspaceTitle(workspace)} side={workspace === 'agents' ? 'left' : workspace === 'interventions' ? 'bottom' : 'right'} onClose={() => setWorkspace(null)}>
      {workspace === 'market' ? <MarketWorkspace projection={projection} /> : null}
      {workspace === 'agents' ? <AgentExplorer key={`${branchId}:${focusedAgentId ?? ''}:${historicalCursor ?? 'live'}`} branchId={branchId} cursor={historicalCursor ?? undefined} initialAgentId={focusedAgentId ?? undefined} /> : null}
      {workspace === 'events' ? <EventExplorer events={events} /> : null}
      {workspace === 'information' ? <InformationWorkspace projection={projection} /> : null}
      {workspace === 'interventions' ? <InterventionWorkspace key={`${branchId}:${informationDraft?.key ?? 'default'}`} branchId={branchId} branchStatus={branchStatus} simTimeUs={projection.sim_time_us} provider={activeLlmProvider} onChanged={refresh} initialInformation={informationDraft ?? undefined} /> : null}
      {workspace === 'branches' ? <BranchExplorer run={run} activeBranchId={branchId} projection={projection} checkpointId={checkpointId} onSelect={next => { void loadBranch(run, next) }} onFork={fork} onReplay={cursor => { void loadBranch(run, branchId, cursor) }} onExport={exportArchive} onImport={importArchive} /> : null}
      {workspace === 'scenario' ? <QuickStartPage embedded onRun={acceptRun} /> : null}
    </WorkspaceOverlay> : null}

    <nav className="mobile-command-bar" aria-label="移动端工作区">
      <button onClick={() => openWorkspace('market')}><BookOpenText size={18} /><span>市场</span></button>
      <button onClick={() => openWorkspace('agents')}><Users size={18} /><span>Agent</span></button>
      <button onClick={() => openWorkspace('events')}><Archive size={18} /><span>事件</span></button>
      <button onClick={() => openWorkspace('branches')}><GitFork size={18} /><span>分支</span></button>
      <button onClick={() => openWorkspace('scenario')}><Settings2 size={18} /><span>场景</span></button>
    </nav>
  </div>
}

function workspaceTitle(view: WorkspaceView): string {
  return {
    market: '订单簿与市场微观结构',
    agents: 'Agent 审计',
    events: '事件浏览器',
    information: '信息传播链',
    interventions: '情景干预工作舱',
    branches: '平行世界与归档',
    scenario: '新建场景',
  }[view]
}
