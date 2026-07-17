"""交通验证工具函数"""

from feichangzhun_service import SHORT_AIRPORT_MAP
from datetime import date as date_type, datetime as dt_type


def _validate_transport_airports(trip_data: dict, departure_city: str = "", dest: str = "", travel_date: str = "", variflight_data: dict = None, route_schedule: dict = None, user_transport_mode: str = ""):
    """飞常准API验证：所有班次必须经飞常准API验证成功后才可安排。
    飞常准API是唯一数据源，绝不使用本地预存数据。
    返回: {"valid": bool, "issues": list, "fabricated": list}"""
    from feichangzhun_service import SHORT_AIRPORT_MAP
    from datetime import date as date_type, datetime as dt_type

    result = {"valid": True, "issues": [], "fabricated": []}

    # 解析出行日期，校验年份
    travel_date_obj = None
    travel_year = ""
    if travel_date:
        try:
            travel_date_obj = date_type.fromisoformat(travel_date)
            travel_year = str(travel_date_obj.year)
        except ValueError:
            pass

    # 辅助函数：根据Variflight数据项判断交通类型
    def _get_type_from_vf(item):
        if item.get("from_airport"):
            return "飞机"
        if item.get("from_station"):
            return "高铁"
        return ""

    # 构建飞常准API数据索引（唯一数据源）
    vf_flights = []
    vf_trains = []
    if variflight_data and variflight_data.get("success"):
        vf_flights = variflight_data.get("flights", [])
        vf_trains = variflight_data.get("trains", [])

    # 🔴 飞常准API是唯一数据源，不使用预存COMMON_ROUTES回退
    # 如果API无数据，all_vf_items为空，后续验证将标记所有班次为未验证

    # 🔴 辅助函数：根据用户选择的交通方式过滤可用班次（必须在调用前定义）
    def _filter_by_user_mode(items, mode):
        """根据用户选择的交通方式过滤班次列表，确保替换时不会把飞机换成高铁（或反之）
        如果用户指定了交通方式，严格过滤，无匹配时不回退（保持空列表让调用方处理）"""
        if not mode or mode not in ("飞机", "高铁"):
            return items  # 用户未明确选择，不过滤
        if mode == "飞机":
            filtered = [item for item in items if item.get("from_airport")]
            return filtered  # 只返回航班，不回退到全部
        if mode == "高铁":
            filtered = [item for item in items if item.get("from_station")]
            return filtered  # 只返回高铁，不回退到全部
        return items

    all_vf_items = vf_flights + vf_trains
    all_real_nums = {item["num"] for item in all_vf_items if item.get("num")}
    # 🔴 根据用户交通方式预过滤all_vf_items，确保后续匹配不会把飞机换成高铁（或反之）
    if user_transport_mode and user_transport_mode in ("飞机", "高铁"):
        vf_items_by_mode = _filter_by_user_mode(all_vf_items, user_transport_mode)
        if vf_items_by_mode:
            all_vf_items = vf_items_by_mode
            all_real_nums = {item["num"] for item in all_vf_items if item.get("num")}
    # 记录已分配给出发交通的班次，避免返程使用同一班次
    used_departure_num = None

    for key in ("departure_transport", "return_transport"):
        transport = trip_data.get(key, {})
        if not transport:
            continue

        transport_type = str(transport.get("type", "")).strip()
        effective_user_mode = user_transport_mode or trip_data.get("_transport_mode", "")

        station = transport.get("station", "")
        is_train = transport_type in ("高铁", "火车", "动车")
        is_flight = transport_type in ("飞机", "航班")
        is_low_cost = transport_type in ("大巴", "自驾", "汽车", "打车", "公交", "城际", "步行", "地铁")
        flight_num = transport.get("flight_number", "")

        # 🔴 用户交通方式强制校验：AI输出的type必须与用户选择一致
        if effective_user_mode and effective_user_mode in ("飞机", "高铁"):
            if transport_type and transport_type != effective_user_mode and not is_low_cost:
                issue = f"🔴 {key}交通类型为'{transport_type}'，但用户指定了'{effective_user_mode}'出行，type必须修正为'{effective_user_mode}'！"
                print(f"[VALIDATE] {issue}")
                result["issues"].append(issue)
                result["valid"] = False
                # 强制修正type，并清除所有错误交通方式的字段，避免高铁数据残留在飞机卡片中
                transport["type"] = effective_user_mode
                transport["flight_number"] = ""   # 清除错误类型的班次号
                transport["departure_time"] = ""  # 清除错误类型的出发时间
                transport["arrival_time"] = ""    # 清除错误类型的到达时间
                transport["duration"] = ""        # 清除错误类型的耗时
                transport["station"] = ""         # 清除错误类型的机场/车站
                transport_type = effective_user_mode
                is_train = transport_type in ("高铁", "火车", "动车")
                is_flight = transport_type in ("飞机", "航班")

        # 低成本交通方式（大巴/自驾/汽车/打车等）不需要飞常准验证，跳过
        if is_low_cost:
            print(f"[INFO] {key}交通类型为'{transport_type}'（低成本出行），跳过飞常准验证")
            transport["_verified"] = True
            transport["_verified_source"] = f"低成本出行({transport_type})，无需航班验证"
            if not transport.get("note"):
                transport["note"] = f"{transport_type}出行，建议通过高德地图查询实时路况"
            continue

        # 🔴 飞常准API是唯一数据源，机场有效性由API返回数据验证，不做本地黑白名单检查

        # 🔴 核心：飞常准API验证（唯一数据源，所有班次必须经此验证）
        if departure_city and dest:
            if key == "return_transport":
                dep_city, arr_city = dest, departure_city
            else:
                dep_city, arr_city = departure_city, dest

            vf_matched = None
            if flight_num and all_vf_items:
                # 返程排除已用于出发的班次号
                available_items = all_vf_items
                if key == "return_transport" and used_departure_num:
                    available_items = [item for item in all_vf_items if item.get("num") != used_departure_num]
                    if not available_items:
                        available_items = all_vf_items  # 回退，确保有可选数据
                for item in available_items:
                    if item.get("num") == flight_num:
                        vf_matched = item
                        break

            if vf_matched:
                # ✅ 飞常准API匹配成功 — 用API数据同步所有字段，机场名以API为准
                transport["flight_number"] = vf_matched["num"]
                transport["departure_time"] = vf_matched.get("dep", transport.get("departure_time", ""))
                transport["arrival_time"] = vf_matched.get("arr", transport.get("arrival_time", ""))
                vf_type = _get_type_from_vf(vf_matched)
                if vf_type:
                    transport["type"] = vf_type
                if vf_matched.get("duration"):
                    transport["duration"] = f"{vf_matched['num']} {vf_matched['duration']}"
                # 机场/车站名以飞常准API返回为准（即使不在白名单也有效）
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
                if key == "departure_transport":
                    used_departure_num = vf_matched["num"]
                print(f"[OK] 飞常准API验证通过: {flight_num} {vf_matched.get('dep','')}→{vf_matched.get('arr','')} type={transport.get('type','')}")

            elif flight_num and all_vf_items and not vf_matched:
                # ❌ 飞常准API有数据但AI选的班次不在其中 → 必须替换
                # 🔴 返程不能使用出发的同一班次，且必须尊重用户交通方式选择
                available_items = all_vf_items
                if key == "return_transport" and used_departure_num and len(all_vf_items) > 1:
                    available_items = [item for item in all_vf_items if item.get("num") != used_departure_num]
                # 🔴 根据用户交通方式过滤：用户选飞机则只替换为航班，选高铁则只替换为高铁
                mode_filtered = _filter_by_user_mode(available_items, effective_user_mode)
                if mode_filtered:
                    available_items = mode_filtered
                elif effective_user_mode:
                    # 🔴 用户指定了交通方式但VF数据中没有匹配的班次，不替换，保留原type
                    issue = f"{key}班次{flight_num}不在飞常准API数据中，且无{effective_user_mode}类型班次可替换，保留原type={effective_user_mode}"
                    print(f"[WARN] {issue}")
                    result["issues"].append(issue)
                    result["fabricated"].append(flight_num)
                    result["valid"] = False
                    transport["flight_number"] = ""  # 清空编造的班次号
                    transport["type"] = effective_user_mode  # 保持用户选择的交通方式
                    transport["_verified"] = False
                    transport["_verified_source"] = f"未验证（飞常准API无{effective_user_mode}数据）"
                    transport["note"] = (transport.get("note", "") + f"（⚠️ {effective_user_mode}班次未验证，请自行核实）").strip()
                    continue  # 跳过后续替换逻辑
                elif transport_type in ("飞机", "高铁"):
                    # 🔴 混合交通方式：根据已有type过滤，不跨类型替换
                    type_filtered = _filter_by_user_mode(available_items, transport_type)
                    if type_filtered:
                        available_items = type_filtered
                    else:
                        # 该类型无匹配数据，不替换为其他类型，保留原type
                        issue = f"{key}班次{flight_num}不在飞常准API数据中，且无{transport_type}类型班次可替换，保留原type={transport_type}"
                        print(f"[WARN] {issue}")
                        result["issues"].append(issue)
                        result["fabricated"].append(flight_num)
                        result["valid"] = False
                        transport["flight_number"] = ""  # 清空编造的班次号
                        transport["type"] = transport_type  # 保持当前交通类型
                        transport["_verified"] = False
                        transport["_verified_source"] = f"未验证（飞常准API无{transport_type}数据）"
                        transport["note"] = (transport.get("note", "") + f"（⚠️ {transport_type}班次未验证，请自行核实）").strip()
                        continue
                chosen = available_items[0]
                issue = f"{key}班次{flight_num}不在飞常准API数据中，已替换为{chosen['num']}"
                if key == "return_transport" and used_departure_num and chosen["num"] == used_departure_num:
                    issue += "（⚠️ 飞常准API仅有一个班次，往返共用同一班次号）"
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
                if key == "departure_transport":
                    used_departure_num = chosen["num"]

            elif not flight_num and all_vf_items:
                # AI没填班次号但飞常准API有数据，自动填充
                # 🔴 返程不能使用出发的同一班次，且必须尊重用户交通方式选择
                available_items = all_vf_items
                if key == "return_transport" and used_departure_num and len(all_vf_items) > 1:
                    available_items = [item for item in all_vf_items if item.get("num") != used_departure_num]
                # 🔴 根据用户交通方式过滤
                mode_filtered = _filter_by_user_mode(available_items, effective_user_mode)
                if mode_filtered:
                    available_items = mode_filtered
                elif effective_user_mode:
                    # 🔴 用户指定了交通方式但VF数据中没有匹配的班次，不自动填充
                    print(f"[WARN] {key}飞常准API有数据但无{effective_user_mode}类型班次，保留type={effective_user_mode}，不自动填充")
                    transport["type"] = effective_user_mode
                    transport["_verified"] = False
                    transport["_verified_source"] = f"未验证（飞常准API无{effective_user_mode}数据）"
                    continue  # 跳过自动填充
                elif transport_type in ("飞机", "高铁"):
                    # 🔴 混合交通方式：根据已有type过滤，不跨类型填充
                    type_filtered = _filter_by_user_mode(available_items, transport_type)
                    if type_filtered:
                        available_items = type_filtered
                    else:
                        print(f"[WARN] {key}飞常准API有数据但无{transport_type}类型班次，保留type={transport_type}，不自动填充")
                        transport["type"] = transport_type
                        transport["_verified"] = False
                        transport["_verified_source"] = f"未验证（飞常准API无{transport_type}数据）"
                        continue
                chosen = available_items[0]
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
                if key == "departure_transport":
                    used_departure_num = chosen["num"]
                print(f"[OK] 飞常准API自动填充: {chosen['num']} type={transport.get('type','')}")

            elif flight_num and not all_vf_items:
                # 飞常准API无数据，保留AI生成的班次号但标记为未验证（用户需要看到班次信息）
                issue = f"{key}飞常准API无{dep_city}-{arr_city}数据，班次{flight_num}保留但标记为未验证"
                print(f"[WARN] {issue}")
                result["issues"].append(issue)
                transport["_verified"] = False
                transport["_verified_source"] = "未验证（飞常准API无数据）"
                transport["note"] = (transport.get("note", "") + "（⚠️ 此班次来自AI规划，飞常准API暂无数据，请自行核实）").strip()

            elif not flight_num and not all_vf_items:
                # 飞常准API无数据，AI也没填班次号 → 可接受（保持现状）
                pass

        # 日期年份校验：确保班次日期与出行日期一致
        if transport.get("_verified") and travel_date_obj:
            vf_date = transport.get("_verified_date", "")
            if vf_date and vf_date != travel_date:
                print(f"[WARN] {key}班次{transport.get('flight_number','')}验证日期{vf_date}与出行日期{travel_date}不一致")
                # 不标记为invalid，但添加提醒
                transport["note"] = (transport.get("note", "") + f"（班次日期为{vf_date}，请核实）").strip()

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

    # 交通类型一致性校验：确保行程卡片与交通卡片描述的交通方式一致
    _check_transport_type_consistency(trip_data, dep_trans, ret_trans)


