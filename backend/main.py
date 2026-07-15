"""行旅白 AI 旅行规划 - FastAPI 后端"""
import os
import json
import httpx
import asyncio
import datetime
from fastapi import FastAPI, Request
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from models import TripRequest
from config import AMAP_KEY, DEEPSEEK_KEY, VARIFLIGHT_KEY, AMAP_REGEO_URL
from amap_service import amap_poi_search, amap_weather, amap_geocode, fill_coordinates
from deepseek_service import call_deepseek, build_trip_prompt, build_booking_prompt, build_regenerate_prompt, build_retry_prompt
from image_service import fill_images, fill_booking_images, resolve_spot_image, resolve_hotel_image
from image_search_service import search_images
from feichangzhun_service import judge_transport, search_flights, build_flight_query_text, get_route_schedule, get_nearest_hub, get_transfer_routes, sanitize_airport_name, is_airport_valid
from weather_detail_service import get_hourly_weather, check_weather_alerts, get_realtime_weather
from china_weather_service import get_observation, get_air_quality, get_weather_chat
from route_service import get_route_plan, calculate_self_drive_plan, calculate_transit_to_station, get_route_time, calculate_station_to_hotel

# 每日机场信息刷新任务
async def _daily_airport_refresh():
    """每天0时刷新全国在运营机场信息，确保机场数据无误"""
    while True:
        now = datetime.datetime.now()
        next_midnight = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        sleep_seconds = max(1, (next_midnight - now).total_seconds())
        await asyncio.sleep(sleep_seconds)
        try:
            from feichangzhun_service import VALID_AIRPORTS, DECOMMISSIONED_AIRPORTS, is_airport_valid
            print(f"[机场刷新] {datetime.datetime.now().isoformat()} - 开始每日机场信息校验")
            valid_count = sum(1 for a in VALID_AIRPORTS if is_airport_valid(a))
            print(f"[机场刷新] 白名单机场 {len(VALID_AIRPORTS)} 个，校验通过 {valid_count} 个，黑名单 {len(DECOMMISSIONED_AIRPORTS)} 个")
        except Exception as e:
            print(f"[机场刷新] 校验失败: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_daily_airport_refresh())
    yield
    task.cancel()

app = FastAPI(title="行旅白 AI 旅行规划", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/app", StaticFiles(directory=_static_dir, html=True), name="static")

@app.get("/api/health")
async def health_check():
    """健康检查：返回API密钥配置状态"""
    return {"status": "ok", "amap_key": bool(AMAP_KEY), "deepseek_key": bool(DEEPSEEK_KEY), "variflight_key": bool(VARIFLIGHT_KEY)}


def _validate_transport_airports(trip_data: dict, departure_city: str = "", dest: str = "", travel_date: str = "", variflight_data: dict = None):
    """后处理验证：严格使用飞常准API数据校验班次真实性，返回校验结果。
    返回: {"valid": bool, "issues": list, "fabricated": list}"""
    from feichangzhun_service import (sanitize_airport_name, is_airport_valid,
                                      DECOMMISSIONED_AIRPORTS, verify_schedule_number,
                                      get_route_schedule, _clean_city_name, SHORT_AIRPORT_MAP)
    from datetime import date as date_type

    result = {"valid": True, "issues": [], "fabricated": []}

    # 提取出行年份
    travel_year = ""
    if travel_date:
        try:
            travel_year = str(date_type.fromisoformat(travel_date).year)
        except ValueError:
            pass

    # 辅助函数：根据Variflight数据项判断交通类型
    def _get_type_from_vf(item):
        if item.get("from_airport"):
            return "飞机"
        if item.get("from_station"):
            return "高铁"
        return ""

    # 构建飞常准API数据索引（用于快速查找）
    vf_flights = []
    vf_trains = []
    if variflight_data and variflight_data.get("success"):
        vf_flights = variflight_data.get("flights", [])
        vf_trains = variflight_data.get("trains", [])

    # 收集所有真实班次号（用于校验）
    all_real_nums = set()
    for item in vf_flights + vf_trains:
        if item.get("num"):
            all_real_nums.add(item["num"])

    for key in ("departure_transport", "return_transport"):
        transport = trip_data.get(key, {})
        if not transport:
            continue

        station = transport.get("station", "")
        # 检查黑名单
        for banned in DECOMMISSIONED_AIRPORTS:
            if banned in station:
                issue = f"{key}使用了停用机场: {station}"
                print(f"[WARN] {issue}")
                result["issues"].append(issue)
                result["valid"] = False
                transport["station"] = ""
                transport["note"] = (transport.get("note", "") + "（原机场已停用，请自行查询当前运营机场）").strip()
                break

        # 如果station不为空但不在白名单中，尝试用SHORT_AIRPORT_MAP解析
        if transport.get("station") and not is_airport_valid(transport.get("station", "")):
            sanitized = sanitize_airport_name(transport.get("station", ""))
            if sanitized:
                transport["station"] = sanitized
            else:
                issue = f"{key}使用了未知机场: {station}"
                print(f"[WARN] {issue}")
                result["issues"].append(issue)
                result["valid"] = False
                transport["station"] = ""
                transport["note"] = (transport.get("note", "") + "（机场信息未验证，请核实）").strip()

        # 检查transfers中的机场名
        for transfer in transport.get("transfers", []):
            for tk in ("from_station", "to_station"):
                ts = transfer.get(tk, "")
                for banned in DECOMMISSIONED_AIRPORTS:
                    if banned in ts:
                        transfer[tk] = ""
                        break
                if transfer.get(tk) and not is_airport_valid(transfer.get(tk, "")):
                    sanitized = sanitize_airport_name(transfer.get(tk, ""))
                    if sanitized:
                        transfer[tk] = sanitized
                    else:
                        transfer[tk] = ""

        # 如果flight_number非空但station为空（说明AI编造了），清空flight_number
        if transport.get("flight_number") and not transport.get("station"):
            issue = f"{key}编造了航班号{transport.get('flight_number')}但无有效机场"
            print(f"[WARN] {issue}")
            result["issues"].append(issue)
            result["fabricated"].append(transport.get("flight_number"))
            result["valid"] = False
            transport["flight_number"] = ""
            transport["note"] = (transport.get("note", "") + "（航班信息未验证，请自行查询）").strip()

        # 🔴 飞常准API数据验证（最高优先级）
        if departure_city and dest:
            flight_num = transport.get("flight_number", "")
            if key == "return_transport":
                dep_city_for_check = dest
                arr_city_for_check = departure_city
            else:
                dep_city_for_check = departure_city
                arr_city_for_check = dest

            # 优先使用飞常准API数据验证
            vf_matched = None
            all_vf_items = vf_flights + vf_trains
            if flight_num and all_vf_items:
                for item in all_vf_items:
                    if item.get("num") == flight_num:
                        vf_matched = item
                        break

            if vf_matched:
                # 飞常准API匹配成功，用API数据强制同步所有字段
                transport["flight_number"] = vf_matched["num"]
                transport["departure_time"] = vf_matched.get("dep", transport.get("departure_time", ""))
                transport["arrival_time"] = vf_matched.get("arr", transport.get("arrival_time", ""))
                vf_type = _get_type_from_vf(vf_matched)
                if vf_type:
                    transport["type"] = vf_type
                vf_dur = vf_matched.get("duration", "")
                if vf_dur:
                    transport["duration"] = f"{vf_matched['num']} {vf_dur}"
                if vf_matched.get("from_airport"):
                    transport["station"] = SHORT_AIRPORT_MAP.get(
                        vf_matched["from_airport"], vf_matched["from_airport"])
                elif vf_matched.get("from_station"):
                    transport["station"] = vf_matched["from_station"]
                if vf_matched.get("price"):
                    transport["cost"] = vf_matched["price"]
                transport["_verified"] = True
                transport["_verified_source"] = "飞常准实时API"
                transport["_verified_date"] = travel_date
                print(f"[OK] 飞常准API验证通过: {flight_num} {vf_matched.get('dep','')}→{vf_matched.get('arr','')} type={transport.get('type','')}")
            elif flight_num and not all_vf_items:
                # 飞常准API无数据，回退到静态数据验证
                schedule = get_route_schedule(dep_city_for_check, arr_city_for_check, travel_date)
                valid_list = schedule.get("flights", []) + schedule.get("trains", [])
                is_valid = False
                for item in valid_list:
                    if item.get("num") == flight_num:
                        is_valid = True
                        if item.get("from_airport"):
                            full_name = SHORT_AIRPORT_MAP.get(item["from_airport"], item["from_airport"])
                            transport["station"] = full_name
                        break
                if not is_valid and valid_list:
                    issue = f"{key}班次{flight_num}不在真实班次表中，已替换为{valid_list[0]['num']}"
                    if flight_num:
                        print(f"[WARN] {issue}")
                        result["issues"].append(issue)
                        result["fabricated"].append(flight_num)
                        result["valid"] = False
                    chosen = valid_list[0]
                    transport["flight_number"] = chosen["num"]
                    transport["departure_time"] = chosen.get("dep", transport.get("departure_time", ""))
                    transport["arrival_time"] = chosen.get("arr", transport.get("arrival_time", ""))
                    vf_type = _get_type_from_vf(chosen)
                    if vf_type:
                        transport["type"] = vf_type
                    if chosen.get("from_airport"):
                        full_name = SHORT_AIRPORT_MAP.get(chosen["from_airport"], chosen["from_airport"])
                        transport["station"] = full_name
                    elif chosen.get("from_station"):
                        transport["station"] = chosen["from_station"]
                    if chosen.get("duration"):
                        transport["duration"] = f"{chosen['num']} {chosen['duration']}"
                    transport["note"] = (transport.get("note", "") + f"（已校准为真实班次{chosen['num']}）").strip()
                    transport["_verified"] = True
                    transport["_verified_source"] = "预存数据"
                elif not is_valid and not valid_list and flight_num:
                    issue = f"{key}无{dep_city_for_check}-{arr_city_for_check}真实班次数据，AI编造了{flight_num}，已清空"
                    print(f"[WARN] {issue}")
                    result["issues"].append(issue)
                    result["fabricated"].append(flight_num)
                    result["valid"] = False
                    transport["flight_number"] = ""
                    transport["note"] = (transport.get("note", "") + f"（原班次{flight_num}无真实数据验证，请自行在携程查询实时班次）").strip()
            elif flight_num and all_vf_items and not vf_matched:
                # 飞常准API有数据但AI选的班次不在其中，用飞常准API第一个班次替换
                chosen = all_vf_items[0]
                issue = f"{key}班次{flight_num}不在飞常准API数据中，已替换为{chosen['num']}"
                print(f"[WARN] {issue}")
                result["issues"].append(issue)
                result["fabricated"].append(flight_num)
                result["valid"] = False
                transport["flight_number"] = chosen["num"]
                transport["departure_time"] = chosen.get("dep", transport.get("departure_time", ""))
                transport["arrival_time"] = chosen.get("arr", transport.get("arrival_time", ""))
                vf_type = _get_type_from_vf(chosen)
                if vf_type:
                    transport["type"] = vf_type
                if chosen.get("duration"):
                    transport["duration"] = f"{chosen['num']} {chosen['duration']}"
                if chosen.get("from_airport"):
                    transport["station"] = SHORT_AIRPORT_MAP.get(chosen["from_airport"], chosen["from_airport"])
                elif chosen.get("from_station"):
                    transport["station"] = chosen["from_station"]
                if chosen.get("price"):
                    transport["cost"] = chosen["price"]
                transport["_verified"] = True
                transport["_verified_source"] = "飞常准实时API（自动校准）"
                transport["note"] = (transport.get("note", "") + f"（已校准为飞常准API真实班次{chosen['num']}）").strip()
            elif not flight_num and all_vf_items:
                # AI没填班次号但飞常准API有数据，自动填充第一个班次
                chosen = all_vf_items[0]
                transport["flight_number"] = chosen["num"]
                transport["departure_time"] = chosen.get("dep", "")
                transport["arrival_time"] = chosen.get("arr", "")
                vf_type = _get_type_from_vf(chosen)
                if vf_type:
                    transport["type"] = vf_type
                if chosen.get("duration"):
                    transport["duration"] = f"{chosen['num']} {chosen['duration']}"
                if chosen.get("from_airport"):
                    transport["station"] = SHORT_AIRPORT_MAP.get(chosen["from_airport"], chosen["from_airport"])
                elif chosen.get("from_station"):
                    transport["station"] = chosen["from_station"]
                if chosen.get("price"):
                    transport["cost"] = chosen["price"]
                transport["_verified"] = True
                transport["_verified_source"] = "飞常准实时API（自动填充）"
                print(f"[OK] 飞常准API自动填充: {chosen['num']} type={transport.get('type','')}")
            elif flight_num and not all_vf_items and not all_real_nums:
                # 飞常准API和静态数据都无数据，但AI填了班次号——这是编造的
                issue = f"{key}飞常准API无{dep_city_for_check}-{arr_city_for_check}任何数据，但AI编造了班次{flight_num}"
                print(f"[WARN] {issue}")
                result["issues"].append(issue)
                result["fabricated"].append(flight_num)
                result["valid"] = False
                transport["flight_number"] = ""
                transport["note"] = (transport.get("note", "") + f"（原班次{flight_num}无真实数据验证，请自行在携程查询实时班次）").strip()

    return result


def _validate_cross_card_consistency(trip_data: dict):
    """交叉验证：确保行程卡片与交通卡片的时间一致性，不可相互独立"""
    dep_trans = trip_data.get("departure_transport", {})
    ret_trans = trip_data.get("return_transport", {})
    itinerary = trip_data.get("itinerary", [])
    if not itinerary:
        return

    # 解析出发交通到达时间
    dep_arrival = dep_trans.get("arrival_time", "")
    dep_type = dep_trans.get("type", "")

    # 解析返程交通出发时间
    ret_departure = ret_trans.get("departure_time", "")

    # 车站到酒店预估时间（分钟）
    station_to_hotel_min = 60  # 默认1小时
    hotel_to_station_min = 60  # 默认1小时

    if dep_trans.get("station_to_hotel"):
        import re
        stn_match = re.search(r'(\d+)\s*分钟', dep_trans["station_to_hotel"])
        if stn_match:
            station_to_hotel_min = int(stn_match.group(1))

    # 第一天：确保景点时间在到达之后
    if dep_arrival and itinerary:
        day1 = itinerary[0]
        dep_hour, dep_min = 0, 0
        try:
            parts = dep_arrival.replace("次日", "").strip().split(":")
            dep_hour = int(parts[0])
            dep_min = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            pass

        if dep_hour > 0 or dep_min > 0:
            # 到达后最早可开始游览时间 = 到达时间 + 车站到酒店时间
            earliest_start = dep_hour * 60 + dep_min + station_to_hotel_min
            earliest_hour = earliest_start // 60
            earliest_min = earliest_start % 60

            # 检查上午景点
            morning_spot = day1.get("morning", {})
            if morning_spot and morning_spot.get("time_slot"):
                try:
                    slot_parts = morning_spot["time_slot"].split("-")[0].strip().split(":")
                    slot_hour = int(slot_parts[0])
                    slot_min = int(slot_parts[1]) if len(slot_parts) > 1 else 0
                    slot_start = slot_hour * 60 + slot_min
                    if slot_start < earliest_start:
                        # 上午景点时间早于到达时间，需要调整
                        new_hour = f"{earliest_hour:02d}:{earliest_min:02d}"
                        old_slot = morning_spot["time_slot"]
                        morning_spot["time_slot"] = morning_spot["time_slot"].replace(
                            old_slot.split("-")[0], new_hour)
                        morning_spot["note"] = (morning_spot.get("note", "") +
                            f"（到达时间为{dep_arrival}，已调整游览开始时间）").strip()
                        print(f"[CONSISTENCY] Day1上午景点时间{old_slot}早于到达时间{dep_arrival}+{station_to_hotel_min}min，已调整")
                except (ValueError, IndexError, AttributeError):
                    pass

            # 如果到达时间是下午/晚上，Day1上午和下午应该为空或只有休息
            if dep_hour >= 14:
                # 下午/晚上到达，Day1只安排晚上
                if day1.get("morning", {}).get("spot"):
                    print(f"[CONSISTENCY] Day1 {dep_arrival}到达，上午景点'{day1['morning']['spot']}'不适用，已清空")
                    day1["morning"] = {}
                if dep_hour >= 17 and day1.get("afternoon", {}).get("spot"):
                    print(f"[CONSISTENCY] Day1 {dep_arrival}到达，下午景点'{day1['afternoon']['spot']}'不适用，已清空")
                    day1["afternoon"] = {}
            elif dep_hour >= 12:
                # 中午到达，Day1上午为空
                if day1.get("morning", {}).get("spot"):
                    print(f"[CONSISTENCY] Day1 {dep_arrival}到达，上午景点'{day1['morning']['spot']}'不适用，已清空")
                    day1["morning"] = {}

    # 最后一天：确保所有景点在返程出发前结束
    if ret_departure and itinerary:
        last_day = itinerary[-1]
        ret_hour, ret_min = 0, 0
        try:
            parts = ret_departure.replace("次日", "").strip().split(":")
            ret_hour = int(parts[0])
            ret_min = int(parts[1]) if len(parts) > 1 else 0
        except (ValueError, IndexError):
            pass

        if ret_hour > 0 or ret_min > 0:
            # 最晚结束时间 = 返程出发时间 - 酒店到车站时间 - 提前到站缓冲（飞机2h，火车1h）
            ret_type = ret_trans.get("type", "")
            buffer_min = 120 if "飞机" in ret_type else 60  # 飞机提前2小时，火车提前1小时
            latest_end = ret_hour * 60 + ret_min - hotel_to_station_min - buffer_min
            latest_hour = latest_end // 60
            latest_min = latest_end % 60

            for slot_key in ["evening", "afternoon", "morning"]:
                slot = last_day.get(slot_key, {})
                if slot and slot.get("time_slot"):
                    try:
                        slot_parts = slot["time_slot"].split("-")[-1].strip().split(":")
                        slot_hour = int(slot_parts[0])
                        slot_min = int(slot_parts[1]) if len(slot_parts) > 1 else 0
                        slot_end = slot_hour * 60 + slot_min
                        if slot_end > latest_end:
                            new_end = f"{latest_hour:02d}:{latest_min:02d}"
                            old_slot = slot["time_slot"]
                            slot["time_slot"] = slot["time_slot"].replace(
                                old_slot.split("-")[-1], new_end)
                            slot["note"] = (slot.get("note", "") +
                                f"（返程{ret_departure}出发，已调整结束时间）").strip()
                            print(f"[CONSISTENCY] 最后一天{slot_key}结束时间{old_slot}晚于返程时间{ret_departure}-{buffer_min}min缓冲，已调整")
                            break  # 只调整最晚的一个时段
                    except (ValueError, IndexError, AttributeError):
                        pass

            # 如果返程在上午，最后一天不应有景点
            if ret_hour < 12:
                for slot_key in ["morning", "afternoon", "evening"]:
                    if last_day.get(slot_key, {}).get("spot"):
                        print(f"[CONSISTENCY] 最后一天返程{ret_departure}出发，{slot_key}景点'{last_day[slot_key]['spot']}'不适用，已清空")
                        last_day[slot_key] = {}


def _ensure_transport_data(trip_data: dict, departure_city: str, dest: str, 
                           variflight_data: dict = None, days: int = 3) -> dict:
    """确保行程数据始终包含往返交通信息，缺失时从飞常准API数据自动填充"""
    vf_flights = []
    vf_trains = []
    if variflight_data and variflight_data.get("success"):
        vf_flights = variflight_data.get("flights", [])
        vf_trains = variflight_data.get("trains", [])

    # 构建默认交通模板
    def _build_transport_template(is_return=False):
        t = {
            "type": "", "flight_number": "", "departure_time": "", "arrival_time": "",
            "station": "", "duration": "", "cost": "", "cross_day": False,
            "station_to_hotel": "", "note": "", "transfers": [],
            "_verified": False, "_verified_source": "自动填充"
        }
        if vf_flights:
            f = vf_flights[0]
            t["type"] = "飞机"
            t["flight_number"] = f["num"]
            t["departure_time"] = f.get("dep", "")
            t["arrival_time"] = f.get("arr", "")
            t["duration"] = f"{f['num']} {f.get('duration', '')}"
            t["station"] = f.get("from_airport", "")
            t["cost"] = f.get("price", "")
            t["_verified"] = True
            t["_verified_source"] = "飞常准实时API"
        elif vf_trains:
            tr = vf_trains[0]
            t["type"] = "高铁"
            t["flight_number"] = tr["num"]
            t["departure_time"] = tr.get("dep", "")
            t["arrival_time"] = tr.get("arr", "")
            t["duration"] = f"{tr['num']} {tr.get('duration', '')}"
            t["station"] = tr.get("from_station", "")
            t["cost"] = tr.get("price", "")
            t["_verified"] = True
            t["_verified_source"] = "飞常准实时API"
        else:
            from feichangzhun_service import judge_transport, get_route_schedule
            try:
                ti = judge_transport(departure_city, dest)
            except Exception as e:
                print(f"[WARN] 交通判断失败: {e}")
                ti = None
            try:
                schedule = get_route_schedule(departure_city, dest)
            except Exception as e:
                print(f"[WARN] 路线班次查询失败: {e}")
                schedule = {}
            if schedule.get("flights"):
                f = schedule["flights"][0]
                t["type"] = "飞机"
                t["flight_number"] = f["num"]
                t["departure_time"] = f.get("dep", "")
                t["arrival_time"] = f.get("arr", "")
                t["duration"] = f"{f['num']} {f.get('duration', '')}"
                t["station"] = f.get("from_airport", "")
                t["_verified"] = True
                t["_verified_source"] = "预存数据"
            elif schedule.get("trains"):
                tr = schedule["trains"][0]
                t["type"] = "高铁"
                t["flight_number"] = tr["num"]
                t["departure_time"] = tr.get("dep", "")
                t["arrival_time"] = tr.get("arr", "")
                t["duration"] = f"{tr['num']} {tr.get('duration', '')}"
                t["station"] = tr.get("from_station", "")
                t["_verified"] = True
                t["_verified_source"] = "预存数据"
            else:
                # 所有数据源都无数据时，至少设置推荐交通方式
                t["type"] = ti.get("mode", "高铁").split("/")[0] if ti else "高铁"
                t["note"] = "暂无实时班次数据，请自行在携程查询"
        return t

    # 从Variflight数据合并缺失字段到已有transport（不覆盖已有值）
    def _merge_vf_to_transport(transport, vf_item):
        if not transport.get("flight_number"):
            transport["flight_number"] = vf_item["num"]
        if not transport.get("departure_time"):
            transport["departure_time"] = vf_item.get("dep", "")
        if not transport.get("arrival_time"):
            transport["arrival_time"] = vf_item.get("arr", "")
        if not transport.get("duration"):
            transport["duration"] = f"{vf_item['num']} {vf_item.get('duration', '')}"
        if not transport.get("station"):
            transport["station"] = vf_item.get("from_airport") or vf_item.get("from_station", "")
        if not transport.get("cost"):
            transport["cost"] = vf_item.get("price", "")
        # 如果type为空或与Variflight数据不一致，以Variflight为准
        if vf_item.get("from_airport"):
            cur_type = str(transport.get("type", ""))
            if not cur_type or "飞机" not in cur_type:
                transport["type"] = "飞机"
        if vf_item.get("from_station"):
            cur_type = str(transport.get("type", ""))
            if not cur_type or ("高铁" not in cur_type and "火车" not in cur_type and "动车" not in cur_type):
                transport["type"] = "高铁"
        if not transport.get("_verified"):
            transport["_verified"] = True
            transport["_verified_source"] = "飞常准实时API（合并填充）"

    # 确保去程交通
    if not trip_data.get("departure_transport") or not isinstance(trip_data.get("departure_transport"), dict):
        print("[TRANSPORT] 去程交通缺失，自动填充默认交通信息")
        trip_data["departure_transport"] = _build_transport_template()
    elif not trip_data["departure_transport"].get("flight_number"):
        # 有type但缺flight_number，尝试从Variflight数据合并填充
        if vf_flights or vf_trains:
            chosen = vf_flights[0] if vf_flights else vf_trains[0]
            print(f"[TRANSPORT] 去程交通缺flight_number，从飞常准API合并: {chosen['num']}")
            _merge_vf_to_transport(trip_data["departure_transport"], chosen)
        elif not trip_data["departure_transport"].get("type"):
            print("[TRANSPORT] 去程交通信息不完整且无API数据，完整填充")
            trip_data["departure_transport"] = _build_transport_template()
        else:
            # 有type但无flight_number且无API数据，尝试从静态数据补全
            print("[TRANSPORT] 去程交通有type无班次号，尝试从静态数据补全")
            trip_data["departure_transport"] = _build_transport_template()

    # 确保返程交通
    if not trip_data.get("return_transport") or not isinstance(trip_data.get("return_transport"), dict):
        print("[TRANSPORT] 返程交通缺失，自动填充默认交通信息")
        trip_data["return_transport"] = _build_transport_template(is_return=True)
    elif not trip_data["return_transport"].get("flight_number"):
        if vf_flights or vf_trains:
            chosen = vf_flights[0] if vf_flights else vf_trains[0]
            print(f"[TRANSPORT] 返程交通缺flight_number，从飞常准API合并: {chosen['num']}")
            _merge_vf_to_transport(trip_data["return_transport"], chosen)
        elif not trip_data["return_transport"].get("type"):
            print("[TRANSPORT] 返程交通信息不完整且无API数据，完整填充")
            trip_data["return_transport"] = _build_transport_template(is_return=True)
        else:
            # 有type但无flight_number且无API数据，尝试从静态数据补全
            print("[TRANSPORT] 返程交通有type无班次号，尝试从静态数据补全")
            trip_data["return_transport"] = _build_transport_template(is_return=True)

    return trip_data


@app.get("/api/locate")
async def locate_city(request: Request):
    """IP定位：高德API优先，ip-api.com兜底，ipapi.co交叉验证。移动端IP可能不准。"""
    import re
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    if not client_ip:
        client_ip = request.headers.get("X-Real-IP", "")
    if not client_ip:
        client_ip = request.client.host if request.client else ""
    is_private = bool(re.match(
        r'^(127\.|10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)', client_ip
    )) or client_ip == "::1"
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 方案1：高德IP定位
        params = {"key": AMAP_KEY}
        if not is_private and client_ip:
            params["ip"] = client_ip
        resp = await client.get("https://restapi.amap.com/v3/ip", params=params)
        amap_data = resp.json()
        if amap_data.get("status") == "1" and amap_data.get("city"):
            amap_city = amap_data["city"].replace("市", "")
            amap_source = "amap"
            # 方案3：用ipapi.co交叉验证（仅在高德返回了结果时）
            try:
                ipapi_resp = await client.get(f"https://ipapi.co/{client_ip}/json/", follow_redirects=True)
                ipapi_data = ipapi_resp.json()
                ipapi_city = (ipapi_data.get("city", "") or "").replace("市", "")
                # 如果两个服务返回不同城市，用ipapi.co的结果（对移动端更准）
                if ipapi_city and ipapi_city != amap_city and len(ipapi_city) >= 2:
                    # 再用ip-api.com作为决胜票
                    try:
                        ipapi2_resp = await client.get(
                            f"http://ip-api.com/json/{client_ip}?lang=zh-CN&fields=city,regionName",
                            follow_redirects=True)
                        ipapi2_data = ipapi2_resp.json()
                        ipapi2_city = (ipapi2_data.get("city", "") or "").replace("市", "")
                        if ipapi2_city and ipapi2_city == ipapi_city:
                            # 两个都不同意高德，用新结果
                            return {"success": True, "city": ipapi_city,
                                    "province": ipapi_data.get("region", ""),
                                    "adcode": "", "source": "ipapi_co"}
                    except Exception:
                        pass
                    return {"success": True, "city": ipapi_city,
                            "province": ipapi_data.get("region", ""),
                            "adcode": "", "source": "ipapi_co"}
            except Exception:
                pass
            return {"success": True, "city": amap_city,
                    "province": amap_data.get("province", ""),
                    "adcode": amap_data.get("adcode", ""), "source": amap_source}
        # 方案2：ip-api.com 兜底
        try:
            ip_url = "http://ip-api.com/json/?lang=zh-CN&fields=city,regionName,country"
            if not is_private and client_ip:
                ip_url = f"http://ip-api.com/json/{client_ip}?lang=zh-CN&fields=city,regionName,country"
            resp2 = await client.get(ip_url, follow_redirects=True)
            data2 = resp2.json()
            if isinstance(data2, dict) and data2.get("city"):
                return {"success": True, "city": data2["city"].replace("市", ""),
                        "province": data2.get("regionName", ""), "adcode": "",
                        "source": "ip-api"}
        except Exception:
            pass
        # 方案4：ipapi.co 最后兜底
        try:
            if not is_private and client_ip:
                ipapi_resp = await client.get(f"https://ipapi.co/{client_ip}/json/", follow_redirects=True)
                ipapi_data = ipapi_resp.json()
                ipapi_city = (ipapi_data.get("city", "") or "").replace("市", "")
                if ipapi_city:
                    return {"success": True, "city": ipapi_city,
                            "province": ipapi_data.get("region", ""),
                            "adcode": "", "source": "ipapi_co"}
        except Exception:
            pass
        return {"success": False, "city": "", "error": "无法定位"}


@app.get("/api/regeo")
async def reverse_geocode(lat: float, lng: float):
    """GPS坐标逆地理编码：通过高德API将经纬度转换为城市名"""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(AMAP_REGEO_URL, params={
            "key": AMAP_KEY, "location": f"{lng},{lat}", "extensions": "base",
        })
        data = resp.json()
        if data.get("status") == "1":
            regeo = data.get("regeocode", {})
            addr = regeo.get("addressComponent", {})
            city = addr.get("city", "") or addr.get("province", "")
            return {"success": True, "city": city.replace("市", "").replace("省", ""),
                    "district": addr.get("district", ""),
                    "province": addr.get("province", ""),
                    "address": regeo.get("formatted_address", "")}
        return {"success": False, "city": "", "error": "逆地理编码失败"}


@app.post("/api/generate-trip")
async def generate_trip(req: TripRequest):
    """生成旅行攻略：高德POI+天气 → DeepSeek itinerary → DeepSeek booking → 返回完整JSON"""
    try:
        dest = req.destination.strip()
        days = max(1, min(31, req.days))
        start_date = req.start_date or ""
        end_date = req.end_date or ""

        # 1. 并行查询高德 POI 和天气
        poi_tasks = [
            amap_poi_search(f"{dest}景点", dest),
            amap_poi_search(f"{dest}美食", dest),
        ]
        if req.interests:
            poi_tasks.append(amap_poi_search(f"{dest}{' '.join(req.interests)}", dest))
        weather_task = amap_weather(dest)

        poi_results = await asyncio.gather(*poi_tasks)
        weather_data = await weather_task

        all_pois = []
        for r in poi_results:
            if isinstance(r, list):
                all_pois.extend(r)

        # 去重并按评分降序排列（高评分优先），取前20个
        seen_names = set()
        unique_pois = []
        for p in all_pois:
            if p["name"] not in seen_names:
                seen_names.add(p["name"])
                unique_pois.append(p)
        unique_pois.sort(key=lambda x: float(x["rating"]) if x["rating"] else 0, reverse=True)
        ranked_pois = unique_pois[:20]

        # 1.5 出发/返程交通规划（自驾/公共交通）
        transport_info = {}
        if req.departure_city:
            # 判断交通工具
            ti = judge_transport(req.departure_city, dest)
            transport_info["transport"] = ti
            # 查询真实航班/火车班次数据（传入日期校准）
            schedule = get_route_schedule(req.departure_city, dest, start_date)
            transport_info["route_schedule"] = schedule
            # 查询中转方案（当无直飞时）
            transfer_info = get_transfer_routes(req.departure_city, dest, start_date)
            transport_info["transfer_info"] = transfer_info
            # 检查出发/目的城市是否需要去邻近枢纽
            dep_hub = get_nearest_hub(req.departure_city)
            dest_hub = get_nearest_hub(dest)
            transport_info["dep_hub"] = dep_hub
            transport_info["dest_hub"] = dest_hub
            # 计算前往机场/车站的时间
            if ti.get("need_flight"):
                to_station = await calculate_transit_to_station(req.departure_city, "airport")
                from_station = await calculate_station_to_hotel(dest, "airport")
                transport_info["to_station"] = to_station
                transport_info["from_station"] = from_station
                # 生成航班查询指引
                transport_info["flight_query_text"] = build_flight_query_text(
                    req.departure_city, dest, start_date)
            else:
                to_station = await calculate_transit_to_station(req.departure_city, "train")
                from_station = await calculate_station_to_hotel(dest, "train")
                transport_info["to_station"] = to_station
                transport_info["from_station"] = from_station
                # 生成火车票查询指引
                transport_info["flight_query_text"] = build_flight_query_text(
                    req.departure_city, dest, start_date)
            # 自驾模式：计算自驾路线
            if req.is_self_drive:
                sd_plan = await calculate_self_drive_plan(
                    req.departure_city, dest, start_date, end_date)
                transport_info["self_drive_plan"] = sd_plan
            # 飞常准API实时查询航班和火车票（多渠道验证）
            if ti.get("need_flight"):
                flight_result = await search_flights(req.departure_city, dest, start_date)
                transport_info["flight_data"] = flight_result.get("flights", [])
                transport_info["flight_query"] = flight_result.get("query", {})
            # 并行查询：飞常准API火车票 + 完整路线数据
            from variflight_service import get_full_route_data
            vf_result = await get_full_route_data(req.departure_city, dest, start_date)
            transport_info["variflight_data"] = {
                "flights": vf_result.get("flights", []),
                "trains": vf_result.get("trains", []),
                "transfers": vf_result.get("transfers", {}),
                "success": vf_result.get("success"),
                "source": vf_result.get("_source", "飞常准API"),
            }
            # 合并飞常准API数据到route_schedule（优先API数据）
            if vf_result.get("success"):
                schedule = transport_info.get("route_schedule", {})
                if not schedule or schedule.get("_no_data"):
                    # 无预存数据时，直接用API数据构建schedule
                    schedule = {
                        "flights": vf_result.get("flights", []),
                        "trains": vf_result.get("trains", []),
                        "_verified": f"{start_date}", "_source": "飞常准实时API",
                    }
                else:
                    # 有预存数据时，API数据作为补充
                    api_flights = vf_result.get("flights", [])
                    if api_flights:
                        existing_nums = {f["num"] for f in schedule.get("flights", [])}
                        for f in api_flights:
                            if f["num"] not in existing_nums:
                                schedule.setdefault("flights", []).append(f)
                    api_trains = vf_result.get("trains", [])
                    if api_trains:
                        existing_nums = {t["num"] for t in schedule.get("trains", [])}
                        for t in api_trains:
                            if t["num"] not in existing_nums:
                                schedule.setdefault("trains", []).append(t)
                    schedule["_source"] = f"{schedule.get('_source', '')} + 飞常准实时API"
                transport_info["route_schedule"] = schedule

        # 2. 调用 DeepSeek 生成行程
        prompt = build_trip_prompt(dest, days, req.budget, req.interests, ranked_pois, weather_data,
                                   start_date, end_date, req.travelers, req.budget_type, req.pace,
                                   req.is_self_drive, req.departure_city, transport_info)
        dynamic_tokens = 4000 + days * 500
        try:
            raw = await call_deepseek("你是一个专业的旅行规划师，只输出JSON格式数据。", prompt, dynamic_tokens)
        except httpx.HTTPStatusError as e:
            err_msg = "AI服务调用失败"
            if e.response.status_code == 402:
                err_msg = "DeepSeek API 余额不足，请充值后重试"
            elif e.response.status_code == 401:
                err_msg = "DeepSeek API Key 无效"
            elif e.response.status_code == 429:
                err_msg = "请求过于频繁，请稍后重试"
            return {"success": False, "error": err_msg}
        except Exception:
            return {"success": False, "error": "AI服务调用失败，请重试"}

        raw_clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            trip_data = json.loads(raw_clean)
        except Exception:
            return {"success": False, "error": "AI返回数据格式异常，请重试"}

        # 后处理验证与重生成：飞常准API严格校验班次真实性，不准确则重新生成（最多2次）
        validation_result = {"valid": True, "issues": [], "fabricated": []}
        max_retries = 2
        for retry_attempt in range(max_retries + 1):
            try:
                validation_result = _validate_transport_airports(
                    trip_data, req.departure_city, dest, req.start_date,
                    transport_info.get("variflight_data"))
            except Exception as e:
                print(f"[WARN] 交通验证失败（不影响主流程）: {e}")
                validation_result = {"valid": True, "issues": [], "fabricated": []}

            if validation_result.get("valid") and not validation_result.get("fabricated"):
                break  # 验证通过，无需重生成

            if retry_attempt < max_retries and validation_result.get("fabricated"):
                print(f"[RETRY] 第{retry_attempt+1}次重生成：AI编造了班次 {validation_result['fabricated']}")
                retry_prompt = build_retry_prompt(
                    prompt, validation_result, transport_info,
                    req.departure_city, dest, req.start_date)
                try:
                    retry_raw = await call_deepseek(
                        "你是一个专业的旅行规划师，只输出JSON格式数据。必须严格使用飞常准API提供的真实班次！",
                        retry_prompt, dynamic_tokens)
                    retry_clean = retry_raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    trip_data = json.loads(retry_clean)
                except Exception as e:
                    print(f"[WARN] 重生成失败: {e}")
                    break  # 重生成失败，使用当前数据
            else:
                break  # 已达最大重试次数或无需重试

        # 确保往返交通信息始终存在
        try:
            _ensure_transport_data(trip_data, req.departure_city, dest,
                                   transport_info.get("variflight_data"), req.days)
        except Exception as e:
            print(f"[WARN] 交通数据补全失败（不影响主流程）: {e}")
        # 交叉验证：确保行程卡片与交通卡片时间一致性
        try:
            _validate_cross_card_consistency(trip_data)
        except Exception as e:
            print(f"[WARN] 交叉验证失败（不影响主流程）: {e}")

        # 3. 补全景点坐标（带异常保护，不影响主流程）
        try:
            await fill_coordinates(trip_data, dest)
        except Exception as e:
            print(f"[WARN] 坐标补全失败（不影响主流程）: {e}")

        # 4. 调用 DeepSeek 查询订票/酒店信息
        itinerary = trip_data.get("itinerary", [])
        booking_prompt = build_booking_prompt(dest, start_date, end_date, req.budget, itinerary,
                                              req.departure_city, transport_info,
                                              trip_data.get("departure_transport"),
                                              trip_data.get("return_transport"),
                                              transport_info.get("variflight_data"))
        try:
            booking_raw = await call_deepseek("你是一个旅行服务顾问，只输出JSON格式数据。", booking_prompt, 3000)
            booking_clean = booking_raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            booking_info = json.loads(booking_clean)
        except Exception:
            booking_info = {"flights": [], "hotels": [], "tickets": [], "booking_tips": []}

        # 6. 为酒店和门票补全坐标
        for hotel in booking_info.get("hotels", []):
            if hotel.get("name") and not hotel.get("location"):
                hotel["location"] = await amap_geocode(hotel["name"], dest)
        for change in booking_info.get("hotel_changes", []):
            if change.get("to_hotel") and not change.get("location"):
                change["location"] = await amap_geocode(change["to_hotel"], dest)
        for ticket in booking_info.get("tickets", []):
            if ticket.get("spot") and not ticket.get("location"):
                ticket["location"] = await amap_geocode(ticket["spot"], dest)

        # 7. 为景点和天气获取真实图片URL（带超时，不阻塞主流程）
        try:
            await asyncio.wait_for(fill_images(trip_data, dest), timeout=25.0)
        except (asyncio.TimeoutError, Exception):
            pass  # 图片获取超时或失败不阻塞攻略生成
        # 为酒店获取真实门面图片（带超时）
        try:
            await asyncio.wait_for(fill_booking_images(booking_info, dest), timeout=25.0)
        except (asyncio.TimeoutError, Exception):
            pass  # 酒店图片获取超时或失败不阻塞攻略生成

        trip_data["booking_info"] = booking_info
        trip_data["transport_info"] = transport_info
        return {"success": True, "data": trip_data}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"服务异常：{str(e)}"}


@app.get("/api/weather-hourly")
async def weather_hourly(city: str, date: str):
    """获取指定日期的逐时天气估算"""
    return await get_hourly_weather(city, date)


@app.get("/api/weather-alerts")
async def weather_alerts(city: str):
    """获取极端天气预警"""
    return await check_weather_alerts(city)


@app.get("/api/weather-now")
async def weather_now(city: str):
    """获取实时天气（中国天气智能体集成）"""
    return await get_realtime_weather(city)


@app.get("/api/china-weather/observation")
async def china_weather_observation(city: str):
    """中国天气智能体-实况观测：综合实时数据+预报摘要"""
    return await get_observation(city)


@app.get("/api/china-weather/air-quality")
async def china_weather_air_quality(city: str):
    """中国天气智能体-空气质量指数"""
    return await get_air_quality(city)


@app.get("/api/china-weather/chat")
async def china_weather_chat(city: str, query: str = ""):
    """中国天气智能体-AI天气对话助手"""
    return await get_weather_chat(city, query)


@app.get("/api/spot-detail")
async def spot_detail(name: str, city: str, reason: str = "", route_detail: str = ""):
    """DeepSeek 生成景点详细介绍（≥500字），含著名小景点"""
    prompt = f"""请为景点「{name}」（位于{city}）撰写一份详细的图文介绍。

要求：
1. 总字数不低于500字
2. 包含景点历史背景、文化特色、建筑风格、著名打卡点
3. 在段落之间穿插介绍该景点内2-3个著名小景点/子景点（如具体宫殿、塔楼、园林、展厅等），每个小景点3-4句话
4. 语言优美，适合旅行攻略阅读
5. 输出纯文本，不要markdown格式，分段用空行隔开"""

    try:
        raw = await call_deepseek("你是一个资深旅行编辑，擅长撰写景点深度介绍。", prompt, 2000)
        return {"success": True, "content": raw.strip()}
    except Exception as e:
        return {"success": False, "content": reason or f"{name}是{city}的著名景点，值得一游。", "error": str(e)}


@app.get("/api/hotel-detail")
async def hotel_detail(name: str, city: str, area: str = "", reason: str = ""):
    """DeepSeek 生成酒店详细介绍（≥500字）"""
    prompt = f"""请为酒店「{name}」（位于{city}{area}）撰写一份详细的介绍。

要求：
1. 总字数不低于500字
2. 包含酒店位置优势、周边交通、配套设施、房型特色、服务亮点
3. 在段落之间穿插介绍酒店周边2-3个便利设施或景点（如附近地铁站、商圈、夜市、公园等）
4. 语言专业，适合旅行攻略阅读
5. 输出纯文本，不要markdown格式，分段用空行隔开"""

    try:
        raw = await call_deepseek("你是一个资深旅行编辑，擅长撰写酒店深度介绍。", prompt, 2000)
        return {"success": True, "content": raw.strip()}
    except Exception as e:
        return {"success": False, "content": reason or f"{name}位于{city}{area}，地理位置优越，是旅途中的理想下榻之选。", "error": str(e)}


@app.post("/api/route-plan")
async def route_plan(request: Request):
    """高德路线规划：实时路况、驾车耗时、到达时间预测"""
    body = await request.json()
    spots = body.get("spots", [])
    if not spots or len(spots) < 2:
        return {"success": False, "error": "至少需要2个景点"}
    routes = await get_route_plan(spots)
    return {"success": True, "routes": routes}


@app.post("/api/monitor-trip")
async def monitor_trip(request: Request):
    """DeepSeek实时监测：检查路况/天气变化，给出突发情况建议"""
    body = await request.json()
    trip_data = body.get("trip_data", {})
    current_location = body.get("current_location", {})  # {lng, lat}
    rejected = body.get("rejected", False)  # 用户是否已拒绝过

    if rejected:
        return {"success": True, "has_alert": False, "message": ""}

    dest = trip_data.get("destination", "")
    if not dest:
        return {"success": False, "error": "缺少目的地信息"}

    alerts = []
    # 1. 检查天气预警
    try:
        w_alerts = await check_weather_alerts(dest)
        if w_alerts.get("alerts"):
            alerts.append({"type": "weather", "message": f"目的地{dest}天气预警：" + w_alerts["alerts"][0]["message"]})
    except Exception:
        pass

    # 2. 检查实时路况（如果用户提供了当前位置）
    if current_location.get("lng") and current_location.get("lat"):
        try:
            # 获取目的地坐标
            dest_loc = await amap_geocode(dest, dest)
            if dest_loc:
                dlng, dlat = map(float, dest_loc.split(","))
                route = await get_route_time(
                    current_location["lng"], current_location["lat"], dlng, dlat)
                if route.get("traffic") in ("拥堵", "缓行"):
                    alerts.append({"type": "traffic",
                                   "message": f"当前路况{route['traffic']}，预计耗时{route['duration']}分钟，建议提前出发或调整路线"})
        except Exception:
            pass

    if not alerts:
        return {"success": True, "has_alert": False, "message": ""}

    # 3. 调用DeepSeek给出建议方案
    alert_text = "\n".join([a["message"] for a in alerts])
    prompt = f"""旅行目的地：{dest}。检测到以下突发情况：
{alert_text}

请给出应对建议（200字以内），包括是否需要调整行程、提前出发时间、备选方案等。"""
    try:
        reply = await call_deepseek("你是旅行应急助手，给出简洁实用的建议。", prompt, 500)
        suggestion = reply.strip()
    except Exception:
        suggestion = "建议关注实时路况和天气变化，提前出发，预留充足时间。"

    return {"success": True, "has_alert": True, "alerts": alerts, "suggestion": suggestion}


@app.post("/api/real-time-traffic")
async def real_time_traffic(request: Request):
    """获取实时路况：用户当前位置到目的地的驾车时间"""
    body = await request.json()
    origin_lng = body.get("origin_lng")
    origin_lat = body.get("origin_lat")
    dest_lng = body.get("dest_lng")
    dest_lat = body.get("dest_lat")

    if not all([origin_lng, origin_lat, dest_lng, dest_lat]):
        return {"success": False, "error": "缺少坐标参数"}

    route = await get_route_time(float(origin_lng), float(origin_lat),
                                  float(dest_lng), float(dest_lat))
    return {"success": True, "route": route}


@app.get("/api/saved-trips/refresh")
async def refresh_saved_trip(city: str, days: int):
    """刷新收藏行程的实时天气和景点信息"""
    try:
        weather_data = await amap_weather(city)
        return {"success": True, "weather": weather_data, "city": city,
                "updated_at": __import__("datetime").datetime.now().isoformat()}
    except Exception as e:
        return {"success": False, "error": str(e)}


@app.get("/api/spot-images")
async def spot_images(query: str, limit: int = 5):
    """搜索景点/酒店真实图片（Wikimedia Commons + DeepSeek辅助筛选）"""
    return await search_images(query, limit)


@app.get("/api/resolve-image")
async def resolve_image(name: str, city: str = "", type: str = "spot"):
    """解析图片URL为CDN直链（用于详情页预加载），返回最终可用的图片URL"""
    try:
        if type == "hotel":
            url = await resolve_hotel_image(name, city)
        else:
            url = await resolve_spot_image(name, city)
        return {"success": True, "url": url}
    except Exception as e:
        return {"success": False, "url": "", "error": str(e)}


@app.post("/api/regenerate-trip")
async def regenerate_trip(request: Request):
    """根据用户新需求重新生成旅行计划，重点参考用户输入"""
    try:
        body = await request.json()
        user_input = body.get("user_input", "").strip()
        trip_data = body.get("trip_data", {})
        is_self_drive = body.get("is_self_drive", False)
        departure_city = body.get("departure_city", "")

        if not user_input:
            return {"success": False, "error": "请输入新计划需求"}

        dest = trip_data.get("destination", "")
        days = trip_data.get("days", 3)
        start_date = trip_data.get("start_date", "")
        end_date = trip_data.get("end_date", "")
        old_itinerary = trip_data.get("itinerary", [])

        if not dest:
            return {"success": False, "error": "缺少目的地信息"}

        # 获取最新天气
        try:
            weather_data = await amap_weather(dest)
        except Exception:
            weather_data = []

        # 获取交通判断信息（用于AI选择交通工具）
        transport_info = {}
        if departure_city:
            try:
                ti = judge_transport(departure_city, dest)
                transport_info["transport"] = ti
            except Exception:
                pass
            try:
                schedule = get_route_schedule(departure_city, dest, start_date)
                transport_info["route_schedule"] = schedule
            except Exception:
                pass
            try:
                transfer_info = get_transfer_routes(departure_city, dest, start_date)
                transport_info["transfer_info"] = transfer_info
            except Exception:
                pass
            try:
                dep_hub = get_nearest_hub(departure_city)
                transport_info["dep_hub"] = dep_hub
            except Exception:
                pass
            try:
                dest_hub = get_nearest_hub(dest)
                transport_info["dest_hub"] = dest_hub
            except Exception:
                pass
            # 飞常准API实时查询航班和火车票
            try:
                from variflight_service import get_full_route_data
                vf_result = await get_full_route_data(departure_city, dest, start_date)
                transport_info["variflight_data"] = {
                    "flights": vf_result.get("flights", []),
                    "trains": vf_result.get("trains", []),
                    "transfers": vf_result.get("transfers", {}),
                    "success": vf_result.get("success"),
                    "source": vf_result.get("_source", "飞常准API"),
                }
                if vf_result.get("success"):
                    schedule = transport_info.get("route_schedule", {})
                    if not schedule or schedule.get("_no_data"):
                        schedule = {
                            "flights": vf_result.get("flights", []),
                            "trains": vf_result.get("trains", []),
                            "_verified": f"{start_date}", "_source": "飞常准实时API",
                        }
                    else:
                        api_flights = vf_result.get("flights", [])
                        if api_flights:
                            existing_nums = {f["num"] for f in schedule.get("flights", [])}
                            for f in api_flights:
                                if f["num"] not in existing_nums:
                                    schedule.setdefault("flights", []).append(f)
                        api_trains = vf_result.get("trains", [])
                        if api_trains:
                            existing_nums = {t["num"] for t in schedule.get("trains", [])}
                            for t in api_trains:
                                if t["num"] not in existing_nums:
                                    schedule.setdefault("trains", []).append(t)
                        schedule["_source"] = f"{schedule.get('_source', '')} + 飞常准实时API"
                    transport_info["route_schedule"] = schedule
            except Exception:
                pass

        # 构建regenerate prompt
        prompt = build_regenerate_prompt(dest, days, user_input, old_itinerary,
                                         weather_data, start_date, end_date,
                                         is_self_drive, departure_city, transport_info)
        # 调用DeepSeek
        try:
            raw = await call_deepseek("你是一个专业的旅行规划师，只输出JSON格式数据。", prompt, 6000)
        except httpx.HTTPStatusError as e:
            err_msg = "AI服务调用失败"
            if e.response.status_code == 402:
                err_msg = "DeepSeek API 余额不足，请充值后重试"
            elif e.response.status_code == 401:
                err_msg = "DeepSeek API Key 无效"
            elif e.response.status_code == 429:
                err_msg = "请求过于频繁，请稍后重试"
            return {"success": False, "error": err_msg}
        except Exception:
            return {"success": False, "error": "AI服务调用失败，请重试"}

        # 解析DeepSeek返回的JSON
        raw_clean = raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        try:
            new_trip = json.loads(raw_clean)
        except Exception:
            return {"success": False, "error": "AI返回数据格式异常，请重试"}

        # 后处理验证与重生成：飞常准API严格校验班次真实性，不准确则重新生成（最多2次）
        validation_result = {"valid": True, "issues": [], "fabricated": []}
        max_retries = 2
        for retry_attempt in range(max_retries + 1):
            try:
                validation_result = _validate_transport_airports(
                    new_trip, departure_city, dest, start_date,
                    transport_info.get("variflight_data"))
            except Exception as e:
                print(f"[WARN] 重新生成交通验证失败（不影响主流程）: {e}")
                validation_result = {"valid": True, "issues": [], "fabricated": []}

            if validation_result.get("valid") and not validation_result.get("fabricated"):
                break

            if retry_attempt < max_retries and validation_result.get("fabricated"):
                print(f"[RETRY] 重新生成第{retry_attempt+1}次重试：AI编造了班次 {validation_result['fabricated']}")
                retry_prompt = build_retry_prompt(
                    prompt, validation_result, transport_info,
                    departure_city, dest, start_date)
                try:
                    retry_raw = await call_deepseek(
                        "你是一个专业的旅行规划师，只输出JSON格式数据。必须严格使用飞常准API提供的真实班次！",
                        retry_prompt, 6000)
                    retry_clean = retry_raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
                    new_trip = json.loads(retry_clean)
                except Exception as e:
                    print(f"[WARN] 重新生成重试失败: {e}")
                    break
            else:
                break

        # 确保往返交通信息始终存在
        try:
            _ensure_transport_data(new_trip, departure_city, dest,
                                   transport_info.get("variflight_data"), days)
        except Exception as e:
            print(f"[WARN] 重新生成交通数据补全失败（不影响主流程）: {e}")
        # 交叉验证：确保行程卡片与交通卡片时间一致性
        try:
            _validate_cross_card_consistency(new_trip)
        except Exception as e:
            print(f"[WARN] 重新生成交叉验证失败（不影响主流程）: {e}")

        # 补全坐标
        try:
            await fill_coordinates(new_trip, dest)
        except Exception:
            pass  # 坐标补全失败不影响主流程

        # 获取图片
        try:
            await asyncio.wait_for(fill_images(new_trip, dest), timeout=25.0)
        except (asyncio.TimeoutError, Exception):
            pass

        # 重新生成booking_info（基于新itinerary和交通班次，确保与上方的交通安排是同一班次）
        new_itinerary = new_trip.get("itinerary", [])
        booking_budget = trip_data.get("budget", "中等")
        booking_prompt = build_booking_prompt(dest, start_date, end_date, booking_budget, new_itinerary,
                                              departure_city, transport_info,
                                              new_trip.get("departure_transport"),
                                              new_trip.get("return_transport"),
                                              transport_info.get("variflight_data"))
        try:
            booking_raw = await call_deepseek("你是一个旅行服务顾问，只输出JSON格式数据。", booking_prompt, 3000)
            booking_clean = booking_raw.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
            booking_info = json.loads(booking_clean)
        except Exception:
            booking_info = trip_data.get("booking_info", {})
        # 为booking_info中的酒店和门票补全坐标
        for hotel in booking_info.get("hotels", []):
            if hotel.get("name") and not hotel.get("location"):
                try:
                    hotel["location"] = await amap_geocode(hotel["name"], dest)
                except Exception:
                    pass
        for change in booking_info.get("hotel_changes", []):
            if change.get("to_hotel") and not change.get("location"):
                try:
                    change["location"] = await amap_geocode(change["to_hotel"], dest)
                except Exception:
                    pass
        for ticket in booking_info.get("tickets", []):
            if ticket.get("spot") and not ticket.get("location"):
                try:
                    ticket["location"] = await amap_geocode(ticket["spot"], dest)
                except Exception:
                    pass
        # 为booking_info中的酒店获取图片
        try:
            await asyncio.wait_for(fill_booking_images(booking_info, dest), timeout=25.0)
        except (asyncio.TimeoutError, Exception):
            pass
        new_trip["booking_info"] = booking_info
        new_trip["transport_info"] = transport_info

        return {"success": True, "data": new_trip}
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {"success": False, "error": f"重新生成失败：{str(e)}"}


@app.post("/api/verify-flight")
async def verify_flight(request: Request):
    """验证航班号/车次号是否真实存在（飞常准API）"""
    try:
        body = await request.json()
        flight_num = body.get("flight_number", "").strip()
        date = body.get("date", "").strip()
        dep = body.get("dep", "").strip()
        arr = body.get("arr", "").strip()
        if not flight_num or not date:
            return {"success": False, "valid": False, "error": "缺少航班号或日期"}
        from variflight_service import verify_flight_number
        result = await verify_flight_number(flight_num, date, dep, arr)
        return {"success": True, "valid": result.get("valid", False),
                "data": result.get("data", {}), "source": result.get("_source", "")}
    except Exception as e:
        return {"success": False, "valid": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)