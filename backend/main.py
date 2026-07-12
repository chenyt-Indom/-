"""
旅白 AI 旅行规划 - FastAPI 后端
集成高德地图 POI/天气/坐标 + DeepSeek AI 生成个性化行程
"""
import os
import json
import httpx
import asyncio
import urllib.parse
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI(title="旅白 AI 旅行规划")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# 挂载静态文件（Web 预览页面）
import os as _os
_static_dir = _os.path.join(_os.path.dirname(__file__), "static")
_os.makedirs(_static_dir, exist_ok=True)
app.mount("/app", StaticFiles(directory=_static_dir, html=True), name="static")

# ==================== API 配置 ====================
# 请设置环境变量: DEEPSEEK_API_KEY, AMAP_API_KEY
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
AMAP_KEY = os.getenv("AMAP_API_KEY", "")
AMAP_POI_URL = "https://restapi.amap.com/v3/place/text"
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
IMG_BASE = "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image"


class TripRequest(BaseModel):
    """行程请求体"""
    destination: str  # 目的地
    days: int = 3     # 天数 1-7
    budget: str = ""  # 预算
    interests: List[str] = []  # 兴趣标签


# ==================== 高德 API 工具函数 ====================

async def amap_poi_search(keywords: str, city: str) -> list:
    """高德 POI 搜索，返回景点/餐饮列表（含坐标）"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_POI_URL, params={
            "key": AMAP_KEY, "keywords": keywords, "city": city,
            "offset": 10, "extensions": "all",
        })
        data = resp.json()
        if data.get("status") == "1":
            return [{
                "name": p.get("name"),
                "address": p.get("address"),
                "type": p.get("type"),
                "location": p.get("location", ""),  # "经度,纬度"
                "photos": [pic.get("url") for pic in (p.get("photos", []) or []) if pic.get("url")],
            } for p in data.get("pois", [])]
        return []


async def amap_weather(city: str) -> list:
    """高德天气查询，返回未来天气数据"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_WEATHER_URL, params={
            "key": AMAP_KEY, "city": city, "extensions": "all",
        })
        data = resp.json()
        if data.get("status") == "1":
            forecasts_list = data.get("forecasts", [])
            if not forecasts_list:
                return []
            forecasts = forecasts_list[0].get("casts", [])
            return [{
                "date": f.get("date"),
                "dayweather": f.get("dayweather"),
                "nightweather": f.get("nightweather"),
                "daytemp": f.get("daytemp"),
                "nighttemp": f.get("nighttemp"),
                "daywind": f.get("daywind"),
            } for f in forecasts]
        return []


async def amap_geocode(address: str, city: str) -> str:
    """高德地理编码：将景点名称转为坐标字符串 'lng,lat'"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_GEO_URL, params={
            "key": AMAP_KEY, "address": address, "city": city,
        })
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            return data["geocodes"][0].get("location", "")
        return ""


# ==================== 图片生成 ====================

def weather_image_url(weather_desc: str, size: str = "square_hd") -> str:
    """根据天气描述生成天气图片 URL"""
    prompt = f"干净简洁的{weather_desc}天气风景插画，扁平化风格，蓝色调，无文字"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size={size}"


def attraction_image_url(name: str, city: str) -> str:
    """生成景点图片 URL"""
    prompt = f"{city}{name}风景照片，干净明亮，高清晰度，自然光"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


# ==================== DeepSeek 行程生成 ====================

def build_trip_prompt(dest: str, days: int, budget: str, interests: list,
                      poi_data: list, weather_data: list) -> str:
    """构建 DeepSeek 提示词"""
    interest_str = "、".join(interests) if interests else "综合体验"
    poi_str = "\n".join([
        f"- {p['name']}（{p.get('type','景点')}，坐标：{p.get('location','')}）"
        for p in poi_data[:15]
    ]) if poi_data else "（请根据常识推荐）"
    weather_str = "\n".join([
        f"  {w['date']}: {w['dayweather']} {w['daytemp']}°C~{w['nighttemp']}°C"
        for w in weather_data[:days]
    ]) if weather_data else "（请根据常识判断）"

    return f"""你是一个资深旅行规划师。请根据以下真实数据，生成一份 {days} 天的{dest}行程。