def _check_transport_type_consistency(trip_data: dict, dep_trans: dict, ret_trans: dict):
    """校验行程卡片中的交通描述与交通卡片的type是否一致，确保交通卡片和行程卡片内容统一
    原则：交通卡片（departure_transport/return_transport）的type是权威来源，行程卡片中的描述必须与之匹配"""
    dep_type = str(dep_trans.get("type", "")).strip()
    ret_type = str(ret_trans.get("type", "")).strip()

    # 确保departure_transport和return_transport的type字段不为空（从flight_number推断）
    if not dep_type and dep_trans.get("flight_number"):
        fn = dep_trans.get("flight_number", "").upper()
        if any(fn.startswith(p) for p in ("CA", "MU", "CZ", "HU", "3U", "MF", "ZH", "SC", "FM", "HO")):
            dep_type = "飞机"; dep_trans["type"] = "飞机"
        elif any(fn.startswith(p) for p in ("G", "D", "C", "K", "T", "Z")):
            dep_type = "高铁"; dep_trans["type"] = "高铁"
    if not ret_type and ret_trans.get("flight_number"):
        fn = ret_trans.get("flight_number", "").upper()
        if any(fn.startswith(p) for p in ("CA", "MU", "CZ", "HU", "3U", "MF", "ZH", "SC", "FM", "HO")):
            ret_type = "飞机"; ret_trans["type"] = "飞机"
        elif any(fn.startswith(p) for p in ("G", "D", "C", "K", "T", "Z")):
            ret_type = "高铁"; ret_trans["type"] = "高铁"

    # 如果type仍为空但从note/duration可推断，尝试推断
    if not dep_type and dep_trans:
        note = dep_trans.get("note", "") + dep_trans.get("duration", "")
        if any(kw in note for kw in ["飞机", "航班", "飞行"]):
            dep_type = "飞机"; dep_trans["type"] = "飞机"
        elif any(kw in note for kw in ["高铁", "火车", "动车", "列车"]):
            dep_type = "高铁"; dep_trans["type"] = "高铁"
    if not ret_type and ret_trans:
        note = ret_trans.get("note", "") + ret_trans.get("duration", "")
        if any(kw in note for kw in ["飞机", "航班", "飞行"]):
            ret_type = "飞机"; ret_trans["type"] = "飞机"
        elif any(kw in note for kw in ["高铁", "火车", "动车", "列车"]):
            ret_type = "高铁"; ret_trans["type"] = "高铁"

    # 交通方式关键词映射：用于检测和替换行程卡片中的不一致描述
    # 每种交通方式定义了其关键词，以及检测到冲突时的替换词
    dep_keywords = {
        "飞机": {"keywords": ["飞机", "航班", "登机", "候机", "值机", "机票", "飞行"], "replace": "飞机"},
        "高铁": {"keywords": ["高铁", "火车", "动车", "列车", "车票", "候车", "铁路"], "replace": "高铁"},
        "大巴": {"keywords": ["大巴", "长途汽车", "客运", "班车"], "replace": "大巴"},
        "自驾": {"keywords": ["自驾", "开车", "驾车", "驾驶"], "replace": "自驾"},
        "公交": {"keywords": ["公交", "地铁", "轻轨", "BRT"], "replace": "公交"},
    }

    def _get_conflict_keywords(expected_type):
        """获取所有与期望类型冲突的关键词（即其他类型的关键词）"""
        conflicts = []
        for trans_type, info in dep_keywords.items():
            if trans_type != expected_type:
                conflicts.extend(info["keywords"])
        return conflicts

    def _fix_text_inconsistency(text, expected_type, field_name, day_info):
        """检查文本中是否有与期望交通方式冲突的表述，有则替换为期望类型"""
        if not text or not isinstance(text, str) or not expected_type:
            return text
        if expected_type not in dep_keywords:
            return text
        expected_info = dep_keywords[expected_type]
        conflict_kws = _get_conflict_keywords(expected_type)
        for kw in conflict_kws:
            if kw in text:
                # 找到冲突关键词，替换为期望类型的代表词
                expected_kw = expected_info["replace"]
                print(f"[CONSISTENCY] {day_info}的{field_name}中包含'{kw}'（暗示非{expected_type}），但交通卡片为{expected_type}，已替换为'{expected_kw}'")
                text = text.replace(kw, expected_kw)
        return text

    # 检查行程备注
    if dep_type and trip_data.get("note"):
        trip_data["note"] = _fix_text_inconsistency(trip_data["note"], dep_type, "note", "行程备注")

    # 检查每个行程日卡片中的交通描述
    itinerary = trip_data.get("itinerary", [])
    if not itinerary:
        return

    for day_data in itinerary:
        if not isinstance(day_data, dict):
            continue
        day_num = day_data.get("day", 0)
        # 确定当前日对应的期望交通方式
        is_first_day = (day_num == 1)
        is_last_day = (day_num == len(itinerary))
        expected_transport = None
        if is_first_day and dep_type:
            expected_transport = dep_type
        elif is_last_day and ret_type:
            expected_transport = ret_type

        if not expected_transport:
            continue

        day_info = f"Day{day_num}"

        # 检查每个时段景点中的reason、note、route_detail、spot字段
        for slot_key in ["morning", "afternoon", "evening"]:
            slot = day_data.get(slot_key, {})
            if not slot or not isinstance(slot, dict):
                continue
            for field in ["reason", "note", "route_detail", "spot"]:
                if slot.get(field):
                    slot[field] = _fix_text_inconsistency(slot[field], expected_transport, f"{slot_key}.{field}", day_info)

        # 检查日的交通建议字段
        if day_data.get("transport"):
            day_data["transport"] = _fix_text_inconsistency(day_data["transport"], expected_transport, "transport", day_info)

        # 检查午餐/晚餐/酒店推荐中是否包含交通方式描述
        for extra_field in ["lunch", "dinner", "hotel", "breakfast"]:
            if day_data.get(extra_field):
                day_data[extra_field] = _fix_text_inconsistency(day_data[extra_field], expected_transport, extra_field, day_info)

    # 额外强制：第一天的transport字段必须与出发交通type一致
    if dep_type and itinerary and isinstance(itinerary[0], dict):
        day0 = itinerary[0]
        if day0.get("transport"):
            # 二次确认：如果transport字段中仍包含冲突关键词，直接重写为期望类型
            conflict_kws = _get_conflict_keywords(dep_type)
            for kw in conflict_kws:
                if kw in str(day0["transport"]):
                    print(f"[CONSISTENCY] 强制重写Day1的transport字段：'{day0['transport']}' → '{dep_type}'")
                    day0["transport"] = dep_type
                    break
    if ret_type and itinerary and len(itinerary) >= 2 and isinstance(itinerary[-1], dict):
        last_day = itinerary[-1]
        if last_day.get("transport"):
            conflict_kws = _get_conflict_keywords(ret_type)
            for kw in conflict_kws:
                if kw in str(last_day["transport"]):
                    print(f"[CONSISTENCY] 强制重写Day{len(itinerary)}的transport字段：'{last_day['transport']}' → '{ret_type}'")
                    last_day["transport"] = ret_type
                    break


