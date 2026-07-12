"""图片生成服务：使用 text_to_image API 生成真实风格照片"""
import urllib.parse
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


def attraction_image_url(name: str, city: str) -> str:
    """生成景点真实照片URL，旅行地标摄影风格"""
    prompt = f"{name} {city}, famous landmark, travel photography, realistic, 4K, no people"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


def hotel_image_url(name: str, area: str) -> str:
    """生成酒店门面真实照片URL"""
    prompt = f"{name} hotel facade, {area}, luxury hotel exterior, travel photography, realistic, 4K, architectural"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


def fill_images(trip_data: dict, dest: str):
    """为行程中的景点和天气补全照片URL"""
    for day in trip_data.get("itinerary", []):
        for slot in ["morning", "afternoon", "evening"]:
            spot_data = day.get(slot)
            if spot_data and spot_data.get("spot"):
                spot_data["image"] = attraction_image_url(spot_data["spot"], dest)
        w = day.get("weather", {})
        if w:
            w["image"] = weather_image_url(w.get("desc", "晴"))


def fill_booking_images(booking_info: dict, dest: str):
    """为酒店和门票景点补全照片URL"""
    for hotel in booking_info.get("hotels", []):
        if hotel.get("name"):
            hotel["image"] = hotel_image_url(hotel["name"], hotel.get("area", dest))
    for change in booking_info.get("hotel_changes", []):
        if change.get("to_hotel"):
            change["image"] = hotel_image_url(change["to_hotel"], change.get("new_area", dest))