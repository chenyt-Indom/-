"""天气图片本地数据库生成脚本：一次性生成所有天气类型图片并保存到static/weather/"""
import os
import urllib.parse
import httpx
import asyncio

IMG_BASE = "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image"
OUT_DIR = os.path.join(os.path.dirname(__file__), "static", "weather")

# 所有需要覆盖的天气类型及其prompt
WEATHER_TYPES = {
    "晴": "sunny day, clear blue sky, bright sunlight, photorealistic landscape, 4K",
    "少云": "mostly clear sky, few clouds, bright sunlight, photorealistic landscape, 4K",
    "晴间多云": "sunny with scattered clouds, beautiful landscape, photorealistic, 4K",
    "多云": "partly cloudy sky, soft sunlight, realistic landscape, 4K",
    "阴": "overcast sky, dramatic clouds, moody landscape, photorealistic, 4K",
    "阴天": "overcast sky, grey clouds, moody atmosphere, photorealistic, 4K",
    "阵雨": "rain shower, wet landscape, photorealistic, 4K",
    "雷阵雨": "thunderstorm, lightning, dramatic storm sky, photorealistic, 4K",
    "雷阵雨伴有冰雹": "thunderstorm with hail, dramatic sky, lightning, photorealistic, 4K",
    "小雨": "light rain, drizzle, wet pavement, photorealistic, 4K",
    "中雨": "moderate rain, rainy cityscape, realistic, 4K",
    "大雨": "heavy rain, storm, dramatic rain scene, photorealistic, 4K",
    "暴雨": "heavy rainstorm, dramatic storm, photorealistic, 4K",
    "大暴雨": "torrential rain, extreme storm, dramatic weather, photorealistic, 4K",
    "特大暴雨": "extreme rainstorm, catastrophic weather, dramatic scene, photorealistic, 4K",
    "冻雨": "freezing rain, ice storm, glazed tree branches, photorealistic, 4K",
    "雨": "rain, wet landscape, rainy atmosphere, photorealistic, 4K",
    "雨夹雪": "sleet, rain and snow mixed, winter weather, photorealistic, 4K",
    "小雪": "light snow, winter wonderland, photorealistic, 4K",
    "中雪": "snowy scenery, winter landscape, photorealistic, 4K",
    "大雪": "heavy snow, winter wonderland, photorealistic, 4K",
    "暴雪": "blizzard, heavy snowstorm, dramatic winter scene, photorealistic, 4K",
    "雪": "snow, winter scenery, snowy landscape, photorealistic, 4K",
    "雾": "foggy morning, misty landscape, atmospheric fog, photorealistic, 4K",
    "霾": "hazy cityscape, smog, atmospheric haze, photorealistic, 4K",
    "浮尘": "floating dust, hazy atmosphere, muted landscape, photorealistic, 4K",
    "扬沙": "blowing sand, dusty wind, desert landscape, photorealistic, 4K",
    "沙尘暴": "sandstorm, dramatic dust storm, apocalyptic sky, photorealistic, 4K",
    "强沙尘暴": "severe sandstorm, dramatic dust wall, apocalyptic scene, photorealistic, 4K",
    "大风": "strong wind, trees swaying, dramatic clouds, photorealistic, 4K",
    "台风": "typhoon, hurricane, extreme wind, dramatic stormy sea, photorealistic, 4K",
    "热带风暴": "tropical storm, powerful winds, dramatic ocean waves, photorealistic, 4K",
    "风": "windy weather, swaying trees, dramatic clouds, photorealistic, 4K",
    "热": "hot sunny day, heat wave, bright sun, photorealistic, 4K",
    "冷": "cold winter day, frost, icy landscape, photorealistic, 4K",
}


async def generate_one(client, name, prompt, size="landscape_16_9"):
    """生成单张天气图片并保存"""
    safe_name = name.replace("/", "_").replace("\\", "_")
    out_path = os.path.join(OUT_DIR, f"{safe_name}.jpg")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        print(f"  [跳过] {name} - 已存在")
        return True

    url = f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size={size}"
    try:
        resp = await client.get(url, follow_redirects=True, timeout=60.0)
        if resp.status_code == 200 and len(resp.content) > 500:
            with open(out_path, "wb") as f:
                f.write(resp.content)
            print(f"  [成功] {name} -> {safe_name}.jpg ({len(resp.content)} bytes)")
            return True
        else:
            print(f"  [失败] {name} - HTTP {resp.status_code}, size={len(resp.content)}")
            return False
    except Exception as e:
        print(f"  [错误] {name} - {e}")
        return False


async def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"开始生成天气图片，共 {len(WEATHER_TYPES)} 种天气类型\n")

    async with httpx.AsyncClient(timeout=60.0) as client:
        success = 0
        fail = 0
        for name, prompt in WEATHER_TYPES.items():
            if await generate_one(client, name, prompt):
                success += 1
            else:
                fail += 1
            await asyncio.sleep(1)  # 避免请求过快

    print(f"\n完成！成功: {success}, 失败: {fail}")
    # 列出生成的文件
    files = os.listdir(OUT_DIR)
    print(f"共生成 {len(files)} 个文件")


if __name__ == "__main__":
    asyncio.run(main())