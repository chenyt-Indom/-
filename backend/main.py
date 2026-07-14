"""行旅白 AI 旅行规划 - FastAPI 后端"""
import os
import json
import httpx
import asyncio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models import TripRequest
from config import AMAP_KEY, DEEPSEEK_KEY, AMAP_REGEO_URL
from amap_service import amap_poi_search, amap_weather, amap_geocode, fill_coordinates
from deepseek_service import call_deepseek, build_trip_prompt, build_booking_prompt, build_regenerate_prompt
from image_service import fill_images, fill_booking_images, resolve_spot_image, resolve_hotel_image
from image_search_service import search_images
from feichangzhun_service import (
    judge_transport, search_flights, build_flight_query_text,
    get_route_schedule, get_nearest_hub, get_transfer_routes,
    sanitize_airport_name, is_airport_valid, DECOMMISSIONED_AIRPORTS
)
from weather_detail_service import get_hourly_weather, check_weather_alerts, get_realtime_weather
from china_weather_service import get_observation, get_air_quality, get_weather_chat
from route_service import (
    get_route_plan, calculate_self_drive_plan,
    calculate_transit_to_station, get_route_time, calculate_station_to_hotel
)

app = FastAPI(title="行旅白 AI 旅行规划")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/app", StaticFiles(directory=_static_dir, html=True), name="static")


# ===================== 辅助函数 =====================

def _parse_ai_json(raw_text: str) -> dict:
    """解析AI返回的JSON文本，清理markdown代码块前缀后缀"""
    return json.loads(
        raw_text.strip().removeprefix("```json").removeprefix("```")
        .removesuffix("```").strip()
    )


def _map_deepseek_error(status_code: int) -> str:
    """将DeepSeek HTTP状态码映射为用户友好的错误消息"""
    error_map = {
        402: "DeepSeek API 余额不足，请充值后重试",
        401: "DeepSeek API Key 无效",
        429: "请求过于频繁，请稍后重试",
    }
    return error_map.get(status_code, "AI服务调用失败")


async def _call_deepseek_safely(system_prompt: str, user_prompt: str,
                                 max_tokens: int = 4000) -> str:
    """安全调用DeepSeek API，统一处理HTTP错误"""
    try:
        return await call_deepseek(system_prompt, user_prompt, max_tokens)
    except httpx.HTTPStatusError as error:
        raise ValueError(_map_deepseek_error(error.response.status_code))
    except Exception:
        raise ValueError("AI服务调用失败，请重试")


async def _gather_poi_and_weather(dest: str, interests: list) -> tuple:
    """并行查询高德POI和天气数据，返回去重排序后的POI列表和天气数据"""
    poi_tasks = [
        amap_poi_search(f"{dest}景点", dest),
        amap_poi_search(f"{dest}美食", dest),
    ]
    if interests:
        poi_tasks.append(amap_poi_search(f"{dest}{' '.join(interests)}", dest))

    poi_results, weather_data = await asyncio.gather(
        asyncio.gather(*poi_tasks),
        amap_weather(dest)
    )

    # 合并POI结果
    all_pois = []
    for poi_result in poi_results:
        if isinstance(poi_result, list):
            all_pois.extend(poi_result)

    # 去重并按评分降序排列
    seen_names = set()
    unique_pois = []
    for poi_item in all_pois:
        if poi_item["name"] not in seen_names:
            seen_names.add(poi_item["name"])
            unique_pois.append(poi_item)
    unique_pois.sort(key=lambda x: float(x["rating"]) if x["rating"] else 0, reverse=True)
    return unique_pois[:20], weather_data


