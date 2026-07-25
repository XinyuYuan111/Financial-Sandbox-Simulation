import { useEffect, useMemo, useRef, useState } from 'react'
import { Maximize2 } from 'lucide-react'
import type { EventEnvelope, Projection } from '../../types'
import { formatInteger } from '../../components/ui'

const PALETTE = ['#5B8DBE', '#C9922A', '#6FA287', '#D8CFBB', '#4E6E9E', '#A45A4A', '#8B7F9E', '#7A8B8F']
const EMBLEMS = ['◇', '△', '○', '▽', '☰', '✕', '⌘', '◈']
const PAWN_PATH =
  'M24 5 C28.9 5 32 8.4 32 12.4 C32 15.2 30.6 17.6 28.5 19 L31.5 23 ' +
  'C32.2 24 31.5 25.4 30.2 25.4 L27.5 25.4 C29.8 31 33.5 38 36.5 46 ' +
  'C38.5 51.4 40 55 42 58 C43.4 60.1 42.6 63 40 63 L8 63 C5.4 63 4.6 60.1 6 58 ' +
  'C8 55 9.5 51.4 11.5 46 C14.5 38 18.2 31 20.5 25.4 L17.8 25.4 ' +
  'C16.5 25.4 15.8 24 16.5 23 L19.5 19 C17.4 17.6 16 15.2 16 12.4 C16 8.4 19.1 5 24 5 Z'
const CURRENTS = [
  { d: 'M-20,428 C200,398 380,468 560,443 S880,408 1020,438', c: '#5B8DBE', dur: '67s' },
  { d: 'M-20,468 C240,443 420,503 640,478 S900,448 1020,473', c: '#4E6E9E', dur: '89s' },
  { d: 'M-20,388 C180,368 400,423 620,398 S860,373 1020,393', c: '#7A8B8F', dur: '113s' },
]
const SEAL_PERIOD_US = 90_000_000
const MAX_PAWNS = 12
const CHANNEL_RING: Record<string, string> = {
  PublicFeed: '#5B8DBE', OfficialAnnouncement: '#C9922A', TradingTerminal: '#6FA287', PrivateChannel: '#8B7F9E',
}

type StageTone = 'neutral' | 'calm' | 'heat' | 'halted'
type FxKind = 'footprint' | 'glyph' | 'ripple' | 'packet' | 'ring' | 'seal' | 'intervention' | 'link'
type FxItem = {
  id: string
  kind: FxKind
  x: number
  y: number
  color?: string
  text?: string
  x2?: number
  y2?: number
  agentId?: string
  peerId?: string
  ttl: number
}
type BubbleOverride = { id: string; agentId: string; text: string; kind: 'speak' | 'judge' | 'pm'; cred?: string }
type PawnPos = { x: number; y: number; s: number; index: number }

function mulberry32(seed: number) {
  let a = seed
  return () => {
    a |= 0; a = a + 0x6D2B79F5 | 0
    let t = Math.imul(a ^ a >>> 15, 1 | a)
    t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t
    return ((t ^ t >>> 14) >>> 0) / 4294967296
  }
}

function slotPos(index: number, count: number): { x: number; y: number; s: number } {
  const t = count <= 1 ? 0 : (index / (count - 1)) * 2 - 1
  return { x: 50 + t * 36, y: 62 - (1 - t * t) * 10, s: 0.84 + 0.18 * Math.abs(t) }
}

const asRecord = (value: unknown): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
const num = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null)

