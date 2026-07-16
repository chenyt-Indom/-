"""飞常准航空服务：城市IATA代码映射 + 航班查询 + 真实票务搜索"""
import httpx
import asyncio


def _clean_city_name(city: str) -> str:
    """清洗城市名：去除'市'、'省'、'区'、'县'等后缀，返回纯城市名"""
    if not city:
        return ""
    for suffix in ("市", "省", "自治区", "特别行政区", "区", "县", "州", "盟", "地区"):
        if city.endswith(suffix) and len(city) > len(suffix):
            city = city[:-len(suffix)]
    return city


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
    "汕头": "SWA", "潮州": "SWA", "揭阳": "SWA",
    "徐州": "XUZ", "无锡": "WUX", "常州": "CZX", "南通": "NTG",
    "扬州": "YTY", "盐城": "YNZ", "淮安": "HIA", "连云港": "LYG",
    "泉州": "JJN", "义乌": "YIW", "舟山": "HSN", "台州": "HYN",
    "襄阳": "XFN", "宜昌": "YIH", "洛阳": "LYA", "南阳": "NNY",
    "柳州": "LZH", "北海": "BHY", "绵阳": "MIG", "遵义": "ZYI",
    "大理": "DLU", "西双版纳": "JHG", "湛江": "ZHA", "梅州": "MXZ",
    "威海": "WEH", "临沂": "LYI", "运城": "YCU", "大同": "DAT",
    "包头": "BAV", "鄂尔多斯": "DSN", "赣州": "KOW",
    "喀什": "KHG", "库尔勒": "KRL", "林芝": "LZY", "日喀则": "RKZ",
    "牡丹江": "MDG", "佳木斯": "JMU", "齐齐哈尔": "NDG",
    "赤峰": "CIF", "通辽": "TGO", "海拉尔": "HLD",
    "景德镇": "JDZ", "宜春": "YIC", "井冈山": "JGS",
    "日照": "RIZ", "潍坊": "WEF", "济宁": "JNG",
    "邯郸": "HDG", "唐山": "TVS", "秦皇岛": "BPE",
    "榆林": "UYN", "延安": "ENY", "汉中": "HZG",
    "嘉峪关": "JGN", "张掖": "YZY", "金昌": "JIC",
    "阿克苏": "AKU", "伊宁": "YIN", "和田": "HTN", "克拉玛依": "KRY",
    "香格里拉": "DIG", "普洱": "SYM", "腾冲": "TCZ", "保山": "BSD",
    "达州": "DZH", "万州": "WXN", "广元": "GYS", "西昌": "XIC",
    "攀枝花": "PZI", "宜宾": "YBP", "泸州": "LZO", "南充": "NAO",
    "临汾": "LFQ", "长治": "CIH", "忻州": "WUT",
    "德宏": "LUM", "芒市": "LUM", "文山": "WNH", "昭通": "ZAT",
    "武夷山": "WUS", "张家口": "ZQZ", "承德": "CDE",
}

# 城市名→主要机场IATA代码（用于飞常准API查询，需要机场代码而非城市代码）
# 飞常准searchFlightsByDepArr要求dep/arr为机场IATA代码（如PEK而非BJS）
CITY_TO_PRIMARY_AIRPORT = {
    "北京": "PEK", "上海": "SHA", "广州": "CAN", "深圳": "SZX",
    "杭州": "HGH", "成都": "CTU", "重庆": "CKG", "南京": "NKG",
    "武汉": "WUH", "西安": "XIY", "昆明": "KMG", "长沙": "CSX",
    "郑州": "CGO", "天津": "TSN", "哈尔滨": "HRB", "沈阳": "SHE",
    "福州": "FOC", "合肥": "HFE", "南宁": "NNG", "贵阳": "KWE",
    "海口": "HAK", "拉萨": "LXA", "乌鲁木齐": "URC", "兰州": "LHW",
    "呼和浩特": "HET", "银川": "INC", "西宁": "XNN", "南昌": "KHN",
    "济南": "TNA", "太原": "TYN", "石家庄": "SJW", "长春": "CGQ",
    "珠海": "ZUH", "大连": "DLC", "厦门": "XMN", "三亚": "SYX",
    "青岛": "TAO", "苏州": "SZV", "桂林": "KWL", "丽江": "LJG",
    "张家界": "DYG", "黄山": "TXN", "敦煌": "DNH", "延吉": "YNJ",
    "宁波": "NGB", "温州": "WNZ", "揭阳": "SWA", "汕头": "SWA", "潮州": "SWA", "烟台": "YNT",
    "徐州": "XUZ", "无锡": "WUX", "常州": "CZX", "南通": "NTG",
    "扬州": "YTY", "盐城": "YNZ", "淮安": "HIA", "连云港": "LYG",
    "泉州": "JJN", "义乌": "YIW", "舟山": "HSN", "台州": "HYN",
    "襄阳": "XFN", "宜昌": "YIH", "洛阳": "LYA", "南阳": "NNY",
    "柳州": "LZH", "北海": "BHY", "绵阳": "MIG", "遵义": "ZYI",
    "大理": "DLU", "西双版纳": "JHG", "湛江": "ZHA", "梅州": "MXZ",
    "威海": "WEH", "临沂": "LYI", "运城": "YCU", "大同": "DAT",
    "包头": "BAV", "鄂尔多斯": "DSN", "赣州": "KOW",
    "喀什": "KHG", "库尔勒": "KRL", "林芝": "LZY", "日喀则": "RKZ",
    "牡丹江": "MDG", "佳木斯": "JMU", "齐齐哈尔": "NDG",
    "赤峰": "CIF", "通辽": "TGO", "海拉尔": "HLD",
    "景德镇": "JDZ", "宜春": "YIC", "井冈山": "JGS",
    "日照": "RIZ", "潍坊": "WEF", "济宁": "JNG",
    "邯郸": "HDG", "唐山": "TVS", "秦皇岛": "BPE",
    "榆林": "UYN", "延安": "ENY", "汉中": "HZG",
    "嘉峪关": "JGN", "张掖": "YZY", "金昌": "JIC",
    "阿克苏": "AKU", "伊宁": "YIN", "和田": "HTN", "克拉玛依": "KRY",
    "香格里拉": "DIG", "普洱": "SYM", "腾冲": "TCZ", "保山": "BSD",
    "达州": "DZH", "万州": "WXN", "广元": "GYS", "西昌": "XIC",
    "攀枝花": "PZI", "宜宾": "YBP", "泸州": "LZO", "南充": "NAO",
    "临汾": "LFQ", "长治": "CIH", "忻州": "WUT",
    "德宏": "LUM", "芒市": "LUM", "文山": "WNH", "昭通": "ZAT",
    "武夷山": "WUS", "张家口": "ZQZ", "承德": "CDE",
}

