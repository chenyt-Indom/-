"""DeepSeek AI 服务：API调用和提示词构建"""
import httpx
from config import DEEPSEEK_KEY, DEEPSEEK_URL


async def call_deepseek(system_prompt: str, user_prompt: str, max_tokens: int = 4000) -> str:
    """调用 DeepSeek API，返回生成的文本内容"""
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            DEEPSEEK_URL,
            headers={
                "Authorization": f"Bearer {DEEPSEEK_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": "deepseek-chat",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": 0.7, "max_tokens": max_tokens,
            },
        )
        resp.raise_for_status()
        data = resp.json()
    return data["choices"][0]["message"]["content"]


# ===================== 辅助函数：格式化各类数据 =====================

def _format_poi_list(poi_data: list) -> str:
    """格式化POI数据为提示词文本"""
    if not poi_data:
        return "（请根据常识推荐）"
    return "\n".join([
        f"- {poi_item['name']}（{poi_item.get('type','景点')}，坐标：{poi_item.get('location','')}，"
        f"评分：{poi_item.get('rating','无')}，商区：{poi_item.get('business_area','')}）"
        for poi_item in poi_data[:20]
    ])


def _format_weather_list(weather_data: list, days: int) -> str:
    """格式化天气数据为提示词文本"""
    if not weather_data:
        return "（请根据常识判断）"
    return "\n".join([
        f"  {weather_day['date']}: {weather_day['dayweather']} "
        f"{weather_day['daytemp']}°C~{weather_day['nighttemp']}°C"
        for weather_day in weather_data[:days + 2]
    ])


def _build_people_info(travelers: int) -> str:
    """构建旅行人数描述"""
    if travelers <= 1:
        return ""
    people_info = f"\n【旅行人数】{travelers}人"
    if travelers <= 2:
        people_info += "（情侣/密友出行，安排浪漫私密体验）"
    elif travelers <= 4:
        people_info += "（家庭/小团体出行，注意协调口味和节奏）"
    elif travelers <= 8:
        people_info += "（中型团体，需考虑分组活动和拼车拼桌）"
    else:
        people_info += "（大型团体，优先安排大巴接送、团餐预订、分批游览）"
    return people_info


def _build_pace_info(pace: int) -> str:
    """构建游玩节奏描述"""
    if pace <= 10:
        pace_desc = "极慢节奏：每天只安排1个核心景点，上午10点后出发，大量自由时间，深度体验为主，适合度假放空"
    elif pace <= 25:
        pace_desc = "慢节奏：每天1-2个景点，上午9:30后出发，每个景点预留充足时间，下午可自由探索"
    elif pace <= 40:
        pace_desc = "偏休闲节奏：每天2个景点，上午9点出发，适当安排休息时间，游览与放松兼顾"
    elif pace <= 55:
        pace_desc = "适中节奏：每天2-3个景点，早上9点出发，合理分配时间，兼顾游览和休息"
    elif pace <= 70:
        pace_desc = "偏紧凑节奏：每天3个景点，早上8:30出发，充分利用白天时间，行程较充实"
    elif pace <= 85:
        pace_desc = "快节奏：每天3-4个景点，早上8点出发，紧密安排行程，适合打卡式旅行"
    else:
        pace_desc = "极快节奏：每天4-5个景点，早上7:30前出发，最大化游览效率，适合特种兵式旅行"
    return f"\n【游玩节奏】{pace_desc}\n【重要】游玩节奏优先于所有其他因素！请严格按照此节奏安排每天行程，人数影响为次要考虑。"


# ===================== 辅助函数：构建交通相关提示词 =====================

def _build_schedule_section(schedule: dict) -> str:
    """构建真实航班/火车班次提示词部分"""
    section = ""
    if not (schedule.get("flights") or schedule.get("trains")):
        return section

    section += "\n【以下是真实可选的航班/火车班次，必须从中选择，不可随意编造！】"
    if schedule.get("flights"):
        section += "\n可选航班："
        for flight in schedule["flights"]:
            section += f"\n  ✈ {flight['num']}：{flight['dep']}出发 → {flight['arr']}到达（{flight['duration']}）"
    if schedule.get("trains"):
        section += "\n可选火车/高铁："
        for train in schedule["trains"]:
            section += f"\n  🚄 {train['num']}：{train['dep']}出发 → {train['arr']}到达（{train['duration']}）"

    section += _get_schedule_match_rules()
    # 无预存数据时的致命警告
    if schedule.get("_no_data"):
        section += ("\n【致命警告-无预存数据】该路线没有预存真实班次数据！"
                    "\n  ① flight_number字段必须留空字符串''，绝对禁止编造任何航班号/车次号！"
                    "\n  ② 只填写交通方式类型（如'飞机'或'高铁'）"
                    "\n  ③ duration只写估算耗时（如'约3小时'）"
                    "\n  ④ 在note中建议用户自行在携程查询实时航班号")
    return section