export function SimulationStage({ projection, events, branchStatus, onOpenAgent, onOpenMarket, onStart }: {
  projection: Projection
  events: EventEnvelope[]
  branchStatus: string
  onOpenAgent: (agentId: string) => void
  onOpenMarket: () => void
  onStart?: () => void
}) {
  const agents = useMemo(() => projection.agents.slice(0, MAX_PAWNS), [projection.agents])
  const trades = projection.market.trades
  const latestPrice = projection.market.last_trade?.price ?? projection.market.bids[0]?.price ?? projection.market.asks[0]?.price ?? 0
  const latestInformation = projection.information.at(-1)
  const latestSource = String(latestInformation?.source_id ?? '')
  const latestTrade = trades.at(-1)
  const tradeVolume = trades.reduce((sum, trade) => sum + trade.quantity, 0)

  const positions = useMemo(() => {
    const map = new Map<string, PawnPos>()
    agents.forEach((agent, index) => map.set(agent.agent_id, { ...slotPos(index, agents.length), index }))
    return map
  }, [agents])

  /* ---------- 舞台温度：交易活跃度三态 ---------- */
  const tone: StageTone = useMemo(() => {
    if (projection.market_status === 'halted') return 'halted'
    const recent = events.slice(-14).filter(event => event.event_type === 'TradeMatched' || event.event_type === 'TradeSettled').length
    if (recent >= 5) return 'heat'
    if (recent <= 1) return 'calm'
    return 'neutral'
  }, [events, projection.market_status])

  const pulse = useMemo(() => buildPulse(trades, projection.market.last_trade?.price), [trades, projection.market.last_trade?.price])
  const depth = useMemo(() => buildDepth(projection.market.bids.map(o => o.remaining), projection.market.asks.map(o => o.remaining)), [projection.market.bids, projection.market.asks])
  const sealProgress = useMemo(() => {
    const lastSeal = [...events].reverse().find(event => event.event_type === 'CheckpointCreated')
    return Math.min(100, Math.max(0, (projection.sim_time_us - (lastSeal?.sim_time_us ?? 0)) / SEAL_PERIOD_US * 100))
  }, [events, projection.sim_time_us])

  /* ---------- 演出：事件驱动的行动 / 气泡 / 连线 ---------- */
  const [fx, setFx] = useState<FxItem[]>([])
  const [bubbles, setBubbles] = useState<BubbleOverride[]>([])
  // 挂载与分支切换时以既有事件快照为基线：历史事件不重放演出，只演出新到事件
  const seenRef = useRef<Set<string> | null>(null)
  const seenBranchRef = useRef<string | null>(null)
  if (seenRef.current === null || seenBranchRef.current !== projection.branch_id) {
    seenBranchRef.current = projection.branch_id
    seenRef.current = new Set(events.map(event => event.event_id))
  }
  const timersRef = useRef<number[]>([])
  useEffect(() => () => { timersRef.current.forEach(timer => window.clearTimeout(timer)) }, [])

  useEffect(() => {
    const seen = seenRef.current ?? new Set<string>()
    seenRef.current = seen
    const additions: FxItem[] = []
    const newBubbles: BubbleOverride[] = []
    for (const event of events) {
      if (seen.has(event.event_id)) continue
      seen.add(event.event_id)
      const payload = asRecord(event.payload)

      if (event.event_type === 'TradeMatched') {
        const buyer = String(payload.buyer_id ?? '')
        const seller = String(payload.seller_id ?? '')
        const isBuy = positions.has(buyer)
        const agentId = isBuy ? buyer : seller
        const pos = positions.get(agentId)
        const quantity = num(payload.quantity)
        if (pos) {
          const color = PALETTE[pos.index % PALETTE.length]
          const glyph = isBuy ? '▲' : '▼'
          // 行动符号：从棋子飞向市场脉搏
          additions.push({ id: `${event.event_id}:glyph`, kind: 'glyph', x: pos.x, y: pos.y - 12, x2: 96, y2: 6, color, text: glyph, agentId, ttl: 1150 })
          // 落子涟漪
          additions.push({ id: `${event.event_id}:ripple`, kind: 'ripple', x: pos.x, y: pos.y, color, agentId, ttl: 1000 })
          // 成交足迹（约 20s 渐隐）
          additions.push({ id: `${event.event_id}:fp`, kind: 'footprint', x: pos.x + 2, y: pos.y + 1, color, text: quantity !== null ? `${glyph}${formatInteger(quantity)}` : glyph, ttl: 20000 })
        } else {
          // 背景市场部门的成交：未建模参与者从舞台之外飞入的行动符号
          const flowBuyer = buyer.includes('flow')
          const flowSeller = seller.includes('flow')
          const glyph = flowBuyer ? '▲' : flowSeller ? '▼' : '△'
          const hash = [...event.event_id].reduce((sum, ch) => sum + ch.charCodeAt(0), 0)
          additions.push({ id: `${event.event_id}:glyph`, kind: 'glyph', x: 15 + (hash % 70), y: 96, x2: 96, y2: 6, color: '#7A8B8F', text: glyph, ttl: 1150 })
        }
      } else if (event.event_type === 'InformationPublished') {
        const channel = String(payload.channel ?? '')
        const ringColor = CHANNEL_RING[channel] ?? '#C8432B'
        const author = positions.get(event.source_id)
        const origin = author ? { x: author.x, y: author.y - 10 } : { x: 50, y: 42 }
        const targetIds = Array.isArray(payload.target_ids) ? payload.target_ids.map(String) : []
        const targets = (targetIds.length ? targetIds : agents.map(agent => agent.agent_id)).filter(id => id !== event.source_id)
        targets.slice(0, MAX_PAWNS).forEach((agentId, index) => {
          const target = positions.get(agentId)
          if (!target) return
          additions.push({ id: `${event.event_id}:pkt:${index}`, kind: 'packet', x: origin.x, y: origin.y, x2: target.x, y2: target.y - 10, color: ringColor, ttl: 1500 + index * 90 })
        })
        additions.push({ id: `${event.event_id}:ring`, kind: 'ring', x: origin.x, y: origin.y, color: ringColor, ttl: 1200 })
        if (author) newBubbles.push({ id: event.event_id, agentId: event.source_id, kind: 'speak', text: String(payload.rendered_content ?? '').slice(0, 42) })
      } else if (event.event_type === 'PrivateMessageDelivered') {
        const from = positions.get(event.source_id)
        const targetId = String(payload.target_id ?? '')
        const to = positions.get(targetId)
        if (from && to) {
          additions.push({ id: event.event_id, kind: 'link', x: from.x, y: from.y - 8, x2: to.x, y2: to.y - 8, agentId: event.source_id, peerId: targetId, ttl: 5200 })
          newBubbles.push({ id: `${event.event_id}:pm`, agentId: targetId, kind: 'pm', text: '收到一条定向消息' })
        }
      } else if (event.event_type === 'BeliefUpdated') {
        const pos = positions.get(event.source_id)
        const confidence = num(payload.confidence_milli)
        if (pos && confidence !== null) {
          newBubbles.push({ id: event.event_id, agentId: event.source_id, kind: 'judge', text: String(payload.subject ?? '市场'), cred: `研判 · 信心 ${confidence} / 1000` })
        }
      } else if (event.event_type === 'CheckpointCreated') {
        additions.push({ id: event.event_id, kind: 'seal', x: 50, y: 42, ttl: 1600 })
      } else if (event.event_type === 'InterventionStageApplied' || event.event_type === 'ControlInterventionApplied') {
        additions.push({ id: event.event_id, kind: 'intervention', x: 50, y: 42, ttl: 1200 })
      }
    }
    if (seen.size > 2000) {
      seen.clear()
      events.forEach(event => seen.add(event.event_id))
    }
    if (!additions.length && !newBubbles.length) return
    if (additions.length) setFx(current => [...current.slice(-48), ...additions])
    if (newBubbles.length) {
      setBubbles(current => [...current.filter(item => !newBubbles.some(addition => addition.agentId === item.agentId)), ...newBubbles].slice(-MAX_PAWNS))
    }
    const ttl = Math.max(...[...additions.map(item => item.ttl), ...newBubbles.map(() => 6800)]) + 200
    const timer = window.setTimeout(() => {
      setFx(current => current.filter(item => !additions.some(addition => addition.id === item.id)))
      setBubbles(current => current.filter(item => !newBubbles.some(addition => addition.id === item.id)))
    }, ttl)
    timersRef.current.push(timer)
  }, [events, positions, agents])

  /* ---------- 演出状态派生 ---------- */
  const actingIds = useMemo(() => new Set(fx.filter(item => item.kind === 'glyph' || item.kind === 'ripple').map(item => item.agentId)), [fx])
  const engagedIds = useMemo(() => new Set(fx.filter(item => item.kind === 'link').flatMap(item => [item.agentId ?? '', item.peerId ?? ''])), [fx])
  const focusing = engagedIds.size > 0
  const shocking = fx.some(item => item.kind === 'glyph' || item.kind === 'intervention')
  const bubbleByAgent = useMemo(() => new Map(bubbles.map(item => [item.agentId, item])), [bubbles])

  /* ---------- 地面装饰（确定性种子，只在挂载时生成一次） ---------- */
  const ground = useMemo(() => {
    const rng = mulberry32(3313)
    const sky = Array.from({ length: 42 }, () => ({
      cx: (rng() * 1000).toFixed(1), cy: (rng() * 320).toFixed(1), r: (0.5 + rng() * 0.9).toFixed(2),
      delay: (rng() * 14).toFixed(1), dur: (7 + rng() * 9).toFixed(1),
    }))
    const radials = Array.from({ length: 24 }, (_, i) => {
      const r = (i * 15) * Math.PI / 180
      return { x1: 500 + Math.cos(r) * 70, y1: 380 + Math.sin(r) * 32, x2: 500 + Math.cos(r) * 560, y2: 380 + Math.sin(r) * 255 }
    })
    return { sky, radials }
  }, [])

  const change = pulse.change
  const changeClass = change > 0.005 ? 'up' : change < -0.005 ? 'down' : 'flat'
  const modeLabel = projection.market_status === 'halted' ? 'HALTED 停牌' : branchStatus === 'Historical' ? 'HISTORICAL' : branchStatus === 'Running' ? 'LIVE' : branchStatus.toUpperCase()

  return <section className={`simulation-stage tone-${tone}`} aria-label="金融市场仿真舞台">
    <div className="stage-tint" />
    <div className="stage-fog fog-a" />
    <div className="stage-fog fog-b" />

    <svg className="stage-ground" viewBox="0 0 1000 600" preserveAspectRatio="xMidYMid slice" aria-hidden="true">
      {ground.radials.map((line, index) => <line key={`r${index}`} className="ground-radial" x1={line.x1.toFixed(1)} y1={line.y1.toFixed(1)} x2={line.x2.toFixed(1)} y2={line.y2.toFixed(1)} />)}
      {[1, 2, 3, 4, 5, 6].map(k => <ellipse key={k} className="ground-ring" cx={500} cy={380} rx={k * 88} ry={k * 40} fill="none" stroke="rgba(216,207,187,.045)" style={{ animationDelay: `${k * 1.3}s` }} />)}
      {CURRENTS.map((current, index) => <path key={index} className="current" d={current.d} stroke={current.c} style={{ animationDuration: current.dur }} />)}
      {ground.sky.map((dot, index) => <circle key={`s${index}`} className="sky-dot" cx={dot.cx} cy={dot.cy} r={dot.r} style={{ animationDelay: `${dot.delay}s`, animationDuration: `${dot.dur}s` }} />)}
      {depth ? <>
        <path className="depth-bids" d={depth.bids} />
        <path className="depth-asks" d={depth.asks} />
      </> : null}
      <ellipse className="seal-dial" cx={500} cy={380} rx={310} ry={142} pathLength={100} strokeDasharray={`${sealProgress.toFixed(1)} 100`} />
    </svg>

    <button className={`market-pulse ${shocking ? 'pulse-shock' : ''}`} onClick={onOpenMarket} aria-label="打开订单簿与成交">
      <svg viewBox="0 0 1000 128" preserveAspectRatio="none" aria-hidden="true">
        {pulse.bars.map((bar, index) => <rect key={index} x={bar.x} y={bar.y} width={bar.w} height={bar.h} fill={bar.color} />)}
        <path className="pulse-area" d={pulse.area} />
        <path className="pulse-ghost" d={pulse.ghost} />
        <path className="pulse-line" d={pulse.line} />
        <circle className="pulse-dot" cx={pulse.dot.x} cy={pulse.dot.y} r={2.4} />
      </svg>
      <span className="stage-mode">{modeLabel}</span>
      <span className="pulse-readout"><b>{latestPrice || '--'}</b><small className={changeClass}>{change > 0 ? '+' : ''}{change.toFixed(2)}%</small></span>
      <Maximize2 size={14} />
    </button>

    <svg className="link-layer" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
      {fx.filter(item => item.kind === 'link').map(item => <line key={item.id} className="rel-line" x1={item.x} y1={item.y} x2={item.x2} y2={item.y2} vectorEffect="non-scaling-stroke" />)}
    </svg>

    <div className={`stage-agent-layer ${focusing ? 'focus' : ''}`}>
      {agents.map((agent, index) => {
        const position = positions.get(agent.agent_id) ?? { x: 50, y: 62, s: 1, index }
        const override = bubbleByAgent.get(agent.agent_id)
        return <AgentPawn
          key={agent.agent_id}
          agent={agent}
          index={index}
          position={position}
          color={PALETTE[index % PALETTE.length]}
          emblem={EMBLEMS[index % EMBLEMS.length]}
          override={override}
          communicating={!override && agent.agent_id === latestSource && Boolean(latestInformation)}
          infoText={String(latestInformation?.rendered_content ?? '').slice(0, 42)}
          planning={Boolean(agent.planning_request_id)}
          trading={Boolean(latestTrade && (latestTrade.buyer_id === agent.agent_id || latestTrade.seller_id === agent.agent_id))}
          acting={actingIds.has(agent.agent_id)}
          engaged={engagedIds.has(agent.agent_id)}
          onOpenAgent={onOpenAgent}
        />
      })}
      {projection.agents.length > agents.length ? <div className="agent-overflow">+{projection.agents.length - agents.length}<span>更多 Agent 在运行</span></div> : null}
    </div>

    <div className="fx-layer" aria-hidden="true">
      {fx.filter(item => item.kind !== 'link').map(item => {
        if (item.kind === 'footprint') return <span key={item.id} className="fx-footprint" style={{ left: `${item.x}%`, top: `${item.y}%`, color: item.color }}>{item.text}</span>
        if (item.kind === 'glyph') return <FlyingGlyph key={item.id} item={item} />
        if (item.kind === 'ripple') return <span key={item.id} className="fx-ripple" style={{ left: `${item.x}%`, top: `${item.y}%`, '--fx-color': item.color } as React.CSSProperties} />
        if (item.kind === 'seal') return <span key={item.id} className="fx-seal-sweep" style={{ left: `${item.x}%`, top: `${item.y}%` }} />
        if (item.kind === 'intervention' || item.kind === 'ring') return <span key={item.id} className="fx-ring" style={{ left: `${item.x}%`, top: `${item.y}%`, borderColor: item.color }} />
        return <FlyingPacket key={item.id} item={item} />
      })}
    </div>

    <div className="stage-readout">
      <span>订单 <b>{projection.market.bids.length + projection.market.asks.length}</b></span>
      <span>成交 <b>{trades.length}</b></span>
      <span>成交量 <b>{formatInteger(tradeVolume)}</b></span>
      <span>信息 <b>{projection.information.length}</b></span>
      <span>事件 <b>{events.length}</b></span>
    </div>

    {branchStatus === 'Ready' ? <div className="standby-veil">
      <div className="sb-inner">
        <div className="sb-label">STANDBY</div>
        <button className="sb-start" onClick={onStart} disabled={!onStart}>开 始</button>
        <div className="sb-hint">分支已就绪 · 开始后世界将自主推进</div>
      </div>
    </div> : null}
  </section>
}

