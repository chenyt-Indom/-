"""图片生成服务：为天气和景点生成展示图片URL"""
import urllib.parse
from config import IMG_BASE


def weather_image_url(weather_desc: str, size: str = "square_hd") -> str:
    """生成天气插图URL"""
    prompt = f"干净简洁的{weather_desc}天气风景插画，扁平化风格，蓝色调，无文字"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size={size}"


def attraction_image_url(name: str, city: str) -> str:
    """生成景点照片URL"""
    prompt = f"{city}{name}风景照片，干净明亮，高清晰度，自然光"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


def fill_images(trip_data: dict, dest: str):
    """为行程中的景点和天气补全图片URL"""
    for day in trip_data.get("itinerary", []):
        for slot in ["morning", "afternoon", "evening"]:
            spot = day.get(slot, {}).get("spot", "")
            if spot:
                day[slot]["image"] = attraction_image_url(spot, dest)
        w = day.get("weather", {})
        if w:
            day["weather"]["image"] = weather_image_url(w.get("desc", "晴"))