'use strict';

/**
 * SlidePanel: 侧滑面板管理器
 * - 管理多个侧滑面板的打开/关闭
 * - 处理面板内容的动态更新
 * - 支持过渡动画
 */

class SlidePanel {
  constructor(containerSelector = '#slide-panels-container') {
    this.container = document.querySelector(containerSelector);
    if (!this.container) {
      // 如果容器不存在，创建它
      this.container = document.createElement('div');
      this.container.id = 'slide-panels-container';
      this.container.style.cssText = `
        position: fixed;
        top: 64px;
        right: 0;
        width: 40vw;
        height: calc(100vh - 64px);
        z-index: 1000;
        background: rgba(12, 16, 22, 0.95);
        backdrop-filter: blur(8px);
        border-left: 1px solid rgba(216, 207, 187, 0.1);
        overflow-y: auto;
        transform: translateX(100%);
        transition: transform 0.3s ease;
      `;
      document.body.appendChild(this.container);
    }

    this.panels = {};
    this.activePanel = null;
    this.renderers = {};
  }

  /**
   * 注册一个侧滑面板及其渲染器
   * @param {string} name - 面板名称
   * @param {string} title - 面板标题
   * @param {function} renderer - 渲染函数(data, container)
   */
  register(name, title, renderer) {
    // 创建面板容器
    const panelEl = document.createElement('div');
    panelEl.className = 'slide-panel';
    panelEl.dataset.name = name;
    panelEl.style.cssText = `
      padding: 20px;
      overflow-y: auto;
      display: none;
    `;

    // 添加面板标题
    const headerEl = document.createElement('div');
    headerEl.className = 'slide-panel-header';
    headerEl.style.cssText = `
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
      padding-bottom: 10px;
      border-bottom: 1px solid rgba(216, 207, 187, 0.2);
    `;
    headerEl.innerHTML = `
      <h3 style="margin: 0; color: #D8CFBB; font-size: 1.2em;">${title}</h3>
      <button class="close-btn" data-panel="${name}" style="
        background: none;
        border: none;
        color: #D8CFBB;
        cursor: pointer;
        font-size: 1.5em;
        padding: 0;
      ">✕</button>
    `;

    const contentEl = document.createElement('div');
    contentEl.className = 'slide-panel-content';

    panelEl.appendChild(headerEl);
    panelEl.appendChild(contentEl);

    this.container.appendChild(panelEl);
    this.panels[name] = {
      el: panelEl,
      contentEl: contentEl,
      title: title,
    };
    this.renderers[name] = renderer;

    // 绑定关闭按钮
    headerEl.querySelector('.close-btn').addEventListener('click', () => {
      this.close();
    });
  }

  /**
   * 打开指定名称的面板并渲染内容
   * @param {string} name - 面板名称
   * @param {*} data - 传递给渲染器的数据
   */
  open(name, data = null) {
    const panel = this.panels[name];
    if (!panel) {
      console.warn(`Panel '${name}' not found`);
      return;
    }

    // 关闭当前打开的面板
    if (this.activePanel && this.activePanel !== name) {
      this.close();
    }

    // 显示面板
    panel.el.style.display = 'block';

    // 渲染内容
    const renderer = this.renderers[name];
    if (renderer && typeof renderer === 'function') {
      renderer(data, panel.contentEl);
    }

    // 打开侧滑
    this.activePanel = name;
    this._slideIn();
  }

  /**
   * 关闭侧滑面板
   */
  close() {
    if (!this.activePanel) return;

    const panel = this.panels[this.activePanel];
    if (panel) {
      panel.el.style.display = 'none';
    }

    this.activePanel = null;
    this._slideOut();
  }

  /**
   * 切换面板打开/关闭状态
   * @param {string} name - 面板名称
   * @param {*} data - 传递给渲染器的数据
   */
  toggle(name, data = null) {
    if (this.activePanel === name) {
      this.close();
    } else {
      this.open(name, data);
    }
  }

  /**
   * 更新活跃面板的数据（重新渲染）
   * @param {string} name - 面板名称
   * @param {*} data - 新数据
   */
  updateData(name, data) {
    if (this.activePanel !== name) return;

    const panel = this.panels[name];
    if (!panel) return;

    const renderer = this.renderers[name];
    if (renderer && typeof renderer === 'function') {
      renderer(data, panel.contentEl);
    }
  }

  /**
   * 获取当前活跃的面板名称
   */
  getActivePanel() {
    return this.activePanel;
  }

  /**
   * 判断指定面板是否打开
   */
  isOpen(name) {
    return this.activePanel === name;
  }

  /**
   * 侧滑进入动画
   */
  _slideIn() {
    this.container.style.transform = 'translateX(0)';
  }

  /**
   * 侧滑退出动画
   */
  _slideOut() {
    this.container.style.transform = 'translateX(100%)';
  }
}

// 导出
if (typeof module !== 'undefined' && module.exports) {
  module.exports = SlidePanel;
}