def _get_schedule_match_rules() -> str:
    """获取班次严格匹配规则文本"""
    return ("\n【强制要求-班次严格匹配】你必须从以上列出的真实班次中选择一个，并且严格使用该班次的全部信息！"
            "\n  ① flight_number字段：必须填写所选班次的航班号/车次号（如CA1515、G1），禁止编造"
            "\n  ② departure_time字段：必须填写所选班次的出发时间（如08:00），与上面列出的时间一致"
            "\n  ③ arrival_time字段：必须填写所选班次的到达时间（如10:05），与上面列出的时间一致"
            "\n  ④ duration字段：必须使用'航班号/车次号 + 耗时'格式（如'G1次 4h29min'或'CA1515 2h10min'），不可只写耗时"
            "\n  ⑤ 以上4个字段必须来自同一个班次，不可交叉混用！如果选择的班次是早上8:00出发，departure_time就必须是8:00，不能改成其他时间"
            "\n  ⑥ 返程如果走相同路线，也必须从以上班次中反向选择合适时间的班次，同样严格匹配"
            "\n  ⑦ 【机场限制-致命警告】只能使用以下真实运营的民用机场，绝对禁止使用南苑、大校场、巫家坝等已关闭/军用机场！"
            "\n     可用机场白名单：北京首都T2/T3、北京大兴、上海虹桥T1/T2、上海浦东T1/T2、广州白云T1/T2/T3、深圳宝安T3、成都双流T1/T2、成都天府T1/T2、杭州萧山T3/T4、西安咸阳T3、武汉天河T3、昆明长水、三亚凤凰、哈尔滨太平、重庆江北、南京禄口、长沙黄花、郑州新郑、天津滨海、沈阳桃仙、福州长乐、合肥新桥、南宁吴圩、贵阳龙洞堡、海口美兰、拉萨贡嘎、乌鲁木齐地窝堡、兰州中川、呼和浩特白塔、银川河东、西宁曹家堡、南昌昌北、济南遥墙、太原武宿、石家庄正定、长春龙嘉、珠海金湾、桂林两江、青岛胶东、大连周水子、厦门高崎、宁波栎社、温州龙湾"
            "\n     如果你填写的机场名不在上述白名单中，就是错误的！必须使用上述白名单中的机场名！")


def _build_transfer_section(transfer_info: dict) -> str:
    """构建中转方案提示词部分"""
    section = ""
    if not transfer_info.get("transfer_options"):
        return section

    section += "\n【中转方案参考】如果无合适直飞航班，可考虑以下中转方案："
    transfer_note = transfer_info.get("_note", "")
    if transfer_note:
        section += f"\n  {transfer_note}"
    for transfer_option in transfer_info["transfer_options"]:
        section += f"\n  方案：经{transfer_option['transfer_city']}中转"
        if transfer_option["leg1"]["flights"]:
            section += f"\n    第一段 {transfer_option['leg1']['from']}→{transfer_option['leg1']['to']}："
            for flight in transfer_option["leg1"]["flights"][:2]:
                section += f"\n      ✈ {flight['num']}：{flight['dep']}→{flight['arr']}（{flight['duration']}）"
        if transfer_option["leg2"]["flights"]:
            section += f"\n    第二段 {transfer_option['leg2']['from']}→{transfer_option['leg2']['to']}："
            for flight in transfer_option["leg2"]["flights"][:2]:
                section += f"\n      ✈ {flight['num']}：{flight['dep']}→{flight['arr']}（{flight['duration']}）"
        section += f"\n    中转提示：{transfer_option['note']}"
    return section