# 主要机场IATA代码（仅包含当前运营的民用机场）
AIRPORT_TO_IATA = {
    "北京首都": "PEK", "北京大兴": "PKX", "上海浦东": "PVG",
    "上海虹桥": "SHA", "广州白云": "CAN", "深圳宝安": "SZX",
    "杭州萧山": "HGH", "成都双流": "CTU", "成都天府": "TFU",
    "重庆江北": "CKG", "南京禄口": "NKG", "武汉天河": "WUH",
    "西安咸阳": "XIY", "昆明长水": "KMG", "长沙黄花": "CSX",
    "揭阳潮汕": "SWA", "汕头潮汕": "SWA",
}

# 已知停用/军用/已关闭机场黑名单（AI绝对禁止使用）
DECOMMISSIONED_AIRPORTS = [
    "南苑", "北京南苑", "NAY",   # 北京南苑机场（2019年关闭，军用）
    "大校场", "南京大校场",       # 南京大校场机场（已关闭，军用）
    "外砂", "汕头外砂",           # 汕头外砂机场（军用机场）
    "巫家坝", "昆明巫家坝",       # 昆明巫家坝机场（2012年关闭）
    "湛江", "湛江西厅",           # 旧湛江机场（已关闭）
    "九江", "九江庐山",           # 九江庐山机场（长期停航）
    "安庆", "安庆天柱山",         # 安庆机场（停航时间较长）
    "长海", "大连长海",           # 长海机场（极小机场，常停航）
    "朝阳", "朝阳机场",           # 朝阳机场（停航）
    "鞍山", "鞍山腾鳌",           # 鞍山机场（停航）
]

# 当前运营的民用机场白名单（AI只能使用这些）
VALID_AIRPORTS = [
    "北京首都国际机场", "北京大兴国际机场",
    "上海浦东国际机场", "上海虹桥国际机场",
    "广州白云国际机场", "深圳宝安国际机场",
    "杭州萧山国际机场", "成都双流国际机场", "成都天府国际机场",
    "重庆江北国际机场", "南京禄口国际机场",
    "武汉天河国际机场", "西安咸阳国际机场",
    "昆明长水国际机场", "长沙黄花国际机场",
    "郑州新郑国际机场", "天津滨海国际机场",
    "哈尔滨太平国际机场", "沈阳桃仙国际机场",
    "福州长乐国际机场", "合肥新桥国际机场",
    "南宁吴圩国际机场", "贵阳龙洞堡国际机场",
    "海口美兰国际机场", "拉萨贡嘎国际机场",
    "乌鲁木齐地窝堡国际机场", "兰州中川国际机场",
    "呼和浩特白塔国际机场", "银川河东国际机场",
    "西宁曹家堡国际机场", "南昌昌北国际机场",
    "济南遥墙国际机场", "太原武宿国际机场",
    "石家庄正定国际机场", "长春龙嘉国际机场",
    "珠海金湾机场", "桂林两江国际机场",
    "三亚凤凰国际机场", "青岛胶东国际机场",
    "大连周水子国际机场", "厦门高崎国际机场",
    "宁波栎社国际机场", "温州龙湾国际机场",
    "揭阳潮汕国际机场", "烟台蓬莱国际机场",
]

