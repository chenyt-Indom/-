"""Pydantic 数据模型"""
from pydantic import BaseModel
from typing import List


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
    pace: str = "moderate"  # 游玩节奏: "relaxed"=休闲, "moderate"=适中, "fast"=快速