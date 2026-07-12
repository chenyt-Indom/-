"""高德地图 API 服务：POI搜索、天气、地理编码"""
import httpx
from config import AMAP_KEY, AMAP_POI_URL, AMAP_WEATHER_URL, AMAP_GEO_URL


async def amap_poi_search(keywords: str, city: str) -> list:
    """高德 POI 搜索，返回景点列表含名称、地址、坐标"""
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
                "location": p.get("location", ""),
                "photos": [pic.get("url") for pic in (p.get("photos", []) or []) if pic.get("url")],
            } for p in data.get("pois", [])]
        return []


async def amap_weather(city: str) -> list:
    """高德天气查询，返回未来天气预报列表"""
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
    """高德地理编码：地址转坐标（lng,lat）"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_GEO_URL, params={
            "key": AMAP_KEY, "address": address, "city": city,
        })
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            return data["geocodes"][0].get("location", "")
        return ""


async def fill_coordinates(trip_data: dict, dest: str):
    """为行程中缺少坐标的景点补全坐标"""
    for day in trip_data.get("itinerary", []):
        for slot in ["morning", "afternoon", "evening"]:
            spot_data = day.get(slot, {})
            spot_name = spot_data.get("spot", "")
            if spot_name and not spot_data.get("location"):
                loc = await amap_geocode(spot_name, dest)
                spot_data["location"] = loc