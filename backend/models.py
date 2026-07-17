"""Pydantic 数据模型"""
from pydantic import BaseModel
from typing import List, Optional


class TripRequest(BaseModel):
    """行程请求体"""
    destination: str
    days: int = 3
    budget: str = ""
    budget_type: str = "total"  # "total"=总预算, "aa"=AA制
    interests: List[str] = []
    start_date: str = ""  # 出发日期 YYYY-MM-DD
    end_date: str = ""    # 返程日期
    departure_city: str = ""  # 出发城市
    travelers: int = 1    # 旅行人数
    pace: int = 50     # 游玩节奏 0-100，0=极慢，100=极快
    is_self_drive: bool = False  # 是否自驾出行
    transport_mode: str = ""  # 出行方式：plane(飞机)/train(高铁)/taxi(打车)/selfdrive(自驾)，空字符串=未选择
    travel_group: str = ""  # 出行人群：youth(青少年)/senior(中老年人)/family(全家出行)，空字符串=未选择