def _build_self_drive_section(departure_city: str, transport_info: dict) -> str:
    """构建自驾出行交通提示词部分"""
    section = f"\n【出行方式】自驾从{departure_city}出发"
    if transport_info:
        self_drive_plan = transport_info.get("self_drive_plan", {})
        section += (f"\n【自驾路线】全程{self_drive_plan.get('total_distance','')}，"
                    f"预计驾驶{self_drive_plan.get('total_duration_min',0)}分钟，"
                    f"当前路况{self_drive_plan.get('traffic','畅通')}")
        if self_drive_plan.get("stopover"):
            stopover_info = self_drive_plan["stopover"]
            section += (f"\n【沿途过夜】{stopover_info.get('suggestion','')}，"
                        f"第一天驾驶{stopover_info.get('day1_drive','')}，"
                        f"第二天驾驶{stopover_info.get('day2_drive','')}")
        section += f"\n【出发建议】{self_drive_plan.get('suggested_departure','')}"
    section += "\n第一天和最后一天需包含出发/返程自驾规划，计算好驾驶时间，不要安排太紧凑，留足休息时间"
    return section


def _build_hub_notes(transport_info: dict) -> str:
    """构建邻近枢纽提示文本"""
    section = ""
    dep_hub = transport_info.get("dep_hub", {})
    dest_hub = transport_info.get("dest_hub", {})
    if dep_hub.get("has_hub"):
        section += f"\n【出发地枢纽】{dep_hub['note']}"
    if dest_hub.get("has_hub"):
        section += f"\n【目的地枢纽】{dest_hub['note']}"
    return section


def _build_station_transit_info(transport_info: dict) -> str:
    """构建前往/离开机场车站的交通信息"""
    section = ""
    if transport_info.get("to_station"):
        to_station_info = transport_info["to_station"]
        section += (f"\n【前往机场/车站】驾车约{to_station_info.get('drive_min',0)}分钟，"
                    f"公交约{to_station_info.get('transit_min',0)}分钟，{to_station_info.get('advice','')}")
    if transport_info.get("from_station"):
        from_station_info = transport_info["from_station"]
        section += (f"\n【到达后交通】从机场/车站到酒店，"
                    f"驾车约{from_station_info.get('drive_min',30)}分钟，"
                    f"公交约{from_station_info.get('transit_min',45)}分钟")
    return section


def _build_public_transport_section(departure_city: str, dest: str, transport_info: dict) -> str:
    """构建公共交通出行提示词部分"""
    section = f"\n【出发城市】{departure_city}"
    if not transport_info:
        return section

    transport_judgment = transport_info.get("transport", {})
    section += f"\n【推荐交通】{transport_judgment.get('mode','')} - {transport_judgment.get('reason','')}"
    section += _build_hub_notes(transport_info)
    section += _build_station_transit_info(transport_info)

    if transport_info.get("flight_query_text"):
        section += f"\n{transport_info['flight_query_text']}"

    # 真实航班/火车班次数据
    schedule = transport_info.get("route_schedule", {})
    section += _build_schedule_section(schedule)

    # 中转方案
    transfer_info = transport_info.get("transfer_info", {})
    section += _build_transfer_section(transfer_info)

    section += f"\n第一天必须包含从{departure_city}出发前往{dest}的交通规划，最后一天必须包含从{dest}返回{departure_city}的交通规划。"
    section += _get_transport_flexible_rules()
    return section


def _get_transport_flexible_rules() -> str:
    """获取出发时间灵活规则文本"""
    return """
【重要-出发时间灵活规则】
1. 出发时间不固定，需根据当天航班/车次时刻表决定，可以是上午、下午、傍晚甚至晚上出发
2. 如果选择飞机：需先查询当天所有直飞航班，选择最合适的时间段（考虑票价、时长、到达时间）
3. 如果选择火车：需查询当天高铁/动车班次，优先选择耗时短、到达时间合理的车次
4. 到达时间规划：如果下午到达，当天可安排1个晚间景点；如果傍晚/晚上到达，当天仅安排入住酒店
5. 跨天到达处理：如果航班/火车在次日凌晨到达，需在departure_transport中标注"次日XX:XX到达"，并规划好到达后的交通和住宿
6. 必须计算从机场/车站到酒店的交通方式、时间和费用（打车/地铁/机场大巴），在departure_transport的note中说明
7. 预留充足缓冲：飞机起飞前2小时到达机场，火车发车前1小时到达车站，加上从住处到机场/车站的时间
8. 返程同理：最后一天需根据返程航班/车次时间倒推最晚出发时间，确保不误机/误车
9. 如果出发当天没有合适的航班/车次，可考虑提前一天出发，并在第一天安排轻松的活动"""
        + "\n【跨天到达示例】如选择晚上20:00航班，飞行2小时，22:00到达机场，打车30分钟到酒店，则第一天行程为：上午准备出发→下午前往机场→晚上航班→到达后入住酒店，不安排游览。"


