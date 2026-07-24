# Financial Sandbox Simulation

这是一个本地运行的多 Agent 金融市场仿真沙盒。用户可以启动市场、暂停运行、加入特殊事件、观察不同 Agent 的反应、保存或分叉历史，并在任意时刻停止推演。

下面的步骤从一台尚未安装开发依赖的新 Windows 电脑开始。

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

安装 `openai` 可选依赖不会产生 API 费用。只有在配置 API Key 并选择 LLM 模式后，项目才会调用 OpenAI。

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

不要关闭正在运行 Uvicorn 的 PowerShell 窗口。需要停止项目时，在该窗口按 `Ctrl+C`。

## 六、完成第一次仿真

第一次使用不需要 OpenAI API Key，也不需要链上数据文件：

1. 在 Quick Start 页面保留 `Fixture` 模式。
2. 填写实验名称、目标资产和随机种子，或直接使用默认值。
3. 点击“解析初始状态”。
4. 检查 Agent、资产和参数预览。
5. 点击“创建运行”。
6. 点击顶部的运行按钮，沙盒会自动推进。
7. 点击暂停按钮后，可以进入“情景干预”创建并确认特殊事件。
8. 恢复运行，观察市场、信息流和各 Agent 的独立反应。
9. 点击停止按钮结束当前分支。

运行数据默认保存在：

```text
data\sandbox.db
```

## 七、可选：使用 OpenAI Agent 规划

Fixture 模式完全在本地运行。只有 `LLM 烟测` 和 `Live` 模式需要 OpenAI API Key，并会产生实际 API 费用。

在启动项目前，于同一个 PowerShell 窗口设置：

```powershell
$env:OPENAI_API_KEY = "你的 OpenAI API Key"
```

可选配置：

```powershell
$env:SANDBOX_OPENAI_MODEL = "gpt-5.6-terra"
$env:SANDBOX_OPENAI_TIMEOUT_SECONDS = "30"
$env:SANDBOX_OPENAI_MAX_RETRIES = "1"
$env:SANDBOX_OPENAI_MAX_IN_FLIGHT = "4"
$env:SANDBOX_OPENAI_MAX_OUTPUT_TOKENS = "1800"
```

然后使用第五节的 Uvicorn 命令启动项目。

API Key 只由本地后端读取，不会写入 SQLite 或导出的沙盒归档。不要把 API Key 写入仓库文件或提交到 Git。

## 八、可选：使用 Live 模式

`Live` 模式除 OpenAI API Key 外，还需要一个本地 finalized holder snapshot JSON 文件。启动前设置：

```powershell
$env:SANDBOX_HOLDER_SNAPSHOT_PATH = (Resolve-Path ".\path\to\finalized-holder-snapshot.json").Path
$env:SANDBOX_HOLDER_CHAIN_ID = "ethereum"
```

文件至少需要包含：

```json
{
  "schema_version": "holder-snapshot.v0.2",
  "chain_id": "ethereum",
  "target_token": "TOKEN",
  "block_height": 123456,
  "block_hash": "0x...",
  "finalized": true,
  "coverage_ratio_milli": 950,
  "total_supply": 1000000
}
```

Quick Start 中选择的链和 Token 必须与文件中的 `chain_id`、`target_token` 一致。仓库中的 `fixtures/holder_snapshots/framework-alpha.fixture.v0.2.json` 是测试数据，不能视为真实链上数据。

## 九、重新启动

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

查找占用端口的进程：

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8000
```

停止占用该端口的程序，或者改用其他端口：

```powershell
.\.venv\Scripts\python.exe -m uvicorn sandbox.app.main:app --host 127.0.0.1 --port 8001
```

使用其他端口时，在浏览器中打开对应地址，例如 <http://127.0.0.1:8001>。

### 页面提示前端尚未构建

重新执行第四节的 `npm ci` 和 `npm run build`，然后重启 Uvicorn。

### Live 或 LLM 模式无法解析

- `LLM 烟测` 需要有效的 `OPENAI_API_KEY`。
- `Live` 还需要有效的 `SANDBOX_HOLDER_SNAPSHOT_PATH`。
- Live 页面选择的链和 Token 必须与 snapshot 文件匹配。
- Provider 检查失败时，系统不会自动退回 Fixture 模式。
