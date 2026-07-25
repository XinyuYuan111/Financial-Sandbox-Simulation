'use strict';

/**
 * UILayer: 处理 UI 更新、交互绑定、数据展示
 * - 订单簿渲染
 * - Agent 审计面板
 * - 事件浏览器
 * - 干预效果面板
 * - 交互事件处理
 */

class UILayer {
  constructor(mockDataLayer, slidePanel) {
    this.dataLayer = mockDataLayer;
    this.slidePanel = slidePanel;

    // 颜色映射
    this.colors = {
      buy: '#7FA88F', // 绿色
      sell: '#B0705F', // 棕色
      accent: '#C8432B', // 朱砂
      neutral: '#D8CFBB', // 淡色
    };

    this._initialize();
  }

  /**
   * 初始化 UI 层
   */
  _initialize() {
    // 注册侧滑面板的渲染函数
    this.slidePanel.register('orderbook-panel', 'orderbook', (data, container) => {
      this._renderOrderBook(data, container);
    });

    this.slidePanel.register('agent-panel', 'agent', (data, container) => {
      this._renderAgentAudit(data, container);
    });

    this.slidePanel.register('intervention-panel', 'intervention', (data, container) => {
      this._renderInterventionPreview(data, container);
    });

    // 绑定交互事件
    this._bindInteractions();

    // 启动 UI 更新循环
    this._startUIUpdate();
  }

  /**
   * 绑定交互事件
   */
  _bindInteractions() {
    // 点击棋子打开 Agent 审计
    document.addEventListener('click', (e) => {
      if (e.target.classList.contains('pawn') || e.target.closest('.pawn')) {
        const agentId = e.target.dataset.agentId || e.target.closest('.pawn').dataset.agentId;
        if (agentId) {
          const agentDetail = this.dataLayer.getAgentDetail(agentId);
          this.slidePanel.open('agent', agentDetail);
        }
      }
    });

    // 点击指标条打开订单簿
    const metricsBar = document.querySelector('#metric-bar');
    if (metricsBar) {
      metricsBar.addEventListener('click', () => {
        const orderBook = this.dataLayer.getOrderBook();
        this.slidePanel.open('orderbook', orderBook);
      });
    }

    // 左栏标签页切换
    const infoTab = document.querySelector('[data-tab="info"]');
    const interventionTab = document.querySelector('[data-tab="intervention"]');

    if (infoTab) {
      infoTab.addEventListener('click', () => {
        this._showInfoPanel();
      });
    }

    if (interventionTab) {
      interventionTab.addEventListener('click', () => {
        this._showInterventionPanel();
      });
    }
  }

  /**
   * 启动 UI 更新循环（每 500ms 更新一次）
   */
  _startUIUpdate() {
    setInterval(() => {
      this._updateMetricsBar();
      this._updateOrderBook();
      this._updateAgentStates();
      this._updateEventLog();

      // 如果侧滑面板打开，更新面板内容
      if (this.slidePanel.getActivePanel()) {
        this._updateActivePanel();
      }
    }, 500);
  }

  /**
   * 更新指标条（顶栏）
   */
  _updateMetricsBar() {
    const orderBook = this.dataLayer.getOrderBook();

    // 更新价格显示
    const priceEl = document.querySelector('#pulse-price');
    if (priceEl) {
      priceEl.textContent = `$${orderBook.lastPrice.toFixed(2)}`;
    }

    // 更新最新交易价格
    const trades = this.dataLayer.getTrades(1);
    if (trades.length > 0) {
      const changeEl = document.querySelector('#pulse-change');
      if (changeEl) {
        const change = ((trades[0].price - orderBook.midPrice) / orderBook.midPrice * 100).toFixed(2);
        changeEl.textContent = `${change > 0 ? '+' : ''}${change}%`;
        changeEl.style.color = change > 0 ? this.colors.buy : this.colors.sell;
      }
    }

    // 添加更多指标信息（如果有指标条元素）
    const metricBar = document.querySelector('#metric-bar');
    if (metricBar) {
      metricBar.innerHTML = `
        <div class="metric-item">
          <span class="metric-label">最新价</span>
          <span class="metric-value">${orderBook.lastPrice.toFixed(2)}</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">成交量</span>
          <span class="metric-value">${(orderBook.volume24h / 1000).toFixed(0)}K</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">最佳买价</span>
          <span class="metric-value" style="color: ${this.colors.buy};">${orderBook.bids[0]?.price.toFixed(2) || '-'}</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">最佳卖价</span>
          <span class="metric-value" style="color: ${this.colors.sell};">${orderBook.asks[0]?.price.toFixed(2) || '-'}</span>
        </div>
        <div class="metric-item">
          <span class="metric-label">价差</span>
          <span class="metric-value">${orderBook.spread}</span>
        </div>
      `;
    }
  }

