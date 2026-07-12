"""图片服务：Wikimedia Commons真实图片 + text_to_image API 兜底"""
import asyncio
import urllib.parse
from image_search_service import get_best_spot_image, get_best_hotel_image
from config import IMG_BASE


def weather_image_url(weather_desc: str, size: str = "landscape_16_9") -> str:
    """生成天气写实风景照片URL，4K 真实摄影风格"""
    weather_map = {
        "晴": "sunny day, clear blue sky, bright sunlight, 4K, photorealistic landscape photography",
        "多云": "partly cloudy sky, soft sunlight, realistic landscape, 4K",
        "阴": "overcast sky, dramatic clouds, moody landscape, photorealistic, 4K",
        "雨": "rainy weather, wet streets, realistic rain scene, 4K photography",
        "小雨": "light rain, drizzle, wet pavement, photorealistic, 4K",
        "中雨": "moderate rain, rainy cityscape, realistic, 4K",
        "大雨": "heavy rain, storm, dramatic rain scene, photorealistic, 4K",
        "雪": "snowy landscape, winter scenery, photorealistic snow, 4K",
        "雾": "foggy morning, misty landscape, atmospheric fog, photorealistic, 4K",
        "风": "windy weather, trees swaying, dramatic wind, photorealistic, 4K",
        "雷阵雨": "thunderstorm, lightning, dramatic storm sky, photorealistic, 4K",
    }
    prompt = weather_map.get(weather_desc, f"{weather_desc} weather landscape, photorealistic, 4K")
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size={size}"


async def fill_images(trip_data: dict, dest: str):
    """为行程中的景点和天气补全真实照片URL（Wikimedia优先，text_to_image兜底）"""
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
    """为单个景点补全真实图片URL"""
    name = spot_data.get("spot", "")
    if not name:
        return
    try:
        spot_data["image"] = await get_best_spot_image(name, dest)
    except Exception:
        spot_data["image"] = _text_to_image_fallback(f"{name} {dest} landmark")


async def fill_booking_images(booking_info: dict, dest: str):
    """为酒店补全真实门面照片URL（Wikimedia优先，text_to_image兜底）"""
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
    """为单个酒店补全真实图片URL"""
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