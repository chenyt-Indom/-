"""图片生成服务：使用 text_to_image API 生成真实风格照片，失败时用SVG兜底"""
import urllib.parse
import base64
from config import IMG_BASE


def _svg_fallback(name: str, icon: str = "🏛️", color: str = "#4A90D9") -> str:
    """生成SVG占位图Data URI，100%可靠，不依赖外部API"""
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450">
  <defs><linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
    <stop offset="0%" style="stop-color:{color};stop-opacity:0.8"/>
    <stop offset="100%" style="stop-color:{color};stop-opacity:0.3"/>
  </linearGradient></defs>
  <rect width="800" height="450" fill="url(#bg)"/>
  <rect width="800" height="450" fill="rgba(0,0,0,0.15)"/>
  <text x="400" y="180" text-anchor="middle" font-size="80" fill="white">{icon}</text>
  <text x="400" y="270" text-anchor="middle" font-size="36" fill="white" font-weight="bold">{name[:12]}</text>
  <text x="400" y="310" text-anchor="middle" font-size="18" fill="rgba(255,255,255,0.7)">点击查看详情</text>
</svg>'''
    b64 = base64.b64encode(svg.encode('utf-8')).decode('utf-8')
    return f"data:image/svg+xml;base64,{b64}"


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


def attraction_image_url(name: str, city: str) -> str:
    """生成景点真实照片URL，旅行地标摄影风格"""
    prompt = f"{name} {city}, famous landmark, travel photography, realistic, 4K, no people"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


def hotel_image_url(name: str, area: str) -> str:
    """生成酒店门面真实照片URL"""
    prompt = f"{name} hotel facade, {area}, luxury hotel exterior, travel photography, realistic, 4K, architectural"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


def fill_images(trip_data: dict, dest: str):
    """为行程中的景点和天气补全照片URL，含SVG兜底fallback"""
    for day in trip_data.get("itinerary", []):
        for slot in ["morning", "afternoon", "evening"]:
            spot_data = day.get(slot)
            if spot_data and spot_data.get("spot"):
                spot_data["image"] = attraction_image_url(spot_data["spot"], dest)
                spot_data["fallback"] = _svg_fallback(spot_data["spot"], "🏛️", "#4A90D9")
        w = day.get("weather", {})
        if w:
            w["image"] = weather_image_url(w.get("desc", "晴"))
            w["fallback"] = _svg_fallback(w.get("desc", "晴"), "🌤️", "#5B9BD5")


def fill_booking_images(booking_info: dict, dest: str):
    """为酒店和门票景点补全照片URL，含SVG兜底fallback"""
    for hotel in booking_info.get("hotels", []):
        if hotel.get("name"):
            hotel["image"] = hotel_image_url(hotel["name"], hotel.get("area", dest))
            hotel["fallback"] = _svg_fallback(hotel["name"], "🏨", "#E67E22")
    for change in booking_info.get("hotel_changes", []):
        if change.get("to_hotel"):
            change["image"] = hotel_image_url(change["to_hotel"], change.get("new_area", dest))
            change["fallback"] = _svg_fallback(change["to_hotel"], "🏨", "#E67E22")