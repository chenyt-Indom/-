"""高德路线规划服务：实时路况、驾车/步行/公交耗时、到达时间预测、自驾沿途规划"""
import httpx
from config import AMAP_KEY

AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"
AMAP_TRANSIT_URL = "https://restapi.amap.com/v3/direction/transit/integrated"
AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
AMAP_DIST_URL = "https://restapi.amap.com/v3/distance"


def _parse_coordinates(location: str) -> tuple:
    """解析坐标字符串 'lng,lat' 为 (lng, lat) 浮点数元组"""
    lng, lat = map(float, location.split(","))
    return lng, lat


async def amap_geocode(address: str, city: str = "") -> str:
    """高德地理编码：地址转坐标（lng,lat）"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_GEO_URL, params={
            "key": AMAP_KEY, "address": address, "city": city,
        })
        data = resp.json()
        if data.get("status") == "1" and data.get("geocodes"):
            return data["geocodes"][0].get("location", "")
        return ""


async def get_route_time(origin_lng: float, origin_lat: float,
                         dest_lng: float, dest_lat: float, city: str = "") -> dict:
    """高德驾车路线规划：获取实时路况下的行驶时间和距离"""
    result = {"success": False, "duration": 0, "distance": "", "traffic": "", "arrival_time": ""}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_DRIVING_URL, params={
                "key": AMAP_KEY, "strategy": "0", "extensions": "all",
                "origin": f"{origin_lng},{origin_lat}",
                "destination": f"{dest_lng},{dest_lat}",
                "city": city or "",
            })
            data = resp.json()
            if data.get("status") == "1" and data.get("route", {}).get("paths"):
                path = data["route"]["paths"][0]
                duration_min = int(path.get("duration", "0")) // 60
                distance_m = int(path.get("distance", "0"))
                result["duration"] = duration_min
                result["distance"] = f"{distance_m/1000:.1f}公里"
                traffic_status = "畅通"
                for step in path.get("steps", []):
                    for tmc in step.get("tmcs", []):
                        status = tmc.get("status", "")
                        if "缓行" in status or "拥堵" in status:
                            traffic_status = "缓行" if "缓行" in status else "拥堵"
                            break
                result["traffic"] = traffic_status
                result["success"] = True
    except Exception:
        pass
    return result


async def get_transit_time(origin_lng: float, origin_lat: float,
                           dest_lng: float, dest_lat: float, city: str = "") -> dict:
    """高德公交路线规划：获取公交/地铁耗时"""
    result = {"success": False, "duration": 0, "distance": "", "mode": ""}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_TRANSIT_URL, params={
                "key": AMAP_KEY, "origin": f"{origin_lng},{origin_lat}",
                "destination": f"{dest_lng},{dest_lat}", "city": city or "",
            })
            data = resp.json()
            if data.get("status") == "1" and data.get("route", {}).get("transits"):
                transit = data["route"]["transits"][0]
                duration_min = int(transit.get("duration", "0")) // 60
                distance_m = int(transit.get("distance", "0"))
                result["duration"] = duration_min
                result["distance"] = f"{distance_m/1000:.1f}公里"
                result["mode"] = "公交/地铁"
                result["success"] = True
    except Exception:
        pass
    return result


async def get_distance_km(origin_lng: float, origin_lat: float,
                          dest_lng: float, dest_lat: float) -> float:
    """高德距离测量：直线距离（公里）"""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_DIST_URL, params={
                "key": AMAP_KEY, "type": "1",
                "origins": f"{origin_lng},{origin_lat}",
                "destination": f"{dest_lng},{dest_lat}",
            })
            data = resp.json()
            if data.get("status") == "1" and data.get("results"):
                return float(data["results"][0].get("distance", "0")) / 1000
    except Exception:
        pass
    return 0


async def get_route_plan(spots: list) -> list:
    """多景点路线规划：计算相邻景点间的驾车时间和距离"""
    routes = []
    for i in range(len(spots) - 1):
        origin = spots[i]
        dest = spots[i + 1]
        if origin.get("lng") and origin.get("lat") and dest.get("lng") and dest.get("lat"):
            route = await get_route_time(origin["lng"], origin["lat"], dest["lng"], dest["lat"])
            route["from"] = origin.get("name", "")
            route["to"] = dest.get("name", "")
            routes.append(route)
        else:
            routes.append({"success": False, "from": origin.get("name", ""),
                           "to": dest.get("name", ""), "duration": 0, "distance": "", "traffic": ""})
    return routes


async def _get_city_coordinates(departure_city: str, dest_city: str) -> tuple:
    """获取出发城市和目的地城市的坐标，返回 (dep_lng, dep_lat, dest_lng, dest_lat) 或 None"""
    dep_loc = await amap_geocode(departure_city)
    dest_loc = await amap_geocode(dest_city)
    if not dep_loc or not dest_loc:
        return None
    dep_lng, dep_lat = _parse_coordinates(dep_loc)
    dest_lng, dest_lat = _parse_coordinates(dest_loc)
    return dep_lng, dep_lat, dest_lng, dest_lat


async def _calculate_midpoint_stopover(dep_lng: float, dep_lat: float,
                                       dest_lng: float, dest_lat: float) -> dict:
    """计算中点过夜停靠点信息，返回 stopover 字典或 None"""
    mid_lng = (dep_lng + dest_lng) / 2
    mid_lat = (dep_lat + dest_lat) / 2
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get("https://restapi.amap.com/v3/geocode/regeo", params={
                "key": AMAP_KEY, "location": f"{mid_lng},{mid_lat}",
            })
            data = resp.json()
            if data.get("status") == "1":
                addr = data.get("regeocode", {}).get("addressComponent", {})
                mid_city = addr.get("city", "") or addr.get("province", "")
                seg1 = await get_route_time(dep_lng, dep_lat, mid_lng, mid_lat)
                seg2 = await get_route_time(mid_lng, mid_lat, dest_lng, dest_lat)
                return {
                    "city": mid_city,
                    "suggestion": f"建议在{mid_city}过夜休整，第二天继续出发",
                    "day1_drive": seg1.get("distance", ""),
                    "day2_drive": seg2.get("distance", ""),
                    "segments": [seg1, seg2]
                }
    except Exception:
        pass
    return None


async def calculate_self_drive_plan(departure_city: str, dest_city: str,
                                    start_date: str, end_date: str) -> dict:
    """计算自驾出行计划：含沿途停靠点、过夜建议、实时路况"""
    coords = await _get_city_coordinates(departure_city, dest_city)
    if coords is None:
        return {"success": False, "error": "无法获取城市坐标"}
    dep_lng, dep_lat, dest_lng, dest_lat = coords

    route = await get_route_time(dep_lng, dep_lat, dest_lng, dest_lat)
    if not route["success"]:
        return {"success": False, "error": "无法计算驾车路线"}

    dist_str = route.get("distance", "0公里")
    try:
        dist_km = float(dist_str.replace("公里", ""))
    except (ValueError, TypeError):
        dist_km = 0

    plan = {
        "success": True,
        "mode": "自驾",
        "total_distance": dist_str,
        "total_duration_min": route["duration"],
        "traffic": route["traffic"],
        "segments": [route],
        "stopover": None,
        "advice": ""
    }

    if dist_km > 500:
        stopover = await _calculate_midpoint_stopover(dep_lng, dep_lat, dest_lng, dest_lat)
        if stopover:
            plan["segments"] = stopover.pop("segments")
            plan["stopover"] = stopover
        plan["advice"] = f"路程较远（{dist_str}），建议分两天驾驶，中途过夜休整，避免疲劳驾驶"

    buffer_min = max(60, int(route["duration"] * 0.2))
    plan["buffer_min"] = buffer_min
    plan["suggested_departure"] = f"建议早上8:00前出发，预留{buffer_min}分钟缓冲时间应对路况变化"

    return plan


async def calculate_transit_to_station(city: str, station_type: str = "airport") -> dict:
    """计算从市中心到机场/火车站的时间"""
    if station_type == "airport":
        station_name = f"{city}机场"
    elif station_type == "train":
        station_name = f"{city}站"
    else:
        station_name = f"{city}站"

    city_loc = await amap_geocode(city)
    station_loc = await amap_geocode(station_name, city)

    if not city_loc or not station_loc:
        return {"success": False, "error": f"无法获取{station_name}坐标"}

    clng, clat = _parse_coordinates(city_loc)
    slng, slat = _parse_coordinates(station_loc)

    # 并行获取驾车和公交时间
    drive = await get_route_time(clng, clat, slng, slat)
    transit = await get_transit_time(clng, clat, slng, slat, city)

    return {
        "success": True,
        "station": station_name,
        "drive_min": drive.get("duration", 0),
        "transit_min": transit.get("duration", 0),
        "drive_traffic": drive.get("traffic", ""),
        "advice": f"建议提前{max(60, drive.get('duration', 30) + 30)}分钟出发前往{station_name}"
    }


async def calculate_station_to_hotel(city: str, station_type: str = "airport") -> dict:
    """计算从机场/火车站到市中心酒店的时间和交通方式"""
    station_name = f"{city}机场" if station_type == "airport" else f"{city}站"
    station_loc = await amap_geocode(station_name, city)
    city_loc = await amap_geocode(city)

    if not city_loc or not station_loc:
        return {"success": False, "drive_min": 30, "transit_min": 45, "advice": "建议打车前往酒店"}

    slng, slat = _parse_coordinates(station_loc)
    clng, clat = _parse_coordinates(city_loc)

    drive = await get_route_time(slng, slat, clng, clat)
    transit = await get_transit_time(slng, slat, clng, clat, city)

    return {
        "success": True,
        "station": station_name,
        "drive_min": drive.get("duration", 30),
        "transit_min": transit.get("duration", 45),
        "drive_traffic": drive.get("traffic", ""),
        "advice": f"从{station_name}到市中心酒店，驾车约{drive.get('duration', 30)}分钟，公交约{transit.get('duration', 45)}分钟"
    }