async def _build_transport_info(departure_city: str, dest: str,
                                 start_date: str, end_date: str,
                                 is_self_drive: bool) -> dict:
    """构建交通信息字典，供AI生成行程使用"""
    transport_info = {}
    if not departure_city:
        return transport_info

    # 判断交通工具
    transport_judgment = judge_transport(departure_city, dest)
    transport_info["transport"] = transport_judgment

    # 查询真实航班/火车班次数据
    transport_info["route_schedule"] = get_route_schedule(departure_city, dest, start_date)
    transport_info["transfer_info"] = get_transfer_routes(departure_city, dest, start_date)

    # 检查邻近枢纽
    transport_info["dep_hub"] = get_nearest_hub(departure_city)
    transport_info["dest_hub"] = get_nearest_hub(dest)

    # 计算前往/离开机场车站的时间
    station_type = "airport" if transport_judgment.get("need_flight") else "train"
    transport_info["to_station"] = await calculate_transit_to_station(departure_city, station_type)
    transport_info["from_station"] = await calculate_station_to_hotel(dest, station_type)

    # 生成票务查询指引
    transport_info["flight_query_text"] = build_flight_query_text(
        departure_city, dest, start_date)

    # 自驾模式：计算自驾路线
    if is_self_drive:
        transport_info["self_drive_plan"] = await calculate_self_drive_plan(
            departure_city, dest, start_date, end_date)

    # 飞常准航班查询
    if transport_judgment.get("need_flight"):
        flight_result = await search_flights(departure_city, dest, start_date)
        transport_info["flight_data"] = flight_result.get("flights", [])
        transport_info["flight_query"] = flight_result.get("query", {})

    return transport_info


async def _fill_booking_coordinates(booking_info: dict, dest: str):
    """为酒店和门票补全坐标"""
    for hotel in booking_info.get("hotels", []):
        if hotel.get("name") and not hotel.get("location"):
            hotel["location"] = await amap_geocode(hotel["name"], dest)
    for change in booking_info.get("hotel_changes", []):
        if change.get("to_hotel") and not change.get("location"):
            change["location"] = await amap_geocode(change["to_hotel"], dest)
    for ticket in booking_info.get("tickets", []):
        if ticket.get("spot") and not ticket.get("location"):
            ticket["location"] = await amap_geocode(ticket["spot"], dest)


async def _fill_images_safely(trip_data: dict, booking_info: dict, dest: str):
    """超时保护下获取景点和酒店图片"""
    try:
        await asyncio.wait_for(fill_images(trip_data, dest), timeout=25.0)
    except (asyncio.TimeoutError, Exception):
        pass
    try:
        await asyncio.wait_for(fill_booking_images(booking_info, dest), timeout=25.0)
    except (asyncio.TimeoutError, Exception):
        pass


def _validate_transport_airports(trip_data: dict):
    """后处理验证：检查AI生成的机场名是否在白名单中，修正非法机场名"""

    def _check_and_sanitize_station(transport: dict, station_key: str = "station"):
        """检查单个transport的station字段，修正非法机场名"""
        station = transport.get(station_key, "")
        # 检查黑名单
        for banned in DECOMMISSIONED_AIRPORTS:
            if banned in station:
                print(f"[WARN] AI使用了停用机场: {station}，已清空{station_key}字段")
                transport[station_key] = ""
                transport["note"] = (transport.get("note", "") +
                                     "（原机场已停用，请自行查询当前运营机场）").strip()
                return

        # 如果station不为空但不在白名单中
        if transport.get(station_key) and not is_airport_valid(transport.get(station_key, "")):
            sanitized = sanitize_airport_name(transport.get(station_key, ""))
            if sanitized:
                transport[station_key] = sanitized
            else:
                print(f"[WARN] AI使用了未知机场: {station}，已清空{station_key}字段")
                transport[station_key] = ""
                transport["note"] = (transport.get("note", "") +
                                     "（机场信息未验证，请核实）").strip()

    def _validate_transfers(transport: dict):
        """检查transfers中的机场名"""
        for transfer in transport.get("transfers", []):
            for trans_key in ("from_station", "to_station"):
                trans_station = transfer.get(trans_key, "")
                for banned in DECOMMISSIONED_AIRPORTS:
                    if banned in trans_station:
                        transfer[trans_key] = ""
                        break
                if transfer.get(trans_key) and not is_airport_valid(transfer.get(trans_key, "")):
                    sanitized = sanitize_airport_name(transfer.get(trans_key, ""))
                    transfer[trans_key] = sanitized if sanitized else ""

    def _validate_flight_number(transport: dict):
        """如果flight_number非空但station为空，清空flight_number"""
        if transport.get("flight_number") and not transport.get("station"):
            print(f"[WARN] AI编造了航班号但无有效机场: {transport.get('flight_number')}，已清空")
            transport["flight_number"] = ""
            transport["note"] = (transport.get("note", "") +
                                 "（航班信息未验证，请自行查询）").strip()

    for key in ("departure_transport", "return_transport"):
        transport = trip_data.get(key, {})
        if not transport:
            continue
        _check_and_sanitize_station(transport)
        _validate_transfers(transport)
        _validate_flight_number(transport)


# ===================== API 路由 =====================