  /**
   * 更新订单簿显示
   */
  _updateOrderBook() {
    // 主要在侧滑面板打开时更新
    if (!this.slidePanel.isOpen('orderbook')) return;

    const orderBook = this.dataLayer.getOrderBook();
    this.slidePanel.updateData('orderbook', orderBook);
  }

  /**
   * 更新 Agent 状态（UI 显示）
   */
  _updateAgentStates() {
    const agents = this.dataLayer.getAgents();

    agents.forEach(agent => {
      // 根据 Agent 更新棋子样式（如果有 DOM 元素）
      const pawnEl = document.querySelector(`[data-agent-id="${agent.id}"]`);
      if (pawnEl) {
        // 更新样式（例如颜色变化表示策略）
        const strategyColor = agent.strategy === 'skeptic' ? '#999' : agent.strategy === 'follower' ? '#66F' : '#F90';
        pawnEl.style.borderColor = strategyColor;
      }
    });
  }

  /**
   * 更新事件日志
   */
  _updateEventLog() {
    const events = this.dataLayer.getEvents();

    // 更新事件列表（如果存在）
    const eventListEl = document.querySelector('#event-list');
    if (eventListEl) {
      eventListEl.innerHTML = events.slice(0, 20).map((event, idx) => `
        <div class="event-item">
          <div class="event-time">${new Date(event.timestamp).toLocaleTimeString()}</div>
          <div class="event-type">${event.type}</div>
          <div class="event-visibility">${event.visibility}</div>
          <div class="event-source">${event.source_id}</div>
        </div>
      `).join('');
    }
  }

  /**
   * 更新活跃的侧滑面板
   */
  _updateActivePanel() {
    const activePanel = this.slidePanel.getActivePanel();

    if (activePanel === 'orderbook') {
      const orderBook = this.dataLayer.getOrderBook();
      this.slidePanel.updateData('orderbook', orderBook);
    } else if (activePanel === 'agent') {
      // Agent 面板暂不自动更新，避免闪烁
    } else if (activePanel === 'intervention') {
      const interventions = this.dataLayer.getInterventions();
      this.slidePanel.updateData('intervention', interventions);
    }
  }

