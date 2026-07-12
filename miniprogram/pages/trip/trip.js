// 行程展示页：卡片详情 + 预约提醒 + 机票/酒店/门票订购跳转
const app = getApp();
const { shareTrip } = require('../../utils/share');

Page({
  data: {
    tripData: {}, booking: {}, budgetList: [],
    slots: [
      { key: 'morning', label: '上午' },
      { key: 'afternoon', label: '下午' },
      { key: 'evening', label: '晚上' },
    ],
  },

  onLoad() {
    const data = app.globalData.tripData;
    if (data) {
      wx.setNavigationBarTitle({ title: `${data.destination}${data.days}日游` });
      const breakdown = data.budget_breakdown || {};
      const budgetList = Object.keys(breakdown).map(key => ({ name: key, value: breakdown[key] }));
      this.setData({ tripData: data, booking: data.booking_info || {}, budgetList });
    } else {
      wx.showToast({ title: '暂无数据，请返回首页', icon: 'none' });
    }
  },

  onOpenAmap(e) {
    const dayIndex = e.currentTarget.dataset.day;
    const day = this.data.tripData.itinerary[dayIndex];
    if (!day) return;
    const spots = [];
    let order = 1;
    ['morning', 'afternoon', 'evening'].forEach(slot => {
      const s = day[slot];
      if (s && s.spot && s.location) {
        const [lng, lat] = s.location.split(',').map(Number);
        if (!isNaN(lng) && !isNaN(lat)) {
          spots.push({ id: order, name: s.spot, latitude: lat, longitude: lng, order: order });
          order++;
        }
      }
    });
    if (spots.length === 0) {
      wx.showToast({ title: '该天暂无景点坐标', icon: 'none' });
      return;
    }
    app.globalData.mapSpots = spots;
    app.globalData.mapTitle = `Day${day.day} ${day.date || ''} 景点路线`;
    wx.navigateTo({ url: '/pages/map/map' });
  },

  onBookLink(e) {
    const link = e.currentTarget.dataset.link;
    const name = e.currentTarget.dataset.name;
    if (!link) return;
    wx.setClipboardData({
      data: link,
      success: () => { wx.showToast({ title: `${name} 链接已复制，请在浏览器打开`, icon: 'none', duration: 2500 }); },
    });
  },

  onShare() { shareTrip(this, this.data.tripData); },
  onBack() { wx.navigateBack(); },
});