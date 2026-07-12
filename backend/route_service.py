"""高德路线规划服务：实时路况、驾车/步行/公交耗时、到达时间预测"""
import httpx
from config import AMAP_KEY

AMAP_DRIVING_URL = "https://restapi.amap.com/v3/direction/driving"
AMAP_WALKING_URL = "https://restapi.amap.com/v3/direction/walking"


async def get_route_time(origin_lng: float, origin_lat: float, dest_lng: float, dest_lat: float, city: str = "") -> dict:
    """高德驾车路线规划：获取实时路况下的行驶时间和距离"""
    result = {"success": False, "duration": 0, "distance": "", "traffic": "", "arrival_time": ""}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(AMAP_DRIVING_URL, params={
                "key": AMAP_KEY, "strategy": "0",
                "extensions": "all",
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
                # 解析路况状态
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
            routes.append({"success": False, "from": origin.get("name", ""), "to": dest.get("name", ""), "duration": 0, "distance": "", "traffic": ""})
    return routes