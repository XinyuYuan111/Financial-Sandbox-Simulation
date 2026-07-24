import { useMemo, useState } from 'react'
import { Filter, Search } from 'lucide-react'
import type { EventEnvelope } from '../../types'
import { EmptyState, formatTime, shortId, StatusBadge } from '../../components/ui'

export function EventExplorer({ events }: { events: EventEnvelope[] }) {
  const [query, setQuery] = useState('')
  const [visibility, setVisibility] = useState('all')
  const filtered = useMemo(() => events.filter(event => {
    const match = !query || `${event.event_type} ${event.source_id} ${JSON.stringify(event.payload)}`.toLowerCase().includes(query.toLowerCase())
    return match && (visibility === 'all' || event.visibility === visibility)
  }), [events, query, visibility])
  return <section className="workspace-panel full-panel event-explorer">
    <div className="panel-heading"><div><h2>事件浏览器</h2><p>{filtered.length} / {events.length} 个事件</p></div><div className="event-filters"><label><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder="搜索事件或主体" /></label><label><Filter size={15} /><select value={visibility} onChange={event => setVisibility(event.target.value)}><option value="all">全部可见性</option><option value="analyst_only">analyst_only</option><option value="participants">participants</option><option value="agent_private">agent_private</option><option value="public">public</option></select></label></div></div>
    {filtered.length ? <div className="table-scroll event-table"><table><thead><tr><th>序号</th><th>时间</th><th>事件</th><th>来源</th><th>可见性</th><th>摘要</th></tr></thead><tbody>{[...filtered].reverse().map(event => <tr key={event.event_id}><td>{event.branch_seq}</td><td>{formatTime(event.sim_time_us)}</td><td><strong>{event.event_type}</strong><small>{shortId(event.event_id)}</small></td><td title={event.source_id}>{shortId(event.source_id)}</td><td><StatusBadge status={event.visibility} /></td><td className="payload-cell">{eventSummary(event.payload)}</td></tr>)}</tbody></table></div> : <EmptyState title="没有匹配事件" />}
  </section>
}

function eventSummary(payload: Record<string, unknown>) {
  const preferred = ['action_type', 'reason', 'request_id', 'checkpoint_id', 'kind', 'message']
  const key = preferred.find(candidate => payload[candidate] !== undefined)
  if (key) return `${key}: ${String(payload[key])}`
  return Object.entries(payload).slice(0, 2).map(([name, value]) => `${name}: ${String(value)}`).join(' · ') || '-'
}
