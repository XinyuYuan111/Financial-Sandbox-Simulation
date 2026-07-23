# Agent 建模上下文

本上下文定义金融沙盒中自主参与者的统一语言，区分 Agent 的认知决策、角色配置与世界执行责任。

## Language

**Agent**:
沙盒中独立初始化的认知与决策主体。每个 Agent 拥有彼此隔离的 Persona、Observation、Memory、Belief、认知预算、策略状态与随机流。
_Avoid_: 角色类型、共享决策群组、LLM 会话

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

**Decision Opportunity**:
一个已保存的 Observation Packet 触发对应 Agent 执行一次决策流程的确定性时机。同一虚拟时刻的相关可见变化可以聚合；不可见或无关事件不得通过唤醒 Agent 暴露其存在。
_Avoid_: 每事件唤醒、现实时间轮询

**Agent Decision**:
一次 Agent 决策流程产生的不可变审计记录，关联所用 Observation Packet 和 Agent 状态版本，并汇集记忆、信念、策略、动作及预算消耗提案。它记录 Agent 想要改变什么，不表示这些提案已经被接受或执行。
_Avoid_: Action 列表、直接状态变更

**Decision Outcome**:
Agent Decision 经各状态所有者校验后的完整结果。整体边界错误会拒绝整次决策；单个提案错误只影响自身及明确依赖项，而所有接受与拒绝结果必须作为一个不可分割的审计记录保存。
_Avoid_: 全部提案连带失败、未记录的部分提交

**Strategy Plan**:
Agent 当前采用的声明式目标、约束、条件策略和有效范围。它表达行动意图，但不构成已经发生的世界动作。
_Avoid_: 固定未来动作脚本、可执行代码

**Planning Request**:
某个 Agent 基于特定 Observation Packet 发起的一次战略规划工作。同一分支中的同一 Agent 最多只能有一个未结 Planning Request；等待期间继续使用最后一个有效 Strategy Plan，新增重规划原因合并等待后续处理。
_Avoid_: 同一 Agent 并发规划、规划等待时停止即时反应

**Planning Activation Time**:
Planning Request 创建时确定的 Strategy Plan 最早虚拟生效时刻。现实 Provider 提前或延迟返回只能影响现实计算耗时，不能提前、推后或重排该虚拟时刻。
_Avoid_: Provider 返回时刻、现实网络延迟

**Strategy Plan Applicability**:
Strategy Plan 在预定生效时刻是否仍可采用的判断。新的普通世界变化或更新 Observation 本身不会使计划失效；只有请求已取消或超时、战略状态已被替代、有效期结束，或必要前提与 Agent 最新合法观察明确冲突时才拒绝采用。
_Avoid_: 任意新观察即过期、无条件接受旧计划

**Reactive Controller**:
依据 Agent 的最新观察与 Strategy Plan 形成及时动作提案的决策部分。它不能绕过世界规则执行或结算动作。
_Avoid_: 撮合引擎、结算器

**Action Proposal**:
Agent 请求世界执行的候选动作。只有通过世界的权限、资源和领域规则校验后，才可能产生权威事实。
_Avoid_: Domain Event、已执行动作
