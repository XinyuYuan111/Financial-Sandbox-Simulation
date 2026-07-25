import { CirclePause, CirclePlay, RefreshCw, Save, Square, StepForward, TimerReset } from 'lucide-react'
import type { AgentProjection, Branch, Run } from '../../types'
import { formatTime, IconButton, shortId, StatusBadge } from '../../components/ui'

export function RunTopbar({ run, branch, simTimeUs, cursor, agents, planning, busy, onCommand, onRefresh }: {
  run: Run
  branch: Branch
  simTimeUs: number
  cursor: number
  agents: AgentProjection[]
  planning?: { total: number; pending: number; applied: number; failed: number; active_plans: number; last_failure_code: string | null; last_failure_message: string | null }
  busy: boolean
  onCommand: (command: 'start' | 'pause' | 'stop' | 'step_fixture' | 'run_for' | 'save') => void
  onRefresh: () => void
}) {
  const pending = planning?.pending ?? agents.filter(agent => agent.planning_request_id).length
  const failed = planning?.failed ?? 0
  const running = branch.status === 'Running'
  const hasLivePlanner = agents.some(agent => agent.planner_profile_id && !/^(rule|replay)\./.test(agent.planner_profile_id))
  const failureTitle = planning?.last_failure_code
    ? `最近失败: ${planning.last_failure_code}${planning.last_failure_message ? ` · ${planning.last_failure_message}` : ''}`
    : undefined
  return <header className="run-topbar glass-topbar"><div className="run-identity"><span className="brand-mark">FS</span><div><strong>{run.name}</strong><small>{shortId(branch.branch_id)} · {run.runtime_version}</small></div></div><div className="run-telemetry"><StatusBadge status={branch.status} /><span><b>{formatTime(simTimeUs)}</b> sim</span><span><b>{cursor}</b> cursor</span><span className={failed ? 'telemetry-warning' : ''} title={failureTitle}><b>{pending}</b> planning{failed ? ` · ${failed} failed` : ''}</span></div><div className="run-controls">{running ? <IconButton title="暂停" onClick={() => onCommand('pause')} disabled={busy}><CirclePause size={18} /></IconButton> : <IconButton title="运行" onClick={() => onCommand('start')} disabled={busy || !['Ready', 'Paused', 'Checkpointed'].includes(branch.status)}><CirclePlay size={18} /></IconButton>}<IconButton title="停止运行" onClick={() => onCommand('stop')} disabled={busy || !['Running', 'Paused', 'Ready', 'Checkpointed'].includes(branch.status)}><Square size={17} /></IconButton><IconButton title="执行 Fixture 步进" onClick={() => onCommand('step_fixture')} disabled={busy || !running}><StepForward size={18} /></IconButton><IconButton title="处理一个规划请求" onClick={() => onCommand('run_for')} disabled={busy || !running || !hasLivePlanner}><TimerReset size={18} /></IconButton><IconButton title="创建检查点" onClick={() => onCommand('save')} disabled={busy || !['Running', 'Paused', 'Ready', 'Completed'].includes(branch.status)}><Save size={18} /></IconButton><IconButton title="刷新" onClick={onRefresh} disabled={busy}><RefreshCw size={18} /></IconButton></div></header>
}