# ===================== 辅助函数：JSON Schema 与要求 =====================

def _get_trip_json_schema(dest: str, days: int, start_date: str, end_date: str) -> str:
    """返回行程JSON schema模板"""
    return f"""{{
  "destination": "{dest}",
  "days": {days},
  "start_date": "{start_date}",
  "end_date": "{end_date}",
  "departure_transport": {{
    "type": "出发交通方式（高铁/飞机/自驾/大巴）",
    "flight_number": "航班号或车次号（如CA1515、G1等，必须从提供的真实班次中选择，自驾则为空字符串）",
    "departure_time": "建议出发时间（如8:00，留足缓冲，也可以是14:00、20:00等任意时刻）",
    "station": "出发站/机场名称（必须使用真实民用机场名称，禁止使用军用/已关闭机场）",
    "arrival_time": "预计到达目的地时间（跨天到达标注"次日XX:XX"）",
    "duration": "交通耗时（必须使用'航班号/车次号+耗时'格式，如'G1次 4h29min'或'CA1515 2h10min'）",
    "cost": "预估费用",
    "cross_day": false,
    "station_to_hotel": "从机场/车站到酒店的方式和时间（如：打车30分钟约50元，或地铁X号线转X号线约45分钟）",
    "note": "注意事项（如提前多久到站、中转信息、是否有合适的航班/车次）",
    "transfers": [
      {{
        "step": 1,
        "type": "交通工具类型（飞机/高铁/大巴/出租车/地铁）",
        "flight_number": "中转段航班号/车次号（如CA1234，如无则留空）",
        "from_station": "出发站/机场",
        "to_station": "到达站/机场",
        "departure_time": "中转段出发时间",
        "arrival_time": "中转段到达时间",
        "duration": "中转段耗时",
        "transfer_time": "中转等待时间（如'1小时30分钟'），必须≥45分钟（飞机）或≥30分钟（火车）",
        "note": "中转说明"
      }}
    ],
    "vehicle_image": "交通工具配图关键词（如'airplane','high_speed_rail','bus'等）"
  }},
  "return_transport": {{
    "type": "返程交通方式",
    "flight_number": "航班号或车次号（必须从提供的真实班次中选择，自驾则为空字符串）",
    "departure_time": "建议出发时间（根据最后一天游玩安排倒推）",
    "station": "出发站/机场名称（必须使用真实民用机场名称）",
    "arrival_time": "预计到达时间（跨天到达标注"次日XX:XX"）",
    "duration": "交通耗时（必须使用'航班号/车次号+耗时'格式）",
    "cost": "预估费用",
    "cross_day": false,
    "station_to_hotel": "从酒店到机场/车站的方式和时间",
    "note": "注意事项",
    "transfers": [],
    "vehicle_image": "交通工具配图关键词"
  }},
  "weather": [
    {{"date": "日期", "weather": "天气", "temp": "温度", "wind": "风力", "icon": "天气图标emoji"}}
  ],
  "itinerary": [
    {{
      "day": 1,
      "date": "日期",
      "weather": {{"desc": "天气", "temp": "温度", "icon": "emoji"}},
      "morning": {{"spot": "景点名", "time_slot": "游玩时间段（如8:00-10:30）", "duration": "建议时长（如2.5小时）", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "afternoon": {{"spot": "景点名", "time_slot": "游玩时间段（如13:00-15:30）", "duration": "建议时长（如2.5小时）", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "evening": {{"spot": "景点名", "time_slot": "游玩时间段（如18:30-20:30）", "duration": "建议时长（如2小时）", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "lunch": "午餐推荐",
      "dinner": "晚餐推荐",
      "transport": "交通建议"
    }}
  ],
  "budget_breakdown": {{"交通": "金额", "住宿": "金额", "餐饮": "金额", "门票": "金额", "其他": "金额"}},
  "tips": ["贴士1", "贴士2", "贴士3"]
}}"""


