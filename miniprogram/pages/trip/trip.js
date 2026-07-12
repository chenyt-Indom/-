// 行程展示页：读取全局数据并展示 AI 生成的攻略内容
const app = getApp();

Page({
  data: {
    tripContent: '',  // 攻略内容
  },

  // 页面加载时从全局数据中读取行程内容
  onLoad() {
    const tripData = app.globalData.tripData;
    if (tripData) {
      this.setData({ tripContent: tripData.trip_content || '暂无数据' });
    } else {
      this.setData({ tripContent: '暂无行程数据，请返回首页重新生成。' });
    }
  },

  // 返回首页
  onBack() {
    wx.navigateBack();
  },
});