/* ---------- 棋子：入场走位 + 气泡优先级（事件 > 交流 > 思考） ---------- */
function AgentPawn({ agent, index, position, color, emblem, override, communicating, infoText, planning, trading, acting, engaged, onOpenAgent }: {
  agent: Projection['agents'][number]
  index: number
  position: PawnPos
  color: string
  emblem: string
  override?: BubbleOverride
  communicating: boolean
  infoText: string
  planning: boolean
  trading: boolean
  acting: boolean
  engaged: boolean
  onOpenAgent: (agentId: string) => void
}) {
  const [entered, setEntered] = useState(false)
  useEffect(() => {
    // setTimeout 而非 rAF：后台标签页 rAF 不触发，棋子会停留在透明态
    const timer = window.setTimeout(() => setEntered(true), 40)
    return () => window.clearTimeout(timer)
  }, [])
  const fromX = position.x < 50 ? -70 : 70
  return <button
    className={`agent-pawn ${override ? 'communicating' : communicating ? 'communicating' : ''} ${trading ? 'trading' : ''} ${acting ? 'acting' : ''} ${planning ? 'planning' : ''} ${engaged ? 'engaged' : ''}`}
    style={{
      left: `${position.x}%`,
      top: `${position.y}%`,
      transform: entered ? `scale(${position.s})` : `translate(${fromX}px, 0) scale(${position.s})`,
      opacity: entered ? undefined : 0,
      transitionDelay: entered ? `${index * 120}ms` : '0ms',
      '--agent-color': color,
      '--delay': `${(index % 6) * -0.7}s`,
    } as React.CSSProperties}
    onClick={() => onOpenAgent(agent.agent_id)}
    aria-label={`打开 ${agent.display_name ?? agent.agent_id} 的 Agent 审计`}
  >
    {override
      ? <span className={`agent-bubble show ${override.kind} ${index % 2 === 1 ? 'raise' : ''}`}>{override.text}{override.cred ? <span className="cred">{override.cred}</span> : null}</span>
      : communicating
        ? <span className={`agent-bubble ${index % 2 === 1 ? 'raise' : ''}`}>{infoText}</span>
        : planning
          ? <span className="agent-bubble thinking"><span className="tdots"><i /><i /><i /></span></span>
          : null}
    <span className="agent-emblem">{emblem}</span>
    <svg className="pawn-svg" viewBox="0 0 48 72" aria-hidden="true">
      <path d={PAWN_PATH} fill={color} fillOpacity=".12" stroke={color} strokeWidth="1.6" strokeLinejoin="round" />
    </svg>
    <span className="agent-shadow" />
    <span className="agent-glow" />
    <span className="agent-name">{agent.display_name ?? agent.agent_id.slice(0, 8)}</span>
    <span className="agent-state">{planning ? '规划中' : agent.portfolio.open_orders.length ? `${agent.portfolio.open_orders.length} 挂单` : agent.role_tags?.[0] ?? '观察'}</span>
  </button>
}

