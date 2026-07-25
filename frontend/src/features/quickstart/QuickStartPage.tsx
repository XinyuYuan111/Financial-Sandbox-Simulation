import { useEffect, useMemo, useState } from 'react'
import { Check, CheckCircle2, Database, KeyRound, Link2, LoaderCircle, Play, RefreshCw, RotateCcw, ShieldAlert, X, Zap } from 'lucide-react'
import { api } from '../../api'
import type {
  AgentConfigurationDraft,
  ChainOption,
  ChainPreflight,
  ParticipantArchetype,
  ProviderProfile,
  ResolvedPreview,
  Run,
} from '../../types'
import { ErrorBanner, formatInteger, StatusBadge } from '../../components/ui'

type Mode = 'test_fixture' | 'live_llm_smoke' | 'live'
type InputMode = 'random' | 'natural_language' | 'detailed'

const BUILT_IN_CHAINS: ChainOption[] = [
  { chain_id: 'ethereum', label: 'Ethereum', holder_source_configured: false },
  { chain_id: 'solana', label: 'Solana', holder_source_configured: false },
  { chain_id: 'injective', label: 'Injective L1', holder_source_configured: false },
]

const asOptionalInteger = (value: string) => value.trim() ? Number.parseInt(value, 10) : null
const populationPreset = (count: number) => count <= 4 ? 'smoke' : count <= 20 ? 'compact' : 'standard'

