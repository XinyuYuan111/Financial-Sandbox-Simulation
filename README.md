# Financial Sandbox Simulation

这是一个本地运行的多 Agent 金融市场仿真沙盒。用户可以启动市场、暂停运行、加入特殊事件、观察不同 Agent 的反应、保存或分叉历史，并在任意时刻停止推演。

下面的步骤从一台尚未安装开发依赖的新 Windows 电脑开始。

## 快速运行（Windows）

已经安装 Git、Python 3.12+ 和 Node.js 22+ 的用户，可以在 PowerShell 中依次执行：

```powershell
git clone https://github.com/XinyuYuan111/FinancialSandboxSimulation.git
cd FinancialSandboxSimulation
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[openai]"
Push-Location frontend
npm ci
npm run build
Pop-Location
.\.venv\Scripts\python.exe -m uvicorn sandbox.app.main:app --host 127.0.0.1 --port 8000
```

保持该 PowerShell 窗口开启，然后访问 <http://127.0.0.1:8000>。停止服务时回到该窗口按 `Ctrl+C`。首次安装、可选运行模式和故障处理见下文。

## 一、开始前需要安装

请先安装以下软件。只下载官方版本：

1. **Git for Windows**

   下载地址：<https://git-scm.com/download/win>

2. **Python 3.12 或更高版本**

   下载地址：<https://www.python.org/downloads/windows/>

   安装时勾选 `Add python.exe to PATH`。

3. **Node.js 22 或更高版本**

   下载地址：<https://nodejs.org/en/download>

   npm 会随 Node.js 一起安装。

安装完成后，打开一个新的 PowerShell 窗口并运行：

```powershell
git --version
python --version
node --version
npm --version
```

四条命令都必须正常显示版本号，并且 Python 版本不能低于 `3.12`。

## 二、克隆仓库

在 PowerShell 中进入你准备存放项目的目录，然后运行：

```powershell
git clone https://github.com/XinyuYuan111/FinancialSandboxSimulation.git
cd FinancialSandboxSimulation
```

后续命令都在 `FinancialSandboxSimulation` 仓库根目录执行。

## 三、安装后端依赖

创建独立的 Python 虚拟环境：

```powershell
python -m venv .venv
```

升级 pip 并安装项目依赖：

```powershell
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[openai]"
```

`openai` 可选依赖只供 OpenAI Provider 使用；DeepSeek Provider 的 HTTP 客户端已包含在基础依赖中。安装依赖本身不会产生 API 费用，只有配置对应 API Key 并选择 LLM 模式后才会调用外部服务。

## 四、安装并构建前端

仓库不会提交 `node_modules` 和构建产物，因此首次启动必须安装前端依赖并构建：

```powershell
Push-Location frontend
npm ci
npm run build
Pop-Location
```

构建成功后应存在 `frontend\dist\index.html`。

## 五、启动项目

