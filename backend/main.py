"""行旅白 AI 旅行规划 - FastAPI 后端"""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from location_routes import router as location_router
from share_routes import router as share_router
from weather_routes import router as weather_router
from detail_routes import router as detail_router
from trip_routes import router as trip_router

app = FastAPI(title="行旅白 AI 旅行规划")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

_static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_static_dir, exist_ok=True)
app.mount("/app", StaticFiles(directory=_static_dir, html=True), name="static")

# 注册各模块路由
app.include_router(location_router)
app.include_router(share_router)
app.include_router(weather_router)
app.include_router(detail_router)
app.include_router(trip_router)