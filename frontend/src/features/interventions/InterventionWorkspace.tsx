import { FormEvent, useCallback, useEffect, useState } from 'react'
import { Ban, Check, CircleAlert, Plus, Send, Sparkles, Trash2 } from 'lucide-react'
import { api } from '../../api'
import type { InterventionEffect, InterventionPlan } from '../../types'
import { EmptyState, shortId, StatusBadge } from '../../components/ui'

type EffectKind = 'publish_information' | 'transfer_asset' | 'set_market_status' | 'set_account_freeze' | 'set_wallet_access' | 'create_world_entity' | 'create_relationship'

type EffectDraft = {
  effect_type: EffectKind
  source_id: string
  channel: 'PublicFeed' | 'OfficialAnnouncement' | 'TradingTerminal' | 'PrivateChannel'
  content: string
  target_ids: string
  from_owner_id: string
  to_owner_id: string
  asset: string
  amount: string
  reason_code: string
  market_id: string
  status: 'active' | 'halted'
  owner_id: string
  frozen: boolean
  wallet_owner_id: string
  grantee_agent_id: string
  permissions: Array<'observe' | 'transact'>
  entity_id: string
  entity_type: 'institution' | 'venue' | 'wallet'
  display_name: string
  relationship_id: string
  relationship_type: 'wallet_control' | 'custody' | 'exposure'
  source_entity_id: string
  target_entity_id: string
}

const blankEffect = (): EffectDraft => ({
  effect_type: 'publish_information',
  source_id: 'scenario_director',
  channel: 'OfficialAnnouncement',
  content: '',
  target_ids: '',
  from_owner_id: '',
  to_owner_id: '',
  asset: 'TOKEN',
  amount: '1',
  reason_code: 'user_confirmed_intervention',
  market_id: 'TOKEN-USDX',
  status: 'halted',
  owner_id: '',
  frozen: true,
  wallet_owner_id: '',
  grantee_agent_id: '',
  permissions: ['observe'],
  entity_id: '', entity_type: 'institution', display_name: '',
  relationship_id: '', relationship_type: 'custody', source_entity_id: '', target_entity_id: '',
})

const splitIds = (value: string) => value.split(',').map(item => item.trim()).filter(Boolean)

function buildEffect(draft: EffectDraft): InterventionEffect {
  const effect_id = `effect_${crypto.randomUUID()}`
  if (draft.effect_type === 'publish_information') return {
    effect_id, effect_type: draft.effect_type, source_id: draft.source_id, channel: draft.channel,
    content: draft.content, target_ids: draft.channel === 'PrivateChannel' ? splitIds(draft.target_ids) : [],
    depends_on_state_effect_ids: [], private_source_refs: [],
  }
  if (draft.effect_type === 'transfer_asset') return {
    effect_id, effect_type: draft.effect_type, from_owner_id: draft.from_owner_id, to_owner_id: draft.to_owner_id,
    asset: draft.asset, amount: Number(draft.amount), reason_code: draft.reason_code, required_relationship_ids: [],
  }
  if (draft.effect_type === 'set_market_status') return {
    effect_id, effect_type: draft.effect_type, market_id: draft.market_id, status: draft.status, reason_code: draft.reason_code,
  }
  if (draft.effect_type === 'set_account_freeze') return {
    effect_id, effect_type: draft.effect_type, owner_id: draft.owner_id, frozen: draft.frozen, reason_code: draft.reason_code,
  }
  if (draft.effect_type === 'create_world_entity') return {
    effect_id, effect_type: draft.effect_type, entity_id: draft.entity_id,
    entity_type: draft.entity_type, display_name: draft.display_name,
  }
  if (draft.effect_type === 'create_relationship') return {
    effect_id, effect_type: draft.effect_type, relationship_id: draft.relationship_id,
    relationship_type: draft.relationship_type, source_entity_id: draft.source_entity_id,
    target_entity_id: draft.target_entity_id,
    asset: draft.relationship_type === 'exposure' ? draft.asset : null,
    amount: draft.relationship_type === 'exposure' ? Number(draft.amount) : null,
  }
  return {
    effect_id, effect_type: draft.effect_type, wallet_owner_id: draft.wallet_owner_id,
    grantee_agent_id: draft.grantee_agent_id, permissions: draft.permissions, reason_code: draft.reason_code,
  }
}

