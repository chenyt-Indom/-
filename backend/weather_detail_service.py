"""天气详情服务：高德逐时预报为主要数据源，wttr.in为补充源"""
import httpx
from datetime import datetime, timedelta
from config import AMAP_KEY, AMAP_WEATHER_URL

# 中国城市名→wttr.in英文名映射
CITY_MAP = {
    "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen",
    "杭州": "Hangzhou", "成都": "Chengdu", "重庆": "Chongqing", "南京": "Nanjing",
    "武汉": "Wuhan", "西安": "Xian", "苏州": "Suzhou", "长沙": "Changsha",
    "天津": "Tianjin", "厦门": "Xiamen", "青岛": "Qingdao", "大连": "Dalian",
    "昆明": "Kunming", "三亚": "Sanya", "桂林": "Guilin", "丽江": "Lijiang",
    "哈尔滨": "Harbin", "拉萨": "Lhasa", "乌鲁木齐": "Urumqi", "贵阳": "Guiyang",
    "郑州": "Zhengzhou", "济南": "Jinan", "合肥": "Hefei", "南昌": "Nanchang",
    "福州": "Fuzhou", "南宁": "Nanning", "海口": "Haikou", "兰州": "Lanzhou",
    "银川": "Yinchuan", "西宁": "Xining", "呼和浩特": "Hohhot", "太原": "Taiyuan",
    "石家庄": "Shijiazhuang", "沈阳": "Shenyang", "长春": "Changchun",
}


def _normalize_date(date_str: str) -> str:
    """将各种日期格式统一为YYYY-MM-DD"""
    import re
    date_str = (date_str or "").strip()
    # 已经是YYYY-MM-DD格式
    if re.match(r'^\d{4}-\d{2}-\d{2}$', date_str):
        return date_str
    # 中文格式：2026年7月13日
    m = re.match(r'(\d{4})年(\d{1,2})月(\d{1,2})日', date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 斜杠格式：2026/07/13
    m = re.match(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_str)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    # 尝试解析
    try:
        from datetime import datetime
        for fmt in ["%Y-%m-%d", "%Y/%m/%d", "%Y年%m月%d日", "%m月%d日"]:
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.year < 2000:
                    dt = dt.replace(year=datetime.now().year)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue
    except Exception:
        pass
    return date_str


async def _fetch_wttr(city: str) -> dict:
    """调用wttr.in获取实时天气数据"""
    en = CITY_MAP.get(city, city)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"https://wttr.in/{en}?format=j1", follow_redirects=True)
        resp.raise_for_status()
        return resp.json()