/* ---------- 行动符号：从棋子飞向市场脉搏 ---------- */
function FlyingGlyph({ item }: { item: FxItem }) {
  const [arrived, setArrived] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setArrived(true), 30)
    return () => window.clearTimeout(timer)
  }, [])
  return <span
    className="fx-glyph"
    style={{
      left: `${arrived ? (item.x2 ?? item.x) : item.x}%`,
      top: `${arrived ? (item.y2 ?? item.y) : item.y}%`,
      color: item.color,
      opacity: arrived ? 0 : 1,
    }}
  >{item.text}</span>
}

/* ---------- 信息包：从舞台中心飞向目标棋子 ---------- */
function FlyingPacket({ item }: { item: FxItem }) {
  const [arrived, setArrived] = useState(false)
  useEffect(() => {
    const timer = window.setTimeout(() => setArrived(true), 30)
    return () => window.clearTimeout(timer)
  }, [])
  return <span
    className="fx-pkt mini"
    style={{
      left: `${arrived ? (item.x2 ?? item.x) : item.x}%`,
      top: `${arrived ? (item.y2 ?? item.y) : item.y}%`,
      background: item.color,
      opacity: arrived ? 0 : 1,
      transitionDelay: `${Math.max(0, item.ttl - 1500)}ms`,
    }}
  />
}

