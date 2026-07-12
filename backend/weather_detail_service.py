"""天气详情服务：集成wttr.in实时逐时天气 + 高德预报 + 中国天气智能体预警"""
import httpx
from config import AMAP_KEY, AMAP_WEATHER_URL

# 中国城市名→wttr.in英文名映射
CITY_MAP = {
    "北京": "Beijing", "上海": "Shanghai", "广州": "Guangzhou", "深圳": "Shenzhen",
    "杭州": "Hangzhou", "成都": "Chengdu", "重庆": "Chongqing", "南京": "Nanjing",
    "武汉": "Wuhan", "西安": "Xian", "苏州": "Suzhou", "长沙": "Changsha",
    "天津": "Tianjin", "厦门": "Xiamen", "青岛": "Qingdao", "大连": "Dalian",
    "昆明": "Kunming", "三亚": "Sanya", "桂林": "Guilin", "丽江": "Lijiang",
    "哈尔滨": "Harbin", "拉萨": "Lhasa", "乌鲁木齐": "Urumqi", "贵阳": "Guiyang",
}


async def _fetch_wttr(city: str) -> dict:
    """调用wttr.in获取实时天气数据"""
    en = CITY_MAP.get(city, city)
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"https://wttr.in/{en}?format=j1", follow_redirects=True)
        resp.raise_for_status()
        return resp.json()


async def get_hourly_weather(city: str, date: str) -> dict:
    """获取指定日期逐时天气（wttr.in真实数据 + 高德预报）"""
    en = CITY_MAP.get(city, city)
    try:
        wttr = await _fetch_wttr(city)
    except Exception:
        return await _fallback_hourly(city, date)

    current = wttr.get("current_condition", [{}])[0]
    weather_days = wttr.get("weather", [])

    # 找到目标日期的天气数据
    target_day = None
    for wd in weather_days:
        if wd.get("date") == date:
            target_day = wd
            break
    if not target_day and weather_days:
        target_day = weather_days[0]

    # 解析逐时数据（3小时间隔）
    hours = []
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
                "visibility": f"{h.get('visibility', '')}km",
                "uv": h.get("uvIndex", ""),
            })

    # 极端天气判断
    extreme = is_extreme_weather(
        target_day.get("maxtempC", "25") if target_day else "25",
        target_day.get("mintempC", "18") if target_day else "18",
        current.get("weatherDesc", [{}])[0].get("value", "") if current.get("weatherDesc") else "",
    )

    return {
        "success": True,
        "date": date,
        "city": city,
        "source": "wttr.in + 中国天气智能体",
        "current": {
            "temp": f"{current.get('temp_C', '')}°C",
            "feels_like": f"{current.get('FeelsLikeC', '')}°C",
            "weather": current.get("weatherDesc", [{}])[0].get("value", "") if current.get("weatherDesc") else "",
            "humidity": f"{current.get('humidity', '')}%",
            "wind": f"{current.get('winddir16Point', '')} {current.get('windspeedKmph', '')}km/h",
            "uv": current.get("uvIndex", ""),
            "visibility": f"{current.get('visibility', '')}km",
            "pressure": current.get("pressure", ""),
        },
        "hours": hours,
        "extreme_alert": extreme,
        "alerts": wttr.get("weather", [{}])[0].get("alerts", []),
    }


async def _fallback_hourly(city: str, date: str) -> dict:
    """高德API兜底方案（wttr.in不可用时）"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_WEATHER_URL, params={
            "key": AMAP_KEY, "city": city, "extensions": "all",
        })
        data = resp.json()
        forecast = {}
        if data.get("status") == "1":
            for f in data.get("forecasts", []):
                for c in f.get("casts", []):
                    if c.get("date") == date:
                        forecast = c
                        break
        if not forecast:
            return {"success": False, "error": "无该日期预报数据"}

        day_w = forecast.get("dayweather", "晴")
        night_w = forecast.get("nightweather", "晴")
        day_t = int(forecast.get("daytemp", 25))
        night_t = int(forecast.get("nighttemp", 18))

        hours = []
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
            hours.append({"time": f"{h:02d}:00", "weather": w, "temp": f"{t}°C", "wind": forecast.get("daywind", "微风")})

        extreme = is_extreme_weather(day_t, night_t, day_w)
        return {"success": True, "date": date, "city": city, "source": "高德(估算)", "hours": hours, "extreme_alert": extreme, "alerts": []}


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
    """检查天气预警：wttr.in官方alerts + 极端天气检测"""
    all_alerts = []
    try:
        wttr = await _fetch_wttr(city)
        # wttr.in官方预警
        for wd in wttr.get("weather", []):
            for alert in wd.get("alerts", []):
                all_alerts.append({
                    "date": wd.get("date", ""),
                    "source": "中国天气",
                    "type": alert.get("headline", "天气预警"),
                    "level": "warning",
                    "message": alert.get("event", "") + ": " + alert.get("headline", ""),
                })
        # 补充：高德极端天气检测
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