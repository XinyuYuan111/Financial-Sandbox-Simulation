import { ArrowDownRight, ArrowUpRight, Info, Landmark, ReceiptText } from 'lucide-react'
import type { Projection } from '../../types'
import { EmptyState, formatInteger, formatTime, shortId } from '../../components/ui'

export function MarketWorkspace({ projection }: { projection: Projection }) {
  const last = projection.market.last_trade
  const volume = projection.market.trades.reduce((sum, trade) => sum + trade.quantity, 0)
  const bestBid = projection.market.bids[0]?.price
  const bestAsk = projection.market.asks[0]?.price
  return <div className="market-workspace">
    <section className="metric-strip">
      <div><span>最新成交</span><strong>{last?.price ?? '-'}</strong><small>USDx ticks</small></div>
      <div><span>累计成交量</span><strong>{formatInteger(volume)}</strong><small>Token units</small></div>
      <div><span>最优买 / 卖</span><strong>{bestBid ?? '-'} <i>/</i> {bestAsk ?? '-'}</strong><small>spread {bestBid && bestAsk ? bestAsk - bestBid : '-'}</small></div>
      <div><span>模拟时间</span><strong>{formatTime(projection.sim_time_us)}</strong><small>cursor {projection.cursor}</small></div>
    </section>
    <div className="market-grid">
      <section className="workspace-panel orderbook-panel">
        <div className="panel-heading"><div><h2>订单簿</h2><p>{projection.market.market_id}</p></div><Landmark size={18} /></div>
        <div className="book-columns"><div><h3><ArrowUpRight size={15} />买盘</h3><table><thead><tr><th>价格</th><th>剩余</th><th>Agent</th></tr></thead><tbody>{projection.market.bids.slice(0, 10).map(order => <tr key={order.order_id}><td className="buy">{order.price}</td><td>{formatInteger(order.remaining)}</td><td title={order.agent_id}>{shortId(order.agent_id)}</td></tr>)}</tbody></table>{!projection.market.bids.length ? <EmptyState title="暂无买单" /> : null}</div><div><h3><ArrowDownRight size={15} />卖盘</h3><table><thead><tr><th>价格</th><th>剩余</th><th>Agent</th></tr></thead><tbody>{projection.market.asks.slice(0, 10).map(order => <tr key={order.order_id}><td className="sell">{order.price}</td><td>{formatInteger(order.remaining)}</td><td title={order.agent_id}>{shortId(order.agent_id)}</td></tr>)}</tbody></table>{!projection.market.asks.length ? <EmptyState title="暂无卖单" /> : null}</div></div>
      </section>
      <section className="workspace-panel tape-panel">
        <div className="panel-heading"><div><h2>成交带</h2><p>最近 {projection.market.trades.length} 笔</p></div><ReceiptText size={18} /></div>
        {projection.market.trades.length ? <div className="table-scroll"><table><thead><tr><th>价格</th><th>数量</th><th>买方</th><th>卖方</th></tr></thead><tbody>{[...projection.market.trades].reverse().slice(0, 14).map(trade => <tr key={trade.trade_id}><td><strong>{trade.price}</strong></td><td>{formatInteger(trade.quantity)}</td><td>{shortId(trade.buyer_id)}</td><td>{shortId(trade.seller_id)}</td></tr>)}</tbody></table></div> : <EmptyState title="暂无成交" detail="执行 Fixture 步进或运行规划请求后，成交会出现在这里。" />}
      </section>
    </div>
  </div>
}

export function InformationWorkspace({ projection }: { projection: Projection }) {
  return <section className="workspace-panel full-panel"><div className="panel-heading"><div><h2>信息流</h2><p>{projection.information.length} 条已发布信息</p></div><Info size={18} /></div>{projection.information.length ? <div className="information-list">{[...projection.information].reverse().map((item, index) => <article key={String(item.information_id ?? index)}><div><strong>{String(item.channel ?? 'PublicFeed')}</strong><span>{formatTime(Number(item.sim_time_us ?? 0))}</span></div><p>{String(item.rendered_content ?? '')}</p><small>{String(item.source_id ?? '-')}</small></article>)}</div> : <EmptyState title="暂无信息" />}</section>
}
