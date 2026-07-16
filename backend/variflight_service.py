"""飞常准(Variflight) REST API 服务：航班查询+火车票查询+中转方案"""
import httpx
from config import VARIFLIGHT_KEY, VARIFLIGHT_URL


def _fmt_duration(raw: str) -> str:
    """将分钟数或秒数转换为 'XhYmin' 格式"""
    if not raw:
        return ""
    try:
        minutes = int(raw)
        if minutes > 1000:  # 秒数
            minutes = minutes // 60
        hours = minutes // 60
        mins = minutes % 60
        if hours > 0 and mins > 0:
            return f"{hours}h{mins}min"
        elif hours > 0:
            return f"{hours}h"
        else:
            return f"{mins}min"
    except (ValueError, TypeError):
        return str(raw)


async def _call_variflight(endpoint: str, params: dict) -> dict:
    """调用飞常准API通用方法，参数必须嵌套在params键下"""
    if not VARIFLIGHT_KEY:
        return {"success": False, "error": "VARIFLIGHT_API_KEY未配置", "data": []}
    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                VARIFLIGHT_URL,
                headers={
                    "X-VARIFLIGHT-KEY": VARIFLIGHT_KEY,
                    "Content-Type": "application/json",
                },
                json={"endpoint": endpoint, "params": params},
            )
            if resp.status_code == 401:
                return {"success": False, "error": "飞常准API Key无效", "data": []}
            if resp.status_code != 200:
                return {"success": False, "error": f"飞常准API错误: {resp.status_code}", "data": []}
            data = resp.json()
            # API返回格式: {"code": 200, "data": [...]}，200才算成功
            if data.get("code") != 200:
                return {"success": False, "error": f"飞常准API返回错误: {data.get('message', '')}", "data": []}
            return {"success": True, "data": data.get("data", data)}
        except Exception as e:
            return {"success": False, "error": f"飞常准API调用失败: {str(e)}", "data": []}


async def search_flights_by_route(dep_city: str, arr_city: str, date: str) -> dict:
    """按出发/到达城市查询直飞航班（使用城市IATA代码）"""
    from feichangzhun_service import get_iata
    dep_iata = get_iata(dep_city)
    arr_iata = get_iata(arr_city)
    if not dep_iata or not arr_iata:
        return {"success": False, "error": f"无法识别城市代码：{dep_city}或{arr_city}", "flights": []}
    result = await _call_variflight("flights", {"depcity": dep_iata, "arrcity": arr_iata, "date": date})
    flights = []
    if result.get("success"):
        raw_data = result.get("data", [])
        if isinstance(raw_data, list):
            for f in raw_data:
                # 飞常准API返回PascalCase字段名，需映射为统一格式
                dep_time = f.get("FlightDeptimePlanDate", f.get("dep", ""))
                arr_time = f.get("FlightArrtimePlanDate", f.get("arr", ""))
                # 提取时间部分（去掉日期前缀）
                if " " in str(dep_time):
                    dep_time = dep_time.split(" ")[-1][:5]
                if " " in str(arr_time):
                    arr_time = arr_time.split(" ")[-1][:5]
                # 时长转换：分钟数 → "XhYmin"格式
                raw_dur = f.get("FlightDuration", f.get("duration", ""))
                duration = _fmt_duration(raw_dur)
                flights.append({
                    "num": f.get("FlightNo", f.get("flightNumber", f.get("fnum", ""))),
                    "dep": dep_time,
                    "arr": arr_time,
                    "duration": duration,
                    "from_airport": f.get("FlightDepAirport", f.get("departureAirport", "")),
                    "to_airport": f.get("FlightArrAirport", f.get("arrivalAirport", "")),
                    "price": f.get("price", ""),
                    "airline": f.get("FlightCompany", f.get("airline", "")),
                    "_source": "飞常准实时API",
                })
    return {"success": result.get("success"), "error": result.get("error", ""),
            "flights": flights, "_source": "飞常准实时API"}