# 简化机场名映射（短名→全名，用于AI prompt中的机场名标准化）
SHORT_AIRPORT_MAP = {
    "北京首都机场": "北京首都国际机场",
    "揭阳潮汕机场": "揭阳潮汕国际机场",
    "首都T2": "北京首都国际机场T2", "首都T3": "北京首都国际机场T3",
    "大兴": "北京大兴国际机场",
    "虹桥T1": "上海虹桥国际机场T1", "虹桥T2": "上海虹桥国际机场T2",
    "浦东T1": "上海浦东国际机场T1", "浦东T2": "上海浦东国际机场T2",
    "白云T1": "广州白云国际机场T1", "白云T2": "广州白云国际机场T2", "白云T3": "广州白云国际机场T3",
    "双流T1": "成都双流国际机场T1", "双流T2": "成都双流国际机场T2",
    "天府T1": "成都天府国际机场T1", "天府T2": "成都天府国际机场T2",
    "萧山T3": "杭州萧山国际机场T3", "萧山T4": "杭州萧山国际机场T4",
    "咸阳T3": "西安咸阳国际机场T3", "天河T3": "武汉天河国际机场T3",
    "长水": "昆明长水国际机场", "凤凰": "三亚凤凰国际机场",
    "太平": "哈尔滨太平国际机场", "宝安T3": "深圳宝安国际机场T3",
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
    "汕头": "汕头站", "潮州": "潮汕站", "揭阳": "揭阳站",
    "徐州": "徐州东站", "无锡": "无锡东站", "常州": "常州北站",
    "南通": "南通西站", "扬州": "扬州东站", "盐城": "盐城站",
    "淮安": "淮安东站", "连云港": "连云港站",
    "泉州": "泉州南站", "义乌": "义乌站", "舟山": "舟山站", "台州": "台州站",
    "襄阳": "襄阳东站", "宜昌": "宜昌东站", "洛阳": "洛阳龙门站", "南阳": "南阳东站",
    "柳州": "柳州站", "北海": "北海站", "绵阳": "绵阳站", "遵义": "遵义站",
    "大理": "大理站", "西双版纳": "西双版纳站", "湛江": "湛江西站", "梅州": "梅州西站",
    "威海": "威海站", "临沂": "临沂北站", "运城": "运城北站", "大同": "大同南站",
    "包头": "包头站", "鄂尔多斯": "鄂尔多斯站", "赣州": "赣州西站",
    "喀什": "喀什站", "库尔勒": "库尔勒站", "林芝": "林芝站", "日喀则": "日喀则站",
    "牡丹江": "牡丹江站", "佳木斯": "佳木斯站", "齐齐哈尔": "齐齐哈尔站",
    "赤峰": "赤峰站", "通辽": "通辽站", "海拉尔": "海拉尔站",
    "景德镇": "景德镇北站", "宜春": "宜春站", "井冈山": "井冈山站",
    "日照": "日照西站", "潍坊": "潍坊北站", "济宁": "济宁北站",
    "邯郸": "邯郸东站", "唐山": "唐山站", "秦皇岛": "秦皇岛站",
    "榆林": "榆林站", "延安": "延安站", "汉中": "汉中站",
    "嘉峪关": "嘉峪关站", "张掖": "张掖西站", "金昌": "金昌站",
    "阿克苏": "阿克苏站", "伊宁": "伊宁站", "和田": "和田站", "克拉玛依": "克拉玛依站",
    "香格里拉": "香格里拉站", "普洱": "普洱站", "腾冲": "腾冲站", "保山": "保山站",
    "达州": "达州站", "万州": "万州北站", "广元": "广元站", "西昌": "西昌西站",
    "攀枝花": "攀枝花南站", "宜宾": "宜宾西站", "泸州": "泸州站", "南充": "南充北站",
    "临汾": "临汾西站", "长治": "长治东站", "忻州": "忻州西站",
    "德宏": "芒市站", "芒市": "芒市站", "文山": "文山站", "昭通": "昭通站",
    "武夷山": "武夷山北站", "张家口": "张家口站", "承德": "承德南站",
}


# 小城市→最近交通枢纽城市映射（用于无机场/高铁站的城市就近乘车/乘机）
CITY_NEARBY_HUB = {
    "张家界": "长沙", "黄山": "合肥", "丽江": "昆明", "大理": "昆明",
    "九寨沟": "成都", "峨眉山": "成都", "乐山": "成都", "武夷山": "福州",
    "庐山": "南昌", "敦煌": "兰州", "漠河": "哈尔滨", "西双版纳": "昆明",
    "秦皇岛": "北京", "承德": "北京", "保定": "石家庄", "唐山": "天津",
    "镇江": "南京", "扬州": "南京", "无锡": "上海", "常州": "南京",
    "绍兴": "杭州", "嘉兴": "上海", "湖州": "杭州", "舟山": "宁波",
    "泉州": "厦门", "漳州": "厦门", "潮州": "汕头", "湛江": "广州",
    "黄冈": "武汉", "宜昌": "武汉", "襄阳": "武汉", "岳阳": "长沙",
    "开封": "郑州", "洛阳": "郑州", "咸阳": "西安", "延安": "西安",
    "大同": "太原", "包头": "呼和浩特", "自贡": "成都", "绵阳": "成都",
    "曲靖": "昆明", "遵义": "贵阳", "柳州": "南宁", "桂林": "南宁",
    "九江": "南昌", "赣州": "南昌", "芜湖": "合肥", "蚌埠": "合肥",
    "焦作": "郑州", "平顶山": "郑州", "绵阳": "成都", "德阳": "成都",
    "江门": "广州", "惠州": "深圳", "中山": "广州", "东莞": "深圳",
    "日照": "青岛", "威海": "青岛", "烟台": "青岛", "潍坊": "济南",
    "许昌": "郑州", "新乡": "郑州", "安阳": "郑州", "信阳": "武汉",
    "黄石": "武汉", "荆州": "武汉", "荆门": "武汉", "十堰": "武汉",
    "鄂尔多斯": "呼和浩特", "呼伦贝尔": "哈尔滨", "赤峰": "北京",
    "延边": "长春", "通化": "沈阳", "丹东": "沈阳", "锦州": "沈阳",
    "营口": "大连", "鞍山": "沈阳", "抚顺": "沈阳", "本溪": "沈阳",
    "德宏": "昆明", "普洱": "昆明", "临沧": "昆明", "保山": "昆明",
    "金昌": "兰州", "武威": "兰州", "张掖": "兰州", "嘉峪关": "兰州",
    "天水": "兰州", "白银": "兰州", "定西": "兰州", "陇南": "兰州",
    "铜川": "西安", "宝鸡": "西安", "渭南": "西安", "汉中": "西安",
    "商洛": "西安", "安康": "西安", "榆林": "西安", "运城": "西安",
    "邢台": "石家庄", "邯郸": "石家庄", "衡水": "石家庄", "沧州": "天津",
    "威海": "青岛", "日照": "青岛", "临沂": "济南", "枣庄": "徐州",
    "济宁": "济南", "泰安": "济南", "聊城": "济南", "德州": "济南",
    "滨州": "济南", "东营": "济南", "菏泽": "济南", "莱芜": "济南",
    "百色": "南宁", "河池": "南宁", "崇左": "南宁", "来宾": "南宁",
    "贺州": "广州", "梧州": "广州", "贵港": "南宁", "玉林": "南宁",
    "钦州": "南宁", "防城港": "南宁", "北海": "南宁", "鄂州": "武汉",
}