def _get_trip_requirements(days: int) -> str:
    """返回行程生成通用要求文本"""
    return f"""要求：
1. 【热门景点优先】优先选择评分高（≥4.0）的著名景点，确保行程中至少80%的景点来自高评分榜单。POI列表已按评分降序排列，排在前面的优先选择
2. 优先使用高德POI真实数据，location坐标必须填写
3. need_booking 标记需要提前预约的景点（如故宫、莫高窟、迪士尼等热门景点设为true）
4. 结合天气预报合理安排室内外活动
5. 上午/下午各安排1个景点，晚上安排1个
6. 【最高优先级-时间规划】每个景点必须填写 time_slot 字段，给出当天在当地的具体游玩时间段（如"9:00-11:30"），必须严格遵循以下规则：
   a) 上午时段：最早8:00开始，最晚12:00结束，上午景点游玩时间建议2-3小时
   b) 下午时段：最早13:00开始，最晚17:30结束，下午景点游玩时间建议2-3.5小时
   c) 晚上时段：最早18:00开始，最晚21:30结束，晚上景点游玩时间建议1.5-2.5小时
   d) 午餐时间：12:00-13:00为午餐和休息时间，不可安排景点游玩
   e) 晚餐时间：17:30-18:30为晚餐时间，不可安排景点游玩
   f) 景点间交通损耗：相邻景点之间必须预留至少30-60分钟交通和休息时间（根据距离远近），上午景点的结束时间与下午景点的开始时间间隔至少1小时，下午景点的结束时间与晚上景点的开始时间间隔至少1小时
   g) 大景点时间：大型景区（如故宫、黄山、九寨沟、张家界等）上午游玩时间建议3-4小时，下午建议3-4小时
   h) 小景点时间：博物馆、寺庙、公园等小景点建议1.5-2.5小时
   i) 节奏适配：极慢/慢节奏需将游玩时间增加30%，并增加景点间休息时间至60-90分钟；快/极快节奏可适当缩短游玩时间但不可低于1小时，景点间间隔至少30分钟
   j) 所有时间使用24小时制，跨天使用"次日XX:XX"格式
7. 【最高优先级】景点名绝对不能重复！整个{days}天行程中，每个独立景点名只能出现一次，不允许任何例外。即使同一大型景区，不同天也必须用不同子区域命名（如"张家界(金鞭溪-袁家界)"和"张家界(天子山-杨家界)"），确保景点名不重复，避免走回头路
8. 【交通便利性】安排景点顺序时需考虑地理位置和商区分布，将同一商区/相邻区域的景点安排在同一天，减少不必要的交通时间。每天景点之间距离不宜过远
9. 对于大型景区（如张家界、黄山、九寨沟、故宫、颐和园等），每天安排不同区域/入口，按地理位置顺序游览，不走回头路：
   - route_detail 字段中描述当天的具体游览路线（如"南门进→金鞭溪→袁家界→百龙天梯→东门出"）
   - recommended_routes 字段中提供2-3条该景点的经典游览路线方案供用户参考（每条路线一句话描述，如"经典一日游：南门进→金鞭溪→袁家界→天子山→东门出（约6小时）"）
   - 普通景点 recommended_routes 设为空数组 []
10. 【出发/返程-最高优先级】departure_transport和return_transport必须认真填写。flight_number必须从提供的真实航班/车次班次中选择，不可随意编造！duration必须使用'航班号/车次号 + 耗时'格式（如'G1次 4h29min'、'CA1515 2h10min'）。出发时间不能太紧凑，必须留足缓冲时间。飞机需提前2小时到机场，火车需提前1小时到站。出发时间可以是任意时刻（上午/下午/晚上），根据实际航班/车次时刻表决定。如果下午到达，第一天可安排1个晚间景点；如果晚上到达，仅安排入住酒店。跨天到达必须标注"次日XX:XX"并设置cross_day=true。station_to_hotel字段必须填写从机场/车站到酒店的具体交通方式和时间。
11. 【中转/换乘-最高优先级】如果出发城市到目的城市没有直飞航班，或需要中途换乘，必须填写transfers数组。中转规则：
   a) 飞机中转：中转等待时间≥1.5小时（国内转国内），必须明确写出第一段航班号→中转机场→第二段航班号的变化
   b) 火车中转：中转等待时间≥30分钟，必须明确写出第一段车次→中转站→第二段车次的变化
   c) 飞机转火车/火车转飞机：中转等待时间≥2小时，考虑从机场到火车站的交通时间
   d) 每个中转段必须填写：step序号、type、flight_number、from_station、to_station、departure_time、arrival_time、duration、transfer_time
   e) 宁可少安排景点也不能赶时间！中转时间必须充裕，如有跨天中转必须标注
   f) vehicle_image字段：填写交通工具关键词（直飞填"airplane"，高铁填"high_speed_rail"，自驾填"car"，大巴填"bus"），用于前端显示交通工具配图
12. 【时间格式】所有时间必须使用24小时制（如9:00、14:30），绝对禁止出现>23:59的时间（如26:00）。如果活动跨天，请使用"次日8:00"等格式表示。每天上午/下午/晚上的景点安排间隔至少1小时，避免时间冲突
13. 只输出JSON，不要markdown代码块"""


