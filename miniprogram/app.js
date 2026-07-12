// 旅白行 AI 旅行规划 - 小程序入口
App({
  onLaunch() {
    console.log('旅白行 AI 旅行规划启动');
    // 加载历史记录
    const history = wx.getStorageSync('trip_history') || [];
    this.globalData.history = history;
  },
  globalData: {
    apiBase: 'http://localhost:8000',
    tripData: null,
    history: [],  // 历史攻略记录
  },

  // 保存攻略到本地历史
  saveToHistory(data) {
    const history = this.globalData.history;
    // 去重：相同目的地+天数的替换
    const idx = history.findIndex(
      h => h.destination === data.destination && h.days === data.days
    );
    const record = {
      id: Date.now(),
      destination: data.destination,
      days: data.days,
      budget: data.budget || '',
      time: new Date().toLocaleString(),
      data: data,
    };
    if (idx > -1) {
      history[idx] = record;
    } else {
      history.unshift(record);
    }
    // 最多保留20条
    if (history.length > 20) history.pop();
    this.globalData.history = history;
    wx.setStorageSync('trip_history', history);
  },
});