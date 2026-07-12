// 首页逻辑：日历式日期选择，收集用户输入，调用后端生成攻略
const api = require('../../utils/api');
const { startProgress, stopProgress } = require('../../utils/progress');
const app = getApp();

function getToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
}

function calcDays(start, end) {
  if (!start || !end) return 0;
  return Math.max(1, Math.ceil((new Date(end) - new Date(start)) / 86400000) + 1);
}

Page({
  data: {
    destination: '',
    startDate: '',
    endDate: '',
    today: getToday(),
    days: 0,
    budget: '',
    selectedTags: [],
    departureCity: '',
    loading: false,
    progressText: '',
    progressInterval: null,
    history: [],
    showHistory: false,
  },

  onShow() {
    this.setData({ history: app.globalData.history });
  },

  onLoad() {
    this.locateCity();
  },

  // 定位：优先GPS坐标→逆地理编码，失败则IP兜底
  locateCity() {
    // 第一步：尝试微信GPS定位
    wx.getLocation({
      type: 'gcj02',
      success: (pos) => {
        wx.request({
          url: api.BASE_URL + `/api/regeo?lat=${pos.latitude}&lng=${pos.longitude}`,
          success: (res) => {
            if (res.data && res.data.success && res.data.city) {
              this.setData({ departureCity: res.data.city });
              return;
            }
            this.ipLocate();
          },
          fail: () => this.ipLocate(),
        });
      },
      fail: () => this.ipLocate(),
    });
  },

  // IP定位兜底
  ipLocate() {
    wx.request({
      url: api.BASE_URL + '/api/locate',
      success: (res) => {
        if (res.data && res.data.success && res.data.city) {
          this.setData({ departureCity: res.data.city });
        } else {
          this.setData({ departureCity: '点击编辑' });
        }
      },
      fail: () => {
        this.setData({ departureCity: '点击编辑' });
      },
    });
  },

  // 手动编辑出发城市
  editCity() {
    wx.showModal({
      title: '出发城市',
      editable: true,
      placeholderText: '请输入出发城市',
      content: this.data.departureCity || '',
      success: (res) => {
        if (res.confirm && res.content && res.content.trim()) {
          this.setData({ departureCity: res.content.trim() });
        }
      },
    });
  },

  onInput(e) {
    const field = e.currentTarget.dataset.field;
    this.setData({ [field]: e.detail.value });
  },

  onStartDateChange(e) {
    const startDate = e.detail.value;
    this.setData({ startDate, days: calcDays(startDate, this.data.endDate) });
  },

  onEndDateChange(e) {
    const endDate = e.detail.value;
    this.setData({ endDate, days: calcDays(this.data.startDate, endDate) });
  },

  onTagTap(e) {
    const tag = e.currentTarget.dataset.tag;
    let tags = [...this.data.selectedTags];
    const idx = tags.indexOf(tag);
    if (idx > -1) { tags.splice(idx, 1); }
    else { tags.push(tag); }
    this.setData({ selectedTags: tags });
  },
  onGenerate() {
    const { destination, days, budget, selectedTags, startDate, endDate } = this.data;
    if (!destination.trim()) {
      wx.showToast({ title: '请输入目的地', icon: 'none' });
      return;
    }
    if (days < 1 || days > 14) {
      wx.showToast({ title: '请选择出行日期（1-14天）', icon: 'none' });
      return;
    }

    this.setData({ loading: true });
    startProgress(this);

    api.generateTrip({
      destination, days, budget, interests: selectedTags,
      start_date: startDate, end_date: endDate,
      departure_city: this.data.departureCity,
    })
      .then(res => {
        stopProgress(this);
        this.setData({ loading: false });
        if (res.success) {
          app.globalData.tripData = res.data;
          app.saveToHistory(res.data);
          wx.navigateTo({ url: '/pages/overview/overview' });
        } else {
          wx.showToast({ title: res.error || '攻略生成失败，请检查网络后重试', icon: 'none', duration: 3000 });
        }
      })
      .catch(err => {
        stopProgress(this);
        this.setData({ loading: false });
        console.error('生成失败:', err);
        wx.showToast({ title: '攻略生成失败，请检查网络后重试', icon: 'none', duration: 3000 });
      });
  },

  toggleHistory() {
    this.setData({ showHistory: !this.data.showHistory });
  },

  onHistoryTap(e) {
    const id = e.currentTarget.dataset.id;
    const record = this.data.history.find(h => h.id === id);
    if (record && record.data) {
      app.globalData.tripData = record.data;
      wx.navigateTo({ url: '/pages/overview/overview' });
    }
  },
});