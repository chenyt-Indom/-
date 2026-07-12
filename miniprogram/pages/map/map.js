// 地图页：使用微信原生 map 组件，标注当天所有景点，按游览顺序编号 1/2/3
const app = getApp();

Page({
  data: {
    markers: [],
    polyline: [],
    title: '',
    latitude: 39.9,   // 默认中心
    longitude: 116.4,
    scale: 13,
  },

  onLoad() {
    const spots = app.globalData.mapSpots || [];
    const title = app.globalData.mapTitle || '景点地图';

    if (spots.length === 0) {
      wx.showToast({ title: '暂无景点坐标数据', icon: 'none' });
      return;
    }

    wx.setNavigationBarTitle({ title: title });

    // 构建 markers：1/2/3 编号标注
    const markers = spots.map((spot, index) => ({
      id: spot.id,
      latitude: spot.latitude,
      longitude: spot.longitude,
      title: spot.name,
      label: {
        content: `${spot.order}`,
        color: '#fff',
        fontSize: 14,
        fontWeight: 'bold',
        bgColor: '#4A90D9',
        borderRadius: 12,
        padding: 4,
        anchorX: 0,
        anchorY: -30,
      },
      callout: {
        content: `${spot.order}. ${spot.name}`,
        color: '#333',
        fontSize: 13,
        borderRadius: 8,
        padding: 8,
        display: 'ALWAYS',
        bgColor: '#fff',
      },
      width: 30,
      height: 30,
    }));

    // 构建路线连线
    const points = spots.map(s => ({
      latitude: s.latitude,
      longitude: s.longitude,
    }));
    const polyline = points.length > 1 ? [{
      points: points,
      color: '#4A90D9',
      width: 4,
      dottedLine: false,
      arrowLine: true,
    }] : [];

    // 计算中心点
    const centerLat = spots.reduce((sum, s) => sum + s.latitude, 0) / spots.length;
    const centerLng = spots.reduce((sum, s) => sum + s.longitude, 0) / spots.length;

    this.setData({
      markers,
      polyline,
      latitude: centerLat,
      longitude: centerLng,
      title,
    });
  },

  // 标记点点击
  onMarkerTap(e) {
    const markerId = e.detail.markerId;
    const marker = this.data.markers.find(m => m.id === markerId);
    if (marker) {
      wx.showToast({ title: marker.title, icon: 'none' });
    }
  },
});