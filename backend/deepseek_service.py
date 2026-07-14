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
    return resp.json()["choices"][0]["message"]["content"]


def build_trip_prompt(dest: str, days: int, budget: str, interests: list,
                      poi_data: list, weather_data: list, start_date: str, end_date: str,
                      travelers: int = 1, budget_type: str = "total", pace: int = 50,
                      is_self_drive: bool = False, departure_city: str = "",
                      transport_info: dict = None) -> str:
    """构建行程生成提示词，包含POI数据、天气、人数、预算类型、节奏、自驾和JSON格式要求"""
    interest_str = "、".join(interests) if interests else "综合体验"
    poi_str = "\n".join([
        f"- {p['name']}（{p.get('type','景点')}，坐标：{p.get('location','')}，评分：{p.get('rating','无')}，商区：{p.get('business_area','')}）"
        for p in poi_data[:20]
    ]) if poi_data else "（请根据常识推荐）"
    weather_str = "\n".join([
        f"  {w['date']}: {w['dayweather']} {w['daytemp']}°C~{w['nighttemp']}°C"
        for w in weather_data[:days+2]  # 多取2天天气用于出发/返程
    ]) if weather_data else "（请根据常识判断）"
    date_info = f"\n【出行日期】{start_date} 至 {end_date}（共{days}天）" if start_date else ""

    # 出发/返程交通信息
    transport_section = ""
    if departure_city:
        if is_self_drive:
            transport_section = f"\n【出行方式】自驾从{departure_city}出发"
            if transport_info:
                sd = transport_info.get("self_drive_plan", {})
                transport_section += f"\n【自驾路线】全程{sd.get('total_distance','')}，预计驾驶{sd.get('total_duration_min',0)}分钟，当前路况{sd.get('traffic','畅通')}"
                if sd.get("stopover"):
                    so = sd["stopover"]
                    transport_section += f"\n【沿途过夜】{so.get('suggestion','')}，第一天驾驶{so.get('day1_drive','')}，第二天驾驶{so.get('day2_drive','')}"
                transport_section += f"\n【出发建议】{sd.get('suggested_departure','')}"
            transport_section += "\n第一天和最后一天需包含出发/返程自驾规划，计算好驾驶时间，不要安排太紧凑，留足休息时间"
        else:
            transport_section = f"\n【出发城市】{departure_city}"
            if transport_info:
                ti = transport_info.get("transport", {})
                transport_section += f"\n【推荐交通】{ti.get('mode','')} - {ti.get('reason','')}"
                if transport_info.get("to_station"):
                    ts = transport_info["to_station"]
                    transport_section += f"\n【前往机场/车站】驾车约{ts.get('drive_min',0)}分钟，公交约{ts.get('transit_min',0)}分钟，{ts.get('advice','')}"
            transport_section += "\n第一天必须包含从{departure_city}出发前往{dest}的交通规划，最后一天必须包含从{dest}返回{departure_city}的交通规划。出发时间不能太紧凑，必须留足前往机场/车站的时间（飞机至少提前2小时，火车至少提前1小时）"

    # 人数描述
    people_info = ""
    if travelers > 1:
        people_info = f"\n【旅行人数】{travelers}人"
        if travelers <= 2:
            people_info += "（情侣/密友出行，安排浪漫私密体验）"
        elif travelers <= 4:
            people_info += "（家庭/小团体出行，注意协调口味和节奏）"
        elif travelers <= 8:
            people_info += "（中型团体，需考虑分组活动和拼车拼桌）"
        else:
            people_info += "（大型团体，优先安排大巴接送、团餐预订、分批游览）"

    # 预算类型
    budget_info = f"\n【预算】{budget}"
    if budget_type == "aa":
        budget_info += f"（此为AA制每人预算，实际总预算=每人预算×{travelers}人={budget}×{travelers}，请以总预算为准规划但不在输出中显示计算过程）"

    # 节奏描述（连续值 0-100）
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
    pace_info = f"\n【游玩节奏】{pace_desc}"
    pace_info += "\n【重要】游玩节奏优先于所有其他因素！请严格按照此节奏安排每天行程，人数影响为次要考虑。"

    return f"""你是一个资深旅行规划师。请根据以下真实数据，生成一份 {days} 天的{dest}行程。

【目的地】{dest}
【天数】{days}天{date_info}{people_info}{budget_info}{pace_info}{transport_section}
【兴趣】{interest_str}

【高德 POI 真实数据（按评分降序排列，评分越高越热门）】
{poi_str}

【天气预报】
{weather_str}

请严格按照以下 JSON 格式输出（不要输出其他内容）：
{{
  "destination": "{dest}",
  "days": {days},
  "start_date": "{start_date}",
  "end_date": "{end_date}",
  "departure_transport": {{
    "type": "出发交通方式（高铁/飞机/自驾/大巴）",
    "departure_time": "建议出发时间（如8:00，留足缓冲）",
    "station": "出发站/机场名称",
    "arrival_time": "预计到达目的地时间",
    "duration": "交通耗时",
    "cost": "预估费用",
    "note": "注意事项（如提前多久到站、中转信息）"
  }},
  "return_transport": {{
    "type": "返程交通方式",
    "departure_time": "建议出发时间",
    "station": "出发站/机场名称",
    "arrival_time": "预计到达时间",
    "duration": "交通耗时",
    "cost": "预估费用",
    "note": "注意事项"
  }},
  "weather": [
    {{"date": "日期", "weather": "天气", "temp": "温度", "wind": "风力", "icon": "天气图标emoji"}}
  ],
  "itinerary": [
    {{
      "day": 1,
      "date": "日期",
      "weather": {{"desc": "天气", "temp": "温度", "icon": "emoji"}},
      "morning": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "afternoon": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "evening": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "lunch": "午餐推荐",
      "dinner": "晚餐推荐",
      "transport": "交通建议"
    }}
  ],
  "budget_breakdown": {{"交通": "金额", "住宿": "金额", "餐饮": "金额", "门票": "金额", "其他": "金额"}},
  "tips": ["贴士1", "贴士2", "贴士3"]
}}

要求：
1. 【热门景点优先】优先选择评分高（≥4.0）的著名景点，确保行程中至少80%的景点来自高评分榜单。POI列表已按评分降序排列，排在前面的优先选择
2. 优先使用高德POI真实数据，location坐标必须填写
3. need_booking 标记需要提前预约的景点（如故宫、莫高窟、迪士尼等热门景点设为true）
4. 结合天气预报合理安排室内外活动
5. 上午/下午各安排1-2个景点，晚上安排1个
6. 【最高优先级】景点名绝对不能重复！整个{days}天行程中，每个独立景点名只能出现一次，不允许任何例外。即使同一大型景区，不同天也必须用不同子区域命名（如"张家界(金鞭溪-袁家界)"和"张家界(天子山-杨家界)"），确保景点名不重复，避免走回头路
7. 【交通便利性】安排景点顺序时需考虑地理位置和商区分布，将同一商区/相邻区域的景点安排在同一天，减少不必要的交通时间。每天景点之间距离不宜过远
8. 对于大型景区（如张家界、黄山、九寨沟、故宫、颐和园等），每天安排不同区域/入口，按地理位置顺序游览，不走回头路：
   - route_detail 字段中描述当天的具体游览路线（如"南门进→金鞭溪→袁家界→百龙天梯→东门出"）
   - recommended_routes 字段中提供2-3条该景点的经典游览路线方案供用户参考（每条路线一句话描述，如"经典一日游：南门进→金鞭溪→袁家界→天子山→东门出（约6小时）"）
   - 普通景点 recommended_routes 设为空数组 []
9. 【出发/返程】departure_transport和return_transport必须认真填写，出发时间不能太紧凑，必须留足缓冲时间。飞机需提前2小时到机场，火车需提前1小时到站，自驾需预留堵车时间
10. 【时间格式】所有时间必须使用24小时制（如9:00、14:30），绝对禁止出现>23:59的时间（如26:00）。如果活动跨天，请使用"次日8:00"等格式表示。每天上午/下午/晚上的景点安排间隔至少1小时，避免时间冲突
11. 只输出JSON，不要markdown代码块"""


