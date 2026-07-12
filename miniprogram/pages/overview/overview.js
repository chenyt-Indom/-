// 总览页：列表视图(Day1/Day2...) + 真实高德地图标注所有景点
const app = getApp();
const { collectAllSpots, buildMarkers, calcCenter } = require('../../utils/markers');

Page({
  data: {
    dayList: [], markers: [],
    latitude: 39.9, longitude: 116.4, scale: 11,
    hasData: false,
  },

  onLoad() {
    const data = app.globalData.tripData;
    if (!data || !data.itinerary) {
      wx.showToast({ title: '暂无行程数据', icon: 'none' });
      return;
    }
    wx.setNavigationBarTitle({ title: `${data.destination}行程总览` });

    const dayList = [];
    let globalOrder = 1;
    (data.itinerary || []).forEach(day => {
      const spots = [];
      ['morning', 'afternoon', 'evening'].forEach(slot => {
        const s = day[slot];
        if (s && s.spot && s.location) {
          const [lng, lat] = s.location.split(',').map(Number);
          if (!isNaN(lng) && !isNaN(lat)) {
            spots.push({ order: globalOrder, name: s.spot, time: slot === 'morning' ? '上午' : slot === 'afternoon' ? '下午' : '晚上', location: s.location, lat, lng });
            globalOrder++;
          }
        }
      });
      dayList.push({ day: day.day, date: day.date || '', spots: spots, expanded: day.day === 1 });
    });

    const allSpots = collectAllSpots(data);
    const markers = buildMarkers(allSpots);
    const center = calcCenter(allSpots);

    this.setData({ dayList, markers, latitude: center.lat, longitude: center.lng, hasData: true });
  },

  onDayToggle(e) {
    const day = e.currentTarget.dataset.day;
    const dayList = this.data.dayList.map(d => {
      if (d.day === day) d.expanded = !d.expanded;
      return d;
    });
    this.setData({ dayList });
  },

  onSpotLocate(e) {
    const { lat, lng, name } = e.currentTarget.dataset;
    this.setData({ latitude: lat, longitude: lng, scale: 14 });
    wx.showToast({ title: name, icon: 'none', duration: 1500 });
  },

  onViewDetail() { wx.navigateTo({ url: '/pages/trip/trip' }); },
  onBack() { wx.navigateBack(); },
});