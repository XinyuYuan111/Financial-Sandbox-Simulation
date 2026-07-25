import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, Boxes, GitFork, Info, LayoutDashboard, Plus, Settings2, SlidersHorizontal, Users } from 'lucide-react'
import { api } from '../api'
import type { EventEnvelope, Projection, Run } from '../types'
import { ErrorBanner, shortId } from '../components/ui'
import { QuickStartPage } from '../features/quickstart/QuickStartPage'
import { AgentExplorer } from '../features/agents/AgentExplorer'
import { BranchExplorer } from '../features/branches/BranchExplorer'
import { EventExplorer } from '../features/run/EventExplorer'
import { InformationWorkspace, MarketWorkspace } from '../features/run/MarketWorkspace'
import { RunTopbar } from '../features/run/RunTopbar'
import { InterventionWorkspace } from '../features/interventions/InterventionWorkspace'

type View = 'market' | 'agents' | 'events' | 'information' | 'interventions' | 'branches' | 'scenario'

const navigation: Array<{ id: View; label: string; icon: typeof Activity; group: 'run' | 'manage' }> = [
  { id: 'market', label: '市场工作台', icon: LayoutDashboard, group: 'run' },
  { id: 'agents', label: 'Agent 审计', icon: Users, group: 'run' },
  { id: 'events', label: '事件浏览器', icon: Activity, group: 'run' },
  { id: 'information', label: '信息流', icon: Info, group: 'run' },
  { id: 'interventions', label: '情景干预', icon: SlidersHorizontal, group: 'run' },
  { id: 'branches', label: '分支与归档', icon: GitFork, group: 'manage' },
  { id: 'scenario', label: '新建场景', icon: Settings2, group: 'manage' },
]

