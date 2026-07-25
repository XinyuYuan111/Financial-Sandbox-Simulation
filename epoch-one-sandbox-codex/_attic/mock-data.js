'use strict';

/**
 * MockDataLayer: 模拟数据生成器
 * - 生成订单簿（买单/卖单）
 * - 生成成交数据
 * - 生成 Agent 信息及其审计数据
 * - 生成事件日志
 * - 支持确定性随机数（可复现）
 */

class MockDataLayer {
  constructor(seed = 20260725) {
    this.seed = seed;
    this.rng = this._mulberry32(seed);

    // 缓存数据
    this.cache = {
      orderBook: null,
      trades: [],
      agents: [],
      events: [],
      interventions: [],
    };

    // 时间戳
    this.lastUpdate = Date.now();
    this.simulationTime = 0;

    // 初始化数据
    this._initialize();
  }

  /**
   * 初始化所有数据
   */
  _initialize() {
    this.cache.orderBook = this._generateOrderBook();
    this.cache.trades = this._generateTrades();
    this.cache.agents = this._generateAgents();
    this.cache.events = this._generateEvents();
    this.cache.interventions = this._generateInterventions();
  }

  /**
   * 获取订单簿
   */
  getOrderBook() {
    // 更新价格（随机游走）
    if (Date.now() - this.lastUpdate > 500) {
      this._updateOrderBook();
      this.lastUpdate = Date.now();
    }
    return this.cache.orderBook;
  }

  /**
   * 获取最近 N 条成交
   */
  getTrades(limit = 10) {
    return this.cache.trades.slice(0, limit);
  }

  /**
   * 获取所有 Agent
   */
  getAgents() {
    return this.cache.agents;
  }

  /**
   * 获取单个 Agent 的详细信息
   */
  getAgentDetail(agentId) {
    const agent = this.cache.agents.find(a => a.id === agentId);
    if (!agent) return null;

    return {
      id: agentId,
      displayName: agent.displayName,
      strategy: agent.strategy,
      portfolio: agent.portfolio,
      beliefs: [
        { key: '价格信心', value: `${(this.rng() * 100).toFixed(1)}%` },
        { key: '波动率预期', value: `${(this.rng() * 50 + 10).toFixed(2)}%` },
        { key: '流动性评估', value: this.rng() > 0.5 ? '充足' : '紧张' },
      ],
      observations: agent.observations || [],
      decisions: agent.decisions || [],
    };
  }

  /**
   * 获取事件日志
   */
  getEvents() {
    return this.cache.events;
  }

  /**
   * 获取干预计划
   */
  getInterventions() {
    return this.cache.interventions;
  }

  /**
   * =================== 私有方法 ===================
   */

  /**
   * 生成订单簿
   */
  _generateOrderBook() {
    const basePrice = 100;
    const bids = [];
    const asks = [];

    // 生成买单（从高到低）
    for (let i = 0; i < 10; i++) {
      const price = basePrice - i * 0.5 - this.rng() * 0.2;
      const qty = (this.rng() * 1000 + 100).toFixed(2);
      bids.push({
        id: `bid-${i}`,
        side: 'buy',
        price: parseFloat(price.toFixed(2)),
        quantity: parseFloat(qty),
        agent_id: `agent-${Math.floor(this.rng() * 6)}`,
      });
    }

    // 生成卖单（从低到高）
    for (let i = 0; i < 10; i++) {
      const price = basePrice + i * 0.5 + this.rng() * 0.2;
      const qty = (this.rng() * 1000 + 100).toFixed(2);
      asks.push({
        id: `ask-${i}`,
        side: 'sell',
        price: parseFloat(price.toFixed(2)),
        quantity: parseFloat(qty),
        agent_id: `agent-${Math.floor(this.rng() * 6)}`,
      });
    }

    const lastPrice = (bids[0].price + asks[0].price) / 2;
    const midPrice = lastPrice;
    const spread = (asks[0].price - bids[0].price).toFixed(4);

    return {
      bids,
      asks,
      lastPrice,
      midPrice,
      spread,
      volume24h: this.rng() * 10000000 + 5000000,
      timestamp: Date.now(),
    };
  }

  /**
   * 更新订单簿（价格随机游走）
   */
  _updateOrderBook() {
    const ob = this.cache.orderBook;
    const jitter = (this.rng() - 0.5) * 0.01; // ±0.5%

    ob.lastPrice = ob.lastPrice * (1 + jitter);
    ob.midPrice = ob.midPrice * (1 + jitter);

    // 更新买卖单
    ob.bids.forEach(bid => {
      bid.price = bid.price * (1 + jitter);
      bid.quantity = bid.quantity * (this.rng() * 0.2 + 0.9);
    });

    ob.asks.forEach(ask => {
      ask.price = ask.price * (1 + jitter);
      ask.quantity = ask.quantity * (this.rng() * 0.2 + 0.9);
    });

    ob.spread = (ob.asks[0].price - ob.bids[0].price).toFixed(4);
    ob.timestamp = Date.now();

    // 可能生成新的成交
    if (this.rng() > 0.7) {
      this._addTrade(ob);
    }
  }

