"""飞常准航空服务：城市IATA代码映射 + 航班查询集成"""
import httpx

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


def get_iata(city: str) -> str:
    """将中文城市名转换为IATA城市代码"""
    clean = city.replace("市", "").replace("省", "").strip()
    return CITY_TO_IATA.get(clean, "")


def judge_transport(departure_city: str, dest_city: str) -> dict:
    """根据距离和性价比判断推荐交通工具"""
    # 主要城市间高铁/飞机的距离判断
    SHORT_DISTANCE = {"北京-天津": 120, "广州-深圳": 140, "上海-苏州": 100,
                       "上海-杭州": 170, "成都-重庆": 300, "南京-上海": 300,
                       "广州-珠海": 140, "深圳-香港": 40, "北京-石家庄": 280}
    MEDIUM_DISTANCE = {"北京-上海": 1200, "北京-西安": 1100, "上海-武汉": 800,
                        "广州-长沙": 700, "北京-杭州": 1200, "上海-青岛": 700,
                        "成都-西安": 700, "深圳-长沙": 800, "北京-南京": 1000,
                        "广州-厦门": 600, "上海-厦门": 1000, "北京-武汉": 1100}
    key1 = f"{departure_city}-{dest_city}"
    key2 = f"{dest_city}-{departure_city}"
    dist = SHORT_DISTANCE.get(key1) or SHORT_DISTANCE.get(key2) or \
           MEDIUM_DISTANCE.get(key1) or MEDIUM_DISTANCE.get(key2)
    if dist is None:
        iata_dep = get_iata(departure_city)
        iata_arr = get_iata(dest_city)
        if iata_dep and iata_arr and iata_dep != iata_arr:
            return {"mode": "建议飞机/高铁", "reason": "中长途城市间推荐飞机或高铁",
                    "dep_iata": iata_dep, "arr_iata": iata_arr, "need_flight": True}
        return {"mode": "建议高铁/自驾", "reason": "请根据实际距离选择",
                "need_flight": False}
    if dist <= 300:
        return {"mode": "高铁/动车", "reason": f"距离约{dist}km，推荐高铁",
                "need_flight": False}
    elif dist <= 800:
        return {"mode": "高铁优先", "reason": f"距离约{dist}km，高铁便捷",
                "need_flight": False}
    else:
        iata_dep = get_iata(departure_city)
        iata_arr = get_iata(dest_city)
        return {"mode": "飞机/高铁", "reason": f"距离约{dist}km，推荐飞机或高铁",
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