@app.get("/api/health")
async def health_check():
    """健康检查：返回API密钥配置状态"""
    return {"status": "ok", "amap_key": bool(AMAP_KEY), "deepseek_key": bool(DEEPSEEK_KEY)}


@app.get("/api/locate")
async def locate_city(request: Request):
    """IP定位：高德API优先，ip-api.com兜底，ipapi.co交叉验证。移动端IP可能不准。"""
    import re
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.headers.get("X-Real-IP", "")
    if not client_ip:
        client_ip = request.client.host if request.client else ""
    is_private = bool(re.match(
        r'^(127\.|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)', client_ip
    )) or client_ip == "::1"

    async with httpx.AsyncClient(timeout=10.0) as client:
        # 方案1：高德IP定位
        params = {"key": AMAP_KEY}
        if not is_private and client_ip:
            params["ip"] = client_ip
        response = await client.get("https://restapi.amap.com/v3/ip", params=params)
        amap_data = response.json()
        if amap_data.get("status") == "1" and amap_data.get("city"):
            amap_city = amap_data["city"].replace("市", "")
            # 方案3：用ipapi.co交叉验证
            try:
                ipapi_response = await client.get(
                    f"https://ipapi.co/{client_ip}/json/", follow_redirects=True)
                ipapi_data = ipapi_response.json()
                ipapi_city = (ipapi_data.get("city", "") or "").replace("市", "")
                if ipapi_city and ipapi_city != amap_city and len(ipapi_city) >= 2:
                    # 再用ip-api.com作为决胜票
                    try:
                        ipapi2_response = await client.get(
                            f"http://ip-api.com/json/{client_ip}?lang=zh-CN&fields=city,regionName",
                            follow_redirects=True)
                        ipapi2_data = ipapi2_response.json()
                        ipapi2_city = (ipapi2_data.get("city", "") or "").replace("市", "")
                        if ipapi2_city and ipapi2_city == ipapi_city:
                            return {"success": True, "city": ipapi_city,
                                    "province": ipapi_data.get("region", ""),
                                    "adcode": "", "source": "ipapi_co"}
                    except Exception:
                        pass
                    return {"success": True, "city": ipapi_city,
                            "province": ipapi_data.get("region", ""),
                            "adcode": "", "source": "ipapi_co"}
            except Exception:
                pass
            return {"success": True, "city": amap_city,
                    "province": amap_data.get("province", ""),
                    "adcode": amap_data.get("adcode", ""), "source": "amap"}

        # 方案2：ip-api.com 兜底
        try:
            ip_url = "http://ip-api.com/json/?lang=zh-CN&fields=city,regionName,country"
            if not is_private and client_ip:
                ip_url = f"http://ip-api.com/json/{client_ip}?lang=zh-CN&fields=city,regionName,country"
            response2 = await client.get(ip_url, follow_redirects=True)
            data2 = response2.json()
            if isinstance(data2, dict) and data2.get("city"):
                return {"success": True, "city": data2["city"].replace("市", ""),
                        "province": data2.get("regionName", ""), "adcode": "",
                        "source": "ip-api"}
        except Exception:
            pass

        # 方案4：ipapi.co 最后兜底
        try:
            if not is_private and client_ip:
                ipapi_response = await client.get(
                    f"https://ipapi.co/{client_ip}/json/", follow_redirects=True)
                ipapi_data = ipapi_response.json()
                ipapi_city = (ipapi_data.get("city", "") or "").replace("市", "")
                if ipapi_city:
                    return {"success": True, "city": ipapi_city,
                            "province": ipapi_data.get("region", ""),
                            "adcode": "", "source": "ipapi_co"}
        except Exception:
            pass
        return {"success": False, "city": "", "error": "无法定位"}