def build_booking_prompt(dest: str, start_date: str, end_date: str, budget: str,
                         itinerary: list, departure_city: str = "",
                         transport_info: dict = None) -> str:
    """构建订票/酒店/门票查询提示词，包含出发城市、交通判断和飞常准数据"""
    spots_str = ""
    for day in itinerary:
        for slot in ["morning", "afternoon", "evening"]:
            s = day.get(slot, {})
            if s and s.get("spot"):
                spots_str += f"- Day{day['day']} {slot}: {s['spot']}（坐标：{s.get('location','')}，需预约：{'是' if s.get('need_booking') else '否'}）\n"

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


def build_regenerate_prompt(dest: str, days: int, user_input: str, old_itinerary: list,
                            weather_data: list, start_date: str, end_date: str,
                            is_self_drive: bool, departure_city: str) -> str:
    """构建重新生成计划的提示词，重点参考用户输入的新需求"""
    old_summary = ""
    for day in old_itinerary:
        spots = []
        for slot in ["morning", "afternoon", "evening"]:
            s = day.get(slot, {})
            if s and s.get("spot"):
                spots.append(f"{slot}: {s['spot']}")
        old_summary += f"Day{day['day']}({day.get('date','')}): {', '.join(spots)}\n"

    weather_str = "\n".join([
        f"  {w['date']}: {w['dayweather']} {w['daytemp']}°C~{w['nighttemp']}°C"
        for w in (weather_data or [])[:days+2]
    ]) if weather_data else "（请根据常识判断）"

    transport_mode = "自驾" if is_self_drive else "公共交通"

    return f"""你是一个资深旅行规划师。用户查看已有行程后提出了新的需求，请根据新需求重新制定计划。

【目的地】{dest}
【天数】{days}天
【出行日期】{start_date} 至 {end_date}
【出行方式】{transport_mode}
【出发城市】{departure_city}

【用户的新需求】（这是最重要的参考，必须优先满足！）
{user_input}

【原行程概览】
{old_summary}

【天气预报】
{weather_str}

请严格按照以下 JSON 格式输出（不要输出其他内容）：
{{
  "destination": "{dest}",
  "days": {days},
  "start_date": "{start_date}",
  "end_date": "{end_date}",
  "departure_transport": {{"type": "", "departure_time": "", "station": "", "arrival_time": "", "duration": "", "cost": "", "note": ""}},
  "return_transport": {{"type": "", "departure_time": "", "station": "", "arrival_time": "", "duration": "", "cost": "", "note": ""}},
  "itinerary": [
    {{
      "day": 1, "date": "日期",
      "weather": {{"desc": "天气", "temp": "温度", "icon": "emoji"}},
      "morning": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "afternoon": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "evening": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false, "route_detail": "", "recommended_routes": []}},
      "lunch": "午餐推荐", "dinner": "晚餐推荐", "transport": "交通建议"
    }}
  ],
  "budget_breakdown": {{"交通": "金额", "住宿": "金额", "餐饮": "金额", "门票": "金额", "其他": "金额"}},
  "tips": ["贴士1", "贴士2", "贴士3"]
}}

要求：
1. 【最高优先级-用户需求】必须重点参考用户的新需求，在实际可行的情况下务必满足用户的想法。如果用户要求调整出行方式、游览顺序、增减景点、换酒店等，必须严格遵循
2. 结合天气预报合理安排室内外活动
3. 景点名不能重复，同一商区景点安排在同一天
4. 出发/返程时间不能太紧凑，必须留足缓冲
5. 所有时间使用24小时制，禁止>23:59的时间，跨天使用"次日XX:XX"格式
6. 只输出JSON，不要markdown代码块"""