# ===================== 主函数 =====================

def build_trip_prompt(dest: str, days: int, budget: str, interests: list,
                      poi_data: list, weather_data: list, start_date: str, end_date: str,
                      travelers: int = 1, budget_type: str = "total", pace: int = 50,
                      is_self_drive: bool = False, departure_city: str = "",
                      transport_info: dict = None) -> str:
    """构建行程生成提示词，包含POI数据、天气、人数、预算类型、节奏、自驾和JSON格式要求"""
    interest_str = "、".join(interests) if interests else "综合体验"
    poi_str = _format_poi_list(poi_data)
    weather_str = _format_weather_list(weather_data, days)
    date_info = f"\n【出行日期】{start_date} 至 {end_date}（共{days}天）" if start_date else ""

    # 构建交通信息
    transport_section = ""
    if departure_city:
        if is_self_drive:
            transport_section = _build_self_drive_section(departure_city, transport_info)
        else:
            transport_section = _build_public_transport_section(departure_city, dest, transport_info)

    people_info = _build_people_info(travelers)

    # 预算信息
    budget_info = f"\n【预算】{budget}"
    if budget_type == "aa":
        budget_info += (f"（此为AA制每人预算，实际总预算=每人预算×{travelers}人"
                        f"={budget}×{travelers}，请以总预算为准规划但不在输出中显示计算过程）")

    pace_info = _build_pace_info(pace)

    return f"""你是一个资深旅行规划师。请根据以下真实数据，生成一份 {days} 天的{dest}行程。

【目的地】{dest}
【天数】{days}天{date_info}{people_info}{budget_info}{pace_info}{transport_section}
【兴趣】{interest_str}

【高德 POI 真实数据（按评分降序排列，评分越高越热门）】
{poi_str}

【天气预报】
{weather_str}

请严格按照以下 JSON 格式输出（不要输出其他内容）：
{_get_trip_json_schema(dest, days, start_date, end_date)}

{_get_trip_requirements(days)}"""


def build_booking_prompt(dest: str, start_date: str, end_date: str, budget: str,
                         itinerary: list, departure_city: str = "",
                         transport_info: dict = None) -> str:
    """构建订票/酒店/门票查询提示词，包含出发城市、交通判断和飞常准数据"""
    spots_str = ""
    for day in itinerary:
        for slot_name in ["morning", "afternoon", "evening"]:
            slot_item = day.get(slot_name, {})
            if slot_item and slot_item.get("spot"):
                spots_str += (f"- Day{day['day']} {slot_name}: {slot_item['spot']}"
                              f"（坐标：{slot_item.get('location','')}，"
                              f"需预约：{'是' if slot_item.get('need_booking') else '否'}）\n")

    dep_info = f"\n【出发城市】{departure_city}" if departure_city else ""
    trans_info = ""
    flight_info = ""
    if transport_info:
        trans_info = f"""
【交通判断】{transport_info.get('mode', '')} - {transport_info.get('reason', '')}
【城市代码】出发：{transport_info.get('dep_iata', '')}，到达：{transport_info.get('arr_iata', '')}"""
        if transport_info.get("need_flight"):
            flight_info = f"""
飞常准航班查询参数：
- 出发城市：{departure_city}（{transport_info.get('dep_iata', '')}）
- 到达城市：{dest}（{transport_info.get('arr_iata', '')}）
- 出发日期：{start_date}
- 返程日期：{end_date}
航班link：https://flights.ctrip.com/booking/{departure_city}-{dest}-day-1.html
火车票link：https://trains.ctrip.com/booking/{departure_city}-{dest}-day-1.html"""
    else:
        flight_info = f"""
机票link：https://flights.ctrip.com/booking/{departure_city}-{dest}-day-1.html
火车票link：https://trains.ctrip.com/booking/{departure_city}-{dest}-day-1.html"""

    return f"""你是一个旅行服务顾问。请为以下行程查询机票、火车票、酒店和门票推荐信息。

【目的地】{dest}{dep_info}
【日期】{start_date} 至 {end_date}
【预算】{budget}
{trans_info}
{flight_info}

【行程景点】
{spots_str}

请输出以下 JSON 格式（不要输出其他内容）：
{{
  "flights": [
    {{"type": "去程/返程", "suggest": "推荐航班/车次", "price": "参考价格", "link": "航班/火车票链接", "note": "说明"}}
  ],
  "hotels": [
    {{"name": "酒店名", "area": "推荐区域", "price": "参考价格/晚", "reason": "推荐理由", "location": "坐标", "link": "https://hotels.ctrip.com/", "note": "说明", "stay_days": "Day1-Day3"}}
  ],
  "hotel_changes": [
    {{"from_hotel": "原酒店", "to_hotel": "新酒店", "change_day": "第几天换", "reason": "换酒店原因（景点集中在不同区域等）", "new_area": "新区域", "price": "参考价格/晚", "location": "坐标", "link": "https://hotels.ctrip.com/"}}
  ],
  "tickets": [
    {{"spot": "景点名", "price": "门票价格", "need_booking": true, "booking_days": "提前N天", "platform": "预约平台", "link": "https://www.ctrip.com/", "note": "预约说明", "location": "坐标"}}
  ],
  "transport_mode": "推荐交通工具（高铁/动车/飞机/自驾等）",
  "booking_tips": ["预约贴士1", "预约贴士2"]
}}

要求：
1. 根据距离判断交通工具：300km以内推荐高铁/动车，300-800km高铁优先，800km以上推荐飞机
2. flights中机票link必须使用上述格式，填入真实出发城市和目的地
3. 机票/火车票给出真实航线建议和参考价格
4. transport_mode字段：说明推荐的交通工具及理由
5. 酒店推荐位置方便、性价比高的，给出具体名称和位置坐标
6. 门票中 need_booking=true 的景点必须说明提前几天预约
7. 【换酒店推荐】分析行程中景点的地理分布，如果不同天的景点集中在不同区域（如Day1-3在城东，Day4-5在城西），建议中途换酒店减少通勤时间，在 hotel_changes 中列出换酒店建议
8. hotels 中 stay_days 字段注明该酒店适合入住的日期范围
9. 只输出JSON，不要markdown代码块"""


