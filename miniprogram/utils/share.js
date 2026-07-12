// 分享模块：生成行程分享卡片
function shareTrip(context, tripData) {
  wx.showToast({ title: '正在生成分享卡片...', icon: 'loading' });
  const ctx = wx.createCanvasContext('shareCanvas', context);
  ctx.setFillStyle('#4A90D9'); ctx.fillRect(0, 0, 375, 80);
  ctx.setFillStyle('#fff'); ctx.setFontSize(22); ctx.setTextAlign('center');
  ctx.fillText(`行旅白 · ${tripData.destination}${tripData.days}日游`, 187, 50);
  ctx.setFillStyle('#333'); ctx.setFontSize(14); ctx.setTextAlign('left');
  let y = 110;
  (tripData.itinerary || []).forEach(day => {
    if (y > 440) return;
    ctx.fillText(`Day${day.day} | ${day.morning?.spot || ''} → ${day.afternoon?.spot || ''}`, 20, y);
    y += 24;
  });
  ctx.setFillStyle('#666'); ctx.setFontSize(12);
  (tripData.tips || []).forEach(t => { if (y > 480) return; ctx.fillText(`• ${t}`, 20, y); y += 20; });
  ctx.draw(false, () => {
    wx.canvasToTempFilePath({
      canvasId: 'shareCanvas',
      success: (res) => {
        wx.saveImageToPhotosAlbum({
          filePath: res.tempFilePath,
          success: () => { wx.showToast({ title: '已保存到相册', icon: 'success' }); },
          fail: () => { wx.showToast({ title: '请授权保存图片', icon: 'none' }); },
        });
      },
      fail: () => { wx.showToast({ title: '生成失败，请重试', icon: 'none' }); },
    }, context);
  });
}

module.exports = { shareTrip };