@app.get("/api/regeo")
async def reverse_geocode(lat: float, lng: float):
    """GPS坐标逆地理编码：通过高德API将经纬度转换为城市名"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(AMAP_REGEO_URL, params={
            "key": AMAP_KEY, "location": f"{lng},{lat}", "extensions": "base",
        })
        data = response.json()
        if data.get("status") == "1":
            regeo = data.get("regeocode", {})
            addr = regeo.get("addressComponent", {})
            city = addr.get("city", "") or addr.get("province", "")
            return {"success": True, "city": city.replace("市", "").replace("省", ""),
                    "district": addr.get("district", ""),
                    "province": addr.get("province", ""),
                    "address": regeo.get("formatted_address", "")}
        return {"success": False, "city": "", "error": "逆地理编码失败"}


@app.post("/api/generate-trip")
async def generate_trip(req: TripRequest):
    """生成旅行攻略：高德POI+天气 → DeepSeek itinerary → DeepSeek booking → 返回完整JSON"""
    try:
        dest = req.destination.strip()
        days = max(1, min(14, req.days))
        start_date = req.start_date or ""
        end_date = req.end_date or ""

        # 1. 并行查询高德 POI 和天气
        ranked_pois, weather_data = await _gather_poi_and_weather(dest, req.interests)

        # 2. 构建交通信息
        transport_info = await _build_transport_info(
            req.departure_city, dest, start_date, end_date, req.is_self_drive)

        # 3. 调用 DeepSeek 生成行程
        prompt = build_trip_prompt(dest, days, req.budget, req.interests, ranked_pois,
                                   weather_data, start_date, end_date, req.travelers,
                                   req.budget_type, req.pace, req.is_self_drive,
                                   req.departure_city, transport_info)
        try:
            raw = await _call_deepseek_safely("你是一个专业的旅行规划师，只输出JSON格式数据。", prompt)
        except ValueError as error:
            return {"success": False, "error": str(error)}

        try:
            trip_data = _parse_ai_json(raw)
        except Exception:
            return {"success": False, "error": "AI返回数据格式异常，请重试"}

        # 后处理验证：检查并修正AI生成的机场名
        _validate_transport_airports(trip_data)

        # 4. 补全景点坐标
        await fill_coordinates(trip_data, dest)

        # 5. 调用 DeepSeek 查询订票/酒店信息
        itinerary = trip_data.get("itinerary", [])
        booking_prompt = build_booking_prompt(dest, start_date, end_date, req.budget,
                                              itinerary, req.departure_city, transport_info)
        try:
            booking_raw = await _call_deepseek_safely(
                "你是一个旅行服务顾问，只输出JSON格式数据。", booking_prompt, 3000)
            booking_info = _parse_ai_json(booking_raw)
        except Exception:
            booking_info = {"flights": [], "hotels": [], "tickets": [], "booking_tips": []}

        # 6. 为酒店和门票补全坐标
        await _fill_booking_coordinates(booking_info, dest)

        # 7. 获取图片
        await _fill_images_safely(trip_data, booking_info, dest)

        trip_data["booking_info"] = booking_info
        trip_data["transport_info"] = transport_info
        return {"success": True, "data": trip_data}
    except Exception as error:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"服务异常：{str(error)}"}


# ===================== 天气相关 API =====================

@app.get("/api/weather-hourly")
async def weather_hourly(city: str, date: str):
    """获取指定日期的逐时天气估算"""
    return await get_hourly_weather(city, date)


@app.get("/api/weather-alerts")
async def weather_alerts(city: str):
    """获取极端天气预警"""
    return await check_weather_alerts(city)


@app.get("/api/weather-now")
async def weather_now(city: str):
    """获取实时天气（中国天气智能体集成）"""
    return await get_realtime_weather(city)


@app.get("/api/china-weather/observation")
async def china_weather_observation(city: str):
    """中国天气智能体-实况观测：综合实时数据+预报摘要"""
    return await get_observation(city)


@app.get("/api/china-weather/air-quality")
async def china_weather_air_quality(city: str):
    """中国天气智能体-空气质量指数"""
    return await get_air_quality(city)


@app.get("/api/china-weather/chat")
async def china_weather_chat(city: str, query: str = ""):
    """中国天气智能体-AI天气对话助手"""
    return await get_weather_chat(city, query)


# ===================== 景点/酒店详情 API =====================

@app.get("/api/spot-detail")
async def spot_detail(name: str, city: str, reason: str = "", route_detail: str = ""):
    """DeepSeek 生成景点详细介绍（≥500字），含著名小景点"""
    prompt = f"""请为景点「{name}」（位于{city}）撰写一份详细的图文介绍。

