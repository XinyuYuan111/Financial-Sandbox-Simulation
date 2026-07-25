import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, ArrowRight, Boxes, CheckCircle2, ExternalLink, FileKey, FileOutput, GitBranch, Hash, PlayCircle, RefreshCw, Save, ShieldCheck, Users, XCircle } from 'lucide-react'
import { api } from '../../api'
import { ErrorBanner, EmptyState, formatInteger, formatTime, shortId, StatusBadge } from '../../components/ui'
import type { AttestedCheckpoint, AttestedRun, Run } from '../../types'

type Filter = 'all' | 'confirmed' | 'pending' | 'failed' | 'not_submitted'
type ScopeKind = 'checkpoints' | 'runs'

const statusTone: Record<AttestedCheckpoint['attestation']['status'], 'positive' | 'warning' | 'negative' | 'neutral'> = {
  confirmed: 'positive',
  pending: 'warning',
  failed: 'negative',
  not_submitted: 'neutral',
}

const txExplorerUrl = (txHash: string | null) => {
  if (!txHash) return null
  return `https://explorer.testnet.injective.network/tx/${txHash}`
}

export function CheckpointAnchorPage({
  run,
  runs,
  onSwitchRun,
  onResume,
  onExportArchive,
}: {
  run: Run | null
  runs: Run[]
  onSwitchRun: (runId: string) => void
  onResume: (branchId: string) => void
  onExportArchive: () => void
}) {
  const [kind, setKind] = useState<ScopeKind>('runs')
  const [checkpoints, setCheckpoints] = useState<AttestedCheckpoint[]>([])
  const [attestedRuns, setAttestedRuns] = useState<AttestedRun[]>([])
  const [busy, setBusy] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')
  const [resumingId, setResumingId] = useState<string | null>(null)
  const [attestingRunId, setAttestingRunId] = useState<string | null>(null)
  const [resumeError, setResumeError] = useState<string | null>(null)
  const [scope, setScope] = useState<'current' | 'all'>('current')
  const [notice, setNotice] = useState<string | null>(null)

  const loadAll = useCallback(async () => {
    setBusy(true); setError(null)
    try {
      const [cps, ars] = await Promise.all([
        api.listCheckpoints<AttestedCheckpoint[]>(
          scope === 'current' && run ? run.run_id : undefined,
        ),
        api.listAttestedRuns<AttestedRun[]>(),
      ])
      setCheckpoints(cps)
      setAttestedRuns(ars)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '数据加载失败') }
    finally { setBusy(false) }
  }, [run, scope])

  useEffect(() => { void loadAll() }, [loadAll])

  useEffect(() => {
    const hasPending = kind === 'checkpoints'
      ? checkpoints.some(cp => cp.attestation.status === 'pending')
      : attestedRuns.some(ar => ar.attestation.status === 'pending')
    if (hasPending) {
      const timer = window.setInterval(() => { void loadAll() }, 4000)
      return () => window.clearInterval(timer)
    }
  }, [kind, checkpoints, attestedRuns, loadAll])

  const summary = useMemo(() => {
    const list = kind === 'runs' ? attestedRuns : checkpoints
    const total = list.length
    const confirmed = list.filter(x => x.attestation.status === 'confirmed').length
    const pending = list.filter(x => x.attestation.status === 'pending').length
    const failed = list.filter(x => x.attestation.status === 'failed').length
    return { total, confirmed, pending, failed }
  }, [kind, checkpoints, attestedRuns])

  const filtered = useMemo(() => {
    const list = kind === 'runs' ? attestedRuns : checkpoints
    return filter === 'all' ? list : list.filter(x => x.attestation.status === filter)
  }, [kind, filter, checkpoints, attestedRuns])

  const resume = async (checkpoint: AttestedCheckpoint, verifyChain: boolean) => {
    setResumingId(checkpoint.checkpoint_id); setResumeError(null)
    try {
      const result = await api.resumeFromCheckpoint<{ branch_id: string; checkpoint_hash: string }>(
        checkpoint.checkpoint_id,
        verifyChain,
      )
      onResume(result.branch_id)
    } catch (reason) { setResumeError(reason instanceof Error ? reason.message : '续跑失败') }
    finally { setResumingId(null) }
  }

  const attestNow = async (runId: string) => {
    setAttestingRunId(runId); setNotice(null); setError(null)
    try {
      const result = await api.attestRun<{ queued: boolean }>(runId)
      if (result.queued) {
        setNotice('实验已入队，正在上链…几秒后状态会刷新')
        await loadAll()
      }
    } catch (reason) { setError(reason instanceof Error ? reason.message : '上链入队失败，请检查链上 writer 是否已配置') }
    finally { setAttestingRunId(null) }
  }

  return <div className="checkpoint-workspace glass-card">
    <section className="workspace-panel full-panel">
      <div className="panel-heading">
        <div>
          <h2>存档锚定</h2>
          <p>
            「市场实验」(Run) 和 「存档」(Checkpoint) 都会将 SHA256 哈希异步锚定到 Injective 链上。
          </p>
        </div>
        <FileKey size={22} />
      </div>

      <div className="anchor-toolbar">
        <div className="scope-switch kind-switch">
          <button className={kind === 'runs' ? 'selected' : ''} onClick={() => setKind('runs')}>
            <GitBranch size={13} /> 市场实验
          </button>
          <button className={kind === 'checkpoints' ? 'selected' : ''} onClick={() => setKind('checkpoints')}>
            <Save size={13} /> 存档检查点
          </button>
        </div>
        {kind === 'checkpoints' ? (
          <div className="scope-switch">
            <button className={scope === 'current' ? 'selected' : ''} onClick={() => setScope('current')} disabled={!run}>
              当前实验
            </button>
            <button className={scope === 'all' ? 'selected' : ''} onClick={() => setScope('all')}>
              全部历史
            </button>
          </div>
        ) : null}
        {kind === 'checkpoints' && runs.length > 1 && scope === 'current' ? (
          <select value={run?.run_id ?? ''} onChange={e => onSwitchRun(e.target.value)}>
            {runs.map(item => <option key={item.run_id} value={item.run_id}>{item.name} ({shortId(item.run_id)})</option>)}
          </select>
        ) : null}
        <div className="status-filter">
          {(['all', 'confirmed', 'pending', 'failed', 'not_submitted'] as Filter[]).map(f => (
            <button key={f} className={filter === f ? 'selected' : ''} onClick={() => setFilter(f)}>
              {f === 'all' ? '全部' : f === 'not_submitted' ? '未提交' : f === 'confirmed' ? '已上链' : f === 'pending' ? '确认中' : '失败'}
            </button>
          ))}
        </div>
        {kind === 'runs' && run ? (
          <button className="secondary-button compact" onClick={onExportArchive} title="导出 .sandbox 归档并将归档哈希上链（如果 writer 已配置）">
            <FileOutput size={13} /> 导出归档并上链
          </button>
        ) : null}
        <button className="icon-button" onClick={() => void loadAll()} title="刷新" aria-label="刷新">
          <RefreshCw size={16} />
        </button>
      </div>

      <div className="anchor-summary">
        <div className="summary-tile positive">
          <ShieldCheck size={18} />
          <div><small>已锚定</small><b>{summary.confirmed}</b></div>
        </div>
        <div className="summary-tile warning">
          <AlertTriangle size={18} />
          <div><small>链上确认中</small><b>{summary.pending}</b></div>
        </div>
        <div className="summary-tile negative">
          <XCircle size={18} />
          <div><small>上链失败</small><b>{summary.failed}</b></div>
        </div>
        <div className="summary-tile neutral">
          <Save size={18} />
          <div><small>{kind === 'runs' ? '实验总数' : '存档总数'}</small><b>{summary.total}</b></div>
        </div>
      </div>

      {error ? <ErrorBanner message={error} onClose={() => setError(null)} /> : null}
      {notice ? <div className="notice-line">{notice}</div> : null}
      {resumeError ? <ErrorBanner message={`续跑失败：${resumeError}`} onClose={() => setResumeError(null)} /> : null}

      {busy ? (
        <div className="loading-bar" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={kind === 'runs' ? '还没有市场实验' : '还没有存档'}
          detail={kind === 'runs'
            ? '创建场景 → 新建运行 即会出现在这里。可以点每行右侧的「立即上链」按钮手动锚定。'
            : '回到市场工作台，点击 💾 Save 按钮暂停并创建存档。'}
        />
      ) : kind === 'runs' ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>市场实验</th>
                <th>状态</th>
                <th>分支数</th>
                <th>最大游标</th>
                <th>累计模拟时间</th>
                <th>链上状态</th>
                <th>区块 / 交易</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map(ar => {
                const att = ar.attestation
                const tone = statusTone[att.status]
                const url = txExplorerUrl(att.tx_hash)
                const isAttesting = attestingRunId === ar.run_id
                const isCurrent = run?.run_id === ar.run_id
                return (
                  <tr key={ar.run_id} className={isCurrent ? 'active-row' : ''}>
                    <td>
                      <div className="cell-stack">
                        <strong>{ar.name ?? '未命名实验'}</strong>
                        <small className="mono muted"><Hash size={11} /> {shortId(ar.run_id)}</small>
                      </div>
                    </td>
                    <td><StatusBadge status={ar.status} /></td>
                    <td><Boxes size={13} className="inline-icon" /> {formatInteger(ar.branch_count)}</td>
                    <td>{formatInteger(ar.max_cursor)}</td>
                    <td>{formatTime(ar.total_sim_time_us)}</td>
                    <td>
                      <span className={`status-badge ${tone}`}>
                        <span />
                        {att.status === 'confirmed' ? '已上链' :
                         att.status === 'pending' ? '确认中…' :
                         att.status === 'failed' ? '失败' : '未提交'}
                      </span>
                    </td>
                    <td>
                      <div className="cell-stack">
                        {att.block_number ? <small>#{formatInteger(att.block_number)}</small> : <small className="muted">—</small>}
                        {url ? (
                          <a href={url} target="_blank" rel="noreferrer" className="link-tiny">
                            <ExternalLink size={11} /> {shortId(att.tx_hash!)}
                          </a>
                        ) : att.error_message ? (
                          <small className="error-text" title={att.error_message}>
                            {att.error_message.length > 30 ? att.error_message.slice(0, 30) + '…' : att.error_message}
                          </small>
                        ) : <small className="muted">点击右侧按钮手动上链</small>}
                      </div>
                    </td>
                    <td>
                      <div className="row-actions">
                        {att.status !== 'confirmed' && att.status !== 'pending' ? (
                          <button
                            className="primary-button compact"
                            disabled={isAttesting}
                            onClick={() => void attestNow(ar.run_id)}
                            title="立即将当前实验的世界状态哈希上链"
                          >
                            {isAttesting ? <RefreshCw size={13} className="spin" /> : <PlayCircle size={13} />}
                            立即上链
                          </button>
                        ) : null}
                        {isCurrent ? null : (
                          <button className="secondary-button compact" onClick={() => onSwitchRun(ar.run_id)}>
                            <ArrowRight size={13} /> 切换
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Checkpoint</th>
                <th>所属实验 / 分支</th>
                <th>模拟时间</th>
                <th>游标</th>
                <th>Agent</th>
                <th>链上状态</th>
                <th>区块 / 交易</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {filtered.map(cp => {
                const att = cp.attestation
                const tone = statusTone[att.status]
                const url = txExplorerUrl(att.tx_hash)
                const isResuming = resumingId === cp.checkpoint_id
                return (
                  <tr key={cp.checkpoint_id}>
                    <td>
                      <div className="cell-stack">
                        <strong className="mono">{shortId(cp.checkpoint_id)}</strong>
                        <small><Hash size={11} /> {cp.runtime_version}</small>
                      </div>
                    </td>
                    <td>
                      <div className="cell-stack">
                        <small className="muted">run {shortId(cp.run_id)}</small>
                        <span>branch {shortId(cp.branch_id)}</span>
                      </div>
                    </td>
                    <td>{formatTime(cp.sim_time_us)}</td>
                    <td>{formatInteger(cp.branch_seq)}</td>
                    <td><Users size={13} className="inline-icon" /> {formatInteger(cp.agent_count)}</td>
                    <td>
                      <span className={`status-badge ${tone}`}>
                        <span />
                        {att.status === 'confirmed' ? '已上链' :
                         att.status === 'pending' ? '确认中…' :
                         att.status === 'failed' ? '失败' : '未提交'}
                      </span>
                    </td>
                    <td>
                      <div className="cell-stack">
                        {att.block_number ? <small>#{formatInteger(att.block_number)}</small> : <small className="muted">—</small>}
                        {url ? (
                          <a href={url} target="_blank" rel="noreferrer" className="link-tiny">
                            <ExternalLink size={11} /> {shortId(att.tx_hash!)}
                          </a>
                        ) : att.error_message ? (
                          <small className="error-text" title={att.error_message}>
                            {att.error_message.length > 30 ? att.error_message.slice(0, 30) + '…' : att.error_message}
                          </small>
                        ) : <small className="muted">等待提交</small>}
                      </div>
                    </td>
                    <td>
                      <div className="row-actions">
                        {att.status === 'confirmed' ? (
                          <button
                            className="primary-button compact"
                            disabled={isResuming}
                            onClick={() => void resume(cp, true)}
                            title="校验链上哈希后从此存档继续"
                          >
                            {isResuming ? <RefreshCw size={13} className="spin" /> : <CheckCircle2 size={13} />}
                            链校验续跑
                          </button>
                        ) : (
                          <button
                            className="secondary-button compact"
                            disabled={isResuming}
                            onClick={() => void resume(cp, false)}
                            title="跳过链上校验，直接分叉续跑（本地调试用）"
                          >
                            {isResuming ? <RefreshCw size={13} className="spin" /> : <ArrowRight size={13} />}
                            本地续跑
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </section>
  </div>
}