async def get_hourly_weather(city: str, date: str) -> dict:
    """获取指定日期逐时天气：仅当天返回详细数据，非当天只返回摘要"""
    date = _normalize_date(date)
    # 判断是否为当天
    today = datetime.now().strftime("%Y-%m-%d")
    is_today = (date == today)

    en = CITY_MAP.get(city, city)

    # 并行请求：高德(主) + wttr.in(补充)
    amap_data = None
    wttr_data = None

    # 1. 高德预报（主要数据源）
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_WEATHER_URL, params={
                "key": AMAP_KEY, "city": city, "extensions": "all",
            })
            data = resp.json()
            if data.get("status") == "1":
                for f in data.get("forecasts", []):
                    for c in f.get("casts", []):
                        if c.get("date") == date:
                            amap_data = c
                            break
    except Exception:
        pass

    # 非当天：只返回摘要信息，不返回逐时数据
    if not is_today:
        if amap_data:
            return {
                "success": True, "date": date, "city": city,
                "source": "高德预报", "is_today": False,
                "current": {"temp": f"{amap_data.get('daytemp','')}°C",
                            "weather": amap_data.get("dayweather",""),
                            "wind": amap_data.get("daywind","")},
                "hours": [],
                "summary": f"{amap_data.get('dayweather','')} {amap_data.get('daytemp','')}°C~{amap_data.get('nighttemp','')}°C",
                "message": "逐时天气仅当天可用，届时将显示详细数据"
            }
        return {"success": True, "date": date, "city": city, "is_today": False,
                "hours": [], "message": "逐时天气仅当天可用，届时将显示详细数据"}

    # 并行请求：高德(主) + wttr.in(补充)
    amap_data = None
    wttr_data = None

    # 1. 高德预报（主要数据源）
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_WEATHER_URL, params={
                "key": AMAP_KEY, "city": city, "extensions": "all",
            })
            data = resp.json()
            if data.get("status") == "1":
                for f in data.get("forecasts", []):
                    for c in f.get("casts", []):
                        if c.get("date") == date:
                            amap_data = c
                            break
    except Exception:
        pass

    # 2. wttr.in（补充实时数据）
    try:
        wttr_data = await _fetch_wttr(city)
    except Exception:
        pass

    # 如果两个数据源都没有，返回失败
    if not amap_data and not wttr_data:
        return {"success": False, "error": "天气数据暂不可用，请稍后重试"}

    # 构建逐时数据
    hours = []
    current = {}

    # 从wttr.in获取实时数据
    if wttr_data:
        wttr_current = wttr_data.get("current_condition", [{}])[0]
        current = {
            "temp": f"{wttr_current.get('temp_C', '')}°C",
            "feels_like": f"{wttr_current.get('FeelsLikeC', '')}°C",
            "weather": wttr_current.get("weatherDesc", [{}])[0].get("value", "") if wttr_current.get("weatherDesc") else "",
            "humidity": f"{wttr_current.get('humidity', '')}%",
            "wind": f"{wttr_current.get('winddir16Point', '')} {wttr_current.get('windspeedKmph', '')}km/h",
            "uv": wttr_current.get("uvIndex", ""),
            "visibility": f"{wttr_current.get('visibility', '')}km",
        }
        # 从wttr.in获取逐时数据
        weather_days = wttr_data.get("weather", [])
        target_day = None
        for wd in weather_days:
            if wd.get("date") == date:
                target_day = wd
                break
        if target_day:
            for h in target_day.get("hourly", []):
                time_str = h.get("time", "0")
                hour = int(time_str) // 100
                hours.append({
                    "time": f"{hour:02d}:00",
                    "weather": (h.get("weatherDesc", [{}])[0].get("value", "") if h.get("weatherDesc") else ""),
                    "temp": f"{h.get('tempC', '')}°C",
                    "feels_like": f"{h.get('FeelsLikeC', '')}°C",
                    "wind": f"{h.get('winddir16Point', '')} {h.get('windspeedKmph', '')}km/h",
                    "humidity": f"{h.get('humidity', '')}%",
                    "rain_chance": f"{h.get('chanceofrain', '')}%",
                    "uv": h.get("uvIndex", ""),
                })

    # 如果wttr.in没有逐时数据，从高德数据生成估算
    if not hours and amap_data:
        day_w = amap_data.get("dayweather", "晴")
        night_w = amap_data.get("nightweather", "晴")
        try:
            day_t = int(amap_data.get("daytemp", 25))
            night_t = int(amap_data.get("nighttemp", 18))
        except (ValueError, TypeError):
            day_t, night_t = 25, 18
        wind = amap_data.get("daywind", "微风")
        for h in range(24):
            is_day = 6 <= h < 18
            w = day_w if is_day else night_w
            base = day_t if is_day else night_t
            if 6 <= h < 12:
                t = base - 3 + int((h - 6) * 0.5)
            elif 12 <= h < 14:
                t = base + 1
            elif 14 <= h < 18:
                t = base - int((h - 14) * 0.5)
            else:
                t = base - 2
            t = max(min(t, base + 2), base - 5)
            hours.append({
                "time": f"{h:02d}:00", "weather": w, "temp": f"{t}°C",
                "wind": wind, "rain_chance": "0%", "humidity": "", "uv": ""
            })
        if not current and amap_data:
            current = {
                "temp": f"{day_t}°C", "weather": day_w,
                "wind": wind, "humidity": "", "uv": ""
            }

    # 极端天气判断
    if amap_data:
        extreme = is_extreme_weather(
            amap_data.get("daytemp", "25"), amap_data.get("nighttemp", "18"),
            f"{amap_data.get('dayweather', '')} {amap_data.get('nightweather', '')}"
        )
    else:
        extreme = {"has_alert": False, "alerts": []}

    source = "wttr.in + 高德" if wttr_data else "高德预报"

    return {
        "success": True,
        "date": date,
        "city": city,
        "source": source,
        "is_today": True,
        "current": current,
        "hours": hours,
        "extreme_alert": extreme,
        "alerts": (wttr_data.get("weather", [{}])[0].get("alerts", []) if wttr_data else []),
    }


