import { useEffect, useMemo, useState } from 'react'
import { CheckCircle2, Database, KeyRound, LoaderCircle, Play, RefreshCw, ShieldAlert } from 'lucide-react'
import { api } from '../../api'
import type { ProviderProfile, ResolvedPreview, Run } from '../../types'
import { ErrorBanner, formatInteger, StatusBadge } from '../../components/ui'

type Mode = 'test_fixture' | 'live_llm_smoke' | 'live'
type Population = 'fixture' | 'smoke' | 'compact' | 'standard'

export function QuickStartPage({ onRun, embedded = false }: { onRun: (run: Run) => void; embedded?: boolean }) {
  const [mode, setMode] = useState<Mode>('test_fixture')
  const [population, setPopulation] = useState<Population>('fixture')
  const [name, setName] = useState('Agent 市场实验')
  const [token, setToken] = useState('TOKEN')
  const [seed, setSeed] = useState(20260724)
  const [provider, setProvider] = useState('openai')
  const [chain, setChain] = useState('ethereum')
  const [providers, setProviders] = useState<ProviderProfile[]>([])
  const [preflight, setPreflight] = useState<Record<string, unknown> | null>(null)
  const [preview, setPreview] = useState<ResolvedPreview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => { api.providers<ProviderProfile[]>().then(setProviders).catch(() => setProviders([])) }, [])

  const selectedProvider = useMemo(() => providers.find(item => item.provider === provider), [provider, providers])

  const switchMode = (next: Mode) => {
    setMode(next)
    setPopulation(next === 'test_fixture' ? 'fixture' : next === 'live_llm_smoke' ? 'smoke' : 'compact')
    setPreview(null)
    setPreflight(null)
  }

  const checkProvider = async () => {
    setBusy(true); setError(null)
    try { setPreflight(await api.providerPreflight<Record<string, unknown>>(provider)) }
    catch (reason) { setPreflight(null); setError(reason instanceof Error ? reason.message : 'Provider 检查失败') }
    finally { setBusy(false) }
  }

  const resolve = async () => {
    setBusy(true); setError(null)
    try {
      const scenario = await api.createScenario<{ scenario_id: string }>({
        name,
        mode,
        seed,
        target_token: token.trim().toUpperCase(),
        chain_id: mode === 'live' ? chain : null,
        llm_provider: mode === 'test_fixture' ? null : provider,
        population: { preset: population },
      })
      setPreview(await api.resolveScenario<ResolvedPreview>(scenario.scenario_id))
    } catch (reason) { setError(reason instanceof Error ? reason.message : '场景解析失败') }
    finally { setBusy(false) }
  }

  const start = async () => {
    if (!preview) return
    setBusy(true); setError(null)
    try { onRun(await api.createRun<Run>(preview.scenario_id)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '运行创建失败') }
    finally { setBusy(false) }
  }

  return <div className={`quickstart ${embedded ? 'embedded' : ''}`}>
    <header className="quickstart-header">
      <div><span className="eyebrow">Financial Sandbox</span><h1>Agent 市场实验</h1></div>
      <StatusBadge status={preview ? 'Ready' : 'Draft'} />
    </header>
    {error ? <ErrorBanner message={error} onClose={() => setError(null)} /> : null}
    <div className="quickstart-grid">
      <section className="setup-panel">
        <div className="section-title"><div><h2>运行配置</h2><p>framework-alpha · agent.v0.1</p></div><Database size={19} /></div>
        <label>实验名称<input value={name} maxLength={128} onChange={event => { setName(event.target.value); setPreview(null) }} /></label>
        <div className="field-group"><span>运行模式</span><div className="segmented three">
          <button className={mode === 'test_fixture' ? 'selected' : ''} onClick={() => switchMode('test_fixture')}>Fixture</button>
          <button className={mode === 'live_llm_smoke' ? 'selected' : ''} onClick={() => switchMode('live_llm_smoke')}>LLM 烟测</button>
          <button className={mode === 'live' ? 'selected' : ''} onClick={() => switchMode('live')}>Live</button>
        </div></div>
        <div className="form-row"><label>目标资产<input value={token} onChange={event => { setToken(event.target.value); setPreview(null) }} /></label><label>随机种子<input type="number" value={seed} onChange={event => { setSeed(Number(event.target.value)); setPreview(null) }} /></label></div>
        {mode !== 'test_fixture' ? <>
          <div className="form-row"><label>Agent 规模<select value={population} onChange={event => { setPopulation(event.target.value as Population); setPreview(null) }} disabled={mode === 'live_llm_smoke'}>{mode === 'live_llm_smoke' ? <option value="smoke">Smoke · 4</option> : <><option value="compact">Compact · 20</option><option value="standard">Standard · 200</option></>}</select></label><label>规划 Provider<select value={provider} onChange={event => { setProvider(event.target.value); setPreflight(null); setPreview(null) }}>{providers.length ? providers.map(item => <option value={item.provider} key={item.provider}>{item.provider} · {item.model ?? 'default'}</option>) : <option value="openai">openai</option>}</select></label></div>
          {mode === 'live' ? <label>链数据源<select value={chain} onChange={event => { setChain(event.target.value); setPreview(null) }}><option value="ethereum">Ethereum</option><option value="solana">Solana</option></select></label> : null}
          <div className="provider-line"><span><KeyRound size={16} />服务端密钥</span><StatusBadge status={selectedProvider?.key_present ? 'ok' : 'missing'} /><button className="secondary-button" onClick={checkProvider} disabled={busy}><RefreshCw size={15} />检查连接</button></div>
          {preflight ? <div className="success-line"><CheckCircle2 size={16} />{String(preflight.provider)} · {String(preflight.model ?? 'default')} 可用</div> : null}
          <div className="cost-warning"><ShieldAlert size={17} /><span>{mode === 'live_llm_smoke' ? '最多 4 个初始规划请求；使用合成市场数据。' : 'Live 会产生真实 Provider 调用成本；Standard 规模默认创建 200 个 Agent。'}</span></div>
        </> : <div className="fixture-note"><CheckCircle2 size={17} /><span>确定性本地链路，不调用外部 Provider。</span></div>}
        <button className="primary-button wide" onClick={resolve} disabled={busy || !name.trim() || !token.trim()}>{busy ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}解析初始状态</button>
      </section>
      <section className="preview-panel">
        <div className="section-title"><div><h2>解析预览</h2><p>{preview?.preset_version ?? '等待配置确认'}</p></div>{preview ? <CheckCircle2 size={19} /> : <Database size={19} />}</div>
        {preview ? <>
          <div className="fact-grid"><div><span>显式 Agent</span><strong>{preview.agent_definitions.length}</strong></div><div><span>背景市场部门</span><strong>1</strong></div><div><span>Token 总量</span><strong>{formatInteger(preview.total_supply[token.toUpperCase()])}</strong></div><div><span>USDx 总量</span><strong>{formatInteger(preview.total_supply.USDx)}</strong></div></div>
          <div className="preview-table table-scroll"><table><thead><tr><th>Agent</th><th>资金画像</th><th>风险 / 周期</th><th>怀疑度</th><th>注意力</th><th>规划预算</th><th>延迟</th><th>能力</th></tr></thead><tbody>{preview.agent_definitions.map(agent => <tr key={agent.agent_id}><td><strong>{agent.display_name}</strong><small>{agent.agent_id}</small></td><td>{agent.funding_profile}</td><td>{agent.base_persona.risk_tolerance_milli} / {agent.base_persona.time_horizon}</td><td>{agent.base_persona.skepticism_milli}</td><td>{agent.attention_profile.information_capacity} · min {agent.attention_profile.minimum_salience}</td><td>{agent.cognitive_profile.max_plans_per_window} / {agent.cognitive_profile.memory_search_limit}</td><td>{agent.latency_profile.planning_latency_us} / {agent.latency_profile.action_latency_us}</td><td>{agent.capability_set.join(', ') || '-'}</td></tr>)}</tbody></table></div>
          <div className="background-row"><span>背景市场部门</span><b>{formatInteger(preview.background_market_sector.token_balance)} {token.toUpperCase()}</b><b>{formatInteger(preview.background_market_sector.usdx_balance)} USDx</b></div>
          {preview.warnings.map(warning => <div className="warning-line" key={warning}>{warning}</div>)}
          <button className="primary-button wide" onClick={start} disabled={busy}><Play size={17} />创建运行</button>
        </> : <div className="preview-placeholder"><Database size={28} /><strong>尚未解析</strong><span>配置通过校验后显示 Agent 分布和资产守恒结果。</span></div>}
      </section>
    </div>
  </div>
}
