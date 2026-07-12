// 首页逻辑：收集用户输入，调用后端生成攻略
const api = require('../../utils/api');
const app = getApp();

// 进度文字列表
const PROGRESS_TEXTS = [
  '正在查询目的地信息...',
  '正在获取景点数据...',
  '正在查询天气情况...',
  'AI 正在为你规划行程...',
  '正在生成美食推荐...',
  '即将完成，请稍候...',
];

Page({
  data: {
    destination: '',
    days: 3,
    budget: '',
    selectedTags: [],
    loading: false,
    progressText: '',        // 进度文字
    progressInterval: null,  // 定时器ID
    history: [],             // 历史记录
    showHistory: false,      // 是否展示历史记录
  },

  onShow() {
    // 加载历史记录
    this.setData({ history: app.globalData.history });
  },

  // 处理输入框变化
  onInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [field]: e.detail.value });
  },

  // 天数滑块变化
  onDaysSlider(e) {
    this.setData({ days: e.detail.value });
  },

  // 天数手动输入
  onDaysInput(e) {
    let val = parseInt(e.detail.value) || 1;
    val = Math.max(1, Math.min(7, val));
    this.setData({ days: val });
  },

  // 兴趣标签点击切换
  onTagTap(e) {
    const tag = e.currentTarget.dataset.tag;
    let tags = [...this.data.selectedTags];
    const idx = tags.indexOf(tag);
    if (idx > -1) { tags.splice(idx, 1); }
    else { tags.push(tag); }
    this.setData({ selectedTags: tags });
  },

  // 启动进度文字动画
  startProgress() {
    let index = 0;
    this.setData({ progressText: PROGRESS_TEXTS[0] });
    const interval = setInterval(() => {
      index = (index + 1) % PROGRESS_TEXTS.length;
      this.setData({ progressText: PROGRESS_TEXTS[index] });
    }, 2000);
    this.setData({ progressInterval: interval });
  },

  // 停止进度文字动画
  stopProgress() {
    if (this.data.progressInterval) {
      clearInterval(this.data.progressInterval);
      this.setData({ progressInterval: null, progressText: '' });
    }
  },

  // 一键生成攻略
  onGenerate() {
    const { destination, days, budget, selectedTags } = this.data;
    if (!destination.trim()) {
      wx.showToast({ title: '请输入目的地', icon: 'none' });
      return;
    }

    this.setData({ loading: true });
    this.startProgress();  // 启动进度文字动画

    api.generateTrip({ destination, days, budget, interests: selectedTags })
      .then(res => {
        this.stopProgress();
        this.setData({ loading: false });
        if (res.success) {
          app.globalData.tripData = res.data;
          // 保存到历史记录
          app.saveToHistory(res.data);
          // 先跳转到总览地图页
          wx.navigateTo({ url: '/pages/overview/overview' });
        } else {
          wx.showToast({
            title: res.error || '攻略生成失败，请检查网络后重试',
            icon: 'none',
            duration: 3000,
          });
        }
      })
      .catch(err => {
        this.stopProgress();
        this.setData({ loading: false });
        console.error('生成失败:', err);
        wx.showToast({
          title: '攻略生成失败，请检查网络后重试',
          icon: 'none',
          duration: 3000,
        });
      });
  },

  // 切换历史记录展示
  toggleHistory() {
    this.setData({ showHistory: !this.data.showHistory });
  },

  // 点击历史记录，加载已有攻略
  onHistoryTap(e) {
    const id = e.currentTarget.dataset.id;
    const record = this.data.history.find(h => h.id === id);
    if (record && record.data) {
      app.globalData.tripData = record.data;
      wx.navigateTo({ url: '/pages/overview/overview' });
    }
  },
});