  /**
   * 渲染订单簿面板
   */
  _renderOrderBook(orderBook, container) {
    const html = `
      <div class="orderbook-panel">
        <div class="orderbook-stats">
          <div class="stat">
            <span class="stat-label">最新价</span>
            <span class="stat-value">${orderBook.lastPrice.toFixed(2)}</span>
          </div>
          <div class="stat">
            <span class="stat-label">24h成交量</span>
            <span class="stat-value">${(orderBook.volume24h / 1000).toFixed(0)}K</span>
          </div>
          <div class="stat">
            <span class="stat-label">价差</span>
            <span class="stat-value">${orderBook.spread}</span>
          </div>
        </div>

        <div class="orderbook-tables">
          <div class="orderbook-section">
            <h4 class="section-title" style="color: ${this.colors.buy};">买单 (Bids)</h4>
            <table class="orderbook-table">
              <thead>
                <tr>
                  <th>价格</th>
                  <th>数量</th>
                </tr>
              </thead>
              <tbody>
                ${orderBook.bids.slice(0, 10).map(bid => `
                  <tr class="bid-row" style="border-left: 3px solid ${this.colors.buy};">
                    <td class="price">${bid.price.toFixed(2)}</td>
                    <td class="quantity">${bid.quantity.toFixed(2)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>

          <div class="orderbook-section">
            <h4 class="section-title" style="color: ${this.colors.sell};">卖单 (Asks)</h4>
            <table class="orderbook-table">
              <thead>
                <tr>
                  <th>价格</th>
                  <th>数量</th>
                </tr>
              </thead>
              <tbody>
                ${orderBook.asks.slice(0, 10).map(ask => `
                  <tr class="ask-row" style="border-left: 3px solid ${this.colors.sell};">
                    <td class="price">${ask.price.toFixed(2)}</td>
                    <td class="quantity">${ask.quantity.toFixed(2)}</td>
                  </tr>
                `).join('')}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    `;

    container.innerHTML = html;
  }

  /**
   * 渲染 Agent 审计面板
   */
  _renderAgentAudit(agent, container) {
    if (!agent) {
      container.innerHTML = '<div class="empty-state">未选择 Agent</div>';
      return;
    }

    const html = `
      <div class="agent-audit-panel">
        <div class="agent-header">
          <h3>${agent.displayName}</h3>
          <span class="strategy-badge">${agent.strategy}</span>
        </div>

        <div class="agent-balance">
          <h4>持仓</h4>
          <div class="balance-items">
            ${Object.entries(agent.portfolio).map(([symbol, balance]) => `
              <div class="balance-item">
                <span class="symbol">${symbol}</span>
                <span class="free">可用: ${balance.free}</span>
                <span class="locked">锁定: ${balance.locked}</span>
              </div>
            `).join('')}
          </div>
        </div>

        <div class="agent-beliefs">
          <h4>信念</h4>
          <ul class="beliefs-list">
            ${agent.beliefs.map(belief => `
              <li><span class="key">${belief.key}</span>: <span class="value">${belief.value}</span></li>
            `).join('')}
          </ul>
        </div>

        <div class="agent-observations">
          <h4>观察 (最近 5 条)</h4>
          <ul class="observations-list">
            ${agent.observations.slice(0, 5).map(obs => `
              <li>
                <span class="time">${new Date(obs.time).toLocaleTimeString()}</span>
                <span class="summary">${obs.summary}</span>
              </li>
            `).join('')}
          </ul>
        </div>

        <div class="agent-decisions">
          <h4>决策 (最近 5 条)</h4>
          <ul class="decisions-list">
            ${agent.decisions.slice(0, 5).map(decision => `
              <li>
                <span class="time">${new Date(decision.time).toLocaleTimeString()}</span>
                <span class="action">${decision.action}</span>
              </li>
            `).join('')}
          </ul>
        </div>
      </div>
    `;

    container.innerHTML = html;
  }

  /**
   * 渲染干预效果预览面板
   */
  _renderInterventionPreview(interventions, container) {
    if (!interventions || interventions.length === 0) {
      container.innerHTML = '<div class="empty-state">暂无干预计划</div>';
      return;
    }

    const html = `
      <div class="intervention-panel">
        ${interventions.map((intervention, idx) => `
          <div class="intervention-item" data-status="${intervention.status}">
            <h4>${intervention.effect_type} <span class="status-badge ${intervention.status}">${intervention.status}</span></h4>
            <div class="stages">
              ${intervention.stages.map((stage, stageIdx) => `
                <div class="stage">
                  <div class="stage-title">Stage ${stageIdx + 1}</div>
                  <div class="effects">
                    ${stage.effects.map(effect => `
                      <div class="effect">
                        <span>${effect.effect_type}</span>
                        <span class="time">${new Date(effect.timestamp).toLocaleTimeString()}</span>
                      </div>
                    `).join('')}
                  </div>
                </div>
              `).join('')}
            </div>
          </div>
        `).join('')}
      </div>
    `;

    container.innerHTML = html;
  }

  /**
   * 显示信息注入面板
   */
  _showInfoPanel() {
    const infoPanel = document.querySelector('#inject-panel');
    const interventionPanel = document.querySelector('#intervention-panel');

    if (infoPanel) infoPanel.style.display = 'flex';
    if (interventionPanel) interventionPanel.style.display = 'none';
  }

  /**
   * 显示干预效果面板
   */
  _showInterventionPanel() {
    const infoPanel = document.querySelector('#inject-panel');
    const interventionPanel = document.querySelector('#intervention-panel');

    if (infoPanel) infoPanel.style.display = 'none';
    if (interventionPanel) interventionPanel.style.display = 'flex';

    // 显示干预效果的侧滑面板
    const interventions = this.dataLayer.getInterventions();
    this.slidePanel.open('intervention', interventions);
  }
}

/**
 * 自举：按依赖顺序 MockDataLayer → SlidePanel → UILayer 实例化并接线。
 * 暴露 app.js 启动块期望的全局名与 init()/tick() 方法（多为空操作，
 * 因为 UILayer 构造时已自启动 500ms 更新循环、SlidePanel 已自建容器）。
 */
(function bootstrap() {
  function boot() {
    if (typeof MockDataLayer === 'undefined' ||
        typeof SlidePanel === 'undefined' ||
        typeof UILayer === 'undefined') {
      console.warn('[bootstrap] 模块未全部加载，跳过自举');
      return;
    }
    const mock = new MockDataLayer();
    const panels = new SlidePanel();
    const ui = new UILayer(mock, panels);

    // 与 app.js 启动块的调用约定对齐
    mock.init = () => {};
    mock.tick = () => mock.getOrderBook(); // 触发一次价格随机游走 + 可能的成交
    panels.init = () => {};
    ui.init = () => {};

    window.__mockData = mock;
    window.__slidePanel = panels;
    window.__uiLayer = ui;
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = UILayer;
}