def _build_regenerate_transport_section(departure_city: str, dest: str,
                                         is_self_drive: bool, transport_info: dict) -> str:
    """构建重新生成行程时的交通提示词部分"""
    if is_self_drive:
        return (f"\n【出行方式】自驾从{departure_city}出发，"
                "需计算驾驶时间，长途需安排过夜停留")

    section = f"\n【出发城市】{departure_city}，公共交通出行"
    if transport_info:
        transport_judgment = transport_info.get("transport", {})
        section += f"\n【交通建议】{transport_judgment.get('mode','')} - {transport_judgment.get('reason','')}"
        section += _build_hub_notes(transport_info)

    section += f"""
【交通选择原则】根据距离选择：≤5km步行，≤30km公交/地铁/打车，≤100km地铁/城际，≤300km高铁/动车，≤800km高铁优先，>800km飞机/高铁
第一天必须包含从{departure_city}出发前往{dest}的交通规划，最后一天必须包含从{dest}返回{departure_city}的交通规划。
【出发时间灵活】出发时间不固定，根据航班/车次时刻表决定，可以是上午、下午、傍晚甚至晚上。下午到达可安排晚间景点，晚上到达仅入住酒店。跨天到达需标注"次日XX:XX"并规划好到达后交通。需预留充足缓冲时间（飞机提前2小时到机场，火车提前1小时到站）。"""

    if transport_info:
        schedule = transport_info.get("route_schedule", {})
        section += _build_schedule_section(schedule)
        # 中转方案
        transfer_info = transport_info.get("transfer_info", {})
        if transfer_info.get("transfer_options"):
            section += "\n【中转方案参考】如果无合适直飞，可考虑以下中转："
            for transfer_option in transfer_info["transfer_options"]:
                section += f"\n  经{transfer_option['transfer_city']}中转：{transfer_option['note']}"
    return section


def _build_old_itinerary_summary(old_itinerary: list) -> str:
    """构建原行程概览文本"""
    old_summary = ""
    for day in old_itinerary:
        spots = []
        for slot_name in ["morning", "afternoon", "evening"]:
            slot_item = day.get(slot_name, {})
            if slot_item and slot_item.get("spot"):
                spots.append(f"{slot_name}: {slot_item['spot']}")
        old_summary += f"Day{day['day']}({day.get('date','')}): {', '.join(spots)}\n"
    return old_summary