def _ensure_transport_data(trip_data: dict, departure_city: str, dest: str, 
                           variflight_data: dict = None, days: int = 3,
                           route_schedule: dict = None) -> dict:
    """确保行程数据始终包含往返交通信息，缺失时从飞常准API数据自动填充，绝不使用本地预存数据"""
    user_transport = trip_data.get("_transport_mode", "")

    vf_flights = []
    vf_trains = []
    if variflight_data and variflight_data.get("success"):
        vf_flights = variflight_data.get("flights", [])
        vf_trains = variflight_data.get("trains", [])

    # 🔴 飞常准API是唯一数据源，不使用预存COMMON_ROUTES回退

    # 构建默认交通模板
    def _build_transport_template(is_return=False, existing_type_hint=""):
        t = {
            "type": "", "flight_number": "", "departure_time": "", "arrival_time": "",
            "station": "", "duration": "", "cost": "", "cross_day": False,
            "station_to_hotel": "", "note": "", "transfers": [],
            "_verified": False, "_verified_source": "自动填充"
        }
        # 🔴 根据用户交通方式选择优先匹配：用户选飞机时只用航班，选高铁时只用火车
        if user_transport == "飞机" and vf_flights:
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
        elif user_transport == "高铁" and vf_trains:
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
        elif vf_flights and user_transport != "高铁":
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
        elif vf_trains and user_transport != "飞机":
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
            # 🔴 飞常准API是唯一数据源，无API数据时不从本地预存数据填充
            from feichangzhun_service import judge_transport
            try:
                ti = judge_transport(departure_city, dest)
            except Exception as e:
                print(f"[WARN] 交通判断失败: {e}")
                ti = None
            # 不再回退COMMON_ROUTES，只标记为未验证
            t["_verified"] = False
            t["_verified_source"] = "飞常准API无数据，未验证"
            if user_transport:
                t["type"] = user_transport
                t["note"] = f"（⚠️ {user_transport}班次未验证，请自行核实）"
            elif ti:
                t["type"] = ti.get("mode", "")
                t["note"] = "暂无实时班次数据，请自行在携程查询"
            else:
                # 所有数据源都无数据时，优先使用用户指定类型，其次已有类型提示，最后默认交通方式
                if user_transport:
                    t["type"] = user_transport
                elif existing_type_hint:
                    t["type"] = existing_type_hint
                else:
                    t["type"] = ti.get("mode", "高铁").split("/")[0] if ti else "高铁"
                t["note"] = "暂无实时班次数据，请自行在携程查询"
        return t

    # 从Variflight数据合并缺失字段到已有transport（不覆盖已有值，且不改变已有交通类型）
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
        # 🔴 只在type为空时根据Variflight数据设置type，且必须尊重用户交通方式选择
        cur_type = str(transport.get("type", "")).strip()
        if not cur_type:
            if vf_item.get("from_airport"):
                transport["type"] = "飞机"
            elif vf_item.get("from_station"):
                transport["type"] = "高铁"
        elif user_transport and user_transport in ("飞机", "高铁"):
            # 🔴 用户已指定交通方式，VF数据不能覆盖type
            vf_type = "飞机" if vf_item.get("from_airport") else ("高铁" if vf_item.get("from_station") else "")
            if vf_type and vf_type != user_transport:
                print(f"[TRANSPORT] VF数据type={vf_type}与用户选择{user_transport}不一致，保持用户选择")
                # 不覆盖type，但可以合并其他字段
        if not transport.get("_verified"):
            transport["_verified"] = True
            transport["_verified_source"] = "飞常准实时API（合并填充）"

    # 确保去程交通
    if not trip_data.get("departure_transport") or not isinstance(trip_data.get("departure_transport"), dict):
        print("[TRANSPORT] 去程交通缺失，自动填充默认交通信息")
        trip_data["departure_transport"] = _build_transport_template()
    elif not trip_data["departure_transport"].get("flight_number"):
        # 有type但缺flight_number，先检查是否为低成本交通方式
        dep_type = str(trip_data["departure_transport"].get("type", "")).strip()
        is_low_cost = dep_type in ("大巴", "自驾", "汽车", "打车", "公交", "城际", "步行", "地铁")
        if is_low_cost:
            # 低成本交通方式不需要flight_number，直接标记为已验证
            print(f"[TRANSPORT] 去程交通为低成本出行({dep_type})，跳过航班验证")
            trip_data["departure_transport"]["_verified"] = True
            trip_data["departure_transport"]["_verified_source"] = f"低成本出行({dep_type})"
            if not trip_data["departure_transport"].get("note"):
                trip_data["departure_transport"]["note"] = f"{dep_type}出行，建议通过高德地图查询实时路况"
        elif dep_type == "飞机" and vf_flights:
            chosen = vf_flights[0]
            print(f"[TRANSPORT] 去程交通(type=飞机)缺flight_number，从飞常准API航班合并: {chosen['num']}")
            _merge_vf_to_transport(trip_data["departure_transport"], chosen)
        elif dep_type == "高铁" and vf_trains:
            chosen = vf_trains[0]
            print(f"[TRANSPORT] 去程交通(type=高铁)缺flight_number，从飞常准API火车合并: {chosen['num']}")
            _merge_vf_to_transport(trip_data["departure_transport"], chosen)
        elif vf_flights or vf_trains:
            # 🔴 必须尊重用户交通方式选择：用户选飞机时只用航班，选高铁时只用火车
            chosen = None
            if user_transport == "飞机" and vf_flights:
                chosen = vf_flights[0]
            elif user_transport == "高铁" and vf_trains:
                chosen = vf_trains[0]
            elif not user_transport:
                # 🔴 混合交通或无用户指定：根据已有type选择数据源，不跨类型回退
                if dep_type == "飞机" and vf_flights:
                    chosen = vf_flights[0]
                elif dep_type == "高铁" and vf_trains:
                    chosen = vf_trains[0]
                elif dep_type == "飞机" and not vf_flights:
                    # 飞机类型但无航班数据，不降级到高铁
                    print(f"[TRANSPORT] 去程已设为飞机但飞常准API无航班数据，保留type=飞机")
                elif dep_type == "高铁" and not vf_trains:
                    # 高铁类型但无火车数据，不降级到飞机
                    print(f"[TRANSPORT] 去程已设为高铁但飞常准API无火车数据，保留type=高铁")
                elif vf_flights:
                    chosen = vf_flights[0]
                elif vf_trains:
                    chosen = vf_trains[0]
            if chosen:
                print(f"[TRANSPORT] 去程交通缺flight_number，从飞常准API合并: {chosen['num']}")
                _merge_vf_to_transport(trip_data["departure_transport"], chosen)
            else:
                print(f"[TRANSPORT] 去程交通缺flight_number，但飞常准API无匹配类型数据，保留type={dep_type}")
        elif not trip_data["departure_transport"].get("type"):
            # AI生成了transport但缺type和flight_number，从静态数据补全type
            print("[TRANSPORT] 去程交通信息不完整且无API数据，补全type")
            from feichangzhun_service import judge_transport
            try:
                ti = judge_transport(departure_city, dest)
                # 🔴 用户指定了交通方式，优先使用
                if user_transport:
                    trip_data["departure_transport"]["type"] = user_transport
                else:
                    trip_data["departure_transport"]["type"] = ti.get("mode", "高铁").split("/")[0] if ti else "高铁"
            except Exception:
                trip_data["departure_transport"]["type"] = user_transport or "高铁"
            trip_data["departure_transport"]["note"] = (trip_data["departure_transport"].get("note", "") + " 暂无实时班次数据，请自行在携程查询").strip()
        else:
            # 有type但无flight_number且无API数据，保留AI全部数据，仅添加提示
            print("[TRANSPORT] 去程交通有type无班次号，保留AI数据并添加提示")
            trip_data["departure_transport"]["note"] = (trip_data["departure_transport"].get("note", "") + " 暂无实时班次数据，请自行在携程查询").strip()

    # 确保返程交通
    if not trip_data.get("return_transport") or not isinstance(trip_data.get("return_transport"), dict):
        print("[TRANSPORT] 返程交通缺失，自动填充默认交通信息")
        trip_data["return_transport"] = _build_transport_template(is_return=True)
    elif not trip_data["return_transport"].get("flight_number"):
        ret_type = str(trip_data["return_transport"].get("type", "")).strip()
        is_low_cost = ret_type in ("大巴", "自驾", "汽车", "打车", "公交", "城际", "步行", "地铁")
        if is_low_cost:
            print(f"[TRANSPORT] 返程交通为低成本出行({ret_type})，跳过航班验证")
            trip_data["return_transport"]["_verified"] = True
            trip_data["return_transport"]["_verified_source"] = f"低成本出行({ret_type})"
            if not trip_data["return_transport"].get("note"):
                trip_data["return_transport"]["note"] = f"{ret_type}出行，建议通过高德地图查询实时路况"
        elif ret_type == "飞机" and vf_flights:
            chosen = vf_flights[0]
            print(f"[TRANSPORT] 返程交通(type=飞机)缺flight_number，从飞常准API航班合并: {chosen['num']}")
            _merge_vf_to_transport(trip_data["return_transport"], chosen)
        elif ret_type == "高铁" and vf_trains:
            chosen = vf_trains[0]
            print(f"[TRANSPORT] 返程交通(type=高铁)缺flight_number，从飞常准API火车合并: {chosen['num']}")
            _merge_vf_to_transport(trip_data["return_transport"], chosen)
        elif vf_flights or vf_trains:
            # 🔴 必须尊重用户交通方式选择：用户选飞机时只用航班，选高铁时只用火车
            chosen = None
            if user_transport == "飞机" and vf_flights:
                chosen = vf_flights[0]
            elif user_transport == "高铁" and vf_trains:
                chosen = vf_trains[0]
            elif not user_transport:
                # 🔴 混合交通或无用户指定：根据已有type选择数据源，不跨类型回退
                if ret_type == "飞机" and vf_flights:
                    chosen = vf_flights[0]
                elif ret_type == "高铁" and vf_trains:
                    chosen = vf_trains[0]
                elif ret_type == "飞机" and not vf_flights:
                    # 飞机类型但无航班数据，不降级到高铁
                    print(f"[TRANSPORT] 返程已设为飞机但飞常准API无航班数据，保留type=飞机")
                elif ret_type == "高铁" and not vf_trains:
                    # 高铁类型但无火车数据，不降级到飞机
                    print(f"[TRANSPORT] 返程已设为高铁但飞常准API无火车数据，保留type=高铁")
                elif vf_flights:
                    chosen = vf_flights[0]
                elif vf_trains:
                    chosen = vf_trains[0]
            if chosen:
                print(f"[TRANSPORT] 返程交通缺flight_number，从飞常准API合并: {chosen['num']}")
                _merge_vf_to_transport(trip_data["return_transport"], chosen)
            else:
                print(f"[TRANSPORT] 返程交通缺flight_number，但飞常准API无匹配类型数据，保留type={ret_type}")
        elif not trip_data["return_transport"].get("type"):
            # AI生成了transport但缺type和flight_number，从静态数据补全type
            print("[TRANSPORT] 返程交通信息不完整且无API数据，补全type")
            from feichangzhun_service import judge_transport
            try:
                ti = judge_transport(dest, departure_city)
                # 🔴 用户指定了交通方式，优先使用
                if user_transport:
                    trip_data["return_transport"]["type"] = user_transport
                else:
                    trip_data["return_transport"]["type"] = ti.get("mode", "高铁").split("/")[0] if ti else "高铁"
            except Exception:
                trip_data["return_transport"]["type"] = user_transport or "高铁"
            trip_data["return_transport"]["note"] = (trip_data["return_transport"].get("note", "") + " 暂无实时班次数据，请自行在携程查询").strip()
        else:
            # 有type但无flight_number且无API数据，保留AI全部数据，仅添加提示
            print("[TRANSPORT] 返程交通有type无班次号，保留AI数据并添加提示")
            trip_data["return_transport"]["note"] = (trip_data["return_transport"].get("note", "") + " 暂无实时班次数据，请自行在携程查询").strip()

    return trip_data


