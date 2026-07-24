import { CirclePause, CirclePlay, RefreshCw, Save, Square, StepForward, TimerReset } from 'lucide-react'
import type { AgentProjection, Branch, Run } from '../../types'
import { formatTime, IconButton, shortId, StatusBadge } from '../../components/ui'

export function RunTopbar({ run, branch, simTimeUs, cursor, agents, busy, onCommand, onRefresh }: {
  run: Run
  branch: Branch
  simTimeUs: number
  cursor: number
  agents: AgentProjection[]
  busy: boolean
  onCommand: (command: 'start' | 'pause' | 'stop' | 'step_fixture' | 'run_for' | 'save') => void
  onRefresh: () => void
}) {
  const pending = agents.filter(agent => agent.planning_request_id).length
  const running = branch.status === 'Running'
  const hasLivePlanner = agents.some(agent => agent.planner_profile_id?.startsWith('openai'))
  return <header className="run-topbar"><div className="run-identity"><span className="brand-mark">FS</span><div><strong>{run.name}</strong><small>{shortId(branch.branch_id)} · {run.runtime_version}</small></div></div><div className="run-telemetry"><StatusBadge status={branch.status} /><span><b>{formatTime(simTimeUs)}</b> sim</span><span><b>{cursor}</b> cursor</span><span><b>{pending}</b> planning</span></div><div className="run-controls">{running ? <IconButton title="暂停" onClick={() => onCommand('pause')} disabled={busy}><CirclePause size={18} /></IconButton> : <IconButton title="运行" onClick={() => onCommand('start')} disabled={busy || !['Ready', 'Paused', 'Checkpointed'].includes(branch.status)}><CirclePlay size={18} /></IconButton>}<IconButton title="停止运行" onClick={() => onCommand('stop')} disabled={busy || !['Running', 'Paused', 'Ready', 'Checkpointed'].includes(branch.status)}><Square size={17} /></IconButton><IconButton title="执行 Fixture 步进" onClick={() => onCommand('step_fixture')} disabled={busy || !running}><StepForward size={18} /></IconButton><IconButton title="处理一个规划请求" onClick={() => onCommand('run_for')} disabled={busy || !running || !hasLivePlanner}><TimerReset size={18} /></IconButton><IconButton title="创建检查点" onClick={() => onCommand('save')} disabled={busy || !['Running', 'Paused', 'Ready', 'Completed'].includes(branch.status)}><Save size={18} /></IconButton><IconButton title="刷新" onClick={onRefresh} disabled={busy}><RefreshCw size={18} /></IconButton></div></header>
}