export function AppShell() {
  const [runs, setRuns] = useState<Run[]>([])
  const [run, setRun] = useState<Run | null>(null)
  const [branchId, setBranchId] = useState('')
  const [projection, setProjection] = useState<Projection | null>(null)
  const [events, setEvents] = useState<EventEnvelope[]>([])
  const [view, setView] = useState<View>('market')
  const [checkpointId, setCheckpointId] = useState<string | null>(null)
  const [historicalCursor, setHistoricalCursor] = useState<number | null>(null)
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const activeBranch = useMemo(() => run?.branches.find(branch => branch.branch_id === branchId) ?? null, [branchId, run])
  const activeLlmProvider = projection?.planning?.provider ?? null

  const loadBranch = useCallback(async (targetRun: Run, targetBranchId: string, cursor?: number) => {
    setBusy(true); setError(null)
    try {
      const [nextProjection, eventResponse] = await Promise.all([
        api.state<Projection>(targetBranchId, cursor),
        api.events<{ events: EventEnvelope[] }>(targetBranchId),
      ])
      const branch = targetRun.branches.find(item => item.branch_id === targetBranchId)
      const historical = cursor !== undefined && branch !== undefined && cursor < branch.state_version
      setHistoricalCursor(historical ? cursor : null)
      setRun(targetRun); setBranchId(targetBranchId); setProjection(nextProjection)
      setEvents(historical ? eventResponse.events.filter(event => event.branch_seq <= cursor) : eventResponse.events)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '运行数据加载失败') }
    finally { setBusy(false) }
  }, [])

  const refresh = useCallback(async () => {
    if (!run || !branchId || historicalCursor !== null) return
    setBusy(true)
    try {
      const fresh = await api.getRun<Run>(run.run_id)
      setRuns(current => current.map(item => item.run_id === fresh.run_id ? fresh : item))
      await loadBranch(fresh, branchId)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '刷新失败'); setBusy(false) }
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
    }).catch(reason => { if (active) { setError(reason instanceof Error ? reason.message : '服务连接失败'); setBusy(false) } })
    return () => { active = false }
  }, [loadBranch])

  useEffect(() => {
    if (!activeBranch || activeBranch.status !== 'Running' || historicalCursor !== null) return
    const timer = window.setInterval(() => { void refresh() }, 3000)
    return () => window.clearInterval(timer)
  }, [activeBranch, historicalCursor, refresh])

  const acceptRun = async (created: Run) => {
    const branch = created.branches[0]
    setRuns(current => [created, ...current.filter(item => item.run_id !== created.run_id)])
    setView('market'); setCheckpointId(null)
    if (branch) await loadBranch(created, branch.branch_id)
  }

  const command = async (commandType: 'start' | 'pause' | 'stop' | 'step_fixture' | 'run_for' | 'save') => {
    if (!branchId || historicalCursor !== null) return
    setBusy(true); setError(null)
    try {
      const result = await api.command<Record<string, unknown>>(branchId, commandType, commandType === 'run_for' ? { max_requests: 1 } : {})
      if (typeof result.checkpoint_id === 'string') setCheckpointId(result.checkpoint_id)
      const fresh = await api.getRun<Run>(run!.run_id)
      setRuns(current => current.map(item => item.run_id === fresh.run_id ? fresh : item))
      await loadBranch(fresh, branchId)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '命令执行失败'); setBusy(false) }
  }

  const selectRun = async (runId: string) => {
    const selected = runs.find(item => item.run_id === runId)
    const branch = selected?.branches[0]
    if (selected && branch) { setCheckpointId(null); setView('market'); await loadBranch(selected, branch.branch_id) }
  }

  const fork = async () => {
    if (!checkpointId || !run) return
    setBusy(true); setError(null)
    try {
      const result = await api.fork<{ branch_id: string }>(branchId, checkpointId)
      const fresh = await api.getRun<Run>(run.run_id)
      setRuns(current => current.map(item => item.run_id === fresh.run_id ? fresh : item))
      setCheckpointId(null)
      await loadBranch(fresh, result.branch_id)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '分叉失败'); setBusy(false) }
  }

  const exportArchive = async () => {
    if (!run) return
    setBusy(true); setError(null)
    try { await api.exportArchive(run.run_id); window.location.assign(`/api/v1/archives/${run.run_id}/download`) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '归档导出失败') }
    finally { setBusy(false) }
  }

  const importArchive = async (file: File) => {
    setBusy(true); setError(null)
    try {
      await api.importArchive(file)
      const list = await api.listRuns<Run[]>()
      setRuns(list)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '归档导入失败') }
    finally { setBusy(false) }
  }

  if (!run || !projection || !activeBranch) {
    return <main className="entry-screen">{error ? <ErrorBanner message={error} onClose={() => setError(null)} /> : null}{busy ? <div className="app-loading">正在连接本地运行时...</div> : <QuickStartPage onRun={acceptRun} />}</main>
  }

  return <div className="app-shell">
    <RunTopbar run={run} branch={historicalCursor === null ? activeBranch : { ...activeBranch, status: 'Historical' }} simTimeUs={projection.sim_time_us} cursor={projection.cursor} agents={projection.agents} planning={projection.planning} busy={busy} onCommand={command} onRefresh={refresh} />
    <aside className="app-sidebar"><nav>{(['run', 'manage'] as const).map(group => <div className="nav-group" key={group}><span>{group === 'run' ? '运行' : '管理'}</span>{navigation.filter(item => item.group === group).map(item => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? 'selected' : ''} onClick={() => setView(item.id)}><Icon size={17} /><b>{item.label}</b></button> })}</div>)}</nav><div className="run-switcher"><label>当前实验<select value={run.run_id} onChange={event => { void selectRun(event.target.value) }}>{runs.map(item => <option value={item.run_id} key={item.run_id}>{item.name}</option>)}</select></label><span><Boxes size={14} />{run.branches.length} branches</span><small>{shortId(run.run_id)}</small></div></aside>
    <main className="app-workspace">{error ? <ErrorBanner message={error} onClose={() => setError(null)} /> : null}{busy ? <div className="loading-bar" /> : null}
      {view === 'market' ? <MarketWorkspace projection={projection} /> : null}
      {view === 'agents' ? <AgentExplorer branchId={branchId} cursor={historicalCursor ?? undefined} /> : null}
      {view === 'events' ? <EventExplorer events={events} /> : null}
      {view === 'information' ? <InformationWorkspace projection={projection} /> : null}
      {view === 'interventions' ? <InterventionWorkspace branchId={branchId} branchStatus={historicalCursor === null ? activeBranch.status : 'Historical'} simTimeUs={projection.sim_time_us} provider={activeLlmProvider} onChanged={refresh} /> : null}
      {view === 'branches' ? <BranchExplorer run={run} activeBranchId={branchId} projection={projection} checkpointId={checkpointId} onSelect={next => { void loadBranch(run, next) }} onFork={fork} onReplay={cursor => { void loadBranch(run, branchId, cursor) }} onExport={exportArchive} onImport={importArchive} /> : null}
      {view === 'scenario' ? <QuickStartPage embedded onRun={acceptRun} /> : null}
    </main>
    <button className="mobile-create" title="新建场景" aria-label="新建场景" onClick={() => setView('scenario')}><Plus size={19} /></button>
  </div>
}
