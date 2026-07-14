"""图片服务：真实照片搜索 + 天气图片生成 + URL解析"""
import asyncio
import urllib.parse
import httpx
from image_search_service import get_best_spot_image, get_best_hotel_image
from config import IMG_BASE


def weather_image_url(weather_desc: str, size: str = "landscape_16_9") -> str:
    """生成天气写实风景照片URL，覆盖所有高德天气类型"""
    desc = weather_desc or "晴"
    # 处理"X转Y"：优先用更具视觉冲击力的天气
    if "转" in desc:
        parts = desc.split("转")
        # 优先选择雨/雪/雷暴等视觉效果强的天气
        strong = ["暴雨", "大暴雨", "特大暴雨", "暴雪", "大雪", "雷阵雨", "雨", "雪", "大雨", "中雨", "中雪", "小雨", "小雪"]
        for p in parts:
            for s in strong:
                if s in p:
                    desc = p
                    break
            else: continue
            break
        else:
            desc = parts[-1] if parts[-1] else parts[0]
    weather_map = {
        # 晴/多云/阴系列
        "晴": "sunny day, clear blue sky, bright sunlight, photorealistic landscape, 4K",
        "少云": "mostly clear sky, few clouds, bright sunlight, photorealistic landscape, 4K",
        "晴间多云": "sunny with scattered clouds, beautiful landscape, photorealistic, 4K",
        "多云": "partly cloudy sky, soft sunlight, realistic landscape, 4K",
        "阴": "overcast sky, dramatic clouds, moody landscape, photorealistic, 4K",
        # 雨系列
        "阵雨": "rain shower, wet landscape, photorealistic, 4K",
        "雷阵雨": "thunderstorm, lightning, dramatic storm sky, photorealistic, 4K",
        "雷阵雨伴有冰雹": "thunderstorm with hail, dramatic sky, lightning, photorealistic, 4K",
        "小雨": "light rain, drizzle, wet pavement, photorealistic, 4K",
        "中雨": "moderate rain, rainy cityscape, realistic, 4K",
        "大雨": "heavy rain, storm, dramatic rain scene, photorealistic, 4K",
        "暴雨": "heavy rainstorm, dramatic storm, photorealistic, 4K",
        "大暴雨": "torrential rain, extreme storm, dramatic weather, photorealistic, 4K",
        "特大暴雨": "extreme rainstorm, catastrophic weather, dramatic scene, photorealistic, 4K",
        "冻雨": "freezing rain, ice storm, glazed tree branches, photorealistic, 4K",
        # 雪系列
        "雨夹雪": "sleet, rain and snow mixed, winter weather, photorealistic, 4K",
        "小雪": "light snow, winter wonderland, photorealistic, 4K",
        "中雪": "snowy scenery, winter landscape, photorealistic, 4K",
        "大雪": "heavy snow, winter wonderland, photorealistic, 4K",
        "暴雪": "blizzard, heavy snowstorm, dramatic winter scene, photorealistic, 4K",
        # 雾/霾/沙尘系列
        "雾": "foggy morning, misty landscape, atmospheric fog, photorealistic, 4K",
        "霾": "hazy cityscape, smog, atmospheric haze, photorealistic, 4K",
        "浮尘": "floating dust, hazy atmosphere, muted landscape, photorealistic, 4K",
        "扬沙": "blowing sand, dusty wind, desert landscape, photorealistic, 4K",
        "沙尘暴": "sandstorm, dramatic dust storm, apocalyptic sky, photorealistic, 4K",
        "强沙尘暴": "severe sandstorm, dramatic dust wall, apocalyptic scene, photorealistic, 4K",
        # 风系列
        "大风": "strong wind, trees swaying, dramatic clouds, photorealistic, 4K",
        "台风": "typhoon, hurricane, extreme wind, dramatic stormy sea, photorealistic, 4K",
        "热带风暴": "tropical storm, powerful winds, dramatic ocean waves, photorealistic, 4K",
    }
    prompt = weather_map.get(desc, f"{desc} weather landscape, photorealistic, 4K")
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size={size}"


async def resolve_image_url(text_to_image_url: str) -> str:
    """解析text_to_image URL，跟随301重定向获取最终CDN图片直链"""
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
            resp = await client.get(text_to_image_url)
            return str(resp.url)
    except Exception:
        return text_to_image_url


async def resolve_spot_image(name: str, city: str) -> str:
    """获取景点真实图片URL（用于详情页预加载）"""
    url = await get_best_spot_image(name, city)
    return url


async def resolve_hotel_image(name: str, area: str) -> str:
    """获取酒店真实图片URL（用于详情页预加载）"""
    url = await get_best_hotel_image(name, area)
    return url


async def fill_images(trip_data: dict, dest: str):
    """为行程中的景点和天气补全图片URL"""
    tasks = []
    spot_items = []
    weather_items = []
    for day in trip_data.get("itinerary", []):
        for slot_name in ["morning", "afternoon", "evening"]:
            spot_data = day.get(slot_name)
            if spot_data and spot_data.get("spot"):
                spot_items.append(spot_data)
                tasks.append(_fill_spot_image(spot_data, dest))
        w = day.get("weather", {})
        if w:
            # 确保天气图片始终有值，先生成text_to_image URL
            w["image"] = weather_image_url(w.get("desc", "晴"))
            # 同时生成备用URL（不同prompt，确保有图）
            w["image_fallback"] = weather_image_url(
                (w.get("desc", "晴") + " landscape").replace("转", " "), "portrait_4_3")
            weather_items.append(w)
    if tasks:
        await asyncio.gather(*tasks)
    # 解析天气图片text_to_image URL为CDN直链
    resolve_tasks = []
    for w in weather_items:
        img = w.get("image", "")
        if IMG_BASE in img:
            resolve_tasks.append(_resolve_and_set(w, "image", img))
    if resolve_tasks:
        await asyncio.gather(*resolve_tasks)
    # 如果主图片URL解析失败，使用备用URL
    for w in weather_items:
        if not w.get("image") or w["image"] == w.get("image_fallback", ""):
            continue
        # 如果主图片URL还是text_to_image格式（说明CDN解析失败），保留它作为fallback
        if IMG_BASE in w.get("image", ""):
            w["image"] = w["image"]  # 保持text_to_image URL，浏览器会跟随重定向


async def _resolve_and_set(item: dict, key: str, url: str):
    """解析单个text_to_image URL为CDN直链并写回item"""
    try:
        resolved = await resolve_image_url(url)
        if resolved and resolved != url:
            item[key] = resolved
    except Exception:
        pass


async def _fill_spot_image(spot_data: dict, dest: str):
    """为单个景点获取真实照片URL（找不到真实照片时设为空）"""
    name = spot_data.get("spot", "")
    if not name:
        return
    try:
        url = await get_best_spot_image(name, dest)
        if url:
            spot_data["image"] = url
    except Exception:
        pass


async def fill_booking_images(booking_info: dict, dest: str):
    """为酒店补全真实门面照片URL"""
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
    """为单个酒店获取真实照片URL（找不到真实照片时设为空）"""
    name = item.get(name_key, "")
    area = item.get(area_key, dest)
    if not name:
        return
    try:
        url = await get_best_hotel_image(name, area)
        if url:
            item["image"] = url
    except Exception:
        pass