要求：
1. 总字数不低于500字
2. 包含景点历史背景、文化特色、建筑风格、著名打卡点
3. 在段落之间穿插介绍该景点内2-3个著名小景点/子景点（如具体宫殿、塔楼、园林、展厅等），每个小景点3-4句话
4. 语言优美，适合旅行攻略阅读
5. 输出纯文本，不要markdown格式，分段用空行隔开"""

    try:
        raw = await call_deepseek("你是一个资深旅行编辑，擅长撰写景点深度介绍。", prompt, 2000)
        return {"success": True, "content": raw.strip()}
    except Exception as error:
        return {"success": False,
                "content": reason or f"{name}是{city}的著名景点，值得一游。",
                "error": str(error)}


@app.get("/api/hotel-detail")
async def hotel_detail(name: str, city: str, area: str = "", reason: str = ""):
    """DeepSeek 生成酒店详细介绍（≥500字）"""
    prompt = f"""请为酒店「{name}」（位于{city}{area}）撰写一份详细的介绍。

要求：
1. 总字数不低于500字
2. 包含酒店位置优势、周边交通、配套设施、房型特色、服务亮点
3. 在段落之间穿插介绍酒店周边2-3个便利设施或景点（如附近地铁站、商圈、夜市、公园等）
4. 语言专业，适合旅行攻略阅读
5. 输出纯文本，不要markdown格式，分段用空行隔开"""

    try:
        raw = await call_deepseek("你是一个资深旅行编辑，擅长撰写酒店深度介绍。", prompt, 2000)
        return {"success": True, "content": raw.strip()}
    except Exception as error:
        return {"success": False,
                "content": reason or f"{name}位于{city}{area}，地理位置优越，是旅途中的理想下榻之选。",
                "error": str(error)}


# ===================== 路线规划与监控 API =====================

@app.post("/api/route-plan")
async def route_plan(request: Request):
    """高德路线规划：实时路况、驾车耗时、到达时间预测"""
    body = await request.json()
    spots = body.get("spots", [])
    if not spots or len(spots) < 2:
        return {"success": False, "error": "至少需要2个景点"}
    routes = await get_route_plan(spots)
    return {"success": True, "routes": routes}


@app.post("/api/monitor-trip")
async def monitor_trip(request: Request):
    """DeepSeek实时监测：检查路况/天气变化，给出突发情况建议"""
    body = await request.json()
    trip_data = body.get("trip_data", {})
    current_location = body.get("current_location", {})
    rejected = body.get("rejected", False)

    if rejected:
        return {"success": True, "has_alert": False, "message": ""}

    dest = trip_data.get("destination", "")
    if not dest:
        return {"success": False, "error": "缺少目的地信息"}

    alerts = []
    # 1. 检查天气预警
    try:
        weather_alerts_result = await check_weather_alerts(dest)
        if weather_alerts_result.get("alerts"):
            alerts.append({"type": "weather",
                           "message": f"目的地{dest}天气预警：" +
                           weather_alerts_result["alerts"][0]["message"]})
    except Exception:
        pass

    # 2. 检查实时路况
    if current_location.get("lng") and current_location.get("lat"):
        try:
            dest_loc = await amap_geocode(dest, dest)
            if dest_loc:
                dest_lng, dest_lat = map(float, dest_loc.split(","))
                route = await get_route_time(
                    current_location["lng"], current_location["lat"], dest_lng, dest_lat)
                if route.get("traffic") in ("拥堵", "缓行"):
                    alerts.append({"type": "traffic",
                                   "message": f"当前路况{route['traffic']}，"
                                   f"预计耗时{route['duration']}分钟，建议提前出发或调整路线"})
        except Exception:
            pass

    if not alerts:
        return {"success": True, "has_alert": False, "message": ""}

    # 3. 调用DeepSeek给出建议方案
    alert_text = "\n".join([alert["message"] for alert in alerts])
    prompt = f"""旅行目的地：{dest}。检测到以下突发情况：
{alert_text}