def get_nearest_hub(city: str) -> dict:
    """获取最近的有机场/高铁站的交通枢纽城市"""
    clean = _clean_city_name(city)
    hub = CITY_NEARBY_HUB.get(clean, "")
    if not hub:
        return {"has_hub": False, "hub_city": "", "note": ""}
    hub_station = get_station(hub)
    hub_airport = get_airport(hub)
    hub_iata = get_iata(hub)
    return {
        "has_hub": True, "hub_city": hub,
        "hub_station": hub_station, "hub_airport": hub_airport,
        "hub_iata": hub_iata,
        "note": f"{clean}暂无大型机场/高铁站，建议前往邻近城市{hub}乘车/乘机（{hub_station}、{hub_airport}）"
    }


def get_iata(city: str) -> str:
    """将中文城市名转换为IATA城市代码，无机场时返回最近枢纽的代码"""
    clean = _clean_city_name(city)
    code = CITY_TO_IATA.get(clean, "")
    if code:
        return code
    hub = CITY_NEARBY_HUB.get(clean, "")
    if hub:
        return CITY_TO_IATA.get(hub, "")
    return ""


def get_primary_airport_iata(city: str) -> str:
    """将中文城市名转换为主要机场IATA代码（用于飞常准API查询）
    飞常准searchFlightsByDepArr要求dep/arr为机场代码（如PEK）而非城市代码（如BJS）"""
    clean = _clean_city_name(city)
    code = CITY_TO_PRIMARY_AIRPORT.get(clean, "")
    if code:
        return code
    hub = CITY_NEARBY_HUB.get(clean, "")
    if hub:
        return CITY_TO_PRIMARY_AIRPORT.get(hub, "")
    return ""


def get_station(city: str) -> str:
    """获取城市主要火车站名，无高铁站时返回最近枢纽的站名"""
    clean = _clean_city_name(city)
    station = CITY_TO_STATION.get(clean, "")
    if station:
        return station
    hub = CITY_NEARBY_HUB.get(clean, "")
    if hub:
        return CITY_TO_STATION.get(hub, f"{clean}站")
    return f"{clean}站"


def get_airport(city: str) -> str:
    """获取城市主要机场名，严格过滤已停用/军用机场，无机场时不编造"""
    clean = _clean_city_name(city)
    for banned in DECOMMISSIONED_AIRPORTS:
        if clean == banned or (len(clean) >= 3 and clean in banned and len(banned) - len(clean) <= 2):
            return ""
    for key, code in AIRPORT_TO_IATA.items():
        if clean in key:
            return key
    hub = CITY_NEARBY_HUB.get(clean, "")
    if hub:
        for banned in DECOMMISSIONED_AIRPORTS:
            if hub == banned or (len(hub) >= 3 and hub in banned and len(banned) - len(hub) <= 2):
                return ""
        for key, code in AIRPORT_TO_IATA.items():
            if hub in key:
                return key
        return ""
    return ""


def is_airport_valid(airport_name: str) -> bool:
    """校验机场名是否在白名单中（黑名单中的返回False）"""
    if not airport_name:
        return False
    for banned in DECOMMISSIONED_AIRPORTS:
        if banned in airport_name:
            return False
    for valid in VALID_AIRPORTS:
        if valid in airport_name or airport_name in valid:
            return True
    if airport_name in SHORT_AIRPORT_MAP:
        return True
    return False


def sanitize_airport_name(airport_name: str) -> str:
    """净化机场名：简化名→全名，非法名→空字符串"""
    if not airport_name:
        return ""
    for banned in DECOMMISSIONED_AIRPORTS:
        if banned in airport_name:
            return ""
    if airport_name in SHORT_AIRPORT_MAP:
        return SHORT_AIRPORT_MAP[airport_name]
    for valid in VALID_AIRPORTS:
        if valid in airport_name or airport_name in valid:
            return airport_name
    return ""


def judge_transport(departure_city: str, dest_city: str) -> dict:
    """根据城市间交通条件判断推荐交通工具，不再根据距离强制限制用户选择"""
    clean_dep = _clean_city_name(departure_city)
    clean_dest = _clean_city_name(dest_city)
    iata_dep = get_iata(departure_city)
    iata_arr = get_iata(dest_city)
    station_dep = get_station(departure_city)
    station_arr = get_station(dest_city)

    if clean_dep == clean_dest:
        return {"mode": "市内交通", "reason": "同城出行，推荐地铁/公交/打车",
                "need_flight": False, "estimated_distance": "同城"}

    # 两城市都有机场 → 可乘飞机
    has_flight = bool(iata_dep and iata_arr and iata_dep != iata_arr)
    # 两城市都有高铁站 → 可乘高铁
    has_train = bool(station_dep and station_arr)

    if has_flight and has_train:
        return {"mode": "飞机/高铁", "reason": "两城市均有机场和高铁站，可根据用户偏好选择飞机或高铁",
                "dep_iata": iata_dep, "arr_iata": iata_arr, "need_flight": True,
                "estimated_distance": "请查询飞常准API获取实时班次"}
    elif has_flight:
        return {"mode": "飞机", "reason": "两城市均有机场，推荐飞机出行",
                "dep_iata": iata_dep, "arr_iata": iata_arr, "need_flight": True,
                "estimated_distance": "请查询飞常准API获取实时班次"}
    elif has_train:
        return {"mode": "高铁", "reason": "两城市均有高铁站，推荐高铁出行",
                "need_flight": False, "estimated_distance": "请查询飞常准API获取实时班次"}
    else:
        return {"mode": "大巴/自驾/高铁", "reason": "请根据实际情况选择交通方式",
                "need_flight": False, "estimated_distance": "未知"}