在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m uvicorn sandbox.app.main:app --host 127.0.0.1 --port 8000
```

当终端出现下面的信息时，服务已经启动：

```text
Uvicorn running on http://127.0.0.1:8000
```

在浏览器中打开：

<http://127.0.0.1:8000>

不要关闭正在运行 Uvicorn 的 PowerShell 窗口。

## 六、停止项目

如果启动 Uvicorn 的 PowerShell 窗口仍然存在，回到该窗口按 `Ctrl+C`。看到关闭日志并重新出现 PowerShell 提示符后，服务已经停止。关闭浏览器标签页不会停止后端。

如果原来的终端已经关闭，但怀疑服务仍在后台运行，可以在新的 PowerShell 窗口中直接提取监听 `8000` 端口的 PID：

```powershell
$sandboxProcessId = (Get-NetTCPConnection -State Listen -LocalPort 8000 | Select-Object -First 1).OwningProcess
$sandboxProcessId
```

第二条命令输出的纯数字就是 PID。先确认它确实是需要关闭的进程，再停止它：

```powershell
Get-Process -Id $sandboxProcessId
Stop-Process -Id $sandboxProcessId
```

`LocalAddress` 显示的 `127.0.0.1` 是监听地址，不是 PID。如果第一条命令没有找到连接或 `$sandboxProcessId` 没有输出数字，说明 `8000` 端口当前没有服务在运行。不要停止未经确认的进程。

## 七、完成第一次仿真

第一次使用不需要 OpenAI API Key，也不需要链上数据文件：

1. 在 Quick Start 页面保留 `Fixture` 模式。
2. 选择“随机生成”“自然语言”或“详细配置”；只有随机生成会随机化 Agent 字段。
3. 填写实验名称、目标资产和随机种子，或直接使用默认值。
4. 点击“解析初始状态”。
5. 检查 Agent、Token 来源桶、Eligible Active Supply、背景余量和逐资产守恒结果。
6. 点击“确认并创建运行”。
7. 点击顶部的运行按钮，沙盒会自动推进。
8. 点击暂停按钮后，可以进入“情景干预”创建并确认特殊事件。
9. 恢复运行，观察市场、信息流和各 Agent 的独立反应。
10. 点击停止按钮结束当前分支。

Fixture 中的本地 rule Agent 会依据角色、能力、Persona、可用余额和场景 seed 生成确定性的演示计划：市场参与者可以在交易的同时交流，流动性提供者挂双边报价，信息参与者持续发布或保留自己的判断。无原型随机 Agent 默认同时具备 `information.read` 和 `information.publish`；非 replay 规划器返回有效但只有市场动作的计划时，宿主会补入独立、受限的通信指令，避免 LLM 遗漏通信。交易指令每 5 个仿真分钟最多发射一次、每份计划最多两次；通信指令每 2 个仿真分钟最多发射一次、每份计划最多六次。周期指令通过虚拟时间唤醒，不依赖碰巧发生另一笔市场事件。所有动作仍经过正常的能力校验、风控、资产预留、延迟队列、撮合和回执链。修改默认能力后应重新解析场景（或新建场景）再创建运行；已有解析结果和运行中保存的 Agent 能力、旧计划不会被追溯改写。

Agent 之间的信息通过 `InformationDelivered`、`PrivateMessageDelivered`、`InformationViewed` 和 observation 链路传播，不会直接写入其他 Agent 的私有状态。Agent 可以公开表达、向观察到的交易对手定向披露、保留判断，或发布与其私有评估相反的策略性说法。接收方只看到声明和发布者自报信心，不会看到隐藏意图；`CommunicationIntentRecorded` 和 `InformationWithheld` 只供分析端审计。交易型 Agent 会按自身 skepticism 折扣声明，写入 belief，并在收到新信息后重新规划。盘口和成交变化也会形成有来源的市场记忆与信念，不再只有用户干预或消息能改变认知。

背景市场不再只有静态做市：原背景资产会拆分为 maker 与 `background_order_flow` 两个运行账户。maker 维护多档双边深度，order flow 按可复现的概率主动吃 maker 的最优单或在盘口内挂方向单；概率、抽样值和动作类型记录为 `BackgroundOrderFlowSampled`。两者不能自成交，资产总量仍按原背景预算守恒。

运行数据默认保存在：

```text
data\sandbox.db
```

## 八、可选：配置 LLM Agent 规划

Fixture 模式完全在本地运行。`LLM 烟测` 和 `Live` 可以选择 `openai` 或 `deepseek` Provider，并会产生对应服务的实际 API 费用。

`LLM 烟测` 是活动导向的演示模式。若 Provider 返回合法但无 directive 的计划，系统会按场景 seed 确定性采样 75% 的能力安全 fallback；若同一批仍全部无动作，会强制选取第一个合法 fallback，确保烟测能展示市场或信息流。原始 Provider 记录不会改写，宿主选择会单独记录为 `AgentNoOpFallbackSampled` 事件。`Live` 不使用该机制，Agent 在 Live 中仍可合法选择不行动。

运行顶部会分别显示 `active plans`（当前有效计划）和 `pending`（仍在等待 Provider 的规划请求）；`0 pending` 只表示没有等待中的请求，不表示从未产生计划。

### LLM 烟测的虚拟资产

`LLM 烟测` 不需要 `SANDBOX_HOLDER_SNAPSHOT_PATH`。系统根据场景的随机种子和目标 Token，确定性生成一份虚拟 holder snapshot，包括 Token 总量、eligible/locked/protocol/burned 来源桶和 holder 分布。相同 seed 与 Token 会产生相同结果，便于复现。

初始化器仍使用统一的资产分配与守恒校验：

```text
背景 Token = Eligible Active Supply - Agent Token - 其他显式账户 Token
背景 USDx  = Active USDx Supply - Agent USDx - 其他显式账户 USDx
```

预览会明确标记 `synthetic-holder-snapshot`。这些数据只用于烟测，不能解释为真实链上余额。`Live` 模式不会静默回退到虚拟数据。

### 使用 DeepSeek 官网 API

DeepSeek Provider 直接请求官网 `https://api.deepseek.com/chat/completions`，使用 DeepSeek 官网签发的密钥，不需要 `OPENAI_API_KEY`。在启动 Uvicorn 前，于同一个 PowerShell 窗口设置：

```powershell
$env:DEEPSEEK_API_KEY = "你的 DeepSeek 官网 API Key"
$env:SANDBOX_DEEPSEEK_MODEL = "deepseek-chat"
```

通常不需要设置 API 地址。只有需要显式覆盖时才使用：

```powershell
$env:SANDBOX_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
```

不要在地址末尾添加 `/chat/completions`，程序会自动拼接。其他可选配置：

