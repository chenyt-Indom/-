"""旅白 AI 旅行规划 - FastAPI 后端"""
import os
import json
import httpx
import asyncio
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models import TripRequest
from config import AMAP_KEY, DEEPSEEK_KEY
from amap_service import amap_poi_search, amap_weather, amap_geocode, fill_coordinates
from deepseek_service import call_deepseek, build_trip_prompt, build_booking_prompt
from image_service import fill_images

app = FastAPI(title="旅白 AI 旅行规划")
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


@app.post("/api/generate-trip")
async def generate_trip(req: TripRequest):
    """生成旅行攻略：高德POI+天气 → DeepSeek itinerary → DeepSeek booking → 返回完整JSON"""
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
    except Exception:
        return {"success": False, "error": "攻略生成失败，请检查网络后重试"}

    # 3. 补全景点坐标
    await fill_coordinates(trip_data, dest)

    # 4. 调用 DeepSeek 查询订票/酒店信息
    itinerary = trip_data.get("itinerary", [])
    booking_prompt = build_booking_prompt(dest, start_date, end_date, req.budget, itinerary)
    try:
        booking_raw = await call_deepseek("你是一个旅行服务顾问，只输出JSON格式数据。", booking_prompt, 3000)
        booking_clean = booking_raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        booking_info = json.loads(booking_clean)
    except Exception:
        booking_info = {"flights": [], "hotels": [], "tickets": [], "booking_tips": []}

    # 5. 为酒店和门票补全坐标
    for hotel in booking_info.get("hotels", []):
        if hotel.get("name") and not hotel.get("location"):
            hotel["location"] = await amap_geocode(hotel["name"], dest)
    for ticket in booking_info.get("tickets", []):
        if ticket.get("spot") and not ticket.get("location"):
            ticket["location"] = await amap_geocode(ticket["spot"], dest)

    # 6. 为景点和天气生成图片 URL
    fill_images(trip_data, dest)

    trip_data["booking_info"] = booking_info
    return {"success": True, "data": trip_data}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)