"""AI旅行攻略生成器 - FastAPI 后端，提供 /api/generate-trip 接口"""
import os
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="AI旅行攻略生成器")

# 配置跨域，允许小程序本地调试
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

# DeepSeek API 配置
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "your-api-key-here")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"


class TripRequest(BaseModel):
    """请求体：出发地、预算、兴趣爱好"""
    origin: str = ""
    budget: str = ""
    interests: str = ""


def build_prompt(origin: str, budget: str, interests: str) -> str:
    """根据用户输入构建发给 DeepSeek 的提示词"""
    return f"""请为我规划一份详细的旅行攻略：

【出发地】{origin}
【预算】{budget}
【兴趣爱好】{interests}

请按以下格式输出：
1. 推荐目的地及理由
2. 每日行程安排（含景点、餐饮推荐）
3. 预算分配明细
4. 出行注意事项
请用中文回复。"""


@app.get("/api/health")
async def health_check():
    """健康检查接口"""
    return {"status": "ok", "service": "AI旅行攻略生成器"}


@app.post("/api/generate-trip")
async def generate_trip(req: TripRequest):
    """生成旅行攻略：接收用户需求，调用 DeepSeek，返回 JSON 结果"""
    if DEEPSEEK_KEY == "your-api-key-here":
        # 未配置 API Key 时，返回模拟数据用于前端调试
        return {"success": True, "data": {"trip_content": mock_trip(req.origin, req.budget, req.interests)}}

    prompt = build_prompt(req.origin, req.budget, req.interests)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                DEEPSEEK_URL,
                headers={"Authorization": f"Bearer {DEEPSEEK_KEY}", "Content-Type": "application/json"},
                json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": "你是一个资深的旅行规划师。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.7, "max_tokens": 2000,
                },
            )
            resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return {"success": True, "data": {"trip_content": content}}
    except Exception as e:
        return {"success": False, "error": f"AI 服务调用失败：{str(e)}"}


def mock_trip(origin: str, budget: str, interests: str) -> str:
    """未配置 API Key 时返回模拟行程数据，用于前端调试"""
    return f"""【出发地】{origin} | 【预算】{budget} | 【兴趣】{interests}

一、推荐目的地：杭州
二、行程安排：Day1 西湖骑行→断桥残雪→楼外楼晚餐 | Day2 灵隐寺→龙井村品茶→河坊街夜市 | Day3 西溪湿地→返程
三、预算分配：交通40% | 住宿30% | 餐饮20% | 门票10%
四、注意事项：提前订酒店、带雨具、穿舒适鞋子
（提示：设置 DEEPSEEK_API_KEY 环境变量后获取 AI 真实结果）"""


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)