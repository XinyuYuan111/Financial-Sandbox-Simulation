import { Archive, GitFork, History, Upload } from 'lucide-react'
import type { Projection, Run } from '../../types'
import { EmptyState, formatTime, shortId, StatusBadge } from '../../components/ui'

export function BranchExplorer({ run, activeBranchId, projection, checkpointId, onSelect, onFork, onReplay, onExport, onImport }: {
  run: Run
  activeBranchId: string
  projection: Projection
  checkpointId: string | null
  onSelect: (branchId: string) => void
  onFork: () => void
  onReplay: (cursor: number) => void
  onExport: () => void
  onImport: (file: File) => void
}) {
  const activeBranch = run.branches.find(branch => branch.branch_id === activeBranchId)
  return <div className="branch-workspace">
    <section className="workspace-panel full-panel"><div className="panel-heading"><div><h2>平行世界</h2><p>{run.branches.length} 个分支</p></div><GitFork size={18} /></div><div className="table-scroll"><table><thead><tr><th>分支</th><th>状态</th><th>模拟时间</th><th>游标</th><th>父分支</th><th /></tr></thead><tbody>{run.branches.map(branch => <tr key={branch.branch_id} className={branch.branch_id === activeBranchId ? 'active-row' : ''}><td><strong>{shortId(branch.branch_id)}</strong></td><td><StatusBadge status={branch.status} /></td><td>{formatTime(branch.sim_time_us)}</td><td>{branch.state_version}</td><td>{shortId(branch.parent_branch_id)}</td><td><button className="text-button" onClick={() => onSelect(branch.branch_id)}>打开</button></td></tr>)}</tbody></table></div></section>
    <section className="workspace-panel replay-panel"><div className="panel-heading"><div><h2>历史投影</h2><p>当前 cursor {projection.cursor}</p></div><History size={18} /></div>{activeBranch ? <><input className="replay-slider" type="range" min={1} max={Math.max(1, activeBranch.state_version)} value={Math.min(projection.cursor, Math.max(1, activeBranch.state_version))} onChange={event => onReplay(Number(event.target.value))} /><div className="replay-scale"><span>1</span><b>{projection.cursor}</b><span>{activeBranch.state_version}</span></div></> : <EmptyState title="没有活动分支" />}<button className="secondary-button" onClick={onFork} disabled={!checkpointId}><GitFork size={16} />从检查点分叉</button></section>
    <section className="workspace-panel archive-panel"><div className="panel-heading"><div><h2>运行归档</h2><p>.sandbox 可验证归档</p></div><Archive size={18} /></div><button className="secondary-button wide" onClick={onExport}><Archive size={16} />导出归档</button><label className="secondary-button wide file-button"><Upload size={16} />导入归档<input type="file" accept=".sandbox,.zip" onChange={event => { const file = event.target.files?.[0]; if (file) onImport(file) }} /></label></section>
  </div>
}
