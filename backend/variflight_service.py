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
    """调用飞常准API通用方法，支持两种格式：
    1. JSON-RPC 2.0 格式（MCP标准协议）
    2. 自定义REST格式（兜底回退）
    参数必须嵌套在params键下"""
    if not VARIFLIGHT_KEY:
        return {"success": False, "error": "VARIFLIGHT_API_KEY未配置", "data": []}
    async with httpx.AsyncClient(timeout=30.0) as client:
        common_headers = {
            "X-VARIFLIGHT-KEY": VARIFLIGHT_KEY,
            "Content-Type": "application/json",
        }
        # 方案1：JSON-RPC 2.0 格式（MCP标准协议，优先尝试）
        jsonrpc_body = {
            "jsonrpc": "2.0",
            "method": "tools/call",
            "params": {"name": endpoint, "arguments": params},
            "id": 1,
        }
        last_error = ""
        try:
            resp = await client.post(VARIFLIGHT_URL, headers=common_headers, json=jsonrpc_body)
            if resp.status_code == 200:
                data = resp.json()
                # JSON-RPC响应格式: {"result": {"content": [{"type": "text", "text": "..."}]}}
                rpc_result = data.get("result", {})
                if rpc_result:
                    content = rpc_result.get("content", [])
                    if content and len(content) > 0:
                        import json
                        inner_text = content[0].get("text", "")
                        if inner_text:
                            inner_data = json.loads(inner_text)
                            if inner_data.get("code") == 200:
                                return {"success": True, "data": inner_data.get("data", inner_data)}
                            else:
                                last_error = f"JSON-RPC返回错误: {inner_data.get('message', '')}"
                # JSON-RPC错误响应
                rpc_error = data.get("error", {})
                if rpc_error:
                    last_error = f"JSON-RPC错误: {rpc_error.get('message', str(rpc_error))}"
            elif resp.status_code == 401:
                last_error = "飞常准API Key无效(JSON-RPC)"
            else:
                last_error = f"JSON-RPC HTTP错误: {resp.status_code}"
        except Exception as e:
            last_error = f"JSON-RPC调用失败: {str(e)}"

        # 方案2：自定义REST格式（兜底回退）
        try:
            resp = await client.post(
                VARIFLIGHT_URL,
                headers=common_headers,
                json={"endpoint": endpoint, "params": params},
            )
            if resp.status_code == 401:
                return {"success": False, "error": "飞常准API Key无效", "data": []}
            if resp.status_code != 200:
                return {"success": False, "error": f"飞常准API HTTP错误: {resp.status_code} (JSON-RPC also failed: {last_error})", "data": []}
            data = resp.json()
            if data.get("code") == 200:
                return {"success": True, "data": data.get("data", data)}
            return {"success": False, "error": f"飞常准API返回错误: {data.get('message', '')} (JSON-RPC also failed: {last_error})", "data": []}
        except Exception as e:
            return {"success": False, "error": f"飞常准API调用失败: {str(e)} (JSON-RPC also failed: {last_error})", "data": []}


async def _try_flight_query(dep_iata: str, arr_iata: str, date: str) -> dict:
    """尝试查询航班（单个机场对），返回航班列表"""
    result = await _call_variflight("searchFlightsByDepArr", {"dep": dep_iata, "arr": arr_iata, "date": date})
    flights = []
    if result.get("success"):
        raw_data = result.get("data", [])
        if isinstance(raw_data, list):
            for f in raw_data:
                dep_time = f.get("FlightDeptimePlanDate", f.get("dep", ""))
                arr_time = f.get("FlightArrtimePlanDate", f.get("arr", ""))
                if " " in str(dep_time):
                    dep_time = dep_time.split(" ")[-1][:5]
                if " " in str(arr_time):
                    arr_time = arr_time.split(" ")[-1][:5]
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
    return {"success": result.get("success"), "flights": flights, "error": result.get("error", "")}


async def search_flights_by_route(dep_city: str, arr_city: str, date: str) -> dict:
    """按出发/到达城市查询直飞航班（使用机场IATA代码，而非城市代码）
    支持多机场查询：如果主机场无数据，尝试查询邻近枢纽城市的机场"""
    from feichangzhun_service import get_primary_airport_iata, get_nearest_hub, _clean_city_name
    dep_iata = get_primary_airport_iata(dep_city)
    arr_iata = get_primary_airport_iata(arr_city)

    if not dep_iata or not arr_iata:
        # 尝试获取邻近枢纽的机场代码
        dep_hub = get_nearest_hub(dep_city)
        arr_hub = get_nearest_hub(arr_city)
        if not dep_iata and dep_hub.get("has_hub"):
            dep_iata = dep_hub.get("hub_iata", "")
            print(f"[VARIFLIGHT] {dep_city}无机场，使用邻近枢纽{dep_hub['hub_city']}的机场代码: {dep_iata}")
        if not arr_iata and arr_hub.get("has_hub"):
            arr_iata = arr_hub.get("hub_iata", "")
            print(f"[VARIFLIGHT] {arr_city}无机场，使用邻近枢纽{arr_hub['hub_city']}的机场代码: {arr_iata}")
        if not dep_iata or not arr_iata:
            return {"success": False, "error": f"无法识别机场代码：{dep_city}或{arr_city}", "flights": []}

    # 主查询：直接机场对
    result = await _try_flight_query(dep_iata, arr_iata, date)
    flights = result.get("flights", [])

    # 如果主查询无结果，尝试扩展查询：出发城市的其他机场或邻近枢纽机场
    if not flights and dep_iata:
        # 尝试查询出发城市邻近枢纽到目的地的航班
        dep_hub = get_nearest_hub(dep_city)
        if dep_hub.get("has_hub") and dep_hub["hub_iata"] != dep_iata:
            alt_dep_iata = dep_hub["hub_iata"]
            print(f"[VARIFLIGHT] 主查询{dep_iata}->{arr_iata}无结果，尝试邻近枢纽{alt_dep_iata}")
            alt_result = await _try_flight_query(alt_dep_iata, arr_iata, date)
            alt_flights = alt_result.get("flights", [])
            if alt_flights:
                for f in alt_flights:
                    f["_source"] = f"飞常准实时API（邻近枢纽{dep_hub['hub_city']}出发）"
                flights = alt_flights

    return {"success": bool(flights), "error": result.get("error", ""),
            "flights": flights, "_source": "飞常准实时API"}