```powershell
$env:SANDBOX_DEEPSEEK_TIMEOUT_SECONDS = "60"
$env:SANDBOX_DEEPSEEK_MAX_RETRIES = "1"
$env:SANDBOX_DEEPSEEK_MAX_IN_FLIGHT = "4"
$env:SANDBOX_DEEPSEEK_MAX_OUTPUT_TOKENS = "4096"
```

启动后，在 Quick Start 中选择 `deepseek · deepseek-chat`，点击“检查”，然后选择 `LLM 烟测`。“检查”会实际生成并校验一份完整但无动作的 Planning Candidate，而不只是测试网络连通性。后端使用 JSON 输出模式接收结果，并在本地按照 Planning、Scenario Director 或 Agent Configuration 的 Pydantic Schema 重新校验；无效输出不会直接执行。

### 使用 OpenAI 官网 API

```powershell
$env:OPENAI_API_KEY = "你的 OpenAI API Key"
$env:SANDBOX_OPENAI_MODEL = "gpt-5.6-terra"
```

使用 OpenAI Responses API 中转站时，同时设置该站点提供的根地址与模型名：

```powershell
$env:OPENAI_API_KEY = "中转站提供的 API Key"
$env:SANDBOX_OPENAI_BASE_URL = "https://your-trusted-relay.example"
$env:SANDBOX_OPENAI_MODEL = "中转站支持的模型名称"
```

`SANDBOX_OPENAI_BASE_URL` 是本项目专用配置，不要改用全局 `OPENAI_BASE_URL`，否则可能同时改变 Codex 或其他 OpenAI 客户端的请求目标。不要在地址末尾添加 `/responses`。中转站必须支持 Responses API、`responses.parse` 与结构化输出；Codex 能通过同一个域名工作，并不自动证明该模型和密钥也能完成本项目的完整规划 Schema 请求。

其他可选配置：

```powershell
$env:SANDBOX_OPENAI_TIMEOUT_SECONDS = "30"
$env:SANDBOX_OPENAI_MAX_RETRIES = "1"
$env:SANDBOX_OPENAI_MAX_IN_FLIGHT = "4"
$env:SANDBOX_OPENAI_MAX_OUTPUT_TOKENS = "4096"
```

环境变量只在后端启动时读取。设置或修改任一 Key、模型或 Base URL 后，必须重启 Uvicorn，再刷新页面并执行 Provider 检查。`$env:NAME = "value"` 只对当前 PowerShell 进程有效，关闭终端或重启电脑后会消失。需要保存到当前 Windows 用户环境时，可使用 `[Environment]::SetEnvironmentVariable("DEEPSEEK_API_KEY", "新密钥", "User")`；设置后要新开 PowerShell。API Key 只由本地后端读取，不会写入 SQLite 或导出的沙盒归档。不要把 API Key 写入仓库文件、截图或提交到 Git。

Autonomous 运行按真实时间节拍推进：真实 1 秒对应界面显示的 1 个模拟分钟。LLM 规划由独立 Worker 处理，同一批最多并行 `MAX_IN_FLIGHT` 个请求；Provider 等待或重试不会冻结背景市场的模拟时钟。结果仍按请求的虚拟激活时间、Agent ID 和请求 ID 固定排序后提交，因此网络返回顺序不会决定模拟顺序。

后端进程退出时无法保留内存中的 Worker。下次启动会把数据库里中断的 `Running` 分支恢复为 `Paused`，避免旧实验在后台自动产生 LLM 费用；确认 Provider 配置后点击运行即可继续。

## 九、可选：使用 Live 模式

`Live` 模式除所选 LLM Provider 的 API Key 外，还需要一个本地 finalized holder snapshot JSON 文件。启动前设置：

```powershell
$env:SANDBOX_HOLDER_SNAPSHOT_PATH = (Resolve-Path ".\path\to\finalized-holder-snapshot.json").Path
$env:SANDBOX_HOLDER_CHAIN_ID = "ethereum"
```

Live 页面中的链目录是程序固定的，目前包含 `Ethereum`、`Solana` 和 `Injective L1`。固定目录只表示支持这些链的场景身份；真正运行 Live 解析时，仍必须为当前选择的链配置匹配的 finalized holder snapshot。当前版本一次启动注册一个 `SANDBOX_HOLDER_CHAIN_ID` 与文件路径，因此未配置的链会在界面中标记为不可用，而不会在点击解析后才报错。Injective L1 的内部目录值为 `injective`，对应 snapshot 的 `chain_id` 也应使用该值。

文件至少需要包含：

