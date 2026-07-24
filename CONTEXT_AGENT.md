# Agent 建模上下文

本上下文定义金融沙盒中自主参与者的统一语言，区分 Agent 的认知决策、角色配置与世界执行责任。

## Language

**Agent**:
沙盒中独立初始化的认知与决策主体。每个 Agent 拥有彼此隔离的 Persona、Observation、Memory、Belief、认知预算、策略状态与随机流。
_Avoid_: 角色类型、共享决策群组、LLM 会话

**Participant Archetype**:
面向用户的一次性可组合参与者预设，用于把身份标签、资金初始化建议、能力配置建议和 Persona 倾向展开为可独立编辑的配置草稿；它不是 Agent 的运行时子类、持续绑定的配置包，也不决定实际行为。
_Avoid_: Agent 子类、互斥硬类型、持续配置继承、资金档位

**Configuration Provenance**:
Agent 初始化草稿中每个最终字段的来源记录，区分版本化默认值、Archetype 建议、随机采样、用户输入和 LLM 解释。它只解释值从何而来，不参与 Agent 的运行时决策。
_Avoid_: 配置优先级实体、运行时 Persona、审计后补来源

**Agent Configuration Draft**:
Agent 初始化确认前使用的统一结构化草稿；Random、自然语言和详细配置都只是在该草稿中提供不同来源的候选字段。草稿不是可运行 Agent，只有经过默认补齐、确定性校验、Preview 和用户确认后才能冻结为 Agent Definition。
_Avoid_: 自由文本 Prompt、已初始化 Agent、三套输入 Schema

**Agent Configuration Compiler**:
统一初始化解析管线中把 Agent Configuration Draft 确定性解析为候选 Agent Definition 的边界。它补齐版本化默认值并校验字段与跨字段约束，但不调用 LLM 决定业务含义，也不绕过 Resolved Initial State Preview。
_Avoid_: 自治 Agent、LLM 配置者、第二套初始化器

**Configuration Field Authority**:
Agent 配置字段允许被谁提供或确认的边界：用户明确陈述可被解析，软倾向可由 LLM 建议，链状态、资产来源、最终余额和未注册能力必须由系统或用户显式确定。它不是运行时权限，也不允许 LLM 绕过初始化校验。
_Avoid_: LLM 全局写权限、Persona 继承权、隐式资产授予

**Explicit Randomization**:
只有被配置来源明确标记为随机的字段才可使用命名 seed 从版本化分布采样；普通空缺字段使用默认值或保持未设置。所有采样后的最终值和来源都必须在 Preview 中展开。
_Avoid_: 隐式随机、LLM 随机补全、未保存采样结果

**Eligible Active Supply**:
经过链上来源分类后允许进入本地市场并由显式 Agent 或已记账背景账户使用的可交易资产供给。它排除销毁、锁仓、协议/桥接约束和无法确认受益人的非活跃托管余额；原始链上总供给仍只作为守恒基准。
_Avoid_: 原始 totalSupply、全部流通量、未分类余额、即时购买力

**Portfolio Synthesis Distribution**:
把 Eligible Active Supply 拆分为指定数量合成 Portfolio 的版本化分布规则。默认规则由链上 Holder 的余额分位与集中度校准为可复现的长尾分布，但不复制真实地址身份，也不根据 Role Tag 或 Persona 固定财富。
_Avoid_: 角色资金比例、地址数字孪生、平均分配默认值

**Portfolio Composition Distribution**:
在场景级 Token 与 USDx 总额确定后，为各合成 Portfolio 分配资产构成的版本化规则。Token 与 USDx 的个体权重可以相关但不得机械同比，使不同 Agent 可呈现偏 Token、偏 USDx 或相对均衡的初始构成。
_Avoid_: 角色资产配比、Token 持仓同比 USDx、LLM 决定余额

**Role Tag**:
附着在 Agent 上的零个或多个身份与分析标签，例如普通参与者、资本型持有者、流动性提供者、资产发行方或信息参与者。Role Tag 只用于展示和分析，不能自动授予 Capability 或重复分配资产。
_Avoid_: 资金档位、Capability、行为结论