async def verify_flight_number(flight_num: str, date: str, dep: str = "", arr: str = "") -> dict:
    """验证航班号是否真实存在"""
    params = {"fnum": flight_num, "date": date}
    if dep:
        params["dep"] = dep
    if arr:
        params["arr"] = arr
    result = await _call_variflight("flight", params)
    if result.get("success"):
        data = result.get("data", {})
        # API返回航班列表，检查是否有匹配的FlightNo
        if isinstance(data, list) and len(data) > 0:
            for f in data:
                if f.get("FlightNo", f.get("flightNumber", f.get("fnum", ""))) == flight_num:
                    return {"valid": True, "data": f, "_source": "飞常准实时验证"}
        if isinstance(data, dict) and (data.get("FlightNo") or data.get("flightNumber") or data.get("fnum")):
            return {"valid": True, "data": data, "_source": "飞常准实时验证"}
    return {"valid": False, "error": result.get("error", "航班不存在"), "_source": "飞常准实时验证"}


async def search_train_tickets(dep_city: str, arr_city: str, date: str) -> dict:
    """查询火车票（高铁/动车/普通列车）"""
    result = await _call_variflight("trainStanTicket", {
        "cdep": dep_city, "carr": arr_city, "date": date
    })
    trains = []
    if result.get("success"):
        raw_data = result.get("data", [])
        # 火车票API返回嵌套结构: {"code": 0, "data": [...]}
        if isinstance(raw_data, dict):
            raw_data = raw_data.get("data", raw_data)
        if isinstance(raw_data, list):
            for t in raw_data:
                # 取最低票价作为参考价格
                seat_lists = t.get("seatLists", [])
                price = ""
                if seat_lists:
                    prices = [s.get("seatPrice", 0) for s in seat_lists if s.get("seatPrice")]
                    if prices:
                        price = str(min(prices))
                trains.append({
                    "num": t.get("trainNumber", t.get("num", "")),
                    "dep": t.get("fromTime", t.get("departureTime", t.get("dep", ""))),
                    "arr": t.get("toTime", t.get("arrivalTime", t.get("arr", ""))),
                    "duration": _fmt_duration(t.get("useTime", t.get("duration", ""))),
                    "from_station": t.get("fromStation", t.get("departureStation", "")),
                    "to_station": t.get("toStation", t.get("arrivalStation", "")),
                    "type": t.get("trainType", ""),
                    "price": price,
                    "_source": "飞常准实时API",
                })
    return {"success": result.get("success"), "error": result.get("error", ""),
            "trains": trains, "_source": "飞常准实时API"}


async def search_flight_itineraries(dep_city: str, arr_city: str, date: str) -> dict:
    """查询可购航班行程（含价格）"""
    from feichangzhun_service import get_iata
    dep_iata = get_iata(dep_city)
    arr_iata = get_iata(arr_city)
    if not dep_iata or not arr_iata:
        return {"success": False, "error": "无法识别城市代码", "itineraries": []}
    result = await _call_variflight("searchFlightItineraries", {
        "depCityCode": dep_iata, "arrCityCode": arr_iata, "depDate": date
    })
    return {"success": result.get("success"), "error": result.get("error", ""),
            "data": result.get("data", {}), "_source": "飞常准实时API"}


async def get_flight_transfer(dep_city: str, arr_city: str, date: str) -> dict:
    """查询中转航班方案"""
    from feichangzhun_service import get_iata
    dep_iata = get_iata(dep_city)
    arr_iata = get_iata(arr_city)
    if not dep_iata or not arr_iata:
        return {"success": False, "error": "无法识别城市代码", "transfers": []}
    result = await _call_variflight("getFlightTransferInfo", {
        "depcity": dep_iata, "arrcity": arr_iata, "depdate": date
    })
    return {"success": result.get("success"), "error": result.get("error", ""),
            "data": result.get("data", {}), "_source": "飞常准实时API"}


async def get_full_route_data(dep_city: str, arr_city: str, date: str) -> dict:
    """获取完整路线数据：航班+火车票+中转方案（并行查询）"""
    import asyncio
    tasks = [
        search_flights_by_route(dep_city, arr_city, date),
        search_train_tickets(dep_city, arr_city, date),
        get_flight_transfer(dep_city, arr_city, date),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    flights_result = results[0] if not isinstance(results[0], Exception) else {"success": False, "flights": []}
    trains_result = results[1] if not isinstance(results[1], Exception) else {"success": False, "trains": []}
    transfer_result = results[2] if not isinstance(results[2], Exception) else {"success": False, "data": {}}

    return {
        "success": flights_result.get("success") or trains_result.get("success"),
        "flights": flights_result.get("flights", []),
        "trains": trains_result.get("trains", []),
        "transfers": transfer_result.get("data", {}),
        "_source": "飞常准实时API",
        "flight_error": flights_result.get("error", ""),
        "train_error": trains_result.get("error", ""),
    }