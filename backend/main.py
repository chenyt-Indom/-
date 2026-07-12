"""旅白行 AI 旅行规划 - FastAPI 后端"""
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
from image_service import fill_images
from feichangzhun_service import judge_transport, search_flights

app = FastAPI(title="旅白行 AI 旅行规划")
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
    """IP定位：高德API优先，失败则用 ip-api.com 兜底。"""
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
        data = resp.json()
        if data.get("status") == "1" and data.get("city"):
            return {"success": True, "city": data["city"].replace("市", ""),
                    "province": data.get("province", ""),
                    "adcode": data.get("adcode", "")}
        # 方案2：ip-api.com 兜底
        try:
            ip_url = "http://ip-api.com/json/?lang=zh-CN&fields=city,regionName,country"
            if not is_private and client_ip:
                ip_url = f"http://ip-api.com/json/{client_ip}?lang=zh-CN&fields=city,regionName,country"
            resp2 = await client.get(ip_url, follow_redirects=True)
            data2 = resp2.json()
            # ip-api.com 直接返回数据，无 status 字段
            if isinstance(data2, dict) and data2.get("city"):
                return {"success": True, "city": data2["city"].replace("市", ""),
                        "province": data2.get("regionName", ""), "adcode": ""}
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

        # 2. 调用 DeepSeek 生成行程
        prompt = build_trip_prompt(dest, days, req.budget, req.interests, all_pois, weather_data, start_date, end_date)
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

        # 4. 判断交通工具 + 飞常准航班查询
        transport_info = {}
        if req.departure_city:
            transport_info = judge_transport(req.departure_city, dest)
            if transport_info.get("need_flight"):
                flight_result = await search_flights(req.departure_city, dest, start_date)
                transport_info["flight_data"] = flight_result.get("flights", [])
                transport_info["flight_query"] = flight_result.get("query", {})

        # 5. 调用 DeepSeek 查询订票/酒店信息
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
        for ticket in booking_info.get("tickets", []):
            if ticket.get("spot") and not ticket.get("location"):
                ticket["location"] = await amap_geocode(ticket["spot"], dest)

        # 7. 为景点和天气生成图片 URL
        fill_images(trip_data, dest)

        trip_data["booking_info"] = booking_info
        return {"success": True, "data": trip_data}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"服务异常：{str(e)}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)