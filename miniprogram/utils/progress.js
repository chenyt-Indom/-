// 进度动画模块：生成攻略时的加载进度文本轮播
const PROGRESS_TEXTS = [
  '正在查询目的地信息...',
  '正在获取景点数据...',
  '正在查询天气情况...',
  'AI 正在为你规划行程...',
  '正在查询机票酒店信息...',
  '正在生成美食推荐...',
  '即将完成，请稍候...',
];

function startProgress(context) {
  let index = 0;
  context.setData({ progressText: PROGRESS_TEXTS[0] });
  const interval = setInterval(() => {
    index = (index + 1) % PROGRESS_TEXTS.length;
    context.setData({ progressText: PROGRESS_TEXTS[index] });
  }, 2000);
  context.setData({ progressInterval: interval });
}

function stopProgress(context) {
  if (context.data.progressInterval) {
    clearInterval(context.data.progressInterval);
    context.setData({ progressInterval: null, progressText: '' });
  }
}

module.exports = { PROGRESS_TEXTS, startProgress, stopProgress };