**Agent Component**:
Agent 作为沙盒参与者时的可配置决策边界；它只根据自身观察与私有状态形成提案，无权直接修改世界事实。
_Avoid_: 世界执行器、角色子类

**Agent Runtime**:
协调一个 Agent 单次决策循环的边界，保证该 Agent 的观察、认知状态和决策过程不与其他 Agent 混用。
_Avoid_: Agent 管理层级、共享认知上下文

**Agent Decision Pipeline**:
所有显式 Agent 共同遵循的固定决策骨架，从接收自身观察开始，经由记忆与信念、战略规划和即时反应形成 Action Proposal。各环节的实现和参数可以按 Agent 配置变化，但不得改成角色专属流程或任意拓扑。
_Avoid_: 可任意连线的认知图、角色专属生命周期

**Observation Packet**:
某个 Agent 在一个确定世界版本中经过权限、送达和注意力过滤后实际可用的不可变观察。它记录 Agent 当时知道什么，而不是全局世界状态的临时视图。
_Avoid_: World State、回放时重建的观察

**Agent Account Snapshot**:
ObservationService 在 Decision Opportunity 中为 Agent 提供的权威只读账户投影，包含其控制钱包的 PortfolioState revision、可用与预留余额、持仓，以及开放订单、Pending Action 和风险状态引用。它对控制者保证可见但不是 Agent 私有账本；Receipt 只关联结果状态引用，不能直接修改它。快照缺失或版本不一致时 Agent 进入 `hold_and_protect`，禁止建立新资源承诺。
_Avoid_: Agent 可写影子账本、从 Memory 或 Receipt 推算余额、向其他 Agent 暴露私有账户状态

**Decision Opportunity**:
一个已保存的 Observation Packet 触发对应 Agent 执行一次决策流程的确定性时机。`sim_time = 0` 的首次合法 Observation Packet 是每个可运行显式 Agent 的初始规划触发器；系统先完成当前观察屏障内的 World 事件并冻结版本，再把普通观察、定时、风险和规划结果等触发器聚合。初始计划生效前采用 `hold_and_protect`，Background Market Sector 不进入该流程。同一 `agent_id + observation_packet_id` 最多运行一次 Agent Runtime。不可见或无关事件不得通过唤醒 Agent 暴露其存在。
_Avoid_: 每事件唤醒、现实时间轮询

**Agent Decision**:
一次 Agent 决策流程产生的不可变审计记录，关联所用 Observation Packet 和 Agent 状态版本，并汇集记忆、信念、策略、动作及预算消耗提案。它记录 Agent 想要改变什么，不表示这些提案已经被接受或执行。异步规划完成后必须产生引用原决定和 Planning Request 的新 Agent Decision，不得回写原决定。
_Avoid_: Action 列表、直接状态变更

**Decision Rationale**:
Agent Decision 中受限、结构化的行为解释，通过目标、证据、信念、策略版本、风险、不确定性和动作提案引用说明决定依据。它不是完整思维链、权威事实或第二个 MemoryStore。
_Avoid_: 隐藏思维链、无限自由文本理由

**Agent Revision**:
Agent 整体认知状态的审计游标，用于关联历史、Checkpoint 和 Agent View。各可变认知组件另有自己的 revision，供提案声明真实依赖和进行冲突校验；整体 revision 不取代组件状态所有权。
_Avoid_: 单一并发版本、第二套状态真值

**Decision Outcome**:
Agent Decision 经各状态所有者校验后的完整结果。整体边界错误会拒绝整次决策；单个提案错误只影响自身及明确依赖项，而所有接受与拒绝结果必须作为一个不可分割的审计记录保存。
_Avoid_: 全部提案连带失败、未记录的部分提交

**Proposal Dependency**:
同一 Agent Decision 中后置提案对前置提案的显式依赖。依赖只能沿固定决策阶段向前引用；前置提案失败会使依赖项被拒绝，但不影响无依赖的其他提案。
_Avoid_: 隐式依赖、循环依赖、借依赖重排决策阶段

