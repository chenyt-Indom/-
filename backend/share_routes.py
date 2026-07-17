"""分享行程接口路由"""
import os
import json
import datetime
import uuid
from fastapi import APIRouter, Request

router = APIRouter()

SHARED_TRIPS_DIR = os.path.join(os.path.dirname(__file__), "shared_trips")
os.makedirs(SHARED_TRIPS_DIR, exist_ok=True)


@router.post("/api/share-trip")
async def share_trip(request: Request):
    """保存行程计划并返回唯一分享链接，分享者可通过链接查看但不可修改"""
    try:
        body = await request.json()
        trip_data = body.get("trip_data", {})
        if not trip_data or not trip_data.get("destination"):
            return {"success": False, "error": "无效的行程数据"}
        # 生成唯一分享ID
        share_id = uuid.uuid4().hex[:12]
        trip_data["_share_id"] = share_id
        trip_data["_share_time"] = datetime.datetime.now().isoformat()
        # 保存到文件
        file_path = os.path.join(SHARED_TRIPS_DIR, f"{share_id}.json")
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(trip_data, f, ensure_ascii=False, indent=2)
        share_url = f"https://lvbaixing.top/app/?share={share_id}"
        return {"success": True, "share_id": share_id, "share_url": share_url}
    except Exception as e:
        return {"success": False, "error": str(e)}


@router.get("/api/shared-trip/{share_id}")
async def get_shared_trip(share_id: str):
    """获取分享的行程数据（只读，不可修改）"""
    file_path = os.path.join(SHARED_TRIPS_DIR, f"{share_id}.json")
    if not os.path.exists(file_path):
        return {"success": False, "error": "分享链接不存在或已过期"}
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            trip_data = json.load(f)
        return {"success": True, "data": trip_data, "readonly": True}
    except Exception as e:
        return {"success": False, "error": str(e)}