"""飞常准航空服务：城市IATA代码映射 + 航班查询 + 真实票务搜索"""
import httpx
import asyncio

# 中国主要城市名 → IATA城市代码映射
CITY_TO_IATA = {
    "北京": "BJS", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "杭州": "HGH", "成都": "CTU", "重庆": "CKG", "南京": "NKG",
    "武汉": "WUH", "西安": "XIY", "青岛": "TAO", "大连": "DLC",
    "厦门": "XMN", "三亚": "SYX", "昆明": "KMG", "长沙": "CSX",
    "郑州": "CGO", "天津": "TSN", "苏州": "SZV", "哈尔滨": "HRB",
    "沈阳": "SHE", "福州": "FOC", "合肥": "HFE", "南宁": "NNG",
    "贵阳": "KWE", "海口": "HAK", "拉萨": "LXA", "乌鲁木齐": "URC",
    "兰州": "LHW", "呼和浩特": "HET", "银川": "INC", "西宁": "XNN",
    "南昌": "KHN", "济南": "TNA", "太原": "TYN", "石家庄": "SJW",
    "长春": "CGQ", "珠海": "ZUH", "桂林": "KWL", "丽江": "LJG",
    "张家界": "DYG", "黄山": "TXN", "敦煌": "DNH", "延吉": "YNJ",
}

# 主要机场IATA代码
AIRPORT_TO_IATA = {
    "北京首都": "PEK", "北京大兴": "PKX", "上海浦东": "PVG",
    "上海虹桥": "SHA", "广州白云": "CAN", "深圳宝安": "SZX",
    "杭州萧山": "HGH", "成都双流": "CTU", "成都天府": "TFU",
    "重庆江北": "CKG", "南京禄口": "NKG", "武汉天河": "WUH",
    "西安咸阳": "XIY", "昆明长水": "KMG", "长沙黄花": "CSX",
}

# 中国主要城市→主要火车站名映射
CITY_TO_STATION = {
    "北京": "北京南站/北京西站", "上海": "上海虹桥站/上海站", "广州": "广州南站",
    "深圳": "深圳北站", "杭州": "杭州东站", "成都": "成都东站",
    "重庆": "重庆北站", "南京": "南京南站", "武汉": "武汉站",
    "西安": "西安北站", "青岛": "青岛北站", "大连": "大连北站",
    "厦门": "厦门北站", "昆明": "昆明南站", "长沙": "长沙南站",
    "郑州": "郑州东站", "天津": "天津站/天津西站", "哈尔滨": "哈尔滨西站",
    "沈阳": "沈阳北站", "福州": "福州南站", "合肥": "合肥南站",
    "南宁": "南宁东站", "贵阳": "贵阳北站", "海口": "海口东站",
    "拉萨": "拉萨站", "乌鲁木齐": "乌鲁木齐站", "兰州": "兰州西站",
    "呼和浩特": "呼和浩特东站", "银川": "银川站", "西宁": "西宁站",
    "南昌": "南昌西站", "济南": "济南西站", "太原": "太原南站",
    "石家庄": "石家庄站", "长春": "长春西站", "珠海": "珠海站",
}


def get_iata(city: str) -> str:
    """将中文城市名转换为IATA城市代码"""
    clean = city.replace("市", "").replace("省", "").strip()
    return CITY_TO_IATA.get(clean, "")


def get_station(city: str) -> str:
    """获取城市主要火车站名"""
    clean = city.replace("市", "").replace("省", "").strip()
    return CITY_TO_STATION.get(clean, f"{clean}站")


def get_airport(city: str) -> str:
    """获取城市主要机场名"""
    clean = city.replace("市", "").replace("省", "").strip()
    for key, code in AIRPORT_TO_IATA.items():
        if clean in key:
            return key
    return f"{clean}机场"


