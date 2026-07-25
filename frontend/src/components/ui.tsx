import type { ReactNode } from 'react'
import { AlertCircle, Inbox, X } from 'lucide-react'

export const formatInteger = (value: number | null | undefined) =>
  new Intl.NumberFormat('zh-CN').format(value ?? 0)

// The product display relabels each stored simulation-second tick as one minute.
export const formatTime = (value: number | null | undefined) =>
  `模拟第 ${((value ?? 0) / 1_000_000).toFixed(2)} 分钟`

export const shortId = (value: string | null | undefined) =>
  value ? `${value.slice(0, 7)}...${value.slice(-4)}` : '-'

export function IconButton({ title, onClick, disabled, children, className = '' }: {
  title: string
  onClick: () => void
  disabled?: boolean
  children: ReactNode
  className?: string
}) {
  return <button type="button" className={`icon-button ${className}`} title={title} aria-label={title} onClick={onClick} disabled={disabled}>{children}</button>
}

export function StatusBadge({ status }: { status: string }) {
  const tone = ['Running', 'executed', 'accepted', 'Ready', 'ok'].includes(status)
    ? 'positive'
    : ['rejected', 'failed', 'error'].includes(status)
      ? 'negative'
      : ['Queued', 'Running planning', 'Paused'].includes(status)
        ? 'warning'
        : 'neutral'
  const labels: Record<string, string> = {
    Running: '运行中', Ready: '就绪', Queued: '排队中', Paused: '已暂停', Stopped: '已停止',
    accepted: '已接受', rejected: '已拒绝', executed: '已执行', failed: '失败', expired: '已过期',
    canceled: '已取消', active: '可访问', inactive: '未生效', forgotten: '已遗忘', ok: '正常',
    analyst_only: '仅分析端', participants: '参与者可见', agent_private: 'Agent 私有', public: '公开',
  }
  return <span className={`status-badge ${tone}`}><span />{labels[status] ?? status}</span>
}

export function EmptyState({ title, detail }: { title: string; detail?: string }) {
  return <div className="empty-state"><Inbox size={24} /><strong>{title}</strong>{detail ? <span>{detail}</span> : null}</div>
}

export function ErrorBanner({ message, onClose }: { message: string; onClose?: () => void }) {
  return <div className="error-banner" role="alert"><AlertCircle size={17} /><span>{message}</span>{onClose ? <button onClick={onClose} aria-label="关闭错误"><X size={15} /></button> : null}</div>
}

export function JsonBlock({ value }: { value: unknown }) {
  return <pre className="json-block">{JSON.stringify(value, null, 2)}</pre>
}