def _detect_mixed_transport_from_text(text: str) -> dict:
    """从用户输入文本中检测混合交通方式需求（出发和返程不同交通工具）
    返回: {"has_mixed": bool, "departure_mode": str, "return_mode": str, "departure_cn": str, "return_cn": str}
    示例: "出发坐飞机，返程坐高铁" → {"has_mixed": True, "departure_mode": "plane", "return_mode": "train", ...}"""
    if not text:
        return {"has_mixed": False, "departure_mode": "", "return_mode": "", "departure_cn": "", "return_cn": ""}
    
    # 检测出发和返程各自指定的交通方式
    dep_mode = ""
    ret_mode = ""
    
    # 出发相关关键词检测
    dep_keywords = ["出发", "去程", "去时", "前往", "去的时候"]
    ret_keywords = ["返程", "回程", "回来", "返回", "回来的时候", "回的时候"]
    
    # 交通方式关键词映射
    plane_kw = ["飞机", "航班", "飞行", "机票", "登机", "值机", "乘机"]
    train_kw = ["高铁", "火车", "动车", "列车", "车票", "铁路"]
    taxi_kw = ["打车", "出租车", "的士"]
    drive_kw = ["自驾", "开车", "驾车"]
    
    def detect_mode(text_part: str) -> str:
        if any(kw in text_part for kw in plane_kw):
            return "plane"
        if any(kw in text_part for kw in train_kw):
            return "train"
        if any(kw in text_part for kw in taxi_kw):
            return "taxi"
        if any(kw in text_part for kw in drive_kw):
            return "selfdrive"
        return ""
    
    # 查找出发和返程的交通方式
    # 策略：按"出发"/"返程"关键词分割文本
    has_dep_keyword = any(kw in text for kw in dep_keywords)
    has_ret_keyword = any(kw in text for kw in ret_keywords)
    
    if has_dep_keyword and has_ret_keyword:
        # 找到出发和返程各自的位置
        dep_pos = -1
        ret_pos = -1
        for kw in dep_keywords:
            idx = text.find(kw)
            if idx >= 0 and (dep_pos < 0 or idx < dep_pos):
                dep_pos = idx
        for kw in ret_keywords:
            idx = text.find(kw)
            if idx >= 0 and (ret_pos < 0 or idx < ret_pos):
                ret_pos = idx
        
        if dep_pos >= 0 and ret_pos >= 0 and dep_pos != ret_pos:
            # 出发在前、返程在后
            if dep_pos < ret_pos:
                dep_text = text[dep_pos:ret_pos]
                ret_text = text[ret_pos:]
            else:
                ret_text = text[ret_pos:dep_pos]
                dep_text = text[dep_pos:]
            dep_mode = detect_mode(dep_text)
            ret_mode = detect_mode(ret_text)
    
    # 如果没检测到混合，尝试另一种模式：先提到交通工具再提到"往返"
    if not dep_mode or not ret_mode:
        # 检测"去飞机回高铁"、"飞机去高铁回"等模式
        import re
        patterns = [
            (r'(飞机|航班).*(高铁|火车|动车)', "plane", "train"),
            (r'(高铁|火车|动车).*(飞机|航班)', "train", "plane"),
            (r'去.*(飞机|航班).*回.*(高铁|火车|动车)', "plane", "train"),
            (r'去.*(高铁|火车|动车).*回.*(飞机|航班)', "train", "plane"),
        ]
        for pattern, first_mode, second_mode in patterns:
            if re.search(pattern, text):
                if not dep_mode:
                    dep_mode = first_mode
                if not ret_mode:
                    ret_mode = second_mode
                break
    
    if dep_mode and ret_mode and dep_mode != ret_mode:
        cn_map = {"plane": "飞机", "train": "高铁", "taxi": "打车", "selfdrive": "自驾"}
        return {
            "has_mixed": True,
            "departure_mode": dep_mode,
            "return_mode": ret_mode,
            "departure_cn": cn_map.get(dep_mode, dep_mode),
            "return_cn": cn_map.get(ret_mode, ret_mode),
        }
    
    return {"has_mixed": False, "departure_mode": "", "return_mode": "", "departure_cn": "", "return_cn": ""}


