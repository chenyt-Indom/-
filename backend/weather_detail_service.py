"""天气详情服务：逐时天气估算、极端天气预警"""
import httpx
from config import AMAP_KEY, AMAP_WEATHER_URL


async def get_hourly_weather(city: str, date: str) -> dict:
    """根据城市和日期，返回当日逐时天气估算（基于高德预报+实况）"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 获取实况天气
        resp_base = await client.get(AMAP_WEATHER_URL, params={
            "key": AMAP_KEY, "city": city, "extensions": "base",
        })
        base_data = resp_base.json()
        live = {}
        if base_data.get("status") == "1":
            lives = base_data.get("lives", [])
            if lives:
                live = lives[0]

        # 获取预报天气
        resp_all = await client.get(AMAP_WEATHER_URL, params={
            "key": AMAP_KEY, "city": city, "extensions": "all",
        })
        all_data = resp_all.json()
        forecast = {}
        if all_data.get("status") == "1":
            forecasts = all_data.get("forecasts", [])
            if forecasts:
                for cast in forecasts[0].get("casts", []):
                    if cast.get("date") == date:
                        forecast = cast
                        break

    if not forecast:
        return {"success": False, "error": "无该日期预报数据"}

    # 根据天气预报生成逐时估算
    day_weather = forecast.get("dayweather", "晴")
    night_weather = forecast.get("nightweather", "晴")
    day_temp = int(forecast.get("daytemp", 25))
    night_temp = int(forecast.get("nighttemp", 18))
    day_wind = forecast.get("daywind", "微风")
    night_wind = forecast.get("nightwind", "微风")

    # 当前实况补充
    current_temp = live.get("temperature", str(day_temp))
    current_weather = live.get("weather", day_weather)

    hours = []
    for h in range(24):
        if 6 <= h < 18:
            weather = day_weather
            base_temp = day_temp
            wind = day_wind
        else:
            weather = night_weather
            base_temp = night_temp
            wind = night_wind
        # 温度变化：中午最高，凌晨最低
        if 6 <= h < 12:
            temp = base_temp - 3 + int((h - 6) * 0.5)
        elif 12 <= h < 14:
            temp = base_temp + 1
        elif 14 <= h < 18:
            temp = base_temp - int((h - 14) * 0.5)
        elif 18 <= h < 22:
            temp = base_temp - 1
        else:
            temp = base_temp - 2
        temp = max(temp, base_temp - 5)
        temp = min(temp, base_temp + 2)

        hours.append({
            "time": f"{h:02d}:00",
            "weather": weather,
            "temp": f"{temp}°C",
            "wind": wind,
        })

    # 极端天气判断
    extreme = is_extreme_weather(day_weather, night_weather)

    return {
        "success": True,
        "date": date,
        "city": city,
        "day_weather": day_weather,
        "night_weather": night_weather,
        "day_temp": f"{day_temp}°C",
        "night_temp": f"{night_temp}°C",
        "current": {"temp": f"{current_temp}°C", "weather": current_weather},
        "hours": hours,
        "extreme_alert": extreme,
    }


def is_extreme_weather(day_weather: str, night_weather: str) -> dict:
    """判断是否为极端天气，返回预警信息"""
    extreme_keywords = {
        "暴雨": "暴雨预警：请避免户外活动，注意防范城市内涝和山洪",
        "大雨": "大雨预警：出行请携带雨具，注意路面湿滑",
        "中雨": "中雨提醒：建议携带雨具，合理安排户外活动",
        "雷阵雨": "雷阵雨预警：请注意防雷，避免在开阔地带停留",
        "暴雪": "暴雪预警：请减少外出，注意防寒保暖和交通安全",
        "大雪": "大雪预警：出行请注意防滑，做好防寒措施",
        "中雪": "降雪提醒：路面可能结冰，注意出行安全",
        "沙尘暴": "沙尘暴预警：请关闭门窗，外出佩戴口罩",
        "霾": "雾霾预警：请减少户外活动，外出佩戴口罩",
        "台风": "台风预警：请密切关注台风动向，避免外出",
        "高温": "高温预警：请注意防暑降温，避免长时间户外活动",
        "大风": "大风预警：请注意防风，远离广告牌等危险物",
    }
    alerts = []
    for keyword, msg in extreme_keywords.items():
        if keyword in day_weather or keyword in night_weather:
            alerts.append({"type": keyword, "level": "warning", "message": msg})

    if alerts:
        return {"has_alert": True, "alerts": alerts}
    return {"has_alert": False, "alerts": []}


async def check_weather_alerts(city: str) -> dict:
    """检查天气预警：返回当前生效的极端天气预警"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_WEATHER_URL, params={
            "key": AMAP_KEY, "city": city, "extensions": "all",
        })
        data = resp.json()
        if data.get("status") != "1":
            return {"success": False, "alerts": []}

        forecasts = data.get("forecasts", [])
        if not forecasts:
            return {"success": True, "alerts": []}

        all_alerts = []
        for cast in forecasts[0].get("casts", []):
            extreme = is_extreme_weather(
                cast.get("dayweather", ""),
                cast.get("nightweather", "")
            )
            if extreme["has_alert"]:
                for alert in extreme["alerts"]:
                    all_alerts.append({
                        "date": cast.get("date", ""),
                        "type": alert["type"],
                        "level": alert["level"],
                        "message": f"{cast.get('date','')} {alert['message']}",
                    })

        return {"success": True, "alerts": all_alerts}