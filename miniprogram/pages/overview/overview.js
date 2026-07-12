// 总览地图页：展示所有天数景点分布 + 查看详情按钮
const app = getApp();

Page({
  data: {
    markers: [],
    polyline: [],
    latitude: 39.9,
    longitude: 116.4,
    scale: 11,
    title: '',
    hasData: false,
  },

  onLoad() {
    const data = app.globalData.tripData;
    if (!data || !data.itinerary) {
      wx.showToast({ title: '暂无行程数据', icon: 'none' });
      return;
    }

    wx.setNavigationBarTitle({ title: `${data.destination}景点总览` });

    // 收集所有天的所有景点，按顺序编号
    const allSpots = [];
    let globalOrder = 1;
    (data.itinerary || []).forEach(day => {
      ['morning', 'afternoon', 'evening'].forEach(slot => {
        const s = day[slot];
        if (s && s.spot && s.location) {
          const [lng, lat] = s.location.split(',').map(Number);
          if (!isNaN(lng) && !isNaN(lat)) {
            allSpots.push({
              id: globalOrder,
              name: s.spot,
              longitude: lng,
              latitude: lat,
              order: globalOrder,
              day: day.day,
            });
            globalOrder++;
          }
        }
      });
    });

    if (allSpots.length === 0) {
      wx.showToast({ title: '暂无景点坐标数据', icon: 'none' });
      return;
    }

    // 构建 markers
    const markers = allSpots.map(spot => ({
      id: spot.id,
      latitude: spot.latitude,
      longitude: spot.longitude,
      title: spot.name,
      label: {
        content: `${spot.order}`,
        color: '#fff',
        fontSize: 13,
        fontWeight: 'bold',
        bgColor: '#4A90D9',
        borderRadius: 12,
        padding: 3,
        anchorX: 0,
        anchorY: -28,
      },
      callout: {
        content: `${spot.order}. Day${spot.day} ${spot.name}`,
        color: '#333',
        fontSize: 12,
        borderRadius: 8,
        padding: 8,
        display: 'ALWAYS',
        bgColor: '#fff',
      },
      width: 26,
      height: 26,
    }));

    // 中心点
    const centerLat = allSpots.reduce((s, sp) => s + sp.latitude, 0) / allSpots.length;
    const centerLng = allSpots.reduce((s, sp) => s + sp.longitude, 0) / allSpots.length;

    this.setData({
      markers,
      latitude: centerLat,
      longitude: centerLng,
      hasData: true,
    });
  },

  // 查看详情 → 跳转到行程卡片页
  onViewDetail() {
    wx.navigateTo({ url: '/pages/trip/trip' });
  },

  // 返回首页
  onBack() {
    wx.navigateBack();
  },
});