function effectLabel(effect: InterventionEffect) {
  const labels: Record<string, string> = {
    publish_information: '发布信息', transfer_asset: '资产转移', set_market_status: '市场状态',
    set_account_freeze: '账户冻结', set_wallet_access: '钱包访问',
    create_world_entity: '创建实体', create_relationship: '创建关系',
  }
  return labels[effect.effect_type] ?? effect.effect_type
}

function marketImpactText(value: number | undefined): string {
  const impact = value ?? 0
  const degree = Math.abs(impact) >= 700 ? '强烈' : Math.abs(impact) >= 350 ? '明显' : Math.abs(impact) > 0 ? '轻微' : ''
  if (impact > 0) return `${degree}利多，未来背景订单流将更偏向买入`
  if (impact < 0) return `${degree}利空，未来背景订单流将更偏向卖出`
  return '中性，不改变未来背景订单流'
}

function stageStatusText(status: InterventionPlan['stages'][number]['status']): string {
  return { pending: '待生效', applied: '已生效', failed: '应用失败', canceled: '已取消' }[status]
}

export function InterventionWorkspace({ branchId, branchStatus, simTimeUs, provider, onChanged }: {
  branchId: string
  branchStatus: string
  simTimeUs: number
  provider: 'openai' | 'deepseek' | null
  onChanged: () => Promise<void>
}) {
  const [plans, setPlans] = useState<InterventionPlan[]>([])
  const [intent, setIntent] = useState('')
  const [effectiveTime, setEffectiveTime] = useState(String(simTimeUs))
  const [effectDraft, setEffectDraft] = useState<EffectDraft>(blankEffect)
  const [effects, setEffects] = useState<InterventionEffect[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadPlans = useCallback(async () => {
    const response = await api.interventionPlans<{ plans: InterventionPlan[] }>(branchId)
    setPlans(response.plans)
  }, [branchId])

  useEffect(() => { void loadPlans().catch(reason => setError(reason instanceof Error ? reason.message : '干预计划加载失败')) }, [loadPlans])
  useEffect(() => { setEffectiveTime(String(simTimeUs)) }, [simTimeUs])

  const addEffect = () => {
    try {
      setEffects(current => [...current, buildEffect(effectDraft)])
      setEffectDraft(current => ({ ...blankEffect(), effect_type: current.effect_type }))
      setError(null)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '效果参数无效') }
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (!intent.trim() || !effects.length) return
    setBusy(true); setError(null)
    try {
      await api.draftInterventionPlan(branchId, {
        user_intent: intent,
        access_scope: { private_grants: [] },
        private_read_refs: [],
        stages: [{
          stage_id: `stage_${crypto.randomUUID()}`,
          effective_sim_time_us: Number(effectiveTime),
          background_order_flow_impact_milli: 0,
          effects,
          status: 'pending',
          failure_reason: null,
        }],
      })
      setIntent(''); setEffects([])
      await loadPlans()
    } catch (reason) { setError(reason instanceof Error ? reason.message : '干预计划起草失败') }
    finally { setBusy(false) }
  }

  const interpret = async () => {
    if (!intent.trim() || !provider) return
    setBusy(true); setError(null)
    try {
      await api.interpretInterventionPlan(branchId, intent, Number(effectiveTime), provider)
      setIntent(''); setEffects([])
      await loadPlans()
    } catch (reason) { setError(reason instanceof Error ? reason.message : 'Scenario Director 生成失败') }
    finally { setBusy(false) }
  }

  const decide = async (planId: string, decision: 'confirm' | 'reject') => {
    setBusy(true); setError(null)
    try {
      if (decision === 'confirm') await api.confirmInterventionPlan(branchId, planId)
      else await api.rejectInterventionPlan(branchId, planId)
      await Promise.all([loadPlans(), onChanged()])
    } catch (reason) { setError(reason instanceof Error ? reason.message : '计划状态更新失败') }
    finally { setBusy(false) }
  }

  const paused = branchStatus === 'Paused'
  return <div className="intervention-workspace">
    <form className="workspace-panel intervention-builder" onSubmit={submit}>
      <div className="panel-heading"><div><h2>情景干预</h2><p><StatusBadge status={branchStatus} /> · t={simTimeUs}</p></div><Send size={18} /></div>
      {error ? <div className="inline-error"><CircleAlert size={15} />{error}</div> : null}
      <div className="intervention-form">
        <label>用户指令<textarea value={intent} onChange={event => setIntent(event.target.value)} maxLength={4000} disabled={!paused || busy} /></label>
        <label>生效时间<input type="number" min={simTimeUs} step="1" value={effectiveTime} onChange={event => setEffectiveTime(event.target.value)} disabled={!paused || busy} /></label>
        <label>效果类型<select value={effectDraft.effect_type} onChange={event => setEffectDraft(current => ({ ...current, effect_type: event.target.value as EffectKind }))} disabled={!paused || busy}>
          <option value="publish_information">发布信息</option><option value="transfer_asset">资产转移</option><option value="set_market_status">市场状态</option><option value="set_account_freeze">账户冻结</option><option value="set_wallet_access">钱包访问</option><option value="create_world_entity">创建实体</option><option value="create_relationship">创建关系</option>
        </select></label>
        {effectDraft.effect_type === 'publish_information' ? <>
          <label>频道<select value={effectDraft.channel} onChange={event => setEffectDraft(current => ({ ...current, channel: event.target.value as EffectDraft['channel'] }))}><option>PublicFeed</option><option>OfficialAnnouncement</option><option>TradingTerminal</option><option>PrivateChannel</option></select></label>
          <label className="full-field">内容<textarea value={effectDraft.content} onChange={event => setEffectDraft(current => ({ ...current, content: event.target.value }))} maxLength={4000} /></label>
          {effectDraft.channel === 'PrivateChannel' ? <label className="full-field">接收 Agent<input value={effectDraft.target_ids} onChange={event => setEffectDraft(current => ({ ...current, target_ids: event.target.value }))} /></label> : null}
        </> : null}
        {effectDraft.effect_type === 'transfer_asset' ? <><label>来源账户<input value={effectDraft.from_owner_id} onChange={event => setEffectDraft(current => ({ ...current, from_owner_id: event.target.value }))} /></label><label>目标账户<input value={effectDraft.to_owner_id} onChange={event => setEffectDraft(current => ({ ...current, to_owner_id: event.target.value }))} /></label><label>资产<input value={effectDraft.asset} onChange={event => setEffectDraft(current => ({ ...current, asset: event.target.value }))} /></label><label>数量<input type="number" min="1" value={effectDraft.amount} onChange={event => setEffectDraft(current => ({ ...current, amount: event.target.value }))} /></label></> : null}
        {effectDraft.effect_type === 'set_market_status' ? <><label>市场<input value={effectDraft.market_id} onChange={event => setEffectDraft(current => ({ ...current, market_id: event.target.value }))} /></label><label>状态<select value={effectDraft.status} onChange={event => setEffectDraft(current => ({ ...current, status: event.target.value as EffectDraft['status'] }))}><option value="active">Active</option><option value="halted">Halted</option></select></label></> : null}
        {effectDraft.effect_type === 'set_account_freeze' ? <><label>账户<input value={effectDraft.owner_id} onChange={event => setEffectDraft(current => ({ ...current, owner_id: event.target.value }))} /></label><label className="toggle-field"><input type="checkbox" checked={effectDraft.frozen} onChange={event => setEffectDraft(current => ({ ...current, frozen: event.target.checked }))} />冻结</label></> : null}
        {effectDraft.effect_type === 'set_wallet_access' ? <><label>钱包账户<input value={effectDraft.wallet_owner_id} onChange={event => setEffectDraft(current => ({ ...current, wallet_owner_id: event.target.value }))} /></label><label>获权 Agent<input value={effectDraft.grantee_agent_id} onChange={event => setEffectDraft(current => ({ ...current, grantee_agent_id: event.target.value }))} /></label><label>权限<select value={effectDraft.permissions.join(',')} onChange={event => setEffectDraft(current => ({ ...current, permissions: event.target.value.split(',') as EffectDraft['permissions'] }))}><option value="observe">Observe</option><option value="observe,transact">Observe + transact</option><option value="">Revoke</option></select></label></> : null}
        {effectDraft.effect_type === 'create_world_entity' ? <><label>实体 ID<input value={effectDraft.entity_id} onChange={event => setEffectDraft(current => ({ ...current, entity_id: event.target.value }))} /></label><label>实体类型<select value={effectDraft.entity_type} onChange={event => setEffectDraft(current => ({ ...current, entity_type: event.target.value as EffectDraft['entity_type'] }))}><option value="institution">Institution</option><option value="venue">Venue</option><option value="wallet">Wallet</option></select></label><label className="full-field">显示名称<input value={effectDraft.display_name} onChange={event => setEffectDraft(current => ({ ...current, display_name: event.target.value }))} /></label></> : null}
        {effectDraft.effect_type === 'create_relationship' ? <><label>关系 ID<input value={effectDraft.relationship_id} onChange={event => setEffectDraft(current => ({ ...current, relationship_id: event.target.value }))} /></label><label>关系类型<select value={effectDraft.relationship_type} onChange={event => setEffectDraft(current => ({ ...current, relationship_type: event.target.value as EffectDraft['relationship_type'] }))}><option value="wallet_control">Wallet control</option><option value="custody">Custody</option><option value="exposure">Exposure</option></select></label><label>来源实体<input value={effectDraft.source_entity_id} onChange={event => setEffectDraft(current => ({ ...current, source_entity_id: event.target.value }))} /></label><label>目标实体<input value={effectDraft.target_entity_id} onChange={event => setEffectDraft(current => ({ ...current, target_entity_id: event.target.value }))} /></label>{effectDraft.relationship_type === 'exposure' ? <><label>资产<input value={effectDraft.asset} onChange={event => setEffectDraft(current => ({ ...current, asset: event.target.value }))} /></label><label>数量<input type="number" min="0" value={effectDraft.amount} onChange={event => setEffectDraft(current => ({ ...current, amount: event.target.value }))} /></label></> : null}</> : null}
        {effectDraft.effect_type !== 'publish_information' ? <label className="full-field">原因代码<input value={effectDraft.reason_code} onChange={event => setEffectDraft(current => ({ ...current, reason_code: event.target.value }))} /></label> : null}
        <button className="secondary-button add-effect" type="button" onClick={addEffect} disabled={!paused || busy}><Plus size={15} />添加效果</button>
      </div>
      <div className="effect-queue">{effects.map(effect => <div key={effect.effect_id}><span>{effectLabel(effect)}</span><code>{shortId(effect.effect_id)}</code><button type="button" title="移除效果" aria-label="移除效果" onClick={() => setEffects(current => current.filter(item => item.effect_id !== effect.effect_id))}><Trash2 size={14} /></button></div>)}</div>
      <div className="draft-actions"><button className="secondary-button" type="button" onClick={() => void interpret()} disabled={!paused || busy || !intent.trim() || !provider}><Sparkles size={15} />AI 生成</button><button className="primary-button" type="submit" disabled={!paused || busy || !intent.trim() || !effects.length}>生成 Draft</button></div>
    </form>
    <section className="workspace-panel intervention-plans">
      <div className="panel-heading"><div><h2>干预计划</h2><p>{plans.length} 个计划</p></div><Check size={18} /></div>
      {!plans.length ? <EmptyState title="暂无干预计划" /> : <div className="plan-list">{[...plans].reverse().map(plan => <article key={plan.plan_id}>
        <header><div><strong>{plan.director_record.submitted_intent}</strong><small>{shortId(plan.plan_id)} · 世界版本 {plan.base_world_revision}</small></div><StatusBadge status={plan.status} /></header>
        <div className="plan-stage-line">{plan.stages.map(stage => <span key={stage.stage_id}>模拟时间 {stage.effective_sim_time_us} · {stageStatusText(stage.status)} · {stage.effects.length} 项效果</span>)}</div>
        {plan.stages.map(stage => <p className="market-impact-summary" key={`${stage.stage_id}-market-impact`}>对未来订单流：{marketImpactText(stage.background_order_flow_impact_milli)}</p>)}
        {plan.preview.filter(item => item.effect_type !== 'background_order_flow_impact').map(item => <p key={item.effect_id}>{item.summary}</p>)}
        {plan.status === 'draft' ? <footer><button className="secondary-button" onClick={() => void decide(plan.plan_id, 'reject')} disabled={!paused || busy}><Ban size={14} />拒绝</button><button className="primary-button" onClick={() => void decide(plan.plan_id, 'confirm')} disabled={!paused || busy}><Check size={14} />确认</button></footer> : null}
      </article>)}</div>}
    </section>
  </div>
}