**Planning Budget Charge**:
一次 Planning Request 对预算造成的消耗。请求在实际规划开始前只预留并可释放 CognitiveBudget；规划开始后无论成功、失败、超时或过期都消耗该额度，同一认知决策的技术重试只按实际调用增加 ProviderBudget。
_Avoid_: 失败后返还认知额度、技术重试重复计算认知决策

**Strategy Plan**:
Agent 当前采用的版本化声明式计划。每个分支中的每个 Agent 只有一个活跃 revision；所有 Agent 共享统一 Envelope，记录来源观察、版本、有效范围、目标、必要前提、约束、类型化 Directive 和重规划条件。新计划声明所基于的 strategy revision，并以完整、自包含内容原子替换旧计划；历史 revision 不可变。实际可用 Directive 由 Capability 限制，并由 Reactive Controller 确定性解释；自然语言只能作为 Decision Rationale，不能参与控制流。
_Avoid_: 多活跃计划栈、隐式 Patch、角色专属计划类、自由 JSON、可执行代码

**Plan Condition**:
Strategy Plan 中类型化、版本化且只能引用 Agent 合法观察与私有状态的谓词。`activation_precondition` 只决定候选计划能否采用，`directive_guard` 只决定本轮是否解释某项 Directive，`constraint` 限制可提出的动作，`replan_condition` 只累积重规划原因；计划到期则进入无有效计划状态。Planning Request 记录的 Memory/Belief revisions 默认仅作审计依据；只有显式 activation precondition 才能要求稳定认知引用在生效时仍匹配，并且不得复制 Memory 原文。
_Avoid_: 通用 conditions 数组、自然语言谓词、隐藏全局状态、任意认知更新即失效、用计划保存已遗忘内容

**Planning Request**:
某个 Agent 基于特定 Observation Packet 和已提交的认知状态发起的一次战略规划工作。PlanningRequestProposal 显式依赖所需的 Memory/Belief 提案，只有依赖提交后请求才进入 Queued，并记录实际读取的 memory、belief 与 strategy revision。同一分支中的同一 Agent 最多只能有一个未结 Planning Request；等待期间继续使用最后一个有效 Strategy Plan，新增重规划原因合并等待后续处理。成功结果在预定生效边界基于最新合法 Observation Packet 形成一个关联的新 Agent Decision；失败、超时或失效只结束请求并记录预算结果。
_Avoid_: 同一 Agent 并发规划、规划等待时停止即时反应

**Planning Request Lifecycle**:
Planning Request 的执行进度采用 `Queued -> Running -> Ready -> Terminal`；终态原因以独立 outcome 记录为 `applied`、`rejected`、`failed`、`timed_out` 或 `canceled`。`canceled` 只表示排队请求被确定性合并替代，或经授权命令、Agent 终止或分支终止而明确取消；普通新观察和保存所需的 Quiescing 不取消运行中请求。所有转换均事件化，Terminal 请求不得被迟到响应重新打开。
_Avoid_: 每种失败原因一个实体、模糊终态、迟到结果修改 Agent 状态

**Replan Trigger Accumulator**:
Agent 规划状态中用于合并等待期重规划原因的有界运行投影。相同语义键的触发器合并计数和时间，不同原因并存；当前请求结束后只基于最新合法观察把仍有效的触发器原子转移给至多一个新请求。原始触发事实仍属于权威事件日志。
_Avoid_: 每触发器一个请求、单一布尔 replan 标记、不可变请求的事后补写

**Planning Tool Loop**:
同一 Planning Request 内受轮数、调用次数、返回量和预算约束的只读认知查询过程。它只能访问该 Agent 原本有权访问的状态，不能修改 World；全部查询结束后仍只产生一个最终规划结果。
_Avoid_: 新的 Decision Opportunity、直接执行 Action、读取其他 Agent 或全局真值

**Planner Output Validation**:
把 Provider 原始响应转换为候选 Planning Result 前执行的确定性信任边界。结构或整体 Schema 错误只允许在同一 Planning Request 内进行有限修复；仍然无效时规划失败，宿主不得猜测、补造或静默改写输出。Planning Result 只含候选 Strategy Plan、结构化 Rationale 和引用；Agent Runtime 在生效边界校验计划，再由 Reactive Controller 形成 Action Proposal。
_Avoid_: Provider 直接生成 Agent Decision、自动纠错业务含义、把提案拒绝伪装成技术重试

