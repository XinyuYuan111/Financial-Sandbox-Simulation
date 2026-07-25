# EPOCH ONE · 沙盘（codex 前端）

零依赖单页沙盘：`index.html` + `styles.css` + `app.js`，直接起静态服务即可演示。

```bash
python3 -m http.server 8931
# 打开 http://localhost:8931/index.html
```

## 数据源

- **Mock（默认）**：本地确定性引擎（种子随机游走市场 + Agent 状态机 + 本地撮合语义）。
- **Remote**：`?source=remote&branch=<branchId>` 轮询 `/api/v1`（3s）。
  后端不可达时自动降级：顶栏「模拟」+ 远端指示点常亮，本地引擎继续运行。

成交带、持仓、记忆、事件流一律由引擎真实状态派生；mock 仅补足引擎没有的
展示数据（订单簿档位），且始终锚定真实市场价。

## 功能地图（移植自 React 工作台）

| 功能 | 入口 |
|------|------|
| 指标条（最新成交/最优买卖/累计量/价差） | 顶栏常驻 |
| 订单簿 + 成交带 | 顶栏「指标▼」→ 右侧滑 |
| Agent 审计（概览/记忆/成交 + 促动） | 点击棋子 → 左侧滑 |
| 事件浏览（搜索 + 可见性过滤） | 右栏「事件」标签 |
| 干预效果（7 种） | 左栏「干预效果」标签 |
| 控制 | 开始 / 暂停 / 重置 / Agent 数量滑杆 |

干预效果：发布信息、市场停牌、账户冻结、资产转移、创建实体、创建关系、
钱包权限。提交后在舞台、账本与事件流中可见因果反馈（如停牌冻结行情、
冻结棋子置灰、关系连线跟随）。

## 验收钩子

`window.__sandbox`：stats / agents / market / inject / startWorld /
resetWorld / closeSlidePanels / port（events、book、holdings、openAgent、
toggleOrderbook）。

## 目录

- `app.js` — 引擎 + 移植层（单一文件，无构建步骤）
- `_attic/` — 移植过程中被取代的早期 WIP 模块（未加载，仅存档）