请给出应对建议（200字以内），包括是否需要调整行程、提前出发时间、备选方案等。"""
    try:
        reply = await call_deepseek("你是旅行应急助手，给出简洁实用的建议。", prompt, 500)
        suggestion = reply.strip()
    except Exception:
        suggestion = "建议关注实时路况和天气变化，提前出发，预留充足时间。"

    return {"success": True, "has_alert": True, "alerts": alerts, "suggestion": suggestion}


@app.post("/api/real-time-traffic")
async def real_time_traffic(request: Request):
    """获取实时路况：用户当前位置到目的地的驾车时间"""
    body = await request.json()
    origin_lng = body.get("origin_lng")
    origin_lat = body.get("origin_lat")
    dest_lng = body.get("dest_lng")
    dest_lat = body.get("dest_lat")

    if not all([origin_lng, origin_lat, dest_lng, dest_lat]):
        return {"success": False, "error": "缺少坐标参数"}

    route = await get_route_time(float(origin_lng), float(origin_lat),
                                  float(dest_lng), float(dest_lat))
    return {"success": True, "route": route}


# ===================== 收藏/图片/重新生成 API =====================

@app.get("/api/saved-trips/refresh")
async def refresh_saved_trip(city: str, days: int):
    """刷新收藏行程的实时天气和景点信息"""
    try:
        weather_data = await amap_weather(city)
        return {"success": True, "weather": weather_data, "city": city,
                "updated_at": __import__("datetime").datetime.now().isoformat()}
    except Exception as error:
        return {"success": False, "error": str(error)}


@app.get("/api/spot-images")
async def spot_images(query: str, limit: int = 5):
    """搜索景点/酒店真实图片（Wikimedia Commons + DeepSeek辅助筛选）"""
    return await search_images(query, limit)


@app.get("/api/resolve-image")
async def resolve_image(name: str, city: str = "", type: str = "spot"):
    """解析图片URL为CDN直链（用于详情页预加载），返回最终可用的图片URL"""
    try:
        if type == "hotel":
            url = await resolve_hotel_image(name, city)
        else:
            url = await resolve_spot_image(name, city)
        return {"success": True, "url": url}
    except Exception as error:
        return {"success": False, "url": "", "error": str(error)}


async def _build_transport_info_light(departure_city: str, dest: str,
                                       start_date: str) -> dict:
    """构建轻量交通信息（用于regenerate），容错处理"""
    transport_info = {}
    if not departure_city:
        return transport_info

    try:
        transport_info["transport"] = judge_transport(departure_city, dest)
    except Exception:
        pass
    try:
        transport_info["route_schedule"] = get_route_schedule(departure_city, dest, start_date)
    except Exception:
        pass
    try:
        transport_info["transfer_info"] = get_transfer_routes(departure_city, dest, start_date)
    except Exception:
        pass
    try:
        transport_info["dep_hub"] = get_nearest_hub(departure_city)
    except Exception:
        pass
    try:
        transport_info["dest_hub"] = get_nearest_hub(dest)
    except Exception:
        pass
    return transport_info


@app.post("/api/regenerate-trip")
async def regenerate_trip(request: Request):
    """根据用户新需求重新生成旅行计划，重点参考用户输入"""
    try:
        body = await request.json()
        user_input = body.get("user_input", "").strip()
        trip_data = body.get("trip_data", {})
        is_self_drive = body.get("is_self_drive", False)
        departure_city = body.get("departure_city", "")

        if not user_input:
            return {"success": False, "error": "请输入新计划需求"}

        dest = trip_data.get("destination", "")
        days = trip_data.get("days", 3)
        start_date = trip_data.get("start_date", "")
        end_date = trip_data.get("end_date", "")
        old_itinerary = trip_data.get("itinerary", [])

        if not dest:
            return {"success": False, "error": "缺少目的地信息"}

        # 获取最新天气
        try:
            weather_data = await amap_weather(dest)
        except Exception:
            weather_data = []

        # 获取交通信息
        transport_info = await _build_transport_info_light(
            departure_city, dest, start_date)

        # 构建prompt并调用DeepSeek
        prompt = build_regenerate_prompt(dest, days, user_input, old_itinerary,
                                         weather_data, start_date, end_date,
                                         is_self_drive, departure_city, transport_info)
        try:
            raw = await _call_deepseek_safely(
                "你是一个专业的旅行规划师，只输出JSON格式数据。", prompt, 6000)
        except ValueError as error:
            return {"success": False, "error": str(error)}

        try:
            new_trip = _parse_ai_json(raw)
        except Exception:
            return {"success": False, "error": "AI返回数据格式异常，请重试"}

        # 后处理验证
        _validate_transport_airports(new_trip)

        # 补全坐标
        try:
            await fill_coordinates(new_trip, dest)
        except Exception:
            pass

        # 获取图片
        try:
            await asyncio.wait_for(fill_images(new_trip, dest), timeout=25.0)
        except (asyncio.TimeoutError, Exception):
            pass

        # 保留原有booking_info
        new_trip["booking_info"] = trip_data.get("booking_info", {})
        new_trip["transport_info"] = trip_data.get("transport_info", {})

        return {"success": True, "data": new_trip}
    except Exception as error:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"重新生成失败：{str(error)}"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)