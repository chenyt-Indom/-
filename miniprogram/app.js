// AI旅行攻略生成器 - 小程序入口
App({
  onLaunch() {
    // 小程序启动时执行
    console.log('AI旅行攻略小程序启动');
  },

  globalData: {
    apiBase: 'http://localhost:8000',  // 后端API地址
    tripData: null,                     // 存储生成的行程数据
  }
});