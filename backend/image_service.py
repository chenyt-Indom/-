"""图片服务：多源搜索 + text_to_image API 兜底 + URL解析"""
import asyncio
import urllib.parse
import httpx
from image_search_service import get_best_spot_image, get_best_hotel_image
from config import IMG_BASE


def weather_image_url(weather_desc: str, size: str = "landscape_16_9") -> str:
    """生成天气写实风景照片URL，支持复杂天气如'阴转多云'"""
    # 提取主要天气描述（处理'阴转多云'、'多云转晴'等）
    desc = weather_desc or "晴"
    if "转" in desc:
        parts = desc.split("转")
        desc = parts[-1] if parts[-1] else parts[0]  # 取转换后的天气
    weather_map = {
        "晴": "sunny day, clear blue sky, bright sunlight, 4K, photorealistic landscape",
        "多云": "partly cloudy sky, soft sunlight, realistic landscape, 4K",
        "阴": "overcast sky, dramatic clouds, moody landscape, photorealistic, 4K",
        "雨": "rainy weather, wet streets, realistic rain scene, 4K photography",
        "小雨": "light rain, drizzle, wet pavement, photorealistic, 4K",
        "中雨": "moderate rain, rainy cityscape, realistic, 4K",
        "大雨": "heavy rain, storm, dramatic rain scene, photorealistic, 4K",
        "暴雨": "heavy rainstorm, dramatic storm, photorealistic, 4K",
        "雷阵雨": "thunderstorm, lightning, dramatic storm sky, photorealistic, 4K",
        "阵雨": "rain shower, wet landscape, photorealistic, 4K",
        "雪": "snowy landscape, winter scenery, photorealistic snow, 4K",
        "小雪": "light snow, winter wonderland, photorealistic, 4K",
        "中雪": "snowy scenery, winter landscape, photorealistic, 4K",
        "大雪": "heavy snow, snowstorm, winter wonderland, photorealistic, 4K",
        "雨夹雪": "sleet, rain and snow mixed, winter weather, photorealistic, 4K",
        "雾": "foggy morning, misty landscape, atmospheric fog, photorealistic, 4K",
        "霾": "hazy cityscape, smog, atmospheric haze, photorealistic, 4K",
        "沙尘": "dust storm, sandstorm, dramatic weather, photorealistic, 4K",
        "风": "windy weather, trees swaying, dramatic wind, photorealistic, 4K",
    }
    prompt = weather_map.get(desc, f"{desc} weather landscape, photorealistic, 4K")
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size={size}"


async def resolve_image_url(text_to_image_url: str) -> str:
    """解析text_to_image URL，跟随301重定向获取最终CDN图片直链"""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(text_to_image_url)
            return str(resp.url)  # 返回重定向后的最终URL
    except Exception:
        return text_to_image_url  # 解析失败则返回原始URL


async def resolve_spot_image(name: str, city: str) -> str:
    """获取景点图片并解析为CDN直链（用于详情页预加载）"""
    url = await get_best_spot_image(name, city)
    if IMG_BASE in url:
        return await resolve_image_url(url)
    return url


async def resolve_hotel_image(name: str, area: str) -> str:
    """获取酒店图片并解析为CDN直链（用于详情页预加载）"""
    url = await get_best_hotel_image(name, area)
    if IMG_BASE in url:
        return await resolve_image_url(url)
    return url


async def fill_images(trip_data: dict, dest: str):
    """为行程中的景点和天气补全图片URL"""
    tasks = []
    for day in trip_data.get("itinerary", []):
        for slot_name in ["morning", "afternoon", "evening"]:
            spot_data = day.get(slot_name)
            if spot_data and spot_data.get("spot"):
                tasks.append(_fill_spot_image(spot_data, dest))
        w = day.get("weather", {})
        if w:
            w["image"] = weather_image_url(w.get("desc", "晴"))
    if tasks:
        await asyncio.gather(*tasks)


async def _fill_spot_image(spot_data: dict, dest: str):
    """为单个景点补全图片URL"""
    name = spot_data.get("spot", "")
    if not name:
        return
    try:
        spot_data["image"] = await get_best_spot_image(name, dest)
    except Exception:
        spot_data["image"] = _text_to_image_fallback(f"{name} {dest} landmark")


async def fill_booking_images(booking_info: dict, dest: str):
    """为酒店补全门面照片URL"""
    tasks = []
    for hotel in booking_info.get("hotels", []):
        if hotel.get("name"):
            tasks.append(_fill_hotel_image(hotel, dest))
    for change in booking_info.get("hotel_changes", []):
        if change.get("to_hotel"):
            tasks.append(_fill_hotel_image(change, dest, "to_hotel", "new_area"))
    if tasks:
        await asyncio.gather(*tasks)


async def _fill_hotel_image(item: dict, dest: str, name_key: str = "name", area_key: str = "area"):
    """为单个酒店补全图片URL"""
    name = item.get(name_key, "")
    area = item.get(area_key, dest)
    if not name:
        return
    try:
        item["image"] = await get_best_hotel_image(name, area)
    except Exception:
        item["image"] = _text_to_image_fallback(f"{name} hotel {area} facade")


def _text_to_image_fallback(query: str) -> str:
    """text_to_image API 兜底"""
    prompt = f"{query}, travel photography, realistic, 4K, architectural"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"