def _get_regenerate_json_schema(dest: str, days: int, start_date: str, end_date: str) -> str:
    """返回重新生成行程的JSON schema模板"""
    return f"""{{
  "destination": "{dest}",
  "days": {days},
  "start_date": "{start_date}",
  "end_date": "{end_date}",
  "departure_transport": {{"type": "", "flight_number": "", "departure_time": "", "station": "", "arrival_time": "", "duration": "", "cost": "", "note": "", "transfers": [], "vehicle_image": ""}},
  "return_transport": {{"type": "", "flight_number": "", "departure_time": "", "station": "", "arrival_time": "", "duration": "", "cost": "", "note": "", "transfers": [], "vehicle_image": ""}},
  "itinerary": [
    {{
      "day": 1, "date": "日期",
      "weather": {{"desc": "天气", "temp": "温度", "icon": "emoji"}},
      "morning": {{"spot": "景点名", "time_slot": "游玩时间段（如8:00-10:30）", "duration": "建议时长（如2.5小时）", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "afternoon": {{"spot": "景点名", "time_slot": "游玩时间段（如13:00-15:30）", "duration": "建议时长（如2.5小时）", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "evening": {{"spot": "景点名", "time_slot": "游玩时间段（如18:30-20:30）", "duration": "建议时长（如2小时）", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "lunch": "午餐推荐", "dinner": "晚餐推荐", "transport": "交通建议"
    }}
  ],
  "budget_breakdown": {{"交通": "金额", "住宿": "金额", "餐饮": "金额", "门票": "金额", "其他": "金额"}},
  "tips": ["贴士1", "贴士2", "贴士3"]
}}"""


def _get_regenerate_requirements() -> str:
    """返回重新生成行程的通用要求文本"""
    return """要求：
1. 【最高优先级-用户需求】必须重点参考用户的新需求，在实际可行的情况下务必满足用户的想法。如果用户要求调整出行方式、游览顺序、增减景点、换酒店等，必须严格遵循
2. 结合天气预报合理安排室内外活动，雨天优先安排室内景点
3. 景点名绝对不能重复，同一商区/相邻区域景点安排在同一天，减少交通时间
4. 出发/返程时间不能太紧凑，必须留足缓冲。飞机需提前2小时到机场，火车需提前1小时到站
5. 【时间安排-最高优先级】每个景点必须填写 time_slot 字段（如"9:00-11:30"），严格遵循：上午8:00-12:00，下午13:00-17:30，晚上18:00-21:30；午餐12:00-13:00和晚餐17:30-18:30不可安排景点；景点间预留至少30-60分钟交通损耗；大景点3-4小时，小景点1.5-2.5小时；节奏慢则游玩时间+30%，节奏快可缩短但≥1小时。上午结束与下午开始间隔≥1小时，下午结束与晚上开始间隔≥1小时
6. 所有时间使用24小时制，禁止>23:59的时间（如26:00），跨天活动使用"次日XX:XX"格式
7. 公共交通出行时，根据距离选择合适交通工具：短距离步行/公交，中距离地铁/高铁，长距离飞机
8. 【中转/换乘】如果无直飞航班需中转，填写transfers数组，中转等待时间必须充裕（飞机≥1.5小时，火车≥30分钟，跨类型≥2小时），列明班次编号变化，宁可少玩景点也不赶时间
9. 只输出JSON，不要markdown代码块"""


def build_regenerate_prompt(dest: str, days: int, user_input: str, old_itinerary: list,
                            weather_data: list, start_date: str, end_date: str,
                            is_self_drive: bool, departure_city: str,
                            transport_info: dict = None) -> str:
    """构建重新生成计划的提示词，重点参考用户输入的新需求"""
    transport_info = transport_info or {}
    old_summary = _build_old_itinerary_summary(old_itinerary)

    weather_str = _format_weather_list(weather_data, days)

    transport_mode = "自驾" if is_self_drive else "公共交通"
    transport_section = _build_regenerate_transport_section(
        departure_city, dest, is_self_drive, transport_info)

    return f"""你是一个资深旅行规划师。用户查看已有行程后提出了新的需求，请根据新需求重新制定计划。

【目的地】{dest}
【天数】{days}天
【出行日期】{start_date} 至 {end_date}
【出行方式】{transport_mode}{transport_section}

【用户的新需求】（这是最重要的参考，必须优先满足！）
{user_input}

【原行程概览】
{old_summary}

【天气预报】
{weather_str}

请严格按照以下 JSON 格式输出（不要输出其他内容）：
{_get_regenerate_json_schema(dest, days, start_date, end_date)}

{_get_regenerate_requirements()}"""