export function QuickStartPage({ onRun, embedded = false }: { onRun: (run: Run) => void; embedded?: boolean }) {
  const [mode, setMode] = useState<Mode>('test_fixture')
  const [inputMode, setInputMode] = useState<InputMode>('random')
  const [name, setName] = useState('Agent 市场实验')
  const [token, setToken] = useState('TOKEN')
  const [seed, setSeed] = useState(20260724)
  const [agentCount, setAgentCount] = useState(4)
  const [quoteCoverage, setQuoteCoverage] = useState(100)
  const [compositionCorrelation, setCompositionCorrelation] = useState(35)
  const [provider, setProvider] = useState('openai')
  const [chain, setChain] = useState('ethereum')
  const [chains, setChains] = useState<ChainOption[]>(BUILT_IN_CHAINS)
  const [providers, setProviders] = useState<ProviderProfile[]>([])
  const [archetypes, setArchetypes] = useState<ParticipantArchetype[]>([])
  const [selectedArchetypes, setSelectedArchetypes] = useState<string[]>(['ordinary_participant'])
  const [detailName, setDetailName] = useState('自定义参与者')
  const [detailRisk, setDetailRisk] = useState('500')
  const [detailHorizon, setDetailHorizon] = useState<'short' | 'medium' | 'long'>('medium')
  const [detailToken, setDetailToken] = useState('')
  const [detailUsdx, setDetailUsdx] = useState('')
  const [naturalIntent, setNaturalIntent] = useState('')
  const [interpretedDraft, setInterpretedDraft] = useState<AgentConfigurationDraft | null>(null)
  const [preflight, setPreflight] = useState<Record<string, unknown> | null>(null)
  const [preview, setPreview] = useState<ResolvedPreview | null>(null)
  const [chainPreflight, setChainPreflight] = useState<ChainPreflight | null>(null)
  const [chainPreflightLoading, setChainPreflightLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api.providers<ProviderProfile[]>().then(items => {
      setProviders(items)
      setProvider(current => {
        const currentProfile = items.find(item => item.provider === current)
        return currentProfile?.key_present
          ? current
          : items.find(item => item.key_present)?.provider ?? currentProfile?.provider ?? items[0]?.provider ?? current
      })
    }).catch(() => setProviders([]))
    api.chains<ChainOption[]>().then(setChains).catch(() => setChains(BUILT_IN_CHAINS))
    api.agentArchetypes<{ archetypes: ParticipantArchetype[] }>().then(result => setArchetypes(result.archetypes)).catch(() => setArchetypes([]))
  }, [])

  const selectedProvider = useMemo(() => providers.find(item => item.provider === provider), [provider, providers])
  const selectedChain = useMemo(() => chains.find(item => item.chain_id === chain) ?? BUILT_IN_CHAINS[0], [chain, chains])
  const needsProvider = mode !== 'test_fixture' || inputMode === 'natural_language'
  const unresolvedSuggestions = interpretedDraft?.suggestions.filter(item => (
    !interpretedDraft.accepted_suggestion_ids.includes(item.suggestion_id)
    && !interpretedDraft.declined_suggestion_ids.includes(item.suggestion_id)
  )) ?? []

  const invalidate = () => {
    setPreview(null)
    setChainPreflight(null)
  }
  const switchMode = (next: Mode) => {
    setMode(next)
    if (next === 'live_llm_smoke') setAgentCount(4)
    setPreview(null)
    setPreflight(null)
    setChainPreflight(null)
  }

  const explorerUrl = (chainId: string, tokenAddress: string | undefined) => {
    if (!tokenAddress) return undefined
    if (chainId === 'injective') return `https://testnet.explorer.injective.network/contract/${tokenAddress}`
    if (chainId === 'ethereum') return `https://etherscan.io/address/${tokenAddress}`
    if (chainId === 'solana') return `https://explorer.solana.com/address/${tokenAddress}`
    return undefined
  }

  useEffect(() => {
    if (mode !== 'live' || !selectedChain.holder_source_configured) {
      setChainPreflight(null)
      return
    }
    let cancelled = false
    setChainPreflightLoading(true)
    api.chainPreflight<ChainPreflight>(selectedChain.chain_id, token.trim().toUpperCase())
      .then(report => { if (!cancelled) setChainPreflight(report) })
      .catch(() => { if (!cancelled) setChainPreflight({ ok: false, chain_id: selectedChain.chain_id, message: '链上数据源检查失败' }) })
      .finally(() => { if (!cancelled) setChainPreflightLoading(false) })
    return () => { cancelled = true }
  }, [mode, selectedChain.chain_id, selectedChain.holder_source_configured, token])

  const switchInputMode = (next: InputMode) => {
    setInputMode(next)
    setPreview(null)
  }

  const checkProvider = async () => {
    setBusy(true); setError(null)
    try { setPreflight(await api.providerPreflight<Record<string, unknown>>(provider)) }
    catch (reason) { setPreflight(null); setError(reason instanceof Error ? reason.message : 'Provider 检查失败') }
    finally { setBusy(false) }
  }

  const interpret = async () => {
    if (!naturalIntent.trim()) return
    setBusy(true); setError(null); setPreview(null)
    try {
      const result = await api.interpretAgentConfiguration<{ draft: AgentConfigurationDraft }>(naturalIntent.trim(), provider)
      setInterpretedDraft(result.draft)
    } catch (reason) { setError(reason instanceof Error ? reason.message : '自然语言解析失败') }
    finally { setBusy(false) }
  }

  const setSuggestionDisposition = (suggestionId: string, disposition: 'accept' | 'decline') => {
    if (!interpretedDraft) return
    const accepted = interpretedDraft.accepted_suggestion_ids.filter(id => id !== suggestionId)
    const declined = interpretedDraft.declined_suggestion_ids.filter(id => id !== suggestionId)
    setInterpretedDraft({
      ...interpretedDraft,
      accepted_suggestion_ids: disposition === 'accept' ? [...accepted, suggestionId] : accepted,
      declined_suggestion_ids: disposition === 'decline' ? [...declined, suggestionId] : declined,
    })
    setPreview(null)
  }

  const detailedDraft = (): Record<string, unknown> => ({
    draft_id: 'detailed-agent-1',
    input_mode: 'detailed',
    agent_id: 'custom_agent_1',
    display_name: detailName.trim() || '自定义参与者',
    archetype_ids: selectedArchetypes,
    base_persona: {
      risk_tolerance_milli: Number(detailRisk),
      time_horizon: detailHorizon,
    },
    portfolio: {
      token_amount: asOptionalInteger(detailToken),
      usdx_amount: asOptionalInteger(detailUsdx),
    },
  })

  const resolve = async () => {
    if (inputMode === 'natural_language' && (!interpretedDraft || unresolvedSuggestions.length)) return
    setBusy(true); setError(null)
    try {
      const count = mode === 'live_llm_smoke' ? Math.min(agentCount, 4) : agentCount
      const scenario = await api.createScenario<{ scenario_id: string }>({
        name,
        mode,
        seed,
        target_token: token.trim().toUpperCase(),
        chain_id: mode === 'live' ? chain : null,
        llm_provider: mode === 'test_fixture' ? null : provider,
        population: inputMode === 'random'
          ? { preset: populationPreset(count), agent_count: count }
          : { preset: 'smoke' },
        portfolio: {
          token_distribution: 'long_tail',
          quote_coverage_ratio_ppm: Math.round(quoteCoverage * 10_000),
          token_usdx_correlation_milli: Math.round(compositionCorrelation * 10),
        },
        agent_configuration_drafts: inputMode === 'natural_language'
          ? [interpretedDraft]
          : inputMode === 'detailed' ? [detailedDraft()] : null,
      })
      setPreview(await api.resolveScenario<ResolvedPreview>(scenario.scenario_id))
    } catch (reason) { setError(reason instanceof Error ? reason.message : '场景解析失败') }
    finally { setBusy(false) }
  }

  const start = async () => {
    if (!preview) return
    setBusy(true); setError(null)
    try { onRun(await api.createRun<Run>(preview.scenario_id, preview.resolution_hash)) }
    catch (reason) { setError(reason instanceof Error ? reason.message : '运行创建失败') }
    finally { setBusy(false) }
  }

  const toggleArchetype = (archetypeId: string) => {
    setSelectedArchetypes(current => current.includes(archetypeId)
      ? current.filter(item => item !== archetypeId)
      : [...current, archetypeId])
    setPreview(null)
  }

  const resetDetailed = () => {
    setSelectedArchetypes(['ordinary_participant'])
    setDetailName('自定义参与者')
    setDetailRisk('500')
    setDetailHorizon('medium')
    setDetailToken('')
    setDetailUsdx('')
    setPreview(null)
  }

  const resolveDisabled = busy || !name.trim() || !token.trim()
    || (mode === 'live' && !selectedChain.holder_source_configured)
    || (inputMode === 'natural_language' && (!interpretedDraft || unresolvedSuggestions.length > 0))
    || (inputMode === 'detailed' && (!selectedArchetypes.length || Number(detailRisk) < 0 || Number(detailRisk) > 1000))
  const previewAgents = preview?.agent_definitions.slice(0, 10) ?? []
  const allocationById = new Map(preview?.agents.map(agent => [agent.agent_id, agent]) ?? [])
  const previewAssets = preview?.preview.assets

  return <div className={`quickstart ${embedded ? 'embedded' : ''}`}>
    <header className="quickstart-header">
      <div><span className="eyebrow">Financial Sandbox</span><h1>Agent 市场实验</h1></div>
      <StatusBadge status={preview ? 'Ready' : 'Draft'} />
    </header>
    {mode === 'live' && selectedChain.holder_source_configured ? <div className="chain-status-bar">
      <span className="chain-badge"><Zap size={15} />Powered by {selectedChain.label}</span>
      {chainPreflight?.ok === true ? <>
        <span>代币: <b>{chainPreflight.token_symbol ?? token.trim().toUpperCase()}</b></span>
        <span>最新区块: <b>#{formatInteger(chainPreflight.latest_block ?? 0)}</b></span>
        <span>总供应量: <b>{formatInteger(chainPreflight.total_supply ?? 0)}</b></span>
      </> : <span className="chain-status-loading">{chainPreflightLoading ? <LoaderCircle className="spin" size={13} /> : null}读取链上数据源…</span>}
    </div> : null}
    {error ? <ErrorBanner message={error} onClose={() => setError(null)} /> : null}
    <div className="quickstart-grid">
      <section className="setup-panel">
        <div className="section-title"><div><h2>运行配置</h2><p>framework-alpha · agent-definition.v0.2</p></div><Database size={19} /></div>
        <label>实验名称<input value={name} maxLength={128} onChange={event => { setName(event.target.value); invalidate() }} /></label>
        <div className="field-group"><span>运行模式</span><div className="segmented three">
          <button className={mode === 'test_fixture' ? 'selected' : ''} onClick={() => switchMode('test_fixture')}>Fixture</button>
          <button className={mode === 'live_llm_smoke' ? 'selected' : ''} onClick={() => switchMode('live_llm_smoke')}>LLM 烟测</button>
          <button className={mode === 'live' ? 'selected' : ''} onClick={() => switchMode('live')}>Live</button>
        </div></div>
        <div className="field-group"><span>Agent 输入</span><div className="segmented three">
          <button className={inputMode === 'random' ? 'selected' : ''} onClick={() => switchInputMode('random')}>随机生成</button>
          <button className={inputMode === 'natural_language' ? 'selected' : ''} onClick={() => switchInputMode('natural_language')}>自然语言</button>
          <button className={inputMode === 'detailed' ? 'selected' : ''} onClick={() => switchInputMode('detailed')}>详细配置</button>
        </div></div>
        <div className="form-row"><label>目标资产<input value={token} onChange={event => { setToken(event.target.value); invalidate() }} /></label><label>随机种子<input type="number" value={seed} onChange={event => { setSeed(Number(event.target.value)); invalidate() }} /></label></div>

        {inputMode === 'random' ? <label>Agent 数量<input type="number" min={1} max={mode === 'live_llm_smoke' ? 4 : 10000} value={agentCount} onChange={event => { setAgentCount(Math.max(1, Number(event.target.value))); invalidate() }} /></label> : null}

        {inputMode === 'natural_language' ? <div className="config-editor">
          <label>参与者描述<textarea value={naturalIntent} maxLength={4000} onChange={event => { setNaturalIntent(event.target.value); setInterpretedDraft(null); invalidate() }} /></label>
          <button className="secondary-button wide" onClick={interpret} disabled={busy || !naturalIntent.trim()}>{busy ? <LoaderCircle className="spin" size={15} /> : <RefreshCw size={15} />}解析描述</button>
          {interpretedDraft ? <div className="interpretation-result">
            <div className="interpretation-heading"><strong>{interpretedDraft.display_name ?? '未命名参与者'}</strong><StatusBadge status={unresolvedSuggestions.length ? 'Pending' : 'Confirmed'} /></div>
            {interpretedDraft.suggestions.map(suggestion => <div className="suggestion-row" key={suggestion.suggestion_id}>
              <span><b>{suggestion.kind}</b>{suggestion.value}<small>{suggestion.reason}</small></span>
              <div>
                <button className={interpretedDraft.accepted_suggestion_ids.includes(suggestion.suggestion_id) ? 'selected' : ''} title="接受建议" onClick={() => setSuggestionDisposition(suggestion.suggestion_id, 'accept')}><Check size={14} /></button>
                <button className={interpretedDraft.declined_suggestion_ids.includes(suggestion.suggestion_id) ? 'selected decline' : ''} title="拒绝建议" onClick={() => setSuggestionDisposition(suggestion.suggestion_id, 'decline')}><X size={14} /></button>
              </div>
            </div>)}
            {interpretedDraft.ambiguities.map(item => <div className="warning-line" key={item}>{item}</div>)}
          </div> : null}
        </div> : null}

        {inputMode === 'detailed' ? <div className="config-editor">
          <div className="editor-heading"><strong>Participant Archetype</strong><button className="icon-button" title="重置详细配置" onClick={resetDetailed}><RotateCcw size={15} /></button></div>
          <div className="archetype-options">{archetypes.map(archetype => <label className="check-option" key={archetype.archetype_id}><input type="checkbox" checked={selectedArchetypes.includes(archetype.archetype_id)} onChange={() => toggleArchetype(archetype.archetype_id)} /><span><b>{archetype.label}</b><small>{archetype.suggested_role_tags.join(', ')}</small></span></label>)}</div>
          <label>显示名称<input value={detailName} onChange={event => { setDetailName(event.target.value); invalidate() }} /></label>
          <div className="form-row"><label>风险承受度<input type="number" min={0} max={1000} value={detailRisk} onChange={event => { setDetailRisk(event.target.value); invalidate() }} /></label><label>时间周期<select value={detailHorizon} onChange={event => { setDetailHorizon(event.target.value as typeof detailHorizon); invalidate() }}><option value="short">短期</option><option value="medium">中期</option><option value="long">长期</option></select></label></div>
          <div className="form-row"><label>Token 数量<input type="number" min={0} placeholder="自动分配" value={detailToken} onChange={event => { setDetailToken(event.target.value); invalidate() }} /></label><label>USDx 数量<input type="number" min={0} placeholder="自动分配" value={detailUsdx} onChange={event => { setDetailUsdx(event.target.value); invalidate() }} /></label></div>
        </div> : null}

        <div className="form-row"><label>报价覆盖率 (%)<input type="number" min={0.01} max={1000} step={1} value={quoteCoverage} onChange={event => { setQuoteCoverage(Number(event.target.value)); invalidate() }} /></label><label>Token / USDx 相关度 (%)<input type="number" min={0} max={100} value={compositionCorrelation} onChange={event => { setCompositionCorrelation(Number(event.target.value)); invalidate() }} /></label></div>

        {needsProvider ? <>
          <div className="form-row"><label>Provider<select value={provider} onChange={event => { setProvider(event.target.value); setPreflight(null); invalidate() }}>{providers.length ? providers.map(item => <option value={item.provider} key={item.provider}>{item.provider} · {item.model ?? 'default'}</option>) : <option value="openai">openai</option>}</select></label>{mode === 'live' ? <label>链数据源<select value={chain} onChange={event => { setChain(event.target.value); invalidate() }}>{chains.map(item => <option value={item.chain_id} key={item.chain_id} disabled={!item.holder_source_configured}>{item.label}{item.holder_source_configured ? '' : ' · 未配置 holder snapshot'}</option>)}</select></label> : <span />}</div>
          <div className="provider-line"><span><KeyRound size={16} />服务端密钥</span><StatusBadge status={selectedProvider?.key_present ? 'ok' : 'missing'} /><button className="secondary-button" onClick={checkProvider} disabled={busy}><RefreshCw size={15} />检查</button></div>
          {preflight?.ok === true ? <div className="success-line"><CheckCircle2 size={16} />{String(preflight.provider)} · {String(preflight.model ?? 'default')} 可用</div> : null}
          {mode === 'live' && !selectedChain.holder_source_configured ? <div className="warning-line">{selectedChain.label} 已在固定链目录中，但当前进程没有配置该链的 finalized holder snapshot。</div> : null}
          {mode === 'live' && selectedChain.holder_source_configured ? <div className="chain-preflight-card">
            <div className="chain-preflight-header">
              <Database size={16} />
              <strong>{selectedChain.label} 链上数据源</strong>
              {chainPreflight?.ok === true ? <StatusBadge status="ok" /> : chainPreflightLoading ? <StatusBadge status="Pending" /> : <StatusBadge status="error" />}
            </div>
            {chainPreflight?.ok === true ? <div className="chain-preflight-body">
              <div className="chain-preflight-row"><span>Provider</span><b>{String(chainPreflight.provider)}</b></div>
              <div className="chain-preflight-row"><span>代币符号</span><b>{chainPreflight.token_symbol ?? '-'}</b></div>
              <div className="chain-preflight-row"><span>合约地址</span>
                {chainPreflight.token_address ? <a href={explorerUrl(selectedChain.chain_id, chainPreflight.token_address)} target="_blank" rel="noreferrer" className="chain-address-link"><Link2 size={12} />{chainPreflight.token_address.slice(0, 8)}…{chainPreflight.token_address.slice(-6)}</a> : <b>-</b>}
              </div>
              <div className="chain-preflight-row"><span>Decimals</span><b>{chainPreflight.decimals ?? '-'}</b></div>
              <div className="chain-preflight-row"><span>总供应量</span><b>{formatInteger(chainPreflight.total_supply ?? 0)}</b></div>
              <div className="chain-preflight-row"><span>最新区块</span><b>#{formatInteger(chainPreflight.latest_block ?? 0)}</b></div>
            </div> : <div className="chain-preflight-body">
              <div className="warning-line">{chainPreflightLoading ? '正在连接链上数据源…' : chainPreflight?.message ?? '链上数据源预检失败'}</div>
            </div>}
          </div> : null}
          {mode !== 'test_fixture' ? <div className="cost-warning"><ShieldAlert size={17} /><span>{mode === 'live_llm_smoke' ? '使用 seed 合成 Token、USDx 与背景余量，不需要 holder snapshot；最多 4 个 Agent。' : 'Live 模式会使用真实 Provider 和 holder snapshot。'}</span></div> : null}
        </> : <div className="fixture-note"><CheckCircle2 size={17} /><span>确定性本地链路，不调用外部 Provider。</span></div>}
        <button className="primary-button wide" onClick={resolve} disabled={resolveDisabled}>{busy ? <LoaderCircle className="spin" size={17} /> : <RefreshCw size={17} />}解析初始状态</button>
      </section>

      <section className="preview-panel">
        <div className="section-title"><div><h2>解析预览</h2><p>{preview?.preset_version ?? '等待配置确认'}</p></div>{preview ? <CheckCircle2 size={19} /> : <Database size={19} />}</div>
        {preview ? <>
          <div className="fact-grid"><div><span>显式 Agent</span><strong>{preview.agent_definitions.length}</strong></div><div><span>Eligible Active</span><strong>{formatInteger(preview.chain_snapshot.eligible_active_supply)}</strong></div><div><span>Token 总量</span><strong>{formatInteger(preview.total_supply[preview.market.base_asset])}</strong></div><div><span>Active USDx</span><strong>{formatInteger(preview.total_supply[preview.market.quote_asset])}</strong></div></div>
          <div className="preview-table table-scroll"><table><thead><tr><th>Agent</th><th>角色</th><th>Token / USDx</th><th>风险 / 周期</th><th>配置来源</th></tr></thead><tbody>{previewAgents.map(agent => { const allocation = allocationById.get(agent.agent_id); const sources = [...new Set(Object.values(agent.configuration_provenance).map(item => item.source))]; return <tr key={agent.agent_id}><td><strong>{agent.display_name}</strong><small>{agent.agent_id}</small></td><td>{agent.role_tags.join(', ') || '-'}</td><td>{formatInteger(allocation?.token_balance ?? 0)} / {formatInteger(allocation?.usdx_balance ?? 0)}</td><td>{agent.base_persona.risk_tolerance_milli} / {agent.base_persona.time_horizon}</td><td>{sources.join(', ')}</td></tr> })}</tbody></table>{preview.agent_definitions.length > previewAgents.length ? <div className="table-more">另有 {preview.agent_definitions.length - previewAgents.length} 个 Agent</div> : null}</div>
          <div className="conservation-grid"><div><span>Token 守恒</span><StatusBadge status={previewAssets?.token_conserved ? 'ok' : 'error'} /></div><div><span>USDx 守恒</span><StatusBadge status={previewAssets?.usdx_conserved ? 'ok' : 'error'} /></div></div>
          <div className="source-table table-scroll"><table><thead><tr><th>Token 来源桶</th><th>分类</th><th>数量</th><th>Active</th></tr></thead><tbody>{preview.chain_snapshot.source_buckets.map(bucket => <tr key={bucket.bucket_id}><td>{bucket.bucket_id}</td><td>{bucket.category}</td><td>{formatInteger(bucket.amount)}</td><td>{bucket.eligible_for_active_market ? '是' : '否'}</td></tr>)}</tbody></table></div>
          <div className="background-row"><span>背景市场余量</span><b>{formatInteger(preview.background_market_sector.token_balance)} {preview.market.base_asset}</b><b>{formatInteger(preview.background_market_sector.usdx_balance)} {preview.market.quote_asset}</b></div>
          <div className="resolution-line"><span>确认哈希</span><code>{preview.resolution_hash}</code></div>
          {preview.warnings.map(warning => <div className="warning-line" key={warning}>{warning}</div>)}
          <button className="primary-button wide" onClick={start} disabled={busy || !preview.background_market_sector.two_sided_ready}><Play size={17} />确认并创建运行</button>
        </> : <div className="preview-placeholder"><Database size={28} /><strong>尚未解析</strong><span>解析后显示 Agent、资产来源、背景余量与守恒结果。</span></div>}
      </section>
    </div>
  </div>
}