```json
{
  "schema_version": "holder-snapshot.v0.3",
  "provider": "your-holder-provider",
  "chain_id": "ethereum",
  "target_token": "TOKEN",
  "block_height": 123456,
  "block_hash": "0x...",
  "finalized": true,
  "coverage_ratio_milli": 950,
  "total_supply": 1000000,
  "eligible_active_supply": 900000,
  "covered_eligible_supply": 855000,
  "source_buckets": [
    {"bucket_id": "eligible", "category": "eligible_active", "amount": 900000, "eligible_for_active_market": true},
    {"bucket_id": "locked", "category": "locked", "amount": 100000, "eligible_for_active_market": false}
  ],
  "holder_distribution": {
    "distribution_version": "holder-distribution.v0.1",
    "active_holder_count": 10000,
    "p25_balance": 100,
    "p50_balance": 500,
    "p75_balance": 2000,
    "p90_balance": 10000,
    "p99_balance": 50000,
    "top_10_concentration_milli": 600
  }
}
```

Quick Start 中选择的链和 Token 必须与文件中的 `chain_id`、`target_token` 一致。`source_buckets` 必须合计为 `total_supply`，其中 eligible 桶必须合计为 `eligible_active_supply`。仓库中的 `fixtures/holder_snapshots/framework-alpha.fixture.v0.3.json` 是测试数据，不能视为真实链上数据。

## 十、重新启动

依赖已经安装并且前端没有修改时，只需进入仓库并运行：

```powershell
cd FinancialSandboxSimulation
.\.venv\Scripts\python.exe -m uvicorn sandbox.app.main:app --host 127.0.0.1 --port 8000
```

如果更新了仓库代码，建议重新同步依赖并构建前端：

```powershell
git pull
.\.venv\Scripts\python.exe -m pip install -e ".[openai]"
Push-Location frontend
npm ci
npm run build
Pop-Location
```

## 常见问题

### `python` 不是内部或外部命令

重新安装 Python，并勾选 `Add python.exe to PATH`。安装后关闭并重新打开 PowerShell。

### `npm` 不是内部或外部命令

安装 Node.js 后关闭并重新打开 PowerShell，然后再次运行 `node --version` 和 `npm --version`。

### PowerShell 禁止执行 `.ps1` 脚本

本文不要求激活虚拟环境，而是直接调用 `.venv\Scripts\python.exe`。因此不需要执行 `Activate.ps1`，也不需要修改 PowerShell 执行策略。

### `npm ci` 失败

确认当前目录是仓库根目录，并且 `frontend\package-lock.json` 存在；然后删除未完成的 `frontend\node_modules` 目录，再重新运行第四节命令。

### 端口 8000 已被占用

按照“六、停止项目”中的方法确认并停止占用端口的进程，或者改用其他端口：

```powershell
.\.venv\Scripts\python.exe -m uvicorn sandbox.app.main:app --host 127.0.0.1 --port 8001
```

使用其他端口时，在浏览器中打开对应地址，例如 <http://127.0.0.1:8001>。

### 页面提示前端尚未构建

重新执行第四节的 `npm ci` 和 `npm run build`，然后重启 Uvicorn。

### 重启后提示 `invalid local session`

后端每次启动都会生成新的本地会话令牌。当前版本会在页面刷新或其他安全读取请求中自动把旧 `sandbox_session` Cookie 换成当前令牌，不需要手动清理站点数据。

如果旧页面在后端重启后立即提交写操作，该操作会被拒绝一次；刷新 <http://127.0.0.1:8000> 后重试即可。`sandbox_session` 只包含随机会话标识，不包含实验、存档或用户数据；运行数据仍保存在 `data\sandbox.db` 或用户显式导出的归档中。

### Live 或 LLM 模式无法解析

- `LLM 烟测` 不需要 holder snapshot，但需要所选 Provider 对应的 `OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`。
- `Live` 还需要有效的 `SANDBOX_HOLDER_SNAPSHOT_PATH`。
- Live 页面选择的链和 Token 必须与 snapshot 文件匹配。
- 修改环境变量后必须重启 Uvicorn；只刷新浏览器不会更新后端配置。
- OpenAI 中转站的 `502`、连接错误或超时属于上游请求失败；查看运行顶部的 `failed`、`active plans`、`pending` 计数和 SQLite 中的 `llm_records`，不要把 `0 pending` 误读为从未创建规划请求。
- API 能访问不等于规划可执行：返回内容还必须是完整 JSON，并通过 directive 必填字段、能力和 `based_on_strategy_revision` 校验。失败记录会保存具体的安全裁剪错误；DeepSeek 的第二次尝试会带上第一次的校验反馈。
- `MAX_OUTPUT_TOKENS` 同时要容纳模型的推理 token 和最终 JSON；默认值为 `4096`。若手动保留了旧的 `1800` 环境变量，可能出现空内容或 `Unterminated string`，应修改后重启。
- Provider 检查失败时，系统不会自动改用另一家 Provider，也不会把 Live 静默退回 Fixture 或烟测模式。