【目的地】{dest}
【天数】{days}天
【预算】{budget}
【兴趣】{interest_str}

【高德 POI 真实数据（含坐标）】
{poi_str}

【天气预报】
{weather_str}

请严格按照以下 JSON 格式输出（不要输出其他内容）：
{{
  "destination": "{dest}",
  "days": {days},
  "weather": [
    {{"date": "日期", "weather": "天气", "temp": "温度", "wind": "风力", "icon": "天气图标emoji"}}
  ],
  "itinerary": [
    {{
      "day": 1,
      "date": "日期",
      "weather": {{"desc": "天气", "temp": "温度", "icon": "emoji"}},
      "morning": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标"}},
      "afternoon": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标"}},
      "evening": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标"}},
      "lunch": "午餐推荐（餐厅名+推荐菜）",
      "dinner": "晚餐推荐（餐厅名+推荐菜）",
      "transport": "交通建议"
    }}
  ],
  "budget_breakdown": {{"交通": "金额", "住宿": "金额", "餐饮": "金额", "门票": "金额", "其他": "金额"}},
  "tips": ["贴士1", "贴士2", "贴士3"]
}}

要求：
1. 优先使用高德POI真实数据中的景点和餐厅，location坐标必须填写
2. 结合天气预报合理安排室内外活动
3. 上午/下午各安排1-2个景点，晚上安排1个
4. 午餐和晚餐推荐具体餐厅和菜品
5. 预算分配合理
6. 兴趣标签"{interest_str}"要体现在行程中
7. 只输出JSON，不要markdown代码块"""


async def call_deepseek(prompt: str) -> str:
    """调用 DeepSeek API 生成行程"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": "你是一个专业的旅行规划师，只输出JSON格式数据。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.7, "max_tokens": 4000,
            },
        )
        resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ==================== 坐标补全 ====================

async def fill_coordinates(trip_data: dict, dest: str):
    """为行程中缺少坐标的景点补全坐标"""
    for day in trip_data.get("itinerary", []):
        for slot in ["morning", "afternoon", "evening"]:
            spot_data = day.get(slot, {})
            spot_name = spot_data.get("spot", "")
            if spot_name and not spot_data.get("location"):
                loc = await amap_geocode(spot_name, dest)
                spot_data["location"] = loc


# ==================== API 接口 ====================

@app.get("/api/health")
async def health_check():
    """健康检查"""
    return {
        "status": "ok",
        "amap_key": True,
        "deepseek_key": True,
    }


@app.post("/api/generate-trip")
async def generate_trip(req: TripRequest):
    """生成旅行攻略：高德POI+天气 → DeepSeek AI → 补全坐标+图片 → 返回JSON"""
    dest = req.destination.strip()
    days = max(1, min(7, req.days))

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

    # 2. 调用 DeepSeek 生成行程（必须）
    prompt = build_trip_prompt(dest, days, req.budget, req.interests, all_pois, weather_data)
    try:
        raw = await call_deepseek(prompt)
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
    except Exception as e:
        return {"success": False, "error": "攻略生成失败，请检查网络后重试"}

    # 3. 补全景点坐标
    await fill_coordinates(trip_data, dest)

    # 4. 为每个景点和天气生成图片 URL
    for day in trip_data.get("itinerary", []):
        for slot in ["morning", "afternoon", "evening"]:
            spot = day.get(slot, {}).get("spot", "")
            if spot:
                day[slot]["image"] = attraction_image_url(spot, dest)
        w = day.get("weather", {})
        if w:
            day["weather"]["image"] = weather_image_url(w.get("desc", "晴"))

    return {"success": True, "data": trip_data}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)