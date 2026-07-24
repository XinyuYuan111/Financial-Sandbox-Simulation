# Agent Design

本文档定义 Agent 初始化与用户配置的产品设计。它补充 `CONTEXT_AGENT.md`、`CONTEXT_SANDBOX.md`、`docs/grilling-decisions.md` 和 Agent v0.1 实施方案；已确认的既有决策优先于本文件中的待决问题。

## 目标

用户可以用简短自然语言或结构化配置创建一个可正常初始化的 Agent。系统将输入编译为完整、可校验、可保存、可回放的 `AgentDefinition`，而不是把用户文本直接当作运行时 Prompt 或 World Action。

## 已确认边界

### Agent 不是运行时角色子类

所有显式 Agent 使用同一固定 Agent Decision Pipeline，并保持 Persona、Observation、Memory、Belief、预算、Strategy、请求上下文和随机流隔离。当前不引入散户类、巨鲸类、庄家类或做市商类的专用运行时子类。

### 用户入口使用 Participant Archetype

用户界面可以提供可组合的 `Participant Archetype` 预设。首批预设建议为：

- 普通参与者（散户）
- 资本型持有者（巨鲸倾向）
- 流动性提供者（做市倾向）
- 资产发行方
- 信息参与者

这些名称是用户可理解的入口，不是互斥的领域类型。一个 Agent 可以拥有多个 `Role Tag`。`CapabilitySet` 独立表达硬权限；`BasePersona` 表达行为倾向；资产由 Portfolio 配置表达；运行后的行为类别由事件派生。

“庄家”或“操纵者”不作为首批类别。它描述目标、策略或行为假设，应该进入 Persona 的有限目标/倾向字段，并由实际事件验证，不能由名称直接授予权限或宣称行为事实。

### Archetype 只展开一次

选择 `Participant Archetype` 只会生成一份配置草稿，不会让 Agent 持续继承或绑定整套预设。`Role Tags`、`CapabilitySet`、`BasePersona`、`CognitiveProfile` 和 `AttentionProfile` 在展开后可以独立编辑；资产数量与构成由独立的 Portfolio 配置处理。

用户切换 Archetype 时，系统只更新尚未被用户编辑的建议字段。已经编辑的字段必须保留，除非用户明确选择重置。每个最终字段保存 `Configuration Provenance`，来源至少区分 `default`、`archetype`、`random`、`user` 和 `llm_interpreted`；来源只用于 Preview、审计与重现，不参与运行时决策。

因此，“资金很少、偶尔提供流动性的业余交易者”可以同时具有流动性提供者 Role Tag 和相应报价 Capability，但拥有较小的独立 Portfolio；选择流动性提供者 Archetype 不得强迫其成为资本充足的专业做市商。

### 三种输入共用一条编译管线

`Random`、自然语言和详细配置都生成相同 Schema 的 `Agent Configuration Draft`，再交给同一个确定性的 `Agent Configuration Compiler`：

```text
输入意图
  -> Agent Configuration Draft
  -> 补齐版本化默认值
  -> 字段与跨字段约束校验
  -> Resolved Initial State Preview
  -> 用户确认
  -> 冻结 AgentDefinition
```

三种入口仅改变草稿字段的来源：

- `Random` 使用命名 seed，从版本化模板与合法范围采样。
- 自然语言由受限 LLM Interpreter 转为结构化草稿，并标注推断、歧义和未设置字段。
- 详细配置直接编辑同一个草稿 Schema。

LLM Interpreter 不是可运行 Agent，也不是第二套初始化器。它不能直接冻结 `AgentDefinition`、提交 `Resolved Initial State`、分配最终资产、授予 Capability 或绕过校验。给定相同 Draft、Compiler 版本、外部初始化输入与 seed，解析结果必须相同，不因草稿来自哪种入口而变化。

### 自然语言字段权限

自然语言解析遵循 `Configuration Field Authority`：

- **可直接提取**：用户明确陈述的 Persona 软字段，以及用户明确说出的数值或选择。比如“沉着冷静、略懂基础量化”可映射为风险、时间范围、趋势偏好和有限背景说明；“1000 USDx 和 10 个 Token”可形成待校验的用户资产输入。LLM 只负责解析，来源仍标为 `user`。
- **只能建议**：`Participant Archetype`、`Role Tags` 和 `CapabilitySet`。LLM 可以建议“流动性提供者”或某个受支持 Capability，但结果必须进入 Draft、显示理由/置信度/歧义并等待用户确认。Portfolio 方法和字段来源由 Compiler 根据实际配置记录，不由 LLM 建议。
- **禁止推断或直接写入**：链、目标 Token、链上持仓、资产来源、最终 Token/USDx 数量、钱包控制、未注册 Capability、任意字段、代码和可执行策略。缺少明确输入时保持未设置，交给版本化默认、seeded random、链解析器或用户补充。