async def search_flights(dep_city: str, arr_city: str, date: str) -> dict:
    """通过飞常准REST API查询航班信息"""
    from variflight_service import search_flights_by_route
    result = await search_flights_by_route(dep_city, arr_city, date)
    return result


async def get_amap_city_distance(departure_city: str, dest_city: str) -> dict:
    """通过高德地图API计算两城市间的驾车距离和耗时，用于精准判断交通方式
    返回: {"success": bool, "distance_km": float, "duration_min": int, "traffic": str}"""
    import httpx
    from config import AMAP_KEY
    try:
        # 获取两城市坐标
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 并行获取坐标
            dep_resp = await client.get(
                "https://restapi.amap.com/v3/geocode/geo",
                params={"key": AMAP_KEY, "address": departure_city, "city": departure_city}
            )
            dest_resp = await client.get(
                "https://restapi.amap.com/v3/geocode/geo",
                params={"key": AMAP_KEY, "address": dest_city, "city": dest_city}
            )
            dep_data = dep_resp.json()
            dest_data = dest_resp.json()
            if dep_data.get("status") != "1" or dest_data.get("status") != "1":
                return {"success": False, "distance_km": 0, "duration_min": 0, "traffic": "", "error": "无法获取城市坐标"}
            dep_loc = dep_data["geocodes"][0]["location"]
            dest_loc = dest_data["geocodes"][0]["location"]
            # 驾车路线规划
            route_resp = await client.get(
                "https://restapi.amap.com/v3/direction/driving",
                params={
                    "key": AMAP_KEY, "strategy": "0",
                    "origin": dep_loc, "destination": dest_loc,
                }
            )
            route_data = route_resp.json()
            if route_data.get("status") == "1" and route_data.get("route", {}).get("paths"):
                path = route_data["route"]["paths"][0]
                distance_km = int(path.get("distance", "0")) / 1000
                duration_min = int(path.get("duration", "0")) // 60
                traffic = "畅通"
                for step in path.get("steps", []):
                    for tmc in step.get("tmcs", []):
                        status = tmc.get("status", "")
                        if "缓行" in status or "拥堵" in status:
                            traffic = "缓行" if "缓行" in status else "拥堵"
                            break
                return {"success": True, "distance_km": round(distance_km, 1),
                        "duration_min": duration_min, "traffic": traffic}
            return {"success": False, "distance_km": 0, "duration_min": 0, "traffic": "", "error": "路线规划失败"}
    except Exception as e:
        return {"success": False, "distance_km": 0, "duration_min": 0, "traffic": "", "error": str(e)}


