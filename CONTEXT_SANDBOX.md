# Sandbox 建模上下文

本上下文定义金融沙盒中权威世界、外生干预与运行控制的统一语言，并把用户意图、信息内容和已经生效的世界事实明确分开。

## Language

**Information Intervention**:
用户向沙盒引入的外生信息；它只能通过正常的信息传播边界影响 Agent 可获得的内容，不自动成为权威世界事实。
_Avoid_: State Intervention、系统事实、直接状态修改

**Supported Chain Catalog**:
产品固定版本中的可选链身份与显示名称目录，例如 Ethereum、Solana 和 Injective L1；它定义用户可以选择的网络，不代表该进程已经拥有对应链的 holder 数据。
_Avoid_: Holder Snapshot Provider、任意用户输入链名、链上数据已接通

**Holder Snapshot Provider**:
为指定 Supported Chain 提供已最终确认、可校验的 holder snapshot 的运行时数据源。它必须独立配置并通过链身份、Token、最终性和守恒校验，不能由固定链目录或 LLM 推断替代。
_Avoid_: 链目录、实时余额猜测、合成 Fixture 数据冒充 Live 数据

**State Intervention**:
用户明确授权、具有受支持类型和确定语义的外生世界变化；它在已暂停分支的确定事件边界由相关状态所有者校验和应用。
_Avoid_: Information Intervention、任意状态 Patch、LLM 直接执行

**Scenario Director**:
控制面中仅响应用户明确指令、把用户意图解释和组织为 Intervention Plan 的非权威推演协调者；一次 Plan 结束后其职责结束，不能自主观察市场、修改 World 或替市场 Agent 决策。
_Avoid_: Authoritative World Controller、自治市场导演、市场参与 Agent、全局状态写入者

**Director Access Scope**:
一次用户命令明确授予 Scenario Director 的只读信息边界；完整 World 事实和 Agent 定位信息默认可读，私人认知只有被本次 Scope 明确列入时才可读取，读取权限不自动包含披露权限。
_Avoid_: 全局永久权限、模糊的 full access、运行秘密访问

**Intervention Plan**:
Scenario Director 对干预目标、参数、顺序和预期影响形成的非权威声明；draft、confirmed 和 rejected 是该 Plan 的状态，而不是不同实体，只有 confirmed Plan 才能提交干预。
_Avoid_: Intervention Draft 实体、已生效事件、自由状态 Patch

**Intervention Stage**:
Intervention Plan 中绑定一个虚拟生效时刻的有序效果边界；同一 Stage 的必要世界变化原子提交，依赖这些变化的信息只在提交成功后形成。
_Avoid_: 独立 Intervention 实体、含糊的效果列表、部分提交边界

**Background Order-flow Impact**:
Scenario Director 对一个 Intervention Stage 未来市场含义作出的有符号强度判断，范围从 -1000（极强利空卖压）到 +1000（极强利多买压）。它只在确认后通过有界、可衰减的 Background Market 真实订单影响价格形成，不能直接修改价格，也不能与信息发布者的主观 `signal_direction` 或可信度混为一谈。
_Avoid_: 直接价格 Patch、无限订单、把消息主张当作权威冲击、由用户额外编写价格路径

**Intervention Template**:
一种版本化的受支持复合干预定义，用于把常见外生情景确定地解释为既有领域效果；它不能引入任意代码或绕过状态所有权。
_Avoid_: 自由文本脚本、通用 JSON Patch

**World Entity**:
在权威世界中具有稳定身份、受支持类型和可追溯状态历史的对象；新实例可以从某个 Intervention Stage 开始存在，但不能获得未记录的过去。
_Avoid_: 任意 JSON 对象、LLM 临时发明的类型

**Causal State**:
某项世界效果成立前必须已经存在的实体状态或关系，例如 Exposure、WalletControl、持仓或合同；缺失的 Causal State 不能由 Scenario Director 猜测或追溯补造。
_Avoid_: LLM 推断前提、事后补写历史

**Model Correction Branch**:
从较早边界分叉并修正遗漏或错误前置状态的分支；它改变了实验初始条件，不能被描述为只增加了后续单一干预。
_Avoid_: 普通 Intervention Branch、原分支历史修补

**Paused**:
分支在完成当前原子事件及其 Observation Barrier 后进入的控制状态；它冻结虚拟时间和全部自主推进，但允许显式控制命令在确定边界提交，暂停期间形成的观察只在恢复后触发 Agent 响应。
_Avoid_: World 事件、历史回滚、Agent 仍在后台运行

**Observation Barrier**:
同一虚拟时刻的一组权威效果完成提交、相应 Agent 决策机会尚未形成的世界版本边界；恢复分支时，暂停期间形成的观察先在该边界处理，再继续后续事件。
_Avoid_: 现实时间窗口、可被 Provider 返回穿透的边界、未提交状态快照

**Quote Coverage Ratio**:
用于把 Eligible Active Supply 按初始价格折算为场景级活跃 USDx 总量的可配置市场资金参数。它只决定合成报价资产总量，不由 Agent 类型、Persona 或 LLM 决定，也不规定各 Agent 的个体 USDx 余额。
_Avoid_: 链上稳定币余额、角色资金比例、Agent 购买力标签

**Background Market Sector**:
拥有 Ledger 真实账户、代表未显式建模参与者活动的环境市场部门。初始化时其可用库存必须同时包含 Token 与 USDx，才能分别支持卖单与买单；所有挂单、锁定、成交、费用和耗尽都走与 Agent 相同的市场和结算规则。
_Avoid_: Background Agent、无限流动性、未记账订单生成器、价格稳定器

**Initialization Asset Conservation**:
初始化只在 Agent、Background Market Sector、费用账户、非活跃储备和其他合法来源桶之间分配既定 Token 与 USDx；每种资产在分配前后的总量必须分别相等。除显式记录的发行或销毁事实外，初始化不得增发、丢失或静默缩放资产。
_Avoid_: 净值守恒替代逐资产守恒、隐式 mint、余额残差修复

**Background Remainder Allocation**:
显式 Agent 按已确认配置分配 Token 与 USDx 后，各资产池中剩余的可交易余额归入 Background Market Sector；它不是按固定比例或订单需求额外划拨的资金。背景只有同时拥有已记账的 Token 与 USDx 时，才具备双边订单能力。
_Avoid_: 订单需求增发、固定背景比例、背景无限补资、把剩余锁仓余额当作库存