“散户”不能让 LLM 自行决定余额；“做市商”不能自行取得未确认的权限；明确的资产数字可以被提取，但仍须经过链、资产、守恒和可执行性校验。

### 随机必须显式

配置空缺不等于允许随机：

- 普通配置和自然语言配置的空缺软字段使用版本化默认值或已选 Archetype 的建议值。
- 详细配置的空缺字段同样使用版本化默认值。
- 只有 `random` 入口或被用户逐字段标记为 `random` 的字段，才能使用命名 seed 从版本化合法分布采样。
- 链、目标 Token、资产来源和其他必需的受保护字段缺失时产生阻塞错误，不能用默认值、随机值或 LLM 推断补齐。

Preview 必须展开每个采样结果、分布版本、seed 来源与 Configuration Provenance。自然语言输入相同且未选择 Random 时，不应因为隐藏采样而产生另一种 Agent。

## 当前待决问题

1. 链与目标资产解析完成后，Token、USDx 和非活跃储备的初始分配如何在 UI 中表达并确认。

## 初始化原则

初始化必须逐字段解析，最终只允许完整的 `Resolved Initial State` 进入 Ready。所有自动采样、缩放、资产来源、能力授予、LLM Provider、容量估计和警告都必须在 Preview 中可见；任何失败不得静默改用其他数据源或模式。

Token 与 USDx 在初始化分配前后分别保持总量不变。链上地址只提供余额分位、活跃度、交易规模和集中度等初始特征；Agent 是合成角色，不是现实地址的数字孪生。交易所托管、桥、协议、锁仓、销毁和不确定地址进入来源桶，不直接创建为单一巨鲸 Agent。当前不设显式 Agent 与 Background Market Sector 的固定资本比例；显式 Agent 数量与场景可纳入的链上供给共同决定合成资产规模，背景承接未分配或未显式建模的可用余额，其他不可交易资产保留在对应来源桶。

初始化只允许在 Agent、Background Market Sector、费用账户、非活跃储备和合法来源桶之间转移既定资产。除显式记录的发行或销毁事实外，Compiler 不得增发、丢失、静默缩放或用折算净值代替逐资产守恒。Preview 必须分别证明：

```text
token_total_before == token_total_after
usdx_total_before  == usdx_total_after
```

Background Market Sector 必须拥有 Ledger 已记账的 Token 和 USDx 可用库存；Token 支持其卖单，USDx 支持其买单。任一侧为零时不能声称已初始化可提供双边订单流；背景订单与显式 Agent 一样需要锁定、结算并允许正常耗尽。

### 资产规模口径

原始链上 `totalSupply` 只作为 Token 守恒基准。显式 Agent 资产池使用 `Eligible Active Supply`，即完成来源分类后可进入本地市场的可交易供给；销毁、锁仓、协议/桥接约束和无法确认受益人的非活跃托管余额不得直接成为 Agent 自由余额。

用户配置的显式 Agent 数量决定 Eligible Active Supply 如何拆分成合成 Portfolio；未覆盖、未分配或不可交易余额进入来源桶或已记账背景储备，不设固定显式/背景资本比例。USDx 是沙盒合成资产，按本地可交易 Token、初始价格和 quote coverage 计算，不复制链上稳定币总量。

### 背景库存是显式 Agent 分配后的剩余

背景库存不按订单需求额外预留，也不从固定比例推导。先完成显式 Agent 的 Token 与 USDx 分配，再分别计算：

```text
background_token
  = eligible_active_token_supply - explicit_agent_token - other_explicit_token_accounts

background_usdx
  = active_usdx_supply - explicit_agent_usdx - other_explicit_usdx_accounts
```

两项剩余都必须来自已记账资产池，且不能为负。Background Market Sector 只有在两项都有可用余额时，才可同时提供卖单与买单；它不因订单需求获得额外 Token 或 USDx。

### Token 的 Agent 间分配

显式 Agent 数量 `N` 只决定创建多少个相互独立的 Portfolio；Eligible Active Supply 决定这些 Portfolio 可分配 Token 的总额。默认使用版本化 `Portfolio Synthesis Distribution`，依据链上 Holder 的余额分位、集中度等特征校准长尾形状，并通过命名 seed 稳定采样。

