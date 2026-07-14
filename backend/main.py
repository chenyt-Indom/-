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
from deepseek_service import call_deepseek, build_trip_prompt, build_booking_prompt
from image_service import fill_images, fill_booking_images, resolve_spot_image, resolve_hotel_image
from image_search_service import search_images
from feichangzhun_service import judge_transport, search_flights
from weather_detail_service import get_hourly_weather, check_weather_alerts, get_realtime_weather
from china_weather_service import get_observation, get_air_quality, get_weather_chat
from route_service import get_route_plan, calculate_self_drive_plan, calculate_transit_to_station, get_route_time

app = FastAPI(title="行旅白 AI 旅行规划")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/app", StaticFiles(directory=_static_dir, html=True), name="static")

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
        resp = await client.get("https://restapi.amap.com/v3/ip", params=params)
        amap_data = resp.json()
        if amap_data.get("status") == "1" and amap_data.get("city"):
            amap_city = amap_data["city"].replace("市", "")
            amap_source = "amap"
            # 方案3：用ipapi.co交叉验证（仅在高德返回了结果时）
            try:
                ipapi_resp = await client.get(f"https://ipapi.co/{client_ip}/json/", follow_redirects=True)
                ipapi_data = ipapi_resp.json()
                ipapi_city = (ipapi_data.get("city", "") or "").replace("市", "")
                # 如果两个服务返回不同城市，用ipapi.co的结果（对移动端更准）
                if ipapi_city and ipapi_city != amap_city and len(ipapi_city) >= 2:
                    # 再用ip-api.com作为决胜票
                    try:
                        ipapi2_resp = await client.get(
                            f"http://ip-api.com/json/{client_ip}?lang=zh-CN&fields=city,regionName",
                            follow_redirects=True)
                        ipapi2_data = ipapi2_resp.json()
                        ipapi2_city = (ipapi2_data.get("city", "") or "").replace("市", "")
                        if ipapi2_city and ipapi2_city == ipapi_city:
                            # 两个都不同意高德，用新结果
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
                    "adcode": amap_data.get("adcode", ""), "source": amap_source}
        # 方案2：ip-api.com 兜底
        try:
            ip_url = "http://ip-api.com/json/?lang=zh-CN&fields=city,regionName,country"
            if not is_private and client_ip:
                ip_url = f"http://ip-api.com/json/{client_ip}?lang=zh-CN&fields=city,regionName,country"
            resp2 = await client.get(ip_url, follow_redirects=True)
            data2 = resp2.json()
            if isinstance(data2, dict) and data2.get("city"):
                return {"success": True, "city": data2["city"].replace("市", ""),
                        "province": data2.get("regionName", ""), "adcode": "",
                        "source": "ip-api"}
        except Exception:
            pass
        # 方案4：ipapi.co 最后兜底
        try:
            if not is_private and client_ip:
                ipapi_resp = await client.get(f"https://ipapi.co/{client_ip}/json/", follow_redirects=True)
                ipapi_data = ipapi_resp.json()
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
        resp = await client.get(AMAP_REGEO_URL, params={
            "key": AMAP_KEY, "location": f"{lng},{lat}", "extensions": "base",
        })
        data = resp.json()
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
        poi_tasks = [
            amap_poi_search(f"{dest}景点", dest),
            amap_poi_search(f"{dest}美食", dest),
        ]
        if req.interests:
            poi_tasks.append(amap_poi_search(f"{dest}{' '.join(req.interests)}", dest))
        weather_task = amap_weather(dest)

        poi_results = await asyncio.gather(*poi_tasks)
        weather_data = await weather_task

        all_pois = []
        for r in poi_results:
            if isinstance(r, list):
                all_pois.extend(r)

        # 去重并按评分降序排列（高评分优先），取前20个
        seen_names = set()
        unique_pois = []
        for p in all_pois:
            if p["name"] not in seen_names:
                seen_names.add(p["name"])
                unique_pois.append(p)
        unique_pois.sort(key=lambda x: float(x["rating"]) if x["rating"] else 0, reverse=True)
        ranked_pois = unique_pois[:20]

        # 1.5 出发/返程交通规划（自驾/公共交通）
        transport_info = {}
        if req.departure_city:
            # 判断交通工具
            ti = judge_transport(req.departure_city, dest)
            transport_info["transport"] = ti
            # 计算前往机场/车站的时间
            if ti.get("need_flight"):
                to_station = await calculate_transit_to_station(req.departure_city, "airport")
                transport_info["to_station"] = to_station
            else:
                to_station = await calculate_transit_to_station(req.departure_city, "train")
                transport_info["to_station"] = to_station
            # 自驾模式：计算自驾路线
            if req.is_self_drive:
                sd_plan = await calculate_self_drive_plan(
                    req.departure_city, dest, start_date, end_date)
                transport_info["self_drive_plan"] = sd_plan
            # 飞常准航班查询
            if ti.get("need_flight"):
                flight_result = await search_flights(req.departure_city, dest, start_date)
                transport_info["flight_data"] = flight_result.get("flights", [])
                transport_info["flight_query"] = flight_result.get("query", {})

        # 2. 调用 DeepSeek 生成行程
        prompt = build_trip_prompt(dest, days, req.budget, req.interests, ranked_pois, weather_data,
                                   start_date, end_date, req.travelers, req.budget_type, req.pace,
                                   req.is_self_drive, req.departure_city, transport_info)
        try:
            raw = await call_deepseek("你是一个专业的旅行规划师，只输出JSON格式数据。", prompt)
            raw_clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            trip_data = json.loads(raw_clean)
        except httpx.HTTPStatusError as e:
            err_msg = "AI服务调用失败"
            if e.response.status_code == 402:
                err_msg = "DeepSeek API 余额不足，请充值后重试"
            elif e.response.status_code == 401:
                err_msg = "DeepSeek API Key 无效"
            elif e.response.status_code == 429:
                err_msg = "请求过于频繁，请稍后重试"
            return {"success": False, "error": err_msg}
        except json.JSONDecodeError:
            return {"success": False, "error": "AI返回数据格式异常，请重试"}
        except Exception:
            return {"success": False, "error": "攻略生成失败，请检查网络后重试"}

        # 3. 补全景点坐标
        await fill_coordinates(trip_data, dest)

        # 4. 调用 DeepSeek 查询订票/酒店信息
        itinerary = trip_data.get("itinerary", [])
        booking_prompt = build_booking_prompt(dest, start_date, end_date, req.budget, itinerary,
                                              req.departure_city, transport_info)
        try:
            booking_raw = await call_deepseek("你是一个旅行服务顾问，只输出JSON格式数据。", booking_prompt, 3000)
            booking_clean = booking_raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            booking_info = json.loads(booking_clean)
        except Exception:
            booking_info = {"flights": [], "hotels": [], "tickets": [], "booking_tips": []}

        # 6. 为酒店和门票补全坐标
        for hotel in booking_info.get("hotels", []):
            if hotel.get("name") and not hotel.get("location"):
                hotel["location"] = await amap_geocode(hotel["name"], dest)
        for change in booking_info.get("hotel_changes", []):
            if change.get("to_hotel") and not change.get("location"):
                change["location"] = await amap_geocode(change["to_hotel"], dest)
        for ticket in booking_info.get("tickets", []):
            if ticket.get("spot") and not ticket.get("location"):
                ticket["location"] = await amap_geocode(ticket["spot"], dest)

        # 7. 为景点和天气获取真实图片URL（带超时，不阻塞主流程）
        try:
            await asyncio.wait_for(fill_images(trip_data, dest), timeout=25.0)
        except (asyncio.TimeoutError, Exception):
            pass  # 图片获取超时或失败不阻塞攻略生成
        # 为酒店获取真实门面图片（带超时）
        try:
            await asyncio.wait_for(fill_booking_images(booking_info, dest), timeout=25.0)
        except (asyncio.TimeoutError, Exception):
            pass  # 酒店图片获取超时或失败不阻塞攻略生成

        trip_data["booking_info"] = booking_info
        trip_data["transport_info"] = transport_info
        return {"success": True, "data": trip_data}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"服务异常：{str(e)}"}


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
    except Exception as e:
        return {"success": False, "content": reason or f"{name}是{city}的著名景点，值得一游。", "error": str(e)}


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
    except Exception as e:
        return {"success": False, "content": reason or f"{name}位于{city}{area}，地理位置优越，是旅途中的理想下榻之选。", "error": str(e)}


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
    current_location = body.get("current_location", {})  # {lng, lat}
    rejected = body.get("rejected", False)  # 用户是否已拒绝过

    if rejected:
        return {"success": True, "has_alert": False, "message": ""}

    dest = trip_data.get("destination", "")
    if not dest:
        return {"success": False, "error": "缺少目的地信息"}

    alerts = []
    # 1. 检查天气预警
    try:
        w_alerts = await check_weather_alerts(dest)
        if w_alerts.get("alerts"):
            alerts.append({"type": "weather", "message": f"目的地{dest}天气预警：" + w_alerts["alerts"][0]["message"]})
    except Exception:
        pass

    # 2. 检查实时路况（如果用户提供了当前位置）
    if current_location.get("lng") and current_location.get("lat"):
        try:
            # 获取目的地坐标
            dest_loc = await amap_geocode(dest, dest)
            if dest_loc:
                dlng, dlat = map(float, dest_loc.split(","))
                route = await get_route_time(
                    current_location["lng"], current_location["lat"], dlng, dlat)
                if route.get("traffic") in ("拥堵", "缓行"):
                    alerts.append({"type": "traffic",
                                   "message": f"当前路况{route['traffic']}，预计耗时{route['duration']}分钟，建议提前出发或调整路线"})
        except Exception:
            pass

    if not alerts:
        return {"success": True, "has_alert": False, "message": ""}

    # 3. 调用DeepSeek给出建议方案
    alert_text = "\n".join([a["message"] for a in alerts])
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


@app.get("/api/saved-trips/refresh")
async def refresh_saved_trip(city: str, days: int):
    """刷新收藏行程的实时天气和景点信息"""
    try:
        weather_data = await amap_weather(city)
        return {"success": True, "weather": weather_data, "city": city,
                "updated_at": __import__("datetime").datetime.now().isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}


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
    except Exception as e:
        return {"success": False, "url": "", "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)