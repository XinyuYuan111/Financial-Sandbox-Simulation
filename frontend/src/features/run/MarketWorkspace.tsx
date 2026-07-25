import { ArrowDownRight, ArrowUpRight, Info, Landmark, ReceiptText } from 'lucide-react'
import type { Order, Projection, Trade } from '../../types'
import { EmptyState, formatInteger, formatTime, shortId } from '../../components/ui'
import { channelText, informationNarrative } from '../agents/auditNarrative'

export function MarketWorkspace({ projection }: { projection: Projection }) {
  const last = projection.market.last_trade
  const volume = projection.market.trades.reduce((sum, trade) => sum + trade.quantity, 0)
  const bestBid = projection.market.bids[0]?.price
  const bestAsk = projection.market.asks[0]?.price
  const spread = bestBid != null && bestAsk != null ? bestAsk - bestBid : null
  const midpoint = bestBid != null && bestAsk != null ? (bestBid + bestAsk) / 2 : null
  const spreadBps = spread !== null && midpoint ? spread * 10_000 / midpoint : null
  return <div className="market-workspace">
    <section className="metric-strip">
      <div><span>最新成交</span><strong>{last?.price ?? '-'}</strong><small>USDx ticks</small></div>
      <div><span>累计成交量</span><strong>{formatInteger(volume)}</strong><small>Token units</small></div>
      <div><span>最优买 / 卖</span><strong>{bestBid ?? '-'} <i>/</i> {bestAsk ?? '-'}</strong><small>{spread !== null && spreadBps !== null ? `价差 ${spread} ticks · ${spreadBps.toFixed(2)} bps` : '价差 -'}</small></div>
      <div><span>模拟时间</span><strong>{formatTime(projection.sim_time_us)}</strong><small>cursor {projection.cursor}</small></div>
    </section>
    <div className="market-grid">
      <section className="workspace-panel orderbook-panel">
        <div className="panel-heading"><div><h2>订单簿</h2><p>{projection.market.market_id}</p></div><Landmark size={18} /></div>
        <div className="book-columns">
          <DepthSide title="买盘" tone="buy" orders={projection.market.bids.slice(0, 10)} empty="暂无买单" />
          <DepthSide title="卖盘" tone="sell" orders={projection.market.asks.slice(0, 10)} empty="暂无卖单" />
        </div>
      </section>
      <section className="workspace-panel tape-panel">
        <div className="panel-heading"><div><h2>成交带</h2><p>最近 {projection.market.trades.length} 笔</p></div><ReceiptText size={18} /></div>
        {projection.market.trades.length ? <div className="table-scroll"><table><thead><tr><th /><th>价格</th><th>数量</th><th>买方</th><th>卖方</th></tr></thead><tbody>
          {[...projection.market.trades].reverse().slice(0, 14).map((trade, index, list) => <TapeRow key={trade.trade_id} trade={trade} previous={list[index + 1]} />)}
        </tbody></table></div> : <EmptyState title="暂无成交" detail="等待订单撮合。" />}
      </section>
    </div>
  </div>
}

function DepthSide({ title, tone, orders, empty }: { title: string; tone: 'buy' | 'sell'; orders: Order[]; empty: string }) {
  const icon = tone === 'buy' ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />
  const maxRemaining = Math.max(1, ...orders.map(order => order.remaining))
  const depthColor = tone === 'buy' ? 'rgba(91,141,190,.13)' : 'rgba(201,146,42,.13)'
  return <div>
    <h3>{icon}{title}</h3>
    <table><thead><tr><th>价格</th><th>剩余</th><th>Agent</th></tr></thead><tbody>
      {orders.map(order => {
        const pct = Math.round(order.remaining / maxRemaining * 100)
        return <tr key={order.order_id}>
          <td className={`ob-price ${tone}`}>{order.price}</td>
          <td className="ob-depth" style={{ background: `linear-gradient(90deg, transparent ${100 - pct}%, ${depthColor} ${100 - pct}%)` }}>{formatInteger(order.remaining)}</td>
          <td className="ob-by" title={order.agent_id}>{shortId(order.agent_id)}</td>
        </tr>
      })}
    </tbody></table>
    {!orders.length ? <EmptyState title={empty} /> : null}
  </div>
}

function TapeRow({ trade, previous }: { trade: Trade; previous: Trade | undefined }) {
  const direction = previous && trade.price > previous.price ? 'up' : previous && trade.price < previous.price ? 'down' : ''
  return <tr>
    <td className={`tape-dir ${direction}`}>{direction === 'up' ? '▲' : direction === 'down' ? '▼' : '·'}</td>
    <td><strong>{trade.price}</strong></td>
    <td>{formatInteger(trade.quantity)}</td>
    <td>{shortId(trade.buyer_id)}</td>
    <td>{shortId(trade.seller_id)}</td>
  </tr>
}

export function InformationWorkspace({ projection }: { projection: Projection }) {
  return <section className="workspace-panel full-panel"><div className="panel-heading"><div><h2>Agent 交流</h2><p>{projection.information.length} 条已进入传播链的信息</p></div><Info size={18} /></div>{projection.information.length ? <div className="information-list">{[...projection.information].reverse().map((item, index) => {
    const narrative = informationNarrative(item)
    return <article key={String(item.information_id ?? index)}>
      <div><strong>{channelText(item.channel)}</strong><span>{formatTime(Number(item.sim_time_us ?? 0))}</span></div>
      <p>“{String(item.rendered_content ?? '')}”</p>
      <dl className="information-meta"><div><dt>发布者</dt><dd>{String(item.source_id ?? '未知来源')}</dd></div><div><dt>披露范围</dt><dd>{narrative.scope}</dd></div><div><dt>主张</dt><dd>{narrative.claim}</dd></div><div><dt>信息血缘</dt><dd>{narrative.provenance}</dd></div></dl>
    </article>
  })}</div> : <EmptyState title="暂无 Agent 交流" detail="Agent 的公开观点、定向披露和信息派生会显示在这里；保留未发布的判断只出现在分析审计中。" />}</section>
}
