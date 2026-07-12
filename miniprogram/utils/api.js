// API 工具模块：封装与后端通信的请求方法
// 上线前替换 YOUR_DOMAIN 为你的真实域名
const BASE_URL = 'https://YOUR_DOMAIN.com';

// 生成旅行攻略，请求体包含目的地、天数、预算、兴趣标签、日期范围
function generateTrip(data) {
  return new Promise((resolve, reject) => {
    wx.request({
      url: `${BASE_URL}/api/generate-trip`,
      method: 'POST',
      data: {
        destination: data.destination,
        days: data.days,
        budget: data.budget,
        interests: data.interests || [],
        start_date: data.start_date || '',
        end_date: data.end_date || '',
      },
      success(res) {
        if (res.statusCode === 200) {
          resolve(res.data);
        } else {
          reject(new Error(`请求失败，状态码: ${res.statusCode}`));
        }
      },
      fail(err) {
        reject(err);
      },
    });
  });
}

module.exports = { generateTrip };