def judge_transport(departure_city: str, dest_city: str) -> dict:
    """根据距离和性价比判断推荐交通工具，覆盖步行→公交→地铁→高铁→飞机"""
    # 已知城市间距离字典
    KNOWN_DIST = {
        "北京-天津": 120, "广州-深圳": 140, "上海-苏州": 100,
        "上海-杭州": 170, "成都-重庆": 300, "南京-上海": 300,
        "广州-珠海": 140, "深圳-香港": 40, "北京-石家庄": 280,
        "北京-上海": 1200, "北京-西安": 1100, "上海-武汉": 800,
        "广州-长沙": 700, "北京-杭州": 1200, "上海-青岛": 700,
        "成都-西安": 700, "深圳-长沙": 800, "北京-南京": 1000,
        "广州-厦门": 600, "上海-厦门": 1000, "北京-武汉": 1100,
        "北京-哈尔滨": 1200, "上海-昆明": 2300, "广州-三亚": 800,
        "北京-乌鲁木齐": 2800, "上海-拉萨": 4000, "成都-拉萨": 2100,
        "北京-三亚": 2900, "上海-成都": 1900, "广州-昆明": 1300,
    }
    key1 = f"{departure_city}-{dest_city}"
    key2 = f"{dest_city}-{departure_city}"
    dist = KNOWN_DIST.get(key1) or KNOWN_DIST.get(key2)
    iata_dep = get_iata(departure_city)
    iata_arr = get_iata(dest_city)

    if dist is None:
        if iata_dep and iata_arr and iata_dep != iata_arr:
            return {"mode": "建议飞机/高铁", "reason": "中长途城市间推荐飞机或高铁",
                    "dep_iata": iata_dep, "arr_iata": iata_arr, "need_flight": True,
                    "estimated_distance": ">800km"}
        if departure_city == dest_city:
            return {"mode": "市内交通", "reason": "同城出行，推荐地铁/公交/打车",
                    "need_flight": False, "estimated_distance": "同城"}
        return {"mode": "建议高铁/自驾", "reason": "请根据实际距离选择",
                "need_flight": False, "estimated_distance": "未知"}

    if dist <= 5:
        return {"mode": "步行", "reason": f"距离约{dist}km，步行即可到达", "need_flight": False}
    elif dist <= 30:
        return {"mode": "公交/地铁/打车", "reason": f"距离约{dist}km，推荐公交、地铁或打车", "need_flight": False}
    elif dist <= 100:
        return {"mode": "地铁/城际/自驾", "reason": f"距离约{dist}km，可乘地铁城际或自驾", "need_flight": False}
    elif dist <= 300:
        return {"mode": "高铁/动车", "reason": f"距离约{dist}km，推荐高铁，方便快捷", "need_flight": False}
    elif dist <= 800:
        return {"mode": "高铁优先", "reason": f"距离约{dist}km，高铁约{int(dist/300)}-{int(dist/250)}小时，性价比高", "need_flight": False}
    else:
        return {"mode": "飞机/高铁", "reason": f"距离约{dist}km，推荐飞机（约{int(dist/800)}-{int(dist/600)}小时）或高铁（约{int(dist/300)}-{int(dist/250)}小时）",
                "dep_iata": iata_dep, "arr_iata": iata_arr, "need_flight": True}


async def search_flights(dep_city: str, arr_city: str, date: str) -> dict:
    """通过飞常准MCP查询航班信息（调用封装）"""
    result = {"success": False, "flights": [], "error": ""}
    dep_iata = get_iata(dep_city)
    arr_iata = get_iata(arr_city)
    if not dep_iata or not arr_iata:
        result["error"] = f"无法识别城市代码：{dep_city}→{dep_iata} {arr_city}→{arr_iata}"
        return result
    # 飞常准MCP调用通过mcp_Fei_Chang_Zhun_-Aviation/searchFlightsByDepArr
    # 实际调用由Agent层完成，此处返回查询参数
    result["query"] = {"depcity": dep_iata, "arrcity": arr_iata, "date": date}
    result["success"] = True
    return result


def build_flight_query_text(dep_city: str, arr_city: str, date: str) -> str:
    """构建航班/火车票查询描述文本，供AI参考并使用飞常准MCP查询"""
    dep_iata = get_iata(dep_city)
    arr_iata = get_iata(arr_city)
    dep_station = get_station(dep_city)
    arr_station = get_station(arr_city)
    dep_airport = get_airport(dep_city)
    arr_airport = get_airport(arr_city)

    return f"""【真实票务查询指引】
  出发城市：{dep_city}（IATA:{dep_iata}，机场：{dep_airport}，火车站：{dep_station}）
  目的城市：{arr_city}（IATA:{arr_iata}，机场：{arr_airport}，火车站：{arr_station}）
  查询日期：{date}
  
  请使用飞常准MCP工具 searchFlightsByDepArr 查询出发日期{date}从{dep_city}({dep_iata})到{arr_city}({arr_iata})的所有直飞航班，
  然后根据实际航班时刻表确定最佳出发时间。
  
  航班查询链接：https://flights.ctrip.com/booking/{dep_city}-{arr_city}-day-1.html
  火车票查询链接：https://trains.ctrip.com/booking/{dep_city}-{arr_city}-day-1.html
  
  票务决策规则：
  1. 出发时间可以是任意时刻（上午、下午、晚上均可），根据实际票务情况决定
  2. 优先选择有票且价格合理的航班/车次，不要假设特定时间有票
  3. 如果选择飞机，需在起飞前至少2小时到达机场，加上从住处到机场的时间
  4. 如果选择火车，需在发车前至少1小时到达车站，加上从住处到车站的时间
  5. 到达目的地后，必须计算从机场/车站到酒店的交通方式和时间（打车约多久、地铁怎么坐）
  6. 跨天到达处理：如果航班/火车在次日凌晨到达（如23:00起飞次日1:00到），需在departure_transport中标注"次日XX:XX到达"
  7. 下午到达：当天可安排1个晚间轻松景点；晚上到达：当天仅安排入住酒店，不游览
  8. 请给出具体的航班号/车次、出发时间、到达时间、票价等信息
  9. 返程票同样需要查询，根据最后一天游玩安排倒推合理的返程时间"""