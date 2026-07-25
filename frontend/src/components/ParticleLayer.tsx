import { useState } from 'react'
import type { CSSProperties } from 'react'
import type { Particle } from '../hooks/useTradeEffects'

interface ParticleLayerProps {
  particles: Particle[]
  onParticleEnd?: (id: string) => void
}

/** 单个粒子 — 用 useState 初始化随机偏移，避免每次重渲染时跳变 */
function ParticleDot({ particle, onEnd }: { particle: Particle; onEnd?: (id: string) => void }) {
  const [offsets] = useState(() => ({
    x: (Math.random() - 0.5) * 40,
    y: particle.type === 'buy' ? -30 - Math.random() * 20 : 30 + Math.random() * 20,
  }))
  return (
    <div
      className={`particle ${particle.type === 'buy' ? 'particle-buy' : 'particle-sell'}`}
      style={
        {
          left: `${particle.x}%`,
          top: `${particle.y}%`,
          '--particle-x': `${offsets.x}px`,
          '--particle-y': `${offsets.y}px`,
        } as CSSProperties
      }
      onAnimationEnd={() => onEnd?.(particle.id)}
    />
  )
}

/**
 * 粒子效果渲染层
 * - 绝对定位覆盖在父容器上方（父容器需 position: relative）
 * - 每个粒子用 div 渲染，CSS 动画驱动
 * - 动画结束后通过 onAnimationEnd 回调清理
 */
export function ParticleLayer({ particles, onParticleEnd }: ParticleLayerProps) {
  return (
    <div className="particle-layer">
      {particles.map(p => (
        <ParticleDot key={p.id} particle={p} onEnd={onParticleEnd} />
      ))}
    </div>
  )
}