/* ---------- 价格脉搏：窗口定标 + 均线 + 量能柱 ---------- */
function buildPulse(trades: Projection['market']['trades'], lastPrice: number | null | undefined) {
  const W = 1000, H = 128
  const values = trades.slice(-90).map(trade => trade.price)
  if (lastPrice != null) values.push(lastPrice)
  const fallback = `M0 ${H / 2} L${W} ${H / 2}`
  if (values.length < 2) {
    return { line: fallback, area: `${fallback} L${W} ${H} L0 ${H} Z`, ghost: fallback, dot: { x: W, y: H / 2 }, bars: [] as Array<{ x: number; y: number; w: number; h: number; color: string }>, change: 0 }
  }
  let min = values[0], max = values[0]
  for (const value of values) { if (value < min) min = value; if (value > max) max = value }
  const range = Math.max(max - min, Math.abs(values[values.length - 1]) * 0.002, 1)
  const mid = (max + min) / 2
  const x = (index: number) => index * W / (values.length - 1)
  const y = (price: number) => H * 0.5 - (price - mid) / range * H * 0.62
  const line = values.map((price, index) => `${index ? 'L' : 'M'}${x(index).toFixed(1)} ${y(price).toFixed(1)}`).join(' ')
  const area = `${line} L${W} ${H} L0 ${H} Z`
  const window = 12
  const ghost = values.map((_, index) => {
    const from = Math.max(0, index - window + 1)
    let sum = 0
    for (let k = from; k <= index; k++) sum += values[k]
    return `${index ? 'L' : 'M'}${x(index).toFixed(1)} ${y(sum / (index - from + 1)).toFixed(1)}`
  }).join(' ')
  const recent = trades.slice(-48)
  const maxQty = Math.max(1, ...recent.map(trade => trade.quantity))
  const bars = recent.map((trade, index) => {
    const h = 4 + (trade.quantity / maxQty) * H * 0.3
    const previous = index > 0 ? recent[index - 1].price : trade.price
    const color = trade.price > previous ? 'rgba(111,162,135,.32)' : trade.price < previous ? 'rgba(176,112,95,.32)' : 'rgba(122,139,143,.28)'
    return { x: (index + 0.5) / 48 * W - (W / 48 * 0.52) / 2, y: H - h, w: W / 48 * 0.52, h, color }
  })
  const change = (values[values.length - 1] - values[0]) / Math.max(1e-9, Math.abs(values[0])) * 100
  return { line, area, ghost, dot: { x: W, y: y(values[values.length - 1]) }, bars, change }
}

/* ---------- 深度地形：累计挂单量的地平剪影 ---------- */
function buildDepth(bidQty: number[], askQty: number[]): { bids: string; asks: string } | null {
  if (!bidQty.length || !askQty.length) return null
  const base = 588, cx = 500, maxW = 330, maxH = 62
  const cumulate = (arr: number[]) => { let sum = 0; return arr.map(value => (sum += value)) }
  const cumBids = cumulate(bidQty.slice(0, 8))
  const cumAsks = cumulate(askQty.slice(0, 8))
  const maxCum = Math.max(cumBids.at(-1) ?? 0, cumAsks.at(-1) ?? 0, 1)
  const build = (cum: number[], dir: -1 | 1) => {
    let d = `M${cx},${base}`
    cum.forEach((value, index) => {
      d += ` L${(cx + dir * (index + 1) / cum.length * maxW).toFixed(1)},${(base - (value / maxCum) * maxH).toFixed(1)}`
    })
    return `${d} L${cx + dir * maxW},${base} Z`
  }
  return { bids: build(cumBids, -1), asks: build(cumAsks, 1) }
}