**Planning Activation Time**:
Planning Request 创建时确定的 Strategy Plan 最早虚拟生效时刻。现实 Provider 提前或延迟返回只能影响现实计算耗时，不能提前、推后或重排该虚拟时刻。
_Avoid_: Provider 返回时刻、现实网络延迟

**Strategy Plan Applicability**:
Strategy Plan 在预定生效时刻是否仍可采用的判断。新的普通世界变化或更新 Observation 本身不会使计划失效；只有请求已取消或超时、战略状态已被替代、有效期结束，或必要前提与 Agent 最新合法观察明确冲突时才拒绝采用。
_Avoid_: 任意新观察即过期、无条件接受旧计划

**Reactive Controller**:
依据 Agent 的最新观察与当前或候选 Strategy Plan，确定性地形成及时动作提案的决策部分。Provider 只能通过类型化 Directive 表达行动意图，不能绕过该控制器直接产生、执行或结算 World Action。没有有效计划时采用版本化 `hold_and_protect` 配置：不建立新承诺，只能通过正式动作保护或撤销自身已有承诺，同时仍允许认知更新和请求规划。
_Avoid_: LLM 直出 World Action、隐藏默认计划、无计划时增加风险、撮合引擎、结算器

**Directive Execution Cursor**:
Reactive Controller 按 `plan_revision + directive_id` 维护的私有可变执行游标，记录最近评估观察、guard 状态、发射次数、虚拟时间资格和已发射 action IDs。Directive 通过 `once`、`on_guard_transition`、`periodic` 或受 cooldown 限制的 `while_guarded` 声明发射策略；未来时间条件只能安排下一次 Directive Wakeup，在该时刻重新生成 Observation Packet 和 Action Proposal，不能预展开未来 Action。游标进入 revision、checkpoint、branch 和 replay，但不修改不可变 Strategy Plan。
_Avoid_: 每次观察无条件重复动作、未来 Action 脚本、用现实循环计数、计划替换后复用旧游标

**Action Proposal**:
Agent 请求世界执行的候选动作。只有通过世界的权限、资源和领域规则校验后，才可能产生权威事实。
_Avoid_: Domain Event、已执行动作

**Action Receipt**:
World 对一个 Action 的不可变结果记录，关联 action、proposal、decision、结果代码、虚拟时间、权威事件和结果状态引用。它保证进入发起 Agent 的下一份 Observation Packet，但不自动写入 Memory 或 Belief；普通确认不单独唤醒 Agent，异常、成交和风险/余额变化按观察屏障聚合为 `own_action_outcome` 触发器。
_Avoid_: 第二套 World State、其他 Agent 可见的私有拒绝原因、绕过 Observation 的直接状态更新

**Agent-Authored Information**:
由具备通信 Capability 的 Agent 通过类型化 CommunicationDirective 和 World Action 创作的不可变 InformationItem。它记录真实作者、虚拟时间、频道和可选来源引用，但内容只是可传播的数据，不构成系统真值或作者自身自动相信的信念。
_Avoid_: 伪造系统事实、可执行消息内容、发送即写入 Memory、冒充他人的真实作者身份

**Action Proposal Set**:
一个 Agent Decision 中受数量限制的零到多个 Action Proposal。各提案独立校验和调度，集合顺序不表达执行顺序；需要原子性的行为必须由具有明确语义的领域动作自身提供。
_Avoid_: 必须产生动作、通用原子动作批次

**Action Reservation**:
World 在 Action Proposal 准入后为其锁定的最大资源承诺，用于防止多个待执行动作重复使用同一余额或额度。它与 action ID 绑定，在执行时结算，在取消、过期、拒绝或失败时释放。
_Avoid_: 已执行交易、Agent 私有记账

**Pending Action**:
已通过准入并获得调度与资源预留、但尚未到达执行时刻的 Action。它独立于后续 Strategy Plan 变化，只能依据预先声明的版本依赖、显式取消或有效期结束而终止；进入订单簿后的开放订单不再是 Pending Action。
_Avoid_: Action Proposal、开放订单
