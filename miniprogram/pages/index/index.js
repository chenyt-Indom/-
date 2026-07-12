// 首页逻辑：收集用户输入，调用后端生成攻略
const api = require('../../utils/api');
const app = getApp();

Page({
  data: {
    origin: '',     // 出发地
    budget: '',     // 预算
    interests: '',  // 兴趣爱好
    loading: false, // 加载状态
  },

  // 统一处理输入框内容变化
  onInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [field]: e.detail.value });
  },

  // 点击生成攻略按钮
  onGenerate() {
    const { origin, budget, interests } = this.data;

    // 校验出发地不能为空
    if (!origin.trim()) {
      wx.showToast({ title: '请输入出发地', icon: 'none' });
      return;
    }

    this.setData({ loading: true });

    // 调用后端接口生成攻略
    api.generateTrip({ origin, budget, interests })
      .then(res => {
        this.setData({ loading: false });
        if (res.success) {
          // 将数据存入全局，跳转到行程展示页
          app.globalData.tripData = res.data;
          wx.navigateTo({ url: '/pages/trip/trip' });
        } else {
          wx.showToast({ title: '生成失败，请重试', icon: 'none' });
        }
      })
      .catch(err => {
        this.setData({ loading: false });
        console.error('生成攻略失败:', err);
        wx.showToast({ title: '网络错误，请检查后端是否启动', icon: 'none' });
      });
  },
});