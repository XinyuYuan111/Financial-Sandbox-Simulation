import { useState, useEffect, useRef } from 'react'

export interface Particle {
  id: string
  x: number
  y: number
  type: 'buy' | 'sell'
}

export interface TradeEffectState {
  flashingTradeIds: Set<string>
  priceDirection: 'up' | 'down' | null
  tradingAgentIds: Set<string>
  particles: Particle[]
}

const MAX_PARTICLES = 50
const FLASH_DURATION = 600
const AGENT_TRADE_DURATION = 2000
const PARTICLE_DURATION = 800
const PRICE_DIRECTION_DURATION = 300

type TradeInput = { trade_id: string; buyer_id: string; seller_id: string; price?: number }

/**
 * 监听交易数据变化，触发动画状态。
 * - 新增交易时闪烁 trade_id（600ms）
 * - 标记买卖双方 agent 为交易中（2000ms）
 * - 生成粒子效果（800ms 后清理，上限 50 个 FIFO）
 * - 比较 lastPrice / prevPrice 确定价格方向（300ms）
 */
export function useTradeEffects(
  trades: TradeInput[],
  lastPrice: number | null,
  prevPrice: number | null,
): TradeEffectState {
  const [flashingTradeIds, setFlashingTradeIds] = useState<Set<string>>(new Set())
  const [priceDirection, setPriceDirection] = useState<'up' | 'down' | null>(null)
  const [tradingAgentIds, setTradingAgentIds] = useState<Set<string>>(new Set())
  const [particles, setParticles] = useState<Particle[]>([])

  const prevTradesLengthRef = useRef<number | null>(null)
  const timersRef = useRef<number[]>([])

  /* --- 检测新增交易 --- */
  useEffect(() => {
    const currentLength = trades.length

    // 首次挂载：记录初始长度，不触发效果
    if (prevTradesLengthRef.current === null) {
      prevTradesLengthRef.current = currentLength
      return
    }

    const prevLength = prevTradesLengthRef.current
    prevTradesLengthRef.current = currentLength
    if (currentLength <= prevLength) return

    const newTrades = trades.slice(prevLength)

    // 1) 闪烁 trade_id
    setFlashingTradeIds(prev => {
      const next = new Set(prev)
      newTrades.forEach(t => next.add(t.trade_id))
      return next
    })
    newTrades.forEach(t => {
      const timer = window.setTimeout(() => {
        setFlashingTradeIds(prev => {
          const next = new Set(prev)
          next.delete(t.trade_id)
          return next
        })
      }, FLASH_DURATION)
      timersRef.current.push(timer)
    })

    // 2) 标记交易中的 agent
    const agentIds = new Set<string>()
    newTrades.forEach(t => {
      agentIds.add(t.buyer_id)
      agentIds.add(t.seller_id)
    })
    setTradingAgentIds(prev => {
      const next = new Set(prev)
      agentIds.forEach(id => next.add(id))
      return next
    })
    agentIds.forEach(id => {
      const timer = window.setTimeout(() => {
        setTradingAgentIds(prev => {
          const next = new Set(prev)
          next.delete(id)
          return next
        })
      }, AGENT_TRADE_DURATION)
      timersRef.current.push(timer)
    })

    // 3) 生成粒子
    const newParticles: Particle[] = newTrades.map((trade, index) => {
      const prevTrade = trades[prevLength + index - 1]
      const prevPriceValue = prevTrade?.price
      const isBuy = prevPriceValue == null || (trade.price ?? 0) >= prevPriceValue
      return {
        id: `p-${trade.trade_id}-${index}`,
        x: 30 + Math.random() * 40,
        y: 30 + Math.random() * 40,
        type: isBuy ? 'buy' : 'sell',
      }
    })
    setParticles(prev => {
      const combined = [...prev, ...newParticles]
      return combined.length > MAX_PARTICLES ? combined.slice(combined.length - MAX_PARTICLES) : combined
    })
    newParticles.forEach(p => {
      const timer = window.setTimeout(() => {
        setParticles(prev => prev.filter(item => item.id !== p.id))
      }, PARTICLE_DURATION)
      timersRef.current.push(timer)
    })
  }, [trades])

  /* --- 价格方向 --- */
  useEffect(() => {
    if (lastPrice === null || prevPrice === null || lastPrice === prevPrice) return
    setPriceDirection(lastPrice > prevPrice ? 'up' : 'down')
    const timer = window.setTimeout(() => setPriceDirection(null), PRICE_DIRECTION_DURATION)
    return () => window.clearTimeout(timer)
  }, [lastPrice, prevPrice])

  /* --- 卸载时清理所有定时器 --- */
  useEffect(() => {
    return () => {
      timersRef.current.forEach(t => window.clearTimeout(t))
      timersRef.current = []
    }
  }, [])

  return { flashingTradeIds, priceDirection, tradingAgentIds, particles }
}