  /**
   * 生成成交数据
   */
  _generateTrades(count = 20) {
    const trades = [];
    const now = Date.now();

    for (let i = 0; i < count; i++) {
      const price = 100 + (this.rng() - 0.5) * 2;
      const qty = this.rng() * 500 + 50;

      trades.push({
        id: `trade-${i}`,
        buyer_id: `agent-${Math.floor(this.rng() * 6)}`,
        seller_id: `agent-${Math.floor(this.rng() * 6)}`,
        price: parseFloat(price.toFixed(2)),
        quantity: parseFloat(qty.toFixed(2)),
        fee: parseFloat((qty * price * 0.001).toFixed(2)),
        timestamp: now - (count - i) * 1000,
      });
    }

    return trades.sort((a, b) => b.timestamp - a.timestamp);
  }

  /**
   * 添加单条成交
   */
  _addTrade(orderBook) {
    const price = (orderBook.bids[0].price + orderBook.asks[0].price) / 2;
    const qty = this.rng() * 200 + 20;

    const trade = {
      id: `trade-${Date.now()}`,
      buyer_id: `agent-${Math.floor(this.rng() * 6)}`,
      seller_id: `agent-${Math.floor(this.rng() * 6)}`,
      price: parseFloat(price.toFixed(2)),
      quantity: parseFloat(qty.toFixed(2)),
      fee: parseFloat((qty * price * 0.001).toFixed(2)),
      timestamp: Date.now(),
    };

    this.cache.trades.unshift(trade);
    if (this.cache.trades.length > 100) {
      this.cache.trades.pop();
    }
  }

  /**
   * 生成 Agent 信息
   */
  _generateAgents(count = 6) {
    const agents = [];
    const strategies = ['skeptic', 'follower', 'maker'];

    for (let i = 0; i < count; i++) {
      agents.push({
        id: `agent-${i}`,
        displayName: `Agent ${String.fromCharCode(65 + i)}`,
        strategy: strategies[i % strategies.length],
        portfolio: {
          USDT: {
            free: this.rng() * 100000 + 10000,
            locked: this.rng() * 50000,
          },
          ETH: {
            free: this.rng() * 100,
            locked: this.rng() * 50,
          },
        },
        openOrders: this.rng() > 0.5 ? Math.floor(this.rng() * 5) : 0,
        observations: this._generateObservations(3),
        decisions: this._generateDecisions(3),
      });
    }

    return agents;
  }

  /**
   * 生成观察日志
   */
  _generateObservations(count = 3) {
    const obs = [];
    const templates = [
      '价格上升，卖压增加',
      '交易量突增，流动性改善',
      '买单堆积，看涨信号',
      '连续下跌，风险提升',
      '成交额创新高，市场热度高',
    ];

    for (let i = 0; i < count; i++) {
      obs.push({
        id: `obs-${i}`,
        time: Date.now() - (count - i) * 60000,
        summary: templates[Math.floor(this.rng() * templates.length)],
      });
    }

    return obs;
  }

  /**
   * 生成决策记录
   */
  _generateDecisions(count = 3) {
    const decisions = [];
    const actions = ['buy', 'sell', 'hold', 'increase_position', 'reduce_position'];

    for (let i = 0; i < count; i++) {
      decisions.push({
        id: `decision-${i}`,
        time: Date.now() - (count - i) * 120000,
        action: actions[Math.floor(this.rng() * actions.length)],
        reason: `基于信念更新做出的决策`,
      });
    }

    return decisions;
  }

  /**
   * 生成事件日志
   */
  _generateEvents(count = 30) {
    const events = [];
    const types = ['order_placed', 'order_filled', 'order_cancelled', 'information_published', 'agent_state_changed'];
    const visibilities = ['public', 'participants', 'analyst_only', 'agent_private'];

    for (let i = 0; i < count; i++) {
      events.push({
        id: `event-${i}`,
        type: types[Math.floor(this.rng() * types.length)],
        source_id: `agent-${Math.floor(this.rng() * 6)}`,
        visibility: visibilities[Math.floor(this.rng() * visibilities.length)],
        timestamp: Date.now() - (count - i) * 5000,
        payload: {
          summary: `Event ${i} occurred`,
        },
      });
    }

    return events.sort((a, b) => b.timestamp - a.timestamp);
  }

  /**
   * 生成干预计划
   */
  _generateInterventions(count = 2) {
    const interventions = [];
    const effectTypes = ['publish_information', 'set_market_status', 'transfer_asset', 'create_world_entity'];

    for (let i = 0; i < count; i++) {
      interventions.push({
        id: `intervention-${i}`,
        effect_type: effectTypes[Math.floor(this.rng() * effectTypes.length)],
        status: i === 0 ? 'pending' : 'approved',
        stages: [
          {
            stage_id: 0,
            effects: [
              {
                effect_type: 'publish_information',
                timestamp: Date.now(),
              },
            ],
          },
        ],
      });
    }

    return interventions;
  }

  /**
   * Mulberry32 伪随机数生成器（确定性）
   * @param {number} seed
   */
  _mulberry32(seed) {
    return function () {
      let t = (seed += 0x6d2b79f5);
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = MockDataLayer;
}
