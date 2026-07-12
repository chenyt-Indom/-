// 行程展示页：展示 AI 生成的按天行程、天气、预算、贴士，支持高德地图跳转和分享
const app = getApp();

Page({
  data: {
    tripData: {},
    budgetList: [],
    currentDayIndex: 0,
  },

  onLoad() {
    const data = app.globalData.tripData;
    if (data) {
      wx.setNavigationBarTitle({
        title: `${data.destination}${data.days}日游`,
      });
      const breakdown = data.budget_breakdown || {};
      const budgetList = Object.keys(breakdown).map(key => ({
        name: key,
        value: breakdown[key],
      }));
      this.setData({ tripData: data, budgetList });
    } else {
      wx.showToast({ title: '暂无数据，请返回首页', icon: 'none' });
    }
  },

  // 点击跳转高德地图：收集当天景点坐标，跳转到地图页用特殊图标标注
  onOpenAmap(e) {
    const dayIndex = e.currentTarget.dataset.day;
    const day = this.data.tripData.itinerary[dayIndex];
    if (!day) return;

    // 收集当天有坐标的景点，按游览顺序编号
    const spots = [];
    let order = 1;
    ['morning', 'afternoon', 'evening'].forEach(slot => {
      const s = day[slot];
      if (s && s.spot && s.location) {
        const [lng, lat] = s.location.split(',').map(Number);
        if (!isNaN(lng) && !isNaN(lat)) {
          spots.push({
            id: order,
            name: s.spot,
            latitude: lat,
            longitude: lng,
            order: order,
          });
          order++;
        }
      }
    });

    if (spots.length === 0) {
      wx.showToast({ title: '该天暂无景点坐标', icon: 'none' });
      return;
    }

    // 存储景点数据到全局，跳转到地图页
    app.globalData.mapSpots = spots;
    app.globalData.mapTitle = `Day${day.day} ${day.date || ''} 景点路线`;
    wx.navigateTo({ url: '/pages/map/map' });
  },

  // 分享行程 - 生成图片分享卡片
  onShare() {
    wx.showToast({ title: '正在生成分享卡片...', icon: 'loading' });
    const { tripData } = this.data;
    const ctx = wx.createCanvasContext('shareCanvas', this);
    const width = 375;
    const height = 500;
    ctx.setFillStyle('#4A90D9');
    ctx.fillRect(0, 0, width, 80);
    ctx.setFillStyle('#fff');
    ctx.setFontSize(22);
    ctx.setTextAlign('center');
    ctx.fillText(`旅白 · ${tripData.destination}${tripData.days}日游`, width / 2, 50);
    ctx.setFillStyle('#333');
    ctx.setFontSize(14);
    ctx.setTextAlign('left');
    let y = 110;
    (tripData.itinerary || []).forEach((day) => {
      if (y > height - 60) return;
      ctx.fillText(`Day${day.day} | ${day.morning?.spot || ''} → ${day.afternoon?.spot || ''}`, 20, y);
      y += 24;
    });
    y += 10;
    ctx.setFillStyle('#666');
    ctx.setFontSize(12);
    (tripData.tips || []).forEach(t => {
      if (y > height - 20) return;
      ctx.fillText(`• ${t}`, 20, y);
      y += 20;
    });
    ctx.draw(false, () => {
      wx.canvasToTempFilePath({
        canvasId: 'shareCanvas',
        success: (res) => {
          wx.showToast({ title: '分享卡片已生成', icon: 'success' });
          wx.saveImageToPhotosAlbum({
            filePath: res.tempFilePath,
            success: () => { wx.showToast({ title: '已保存到相册', icon: 'success' }); },
            fail: () => { wx.showToast({ title: '请授权保存图片', icon: 'none' }); },
          });
        },
        fail: () => { wx.showToast({ title: '生成失败，请重试', icon: 'none' }); },
      }, this);
    });
  },

  // 返回总览地图
  onBack() {
    wx.navigateBack();
  },
});