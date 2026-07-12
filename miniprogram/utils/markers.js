// 地图标记构建模块：收集行程景点、酒店、门票坐标，构建地图标记
function collectAllSpots(data) {
  const allSpots = [];
  let globalOrder = 1;
  // 收集行程景点
  (data.itinerary || []).forEach(day => {
    ['morning', 'afternoon', 'evening'].forEach(slot => {
      const s = day[slot];
      if (s && s.spot && s.location) {
        const [lng, lat] = s.location.split(',').map(Number);
        if (!isNaN(lng) && !isNaN(lat)) {
          allSpots.push({ id: globalOrder, name: s.spot, longitude: lng, latitude: lat, order: globalOrder, day: day.day, type: 'spot' });
          globalOrder++;
        }
      }
    });
  });
  // 收集酒店和需预约门票位置
  const bk = data.booking_info || {};
  (bk.hotels || []).forEach(h => {
    if (h.location) {
      const [lng, lat] = h.location.split(',').map(Number);
      if (!isNaN(lng) && !isNaN(lat)) {
        allSpots.push({ id: globalOrder, name: h.name, longitude: lng, latitude: lat, order: globalOrder, day: 0, type: 'hotel' });
        globalOrder++;
      }
    }
  });
  (bk.tickets || []).forEach(t => {
    if (t.location && t.need_booking) {
      const [lng, lat] = t.location.split(',').map(Number);
      if (!isNaN(lng) && !isNaN(lat)) {
        allSpots.push({ id: globalOrder, name: t.spot, longitude: lng, latitude: lat, order: globalOrder, day: 0, type: 'ticket' });
        globalOrder++;
      }
    }
  });
  return allSpots;
}

function buildMarkers(allSpots) {
  return allSpots.map(spot => {
    const isHotel = spot.type === 'hotel';
    const isTicket = spot.type === 'ticket';
    const bgColor = isHotel ? '#E67E22' : isTicket ? '#E74C3C' : '#4A90D9';
    const labelContent = isHotel ? '🏨' : isTicket ? '🎫' : `${spot.order}`;
    const calloutContent = isHotel ? `🏨 ${spot.name}` : isTicket ? `🎫 需预约 ${spot.name}` : `${spot.order}. Day${spot.day} ${spot.name}`;
    return {
      id: spot.id, latitude: spot.latitude, longitude: spot.longitude, title: spot.name,
      label: { content: labelContent, color: '#fff', fontSize: 12, fontWeight: 'bold', bgColor: bgColor, borderRadius: 12, padding: 3, anchorX: 0, anchorY: -28 },
      callout: { content: calloutContent, color: '#333', fontSize: 11, borderRadius: 8, padding: 6, display: 'ALWAYS', bgColor: '#fff' },
      width: 24, height: 24,
    };
  });
}

function calcCenter(allSpots) {
  if (allSpots.length === 0) return { lat: 39.9, lng: 116.4 };
  return {
    lat: allSpots.reduce((s, sp) => s + sp.latitude, 0) / allSpots.length,
    lng: allSpots.reduce((s, sp) => s + sp.longitude, 0) / allSpots.length,
  };
}

module.exports = { collectAllSpots, buildMarkers, calcCenter };