async def get_realtime_weather(city: str) -> dict:
    """获取实时天气（wttr.in）"""
    try:
        wttr = await _fetch_wttr(city)
        c = wttr.get("current_condition", [{}])[0]
        return {"success": True, "city": city,
                "temp": f"{c.get('temp_C', '')}°C",
                "feels_like": f"{c.get('FeelsLikeC', '')}°C",
                "weather": c.get("weatherDesc", [{}])[0].get("value", "") if c.get("weatherDesc") else "",
                "humidity": f"{c.get('humidity', '')}%",
                "wind": f"{c.get('winddir16Point', '')} {c.get('windspeedKmph', '')}km/h",
                "uv": c.get("uvIndex", ""),
                "visibility": f"{c.get('visibility', '')}km"}
    except Exception:
        return {"success": False, "error": "实时天气获取失败"}


def is_extreme_weather(day_temp, night_temp, weather_desc: str) -> dict:
    """判断极端天气，返回预警信息"""
    try:
        hi = float(str(day_temp))
    except (ValueError, TypeError):
        hi = 25
    alerts = []
    keywords = {
        "暴雨": ("暴雨", "warning", "暴雨预警：避免户外活动，注意防范城市内涝和山洪"),
        "大雨": ("大雨", "warning", "大雨预警：出行携带雨具，注意路面湿滑"),
        "雷阵雨": ("雷阵雨", "warning", "雷阵雨预警：注意防雷，避免在开阔地带停留"),
        "暴雪": ("暴雪", "danger", "暴雪预警：减少外出，注意防寒保暖和交通安全"),
        "大雪": ("大雪", "warning", "大雪预警：出行注意防滑，做好防寒措施"),
        "沙尘暴": ("沙尘暴", "danger", "沙尘暴预警：关闭门窗，外出佩戴口罩"),
        "霾": ("雾霾", "warning", "雾霾预警：减少户外活动，外出佩戴口罩"),
        "台风": ("台风", "danger", "台风预警：密切关注台风动向，避免外出"),
        "大风": ("大风", "warning", "大风预警：注意防风，远离广告牌等危险物"),
        "冰雹": ("冰雹", "danger", "冰雹预警：请立即寻找遮蔽处，避免外出"),
        "冻雨": ("冻雨", "danger", "冻雨预警：路面将严重结冰，尽量避免出行"),
    }
    for keyword, (typ, level, msg) in keywords.items():
        if keyword in str(weather_desc):
            alerts.append({"type": typ, "level": level, "message": msg})
    if hi >= 38:
        alerts.append({"type": "高温", "level": "danger", "message": "高温红色预警：气温超38°C，注意防暑降温，避免户外活动"})
    elif hi >= 35:
        if not any("高温" in a["type"] for a in alerts):
            alerts.append({"type": "高温", "level": "warning", "message": "高温预警：气温超35°C，注意防暑，避免长时间户外活动"})
    if alerts:
        return {"has_alert": True, "alerts": alerts}
    return {"has_alert": False, "alerts": []}


async def check_weather_alerts(city: str) -> dict:
    """检查天气预警：高德预警 + wttr.in官方alerts"""
    all_alerts = []
    try:
        wttr = await _fetch_wttr(city)
        for wd in wttr.get("weather", []):
            for alert in wd.get("alerts", []):
                all_alerts.append({
                    "date": wd.get("date", ""),
                    "source": "中国天气",
                    "type": alert.get("headline", "天气预警"),
                    "level": "warning",
                    "message": alert.get("event", "") + ": " + alert.get("headline", ""),
                })
    except Exception:
        pass
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_WEATHER_URL, params={
                "key": AMAP_KEY, "city": city, "extensions": "all",
            })
            data = resp.json()
            if data.get("status") == "1":
                for f in data.get("forecasts", []):
                    for c in f.get("casts", []):
                        extreme = is_extreme_weather(
                            c.get("daytemp", "25"), c.get("nighttemp", "18"),
                            f"{c.get('dayweather', '')} {c.get('nightweather', '')}"
                        )
                        for a in extreme.get("alerts", []):
                            all_alerts.append({
                                "date": c.get("date", ""), "source": "高德",
                                "type": a["type"], "level": a["level"],
                                "message": f"{c.get('date', '')} {a['message']}",
                            })
    except Exception:
        pass
    return {"success": True, "alerts": all_alerts}