Role Tag、Participant Archetype、Persona 和 Capability 不自动决定财富，也不再使用普通参与者 7.5%、资本型 50%、流动性提供者 30% 等固定角色资金比例。Advanced 模式可以明确选择均匀分配或逐 Agent 手动金额，但最终仍必须满足整数最小单位、非负余额、可分配总额和 Token 守恒。

### USDx 总量与 Agent 间分配

场景级活跃 USDx 总量由用户可见的 `Quote Coverage Ratio` 决定：

```text
active_usdx_supply
  = eligible_active_token_supply
  * initial_mid_price
  * quote_coverage_ratio
```

该参数不由 Agent 类型、Persona 或 LLM 决定。个体自由 USDx 使用与 Token 独立但可相关的版本化 `Portfolio Composition Distribution` 分配，使初始 Portfolio 可分别偏 Token、偏 USDx 或相对均衡，而不是按 Token 持仓机械同比分配 USDx。

用户为某个 Agent 明确填写的 USDx 是硬约束并优先保留，剩余 USDx 再按分布分配。手动总额超过场景级活跃 USDx 总量时阻塞 Preview，不允许静默缩放。所有最终金额使用整数最小单位，并与背景账户、费用账户和储备一起满足 USDx 守恒。

## 设计记录

Q184 已确认：用户选择的分类是可组合的 `Participant Archetype` 产品预设，不是互斥的 Agent 运行时子类。该结论细化并复核了 `docs/grilling-decisions.md` 中 Q115 的既有边界。

Q185 已确认：Participant Archetype 是一次性展开的配置草稿，不是持续绑定的配置包。展开后的字段可以独立覆盖；切换 Archetype 不得静默覆盖用户已编辑字段，最终字段必须保存来源。

Q186 已确认：Random、自然语言与详细配置共用一个 Agent Configuration Draft 和一条 Agent Configuration Compiler 管线；LLM 只解释自然语言，不能直接初始化 Agent 或绕过 Preview 与校验。

Q187 已确认：自然语言 LLM 可以解析用户明确陈述的软 Persona 与明确数值；Archetype、Role Tags 和 CapabilitySet 只能作为待确认建议；链、资产来源、最终余额和未注册能力不得由 LLM 推断或直接写入。

Q188 已确认：普通空缺字段使用版本化默认或 Archetype 建议，只有显式 Random 字段才按命名 seed 采样；必需的受保护字段缺失会阻止解析。

Q190 已确认：废止固定的显式 Agent 70% / Background 30% 资本比例。显式 Agent 数量由用户配置，资产规模由链上可纳入场景的供给和版本化分布规则决定；背景部门只承接未分配、非活跃或未建模资产，不设固定资本比例。该结论取代旧日志中相关比例约束，但不取消 Token/USDx 守恒、来源桶和特殊地址边界。

Q191 已确认：资产规模口径使用来源分类后的 Eligible Active Supply，而不是原始链上 totalSupply。销毁、锁仓、协议/桥接约束和无法确认受益人的非活跃托管余额不得直接进入 Agent 自由余额；USDx 继续按本地可交易 Token、初始价格和 quote coverage 合成。

Q192 已确认：Agent 数量决定独立 Portfolio 个数，Eligible Active Supply 决定可分配 Token 总额；默认按链上 Holder 特征校准的版本化长尾分布拆分，不按角色固定分配财富。均匀与逐 Agent 手动金额只作为显式 Advanced 选项。

Q193 已确认：Quote Coverage Ratio 决定场景级活跃 USDx 总量；独立但可相关的 Portfolio Composition Distribution 决定各 Agent 的自由 USDx，避免与 Token 机械同比；用户明确 USDx 金额优先，超过总量时阻塞而不静默缩放。

Q194 已确认：删除 Funding Profile 正式字段，资金初始化方法和逐字段来源分别由 Portfolio 配置与 Configuration Provenance 表达。初始化分配前后 Token 与 USDx 总量必须分别不变；Background Market Sector 必须同时获得已记账 Token 与 USDx 可用库存，才能提供双边订单流。

Q195 已确认：背景库存是显式 Agent 分配完成后各资产池的剩余余额。目标 Token 的剩余来自 Eligible Active Supply；USDx 的剩余来自场景级 active_usdx_supply；背景不按订单需求或固定比例额外获得资产，且只有同时拥有两种已记账资产时才具备双边订单能力。
