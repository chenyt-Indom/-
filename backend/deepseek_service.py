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
                      poi_data: list, weather_data: list, start_date: str, end_date: str) -> str:
    """构建行程生成提示词，包含POI数据、天气和JSON格式要求"""
    interest_str = "、".join(interests) if interests else "综合体验"
    poi_str = "\n".join([
        f"- {p['name']}（{p.get('type','景点')}，坐标：{p.get('location','')}）"
        for p in poi_data[:15]
    ]) if poi_data else "（请根据常识推荐）"
    weather_str = "\n".join([
        f"  {w['date']}: {w['dayweather']} {w['daytemp']}°C~{w['nighttemp']}°C"
        for w in weather_data[:days]
    ]) if weather_data else "（请根据常识判断）"
    date_info = f"\n【出行日期】{start_date} 至 {end_date}（共{days}天）" if start_date else ""

    return f"""你是一个资深旅行规划师。请根据以下真实数据，生成一份 {days} 天的{dest}行程。

【目的地】{dest}
【天数】{days}天{date_info}
【预算】{budget}
【兴趣】{interest_str}

【高德 POI 真实数据（含坐标）】
{poi_str}

【天气预报】
{weather_str}

请严格按照以下 JSON 格式输出（不要输出其他内容）：
{{
  "destination": "{dest}",
  "days": {days},
  "start_date": "{start_date}",
  "end_date": "{end_date}",
  "weather": [
    {{"date": "日期", "weather": "天气", "temp": "温度", "wind": "风力", "icon": "天气图标emoji"}}
  ],
  "itinerary": [
    {{
      "day": 1,
      "date": "日期",
      "weather": {{"desc": "天气", "temp": "温度", "icon": "emoji"}},
      "morning": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false}},
      "afternoon": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false}},
      "evening": {{"spot": "景点名", "duration": "建议时长", "reason": "推荐理由", "location": "坐标", "need_booking": false}},
      "lunch": "午餐推荐",
      "dinner": "晚餐推荐",
      "transport": "交通建议"
    }}
  ],
  "budget_breakdown": {{"交通": "金额", "住宿": "金额", "餐饮": "金额", "门票": "金额", "其他": "金额"}},
  "tips": ["贴士1", "贴士2", "贴士3"]
}}

要求：
1. 优先使用高德POI真实数据，location坐标必须填写
2. need_booking 标记需要提前预约的景点（如故宫、莫高窟、迪士尼等热门景点设为true）
3. 结合天气预报合理安排室内外活动
4. 上午/下午各安排1-2个景点，晚上安排1个
5. 只输出JSON，不要markdown代码块"""


def build_booking_prompt(dest: str, start_date: str, end_date: str, budget: str, itinerary: list) -> str:
    """构建订票/酒店/门票查询提示词"""
    spots_str = ""
    for day in itinerary:
        for slot in ["morning", "afternoon", "evening"]:
            s = day.get(slot, {})
            if s and s.get("spot"):
                spots_str += f"- Day{day['day']} {slot}: {s['spot']}（坐标：{s.get('location','')}，需预约：{'是' if s.get('need_booking') else '否'}）\n"

    return f"""你是一个旅行服务顾问。请为以下行程查询机票、火车票、酒店和门票推荐信息。

【目的地】{dest}
【日期】{start_date} 至 {end_date}
【预算】{budget}

【行程景点】
{spots_str}

请输出以下 JSON 格式（不要输出其他内容）：
{{
  "flights": [
    {{"type": "去程/返程", "suggest": "推荐航班/车次", "price": "参考价格", "link": "https://flights.ctrip.com/", "note": "说明"}}
  ],
  "hotels": [
    {{"name": "酒店名", "area": "推荐区域", "price": "参考价格/晚", "reason": "推荐理由", "location": "坐标", "link": "https://hotels.ctrip.com/", "note": "说明"}}
  ],
  "tickets": [
    {{"spot": "景点名", "price": "门票价格", "need_booking": true, "booking_days": "提前N天", "platform": "预约平台", "link": "https://www.ctrip.com/", "note": "预约说明", "location": "坐标"}}
  ],
  "booking_tips": ["预约贴士1", "预约贴士2"]
}}

要求：
1. 机票/火车票给出真实航线建议和参考价格
2. 酒店推荐位置方便、性价比高的，给出具体名称和位置坐标
3. 门票中 need_booking=true 的景点必须说明提前几天预约、在哪个平台预约
4. link 字段给出真实可跳转的订购链接（携程/去哪儿/12306等）
5. 只输出JSON，不要markdown代码块"""