def _enforce_mixed_transport(trip_data: dict, mixed_transport: dict):
    """强制校验混合交通方式：确保出发和返程交通类型与用户要求一致"""
    if not mixed_transport or not mixed_transport.get("has_mixed"):
        return
    dep_cn = mixed_transport.get("departure_cn", "")
    ret_cn = mixed_transport.get("return_cn", "")
    if not dep_cn or not ret_cn:
        return
    
    # 强制修正出发交通
    dep_trans = trip_data.get("departure_transport", {})
    if dep_trans:
        current_type = dep_trans.get("type", "")
        if current_type != dep_cn:
            print(f"[MIXED] 出发交通类型修正: '{current_type}' → '{dep_cn}'")
            dep_trans["type"] = dep_cn
            # 如果类型改变了，清除旧班次信息（避免飞机类型配高铁班次号）
            if current_type and current_type != dep_cn:
                dep_trans["flight_number"] = ""
                dep_trans["departure_time"] = ""
                dep_trans["arrival_time"] = ""
                dep_trans["station"] = ""
                dep_trans["duration"] = f"约{dep_cn}出行"
    
    # 强制修正返程交通
    ret_trans = trip_data.get("return_transport", {})
    if ret_trans:
        current_type = ret_trans.get("type", "")
        if current_type != ret_cn:
            print(f"[MIXED] 返程交通类型修正: '{current_type}' → '{ret_cn}'")
            ret_trans["type"] = ret_cn
            if current_type and current_type != ret_cn:
                ret_trans["flight_number"] = ""
                ret_trans["departure_time"] = ""
                ret_trans["arrival_time"] = ""
                ret_trans["station"] = ""
                ret_trans["duration"] = f"约{ret_cn}出行"


def _detect_transport_mode_from_text(text: str) -> str:
    """从用户输入文本中检测交通方式变更意图
    返回对应的transport_mode值（plane/train/taxi/selfdrive），无检测到返回空字符串
    注意：检测顺序很重要，先检测更具体的词汇"""
    if not text:
        return ""
    text_lower = text.lower()
    # 高铁/火车/动车检测（优先级最高，因为"高铁"比"飞机"更具体）
    if any(kw in text for kw in ["高铁", "火车", "动车", "列车", "车票", "候车", "铁路"]):
        return "train"
    # 飞机/航班检测
    if any(kw in text for kw in ["飞机", "航班", "飞行", "机票", "登机", "候机", "值机", "乘机"]):
        return "plane"
    # 打车/出租车检测
    if any(kw in text for kw in ["打车", "出租车", "的士", "滴滴"]):
        return "taxi"
    # 自驾检测
    if any(kw in text for kw in ["自驾", "开车", "驾车", "驾驶"]):
        return "selfdrive"
    return ""