async def verify_flight_number(flight_num: str, date: str, dep: str = "", arr: str = "") -> dict:
    """验证航班号是否真实存在（使用机场代码）
    MCP searchFlightsByNumber 参数: fnum(航班号), date(日期), dep/arr(可选机场代码)"""
    from feichangzhun_service import get_primary_airport_iata
    params = {"fnum": flight_num, "date": date}
    if dep:
        params["dep"] = get_primary_airport_iata(dep) or dep
    if arr:
        params["arr"] = get_primary_airport_iata(arr) or arr
    result = await _call_variflight("searchFlightsByNumber", params)
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
    """查询可购航班行程（含价格），使用城市代码（depCityCode/arrCityCode为城市代码）
    MCP searchFlightItineraries 参数: depCityCode(城市代码如BJS), arrCityCode(城市代码如SHA), depDate(日期)"""
    from feichangzhun_service import get_iata
    dep_city_code = get_iata(dep_city)
    arr_city_code = get_iata(arr_city)
    if not dep_city_code or not arr_city_code:
        return {"success": False, "error": "无法识别城市代码", "itineraries": []}
    result = await _call_variflight("searchFlightItineraries", {
        "depCityCode": dep_city_code, "arrCityCode": arr_city_code, "depDate": date
    })
    return {"success": result.get("success"), "error": result.get("error", ""),
            "data": result.get("data", {}), "_source": "飞常准实时API"}


async def get_flight_transfer(dep_city: str, arr_city: str, date: str) -> dict:
    """查询中转航班方案，使用城市代码（depcity/arrcity而非机场代码）
    MCP getFlightTransferInfo 参数: depcity(城市代码), arrcity(城市代码), depdate(日期)"""
    from feichangzhun_service import get_iata
    dep_city_code = get_iata(dep_city)
    arr_city_code = get_iata(arr_city)
    if not dep_city_code or not arr_city_code:
        return {"success": False, "error": "无法识别城市代码", "transfers": []}
    result = await _call_variflight("getFlightTransferInfo", {
        "depcity": dep_city_code, "arrcity": arr_city_code, "depdate": date
    })
    return {"success": result.get("success"), "error": result.get("error", ""),
            "data": result.get("data", {}), "_source": "飞常准实时API"}


async def get_full_route_data(dep_city: str, arr_city: str, date: str, user_transport_mode: str = "") -> dict:
    """获取完整路线数据：航班+火车票+中转方案（并行查询）
    飞常准API优先，无数据时自动回退预存COMMON_ROUTES数据，确保班次号始终可用
    user_transport_mode: 用户选择的出行方式，用于回退时过滤不匹配的交通类型"""
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

    has_flights = bool(flights_result.get("flights"))
    has_trains = bool(trains_result.get("trains"))
    has_data = has_flights or has_trains

    # 飞常准API无数据时，回退预存COMMON_ROUTES数据（确保班次号始终可获取）
    if not has_data:
        from feichangzhun_service import get_route_schedule
        fallback = get_route_schedule(dep_city, arr_city, date, user_transport_mode=user_transport_mode)
        fb_flights = fallback.get("flights", [])
        fb_trains = fallback.get("trains", [])
        if fb_flights or fb_trains:
            print(f"[VARIFLIGHT] API无数据，回退预存COMMON_ROUTES: {len(fb_flights)}航班, {len(fb_trains)}火车")
            return {
                "success": True,
                "flights": fb_flights,
                "trains": fb_trains,
                "transfers": transfer_result.get("data", {}),
                "_source": "预存数据（飞常准API无数据，自动回退）",
                "_no_data": False,
                "_no_data_message": "",
                "flight_error": flights_result.get("error", ""),
                "train_error": trains_result.get("error", ""),
            }

    return {
        "success": flights_result.get("success") or trains_result.get("success"),
        "flights": flights_result.get("flights", []),
        "trains": trains_result.get("trains", []),
        "transfers": transfer_result.get("data", {}),
        "_source": "飞常准实时API",
        "_no_data": not has_data,
        "_no_data_message": "飞常准API暂无该路线实时班次数据，请优先选择大巴/自驾等低成本出行方式，或自行在携程查询实时航班" if not has_data else "",
        "flight_error": flights_result.get("error", ""),
        "train_error": trains_result.get("error", ""),
    }