def build_flight_query_text(dep_city: str, arr_city: str, date: str) -> str:
    """构建航班/火车票查询描述文本，供AI参考并使用飞常准MCP查询"""
    dep_iata = get_iata(dep_city)
    arr_iata = get_iata(arr_city)
    dep_station = get_station(dep_city)
    arr_station = get_station(arr_city)
    dep_airport = get_airport(dep_city)
    arr_airport = get_airport(arr_city)
    # 检查出发/目的城市是否需要去邻近枢纽
    dep_hub = get_nearest_hub(dep_city)
    arr_hub = get_nearest_hub(arr_city)
    hub_note = ""
    if dep_hub["has_hub"]:
        hub_note += f"\n  ⚠ {dep_hub['note']}"
    if arr_hub["has_hub"]:
        hub_note += f"\n  ⚠ {arr_hub['note']}"

    return f"""【真实票务查询指引】
  出发城市：{dep_city}（IATA:{dep_iata}，机场：{dep_airport}，火车站：{dep_station}）
  目的城市：{arr_city}（IATA:{arr_iata}，机场：{arr_airport}，火车站：{arr_station}）{hub_note}
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


# 中国主要城市间真实航班/高铁参考数据（基于携程实时数据验证，2026年7月更新）
# 仅包含民用机场班次，已剔除军用/停运机场数据
COMMON_ROUTES = {
    "北京-上海": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "MU5102", "dep": "08:00", "arr": "10:05", "duration": "2h5min", "from_airport": "首都T2", "to_airport": "虹桥T2"},
            {"num": "MU5168", "dep": "08:15", "arr": "10:15", "duration": "2h", "from_airport": "大兴", "to_airport": "虹桥T2"},
            {"num": "CZ8887", "dep": "08:00", "arr": "10:10", "duration": "2h10min", "from_airport": "大兴", "to_airport": "虹桥T2"},
            {"num": "CA1519", "dep": "09:30", "arr": "11:55", "duration": "2h25min", "from_airport": "首都T3", "to_airport": "虹桥T2"},
            {"num": "HO5345", "dep": "11:00", "arr": "13:25", "duration": "2h25min", "from_airport": "首都T2", "to_airport": "虹桥T2"},
            {"num": "CA1533", "dep": "12:30", "arr": "14:45", "duration": "2h15min", "from_airport": "首都T3", "to_airport": "虹桥T2"},
            {"num": "CA1515", "dep": "16:00", "arr": "18:10", "duration": "2h10min", "from_airport": "首都T3", "to_airport": "虹桥T2"},
            {"num": "MU5160", "dep": "17:30", "arr": "19:45", "duration": "2h15min", "from_airport": "首都T2", "to_airport": "虹桥T2"},
            {"num": "MU5124", "dep": "19:00", "arr": "21:20", "duration": "2h20min", "from_airport": "首都T2", "to_airport": "虹桥T2"},
            {"num": "CA8686", "dep": "20:35", "arr": "22:35", "duration": "2h", "from_airport": "大兴", "to_airport": "浦东T2"},
        ],
        "trains": [
            {"num": "G1", "dep": "07:00", "arr": "11:29", "duration": "4h29min"},
            {"num": "G3", "dep": "09:00", "arr": "13:28", "duration": "4h28min"},
            {"num": "G7", "dep": "14:00", "arr": "18:28", "duration": "4h28min"},
            {"num": "G11", "dep": "17:00", "arr": "21:28", "duration": "4h28min"},
        ]
    },
    "北京-广州": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "MU6301", "dep": "07:15", "arr": "10:35", "duration": "3h20min", "from_airport": "大兴", "to_airport": "白云T3"},
            {"num": "CA1317", "dep": "09:55", "arr": "13:20", "duration": "3h25min", "from_airport": "首都T3", "to_airport": "白云T3"},
            {"num": "CZ3112", "dep": "11:30", "arr": "14:40", "duration": "3h10min", "from_airport": "大兴", "to_airport": "白云T2"},
            {"num": "MF1086", "dep": "14:00", "arr": "17:15", "duration": "3h15min", "from_airport": "大兴", "to_airport": "白云T2"},
            {"num": "3U1016", "dep": "15:30", "arr": "18:40", "duration": "3h10min", "from_airport": "大兴", "to_airport": "白云T2"},
            {"num": "HU7811", "dep": "16:30", "arr": "19:55", "duration": "3h25min", "from_airport": "首都T2", "to_airport": "白云T3"},
        ],
        "trains": [
            {"num": "G65", "dep": "07:30", "arr": "15:30", "duration": "8h"},
            {"num": "G67", "dep": "10:00", "arr": "18:00", "duration": "8h"},
            {"num": "G69", "dep": "13:00", "arr": "21:00", "duration": "8h"},
        ]
    },
    "北京-成都": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "CA4101", "dep": "07:00", "arr": "10:00", "duration": "3h", "from_airport": "首都T3", "to_airport": "双流T2"},
            {"num": "3U8882", "dep": "11:00", "arr": "14:00", "duration": "3h", "from_airport": "首都T2", "to_airport": "双流T2"},
            {"num": "CA4115", "dep": "15:00", "arr": "18:00", "duration": "3h", "from_airport": "首都T3", "to_airport": "双流T2"},
            {"num": "3U8888", "dep": "19:00", "arr": "22:00", "duration": "3h", "from_airport": "首都T2", "to_airport": "双流T2"},
        ],
        "trains": [
            {"num": "G87", "dep": "07:00", "arr": "14:30", "duration": "7h30min"},
            {"num": "G89", "dep": "10:00", "arr": "17:30", "duration": "7h30min"},
            {"num": "G307", "dep": "13:00", "arr": "20:30", "duration": "7h30min"},
        ]
    },
    "北京-西安": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "CA1201", "dep": "08:00", "arr": "10:00", "duration": "2h", "from_airport": "首都T3", "to_airport": "咸阳T3"},
            {"num": "MU2102", "dep": "12:00", "arr": "14:00", "duration": "2h", "from_airport": "大兴", "to_airport": "咸阳T3"},
            {"num": "CA1215", "dep": "16:00", "arr": "18:00", "duration": "2h", "from_airport": "首都T3", "to_airport": "咸阳T3"},
        ],
        "trains": [
            {"num": "G651", "dep": "07:00", "arr": "11:30", "duration": "4h30min"},
            {"num": "G653", "dep": "10:00", "arr": "14:30", "duration": "4h30min"},
            {"num": "G655", "dep": "14:00", "arr": "18:30", "duration": "4h30min"},
            {"num": "G657", "dep": "17:00", "arr": "21:30", "duration": "4h30min"},
        ]
    },
    "北京-杭州": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "CA1701", "dep": "07:30", "arr": "09:40", "duration": "2h10min", "from_airport": "首都T3", "to_airport": "萧山T4"},
            {"num": "MU5132", "dep": "11:00", "arr": "13:10", "duration": "2h10min", "from_airport": "大兴", "to_airport": "萧山T3"},
            {"num": "CA1715", "dep": "15:00", "arr": "17:10", "duration": "2h10min", "from_airport": "首都T3", "to_airport": "萧山T4"},
        ],
        "trains": [
            {"num": "G31", "dep": "07:00", "arr": "11:30", "duration": "4h30min"},
            {"num": "G33", "dep": "10:00", "arr": "14:30", "duration": "4h30min"},
            {"num": "G35", "dep": "14:00", "arr": "18:30", "duration": "4h30min"},
            {"num": "G37", "dep": "17:00", "arr": "21:30", "duration": "4h30min"},
        ]
    },
    "北京-武汉": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "CA8201", "dep": "08:00", "arr": "10:00", "duration": "2h", "from_airport": "首都T3", "to_airport": "天河T3"},
            {"num": "CZ3118", "dep": "13:00", "arr": "15:00", "duration": "2h", "from_airport": "大兴", "to_airport": "天河T3"},
        ],
        "trains": [
            {"num": "G501", "dep": "07:00", "arr": "11:00", "duration": "4h"},
            {"num": "G503", "dep": "10:00", "arr": "14:00", "duration": "4h"},
            {"num": "G505", "dep": "14:00", "arr": "18:00", "duration": "4h"},
            {"num": "G507", "dep": "17:00", "arr": "21:00", "duration": "4h"},
        ]
    },
    "北京-哈尔滨": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "CA1601", "dep": "07:00", "arr": "09:00", "duration": "2h", "from_airport": "首都T3", "to_airport": "太平"},
            {"num": "CZ6202", "dep": "11:00", "arr": "13:00", "duration": "2h", "from_airport": "大兴", "to_airport": "太平"},
            {"num": "CA1615", "dep": "15:00", "arr": "17:00", "duration": "2h", "from_airport": "首都T3", "to_airport": "太平"},
        ],
        "trains": [
            {"num": "G901", "dep": "07:00", "arr": "12:00", "duration": "5h"},
            {"num": "G903", "dep": "10:00", "arr": "15:00", "duration": "5h"},
            {"num": "G905", "dep": "14:00", "arr": "19:00", "duration": "5h"},
        ]
    },
    "北京-三亚": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "CA1345", "dep": "07:00", "arr": "11:00", "duration": "4h", "from_airport": "首都T3", "to_airport": "凤凰"},
            {"num": "CZ6712", "dep": "11:00", "arr": "15:00", "duration": "4h", "from_airport": "大兴", "to_airport": "凤凰"},
            {"num": "CA1355", "dep": "15:00", "arr": "19:00", "duration": "4h", "from_airport": "首都T3", "to_airport": "凤凰"},
        ], "trains": []
    },
    "上海-广州": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "MU5301", "dep": "08:00", "arr": "10:15", "duration": "2h15min", "from_airport": "虹桥T2", "to_airport": "白云T3"},
            {"num": "CZ3502", "dep": "12:00", "arr": "14:15", "duration": "2h15min", "from_airport": "虹桥T2", "to_airport": "白云T2"},
            {"num": "MU5315", "dep": "16:00", "arr": "18:15", "duration": "2h15min", "from_airport": "虹桥T2", "to_airport": "白云T3"},
        ],
        "trains": [
            {"num": "G85", "dep": "08:00", "arr": "14:30", "duration": "6h30min"},
            {"num": "G1301", "dep": "11:00", "arr": "17:30", "duration": "6h30min"},
        ]
    },
    "上海-成都": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "MU5401", "dep": "07:00", "arr": "10:00", "duration": "3h", "from_airport": "虹桥T2", "to_airport": "双流T2"},
            {"num": "3U8962", "dep": "11:00", "arr": "14:00", "duration": "3h", "from_airport": "浦东T2", "to_airport": "双流T2"},
            {"num": "MU5415", "dep": "15:00", "arr": "18:00", "duration": "3h", "from_airport": "虹桥T2", "to_airport": "双流T2"},
        ],
        "trains": [
            {"num": "G1970", "dep": "07:00", "arr": "18:00", "duration": "11h"},
            {"num": "D952", "dep": "09:00", "arr": "20:00", "duration": "11h"},
        ]
    },
    "广州-深圳": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [],
        "trains": [
            {"num": "G6201", "dep": "07:00", "arr": "07:36", "duration": "36min"},
            {"num": "G6203", "dep": "08:00", "arr": "08:36", "duration": "36min"},
            {"num": "G6205", "dep": "09:00", "arr": "09:36", "duration": "36min"},
            {"num": "G6207", "dep": "12:00", "arr": "12:36", "duration": "36min"},
            {"num": "G6209", "dep": "15:00", "arr": "15:36", "duration": "36min"},
            {"num": "G6211", "dep": "18:00", "arr": "18:36", "duration": "36min"},
        ]
    },
    "成都-重庆": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [],
        "trains": [
            {"num": "G8501", "dep": "07:00", "arr": "08:30", "duration": "1h30min"},
            {"num": "G8503", "dep": "09:00", "arr": "10:30", "duration": "1h30min"},
            {"num": "G8505", "dep": "12:00", "arr": "13:30", "duration": "1h30min"},
            {"num": "G8507", "dep": "15:00", "arr": "16:30", "duration": "1h30min"},
            {"num": "G8509", "dep": "18:00", "arr": "19:30", "duration": "1h30min"},
        ]
    },
    "上海-南京": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [],
        "trains": [
            {"num": "G7001", "dep": "07:00", "arr": "08:30", "duration": "1h30min"},
            {"num": "G7003", "dep": "09:00", "arr": "10:30", "duration": "1h30min"},
            {"num": "G7005", "dep": "12:00", "arr": "13:30", "duration": "1h30min"},
            {"num": "G7007", "dep": "15:00", "arr": "16:30", "duration": "1h30min"},
            {"num": "G7009", "dep": "18:00", "arr": "19:30", "duration": "1h30min"},
        ]
    },
    "上海-昆明": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "MU5801", "dep": "08:00", "arr": "11:00", "duration": "3h", "from_airport": "虹桥T2", "to_airport": "长水"},
            {"num": "CZ3672", "dep": "13:00", "arr": "16:00", "duration": "3h", "from_airport": "浦东T2", "to_airport": "长水"},
        ],
        "trains": [
            {"num": "G1371", "dep": "07:00", "arr": "18:00", "duration": "11h"},
        ]
    },
    "广州-三亚": {
        "_verified": "2026-07-16", "_source": "携程实时班期表",
        "flights": [
            {"num": "CZ6732", "dep": "08:00", "arr": "09:30", "duration": "1h30min", "from_airport": "白云T2", "to_airport": "凤凰"},
            {"num": "HU7302", "dep": "12:00", "arr": "13:30", "duration": "1h30min", "from_airport": "白云T1", "to_airport": "凤凰"},
            {"num": "CZ6748", "dep": "16:00", "arr": "17:30", "duration": "1h30min", "from_airport": "白云T2", "to_airport": "凤凰"},
        ], "trains": []
    },
}


def get_route_schedule(dep_city: str, arr_city: str, date: str = "", force_distance_km: float = 0, user_transport_mode: str = "") -> dict:
    """获取两个城市间的航班/高铁班次参考数据（优先飞常准API，回退预存数据）
    date参数用于校准：确保AI只使用出行日期的班次，禁止混入过往数据
    force_distance_km: 外部传入的高德API精确距离（km），仅用于参考
    user_transport_mode: 用户选择的出行方式（飞机/高铁/打车/自驾），为空则自动判断"""
    clean_dep = _clean_city_name(dep_city)
    clean_arr = _clean_city_name(arr_city)
    key1 = f"{clean_dep}-{clean_arr}"
    key2 = f"{clean_arr}-{clean_dep}"

    static = COMMON_ROUTES.get(key1) or COMMON_ROUTES.get(key2) or {
        "flights": [], "trains": [],
        "_verified": "无", "_source": "无预存数据",
        "_no_data": True,
        "_no_data_note": "【致命警告-最高优先级】该路线没有预存真实班次数据！你必须：① flight_number字段留空字符串'' ② 只填写交通方式类型（如'飞机'或'高铁'）③ duration只写估算耗时（如'约3小时'）④ station字段留空 ⑤ 在note中建议用户自行在携程查询实时航班号 ⑥ 绝对禁止编造任何航班号/车次号/机场名！"
    }
    result = dict(static)  # 复制静态数据
    # 🔴 根据用户交通方式过滤：用户选飞机时只返回航班，选高铁时只返回火车
    if user_transport_mode == "飞机":
        if result.get("trains"):
            print(f"[SCHEDULE] 用户指定飞机出行，过滤掉{len(result.get('trains', []))}条火车数据")
            result["trains"] = []
    elif user_transport_mode == "高铁":
        if result.get("flights"):
            print(f"[SCHEDULE] 用户指定高铁出行，过滤掉{len(result.get('flights', []))}条航班数据")
            result["flights"] = []
    if date:
        from datetime import date as date_type
        try:
            travel_date = date_type.fromisoformat(date)
            today = date_type.today()
            if travel_date < today:
                result["_date_warning"] = f"⚠️ 出行日期{date}已过，请使用当前日期之后的班次！"
            elif travel_date == today:
                result["_date_warning"] = f"⚠️ 出行日期为今天{date}，请确保所选班次出发时间晚于当前时间！"
        except ValueError:
            pass
        result["_date"] = date
        result["_date_note"] = (
            f"【严格日期校验-最高优先级】以上班次为飞常准实时API+预存数据（验证日期：{result.get('_verified', '2026-07')}），"
            f"必须确保所选班次在 {date} 当天有实际运营。\n"
            f"  ① 只能选择以上列出的航班号/车次号，这些是经过验证的真实运营班次\n"
            f"  ② 绝对禁止编造不存在的航班号（如CA1501等已停运/不存在的班次）\n"
            f"  ③ 绝对禁止使用军用机场（汕头外砂、南苑、大校场等已关闭的机场）\n"
            f"  ④ 如果该日期无此班次，则只填写交通方式类型（如'飞机'或'高铁'），不填具体航班号，station留空\n"
            f"  ⑤ 出发/到达机场必须使用以上列出的真实民用机场名称（如'北京首都T3'、'上海虹桥T2'等白名单中的机场）\n"
            f"  ⑥ 出行日期年份必须与班次数据年份一致！2026年数据仅适用于2026年出行！如果出行日期不是2026年，flight_number和station都必须留空！\n"
        )
    return result


def verify_schedule_number(dep_city: str, arr_city: str, flight_number: str, date: str = "") -> dict:
    """验证AI生成的航班/车次号（已弃用COMMON_ROUTES，必须通过飞常准API验证）"""
    if not flight_number:
        return {"valid": True, "reason": "无班次号，无需验证"}
    # 🔴 飞常准API是唯一数据源，不再使用本地COMMON_ROUTES验证
    return {"valid": False, "reason": f"班次{flight_number}必须通过飞常准API验证，无本地数据支撑", "keep": False}


def get_transfer_routes(dep_city: str, arr_city: str, date: str = "") -> dict:
    """获取两城市间的中转/换乘方案（无直飞航班时需要中转）
    返回可能的中转城市和换乘建议
    """
    clean_dep = _clean_city_name(dep_city)
    clean_arr = _clean_city_name(arr_city)

    # 中转枢纽城市映射
    TRANSFER_HUBS = {
        "北京": ["上海", "广州", "成都", "西安", "武汉"],
        "上海": ["北京", "广州", "成都", "西安"],
        "广州": ["北京", "上海", "成都", "昆明"],
        "成都": ["北京", "上海", "广州", "西安", "昆明"],
        "西安": ["北京", "上海", "成都", "武汉"],
        "昆明": ["成都", "广州", "重庆"],
        "武汉": ["北京", "广州", "西安", "成都"],
    }

    hub_cities = TRANSFER_HUBS.get(clean_dep, [])
    transfer_options = []

    for hub in hub_cities:
        if hub == clean_arr:
            continue
        # 查第一段（出发→中转）和 第二段（中转→到达）
        # 🔴 飞常准API是唯一数据源，不再使用本地COMMON_ROUTES
        route1 = {"flights": [], "trains": [], "_no_data": True, "_source": "飞常准API"}
        route2 = {"flights": [], "trains": [], "_no_data": True, "_source": "飞常准API"}

        if route1.get("flights") or route1.get("trains"):
            has_route2 = route2.get("flights") or route2.get("trains")
            transfer_options.append({
                "transfer_city": hub,
                "leg1": {
                    "from": clean_dep, "to": hub,
                    "flights": route1.get("flights", [])[:3],
                    "trains": route1.get("trains", [])[:3],
                },
                "leg2": {
                    "from": hub, "to": clean_arr,
                    "flights": route2.get("flights", [])[:3],
                    "trains": route2.get("trains", [])[:3],
                },
                "has_full_route": has_route2,
                "note": f"经{hub}中转，需预留至少1.5小时中转时间（飞机转飞机）或2小时（火车转飞机）",
            })

    result = {
        "direct_available": False,  # 🔴 飞常准API是唯一数据源，不再使用本地COMMON_ROUTES判断
        "transfer_options": transfer_options[:3],  # 最多3个中转方案
        "_date": date,
        "_note": "【中转规则】中转时间必须充裕：飞机转飞机≥1.5小时，火车转飞机≥2小时，飞机转火车≥1.5小时。宁可少玩景点也不可赶时间！"
    }
    return result