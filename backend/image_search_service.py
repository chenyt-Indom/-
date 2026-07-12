"""图片搜索服务：通过Wikimedia Commons获取真实景点/酒店图片，优先高分图片"""
import httpx
import urllib.parse
from config import IMG_BASE


async def search_wikimedia(query: str, limit: int = 5) -> list:
    """搜索Wikimedia Commons真实图片，返回按评分排序的图片URL列表"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # 第一步：搜索图片文件
            search_url = "https://commons.wikimedia.org/w/api.php"
            resp = await client.get(search_url, params={
                "action": "query", "list": "search",
                "srsearch": query, "srnamespace": "6",
                "srlimit": str(limit), "format": "json",
            })
            data = resp.json()
            pages = data.get("query", {}).get("search", [])
            if not pages:
                return images

            # 第二步：获取图片信息（URL、尺寸、评分）
            titles = "|".join([p["title"] for p in pages])
            resp2 = await client.get(search_url, params={
                "action": "query", "titles": titles,
                "prop": "imageinfo|pageassessments",
                "iiprop": "url|size|extmetadata",
                "iiurlwidth": "800", "format": "json",
            })
            data2 = resp2.json()
            pgs = data2.get("query", {}).get("pages", {})

            for pid, pg in pgs.items():
                if "missing" in pg or "imageinfo" not in pg:
                    continue
                info = pg["imageinfo"][0]
                # 优先使用缩略图URL，没有则用原始URL
                url = info.get("thumburl") or info.get("url", "")
                if not url:
                    continue
                # 评分：从extmetadata获取质量信息
                meta = info.get("extmetadata", {})
                quality = 0
                if meta.get("QualityAssessment"):
                    qa = meta["QualityAssessment"].get("value", "")
                    if "featured" in qa.lower():
                        quality = 100
                    elif "quality" in qa.lower():
                        quality = 80
                    elif "valued" in qa.lower():
                        quality = 60
                # 图片尺寸越大分数越高
                w = int(info.get("width", 0))
                if w >= 2000:
                    quality += 30
                elif w >= 1000:
                    quality += 20
                elif w >= 500:
                    quality += 10
                images.append({
                    "url": url, "title": pg.get("title", ""),
                    "width": w, "height": info.get("height", 0),
                    "quality": quality, "source": "wikimedia",
                })
            # 按评分降序排列
            images.sort(key=lambda x: x["quality"], reverse=True)
    except Exception:
        pass
    return images


async def get_best_spot_image(name: str, city: str) -> str:
    """获取景点最佳真实图片URL，失败时返回text_to_image兜底"""
    # 尝试多种搜索词
    queries = [f"{name} {city} landmark", f"{name} {city}", f"{name} China"]
    for q in queries[:2]:
        imgs = await search_wikimedia(q, 5)
        if imgs:
            return imgs[0]["url"]
    # 兜底：text_to_image API
    prompt = f"{name} {city}, famous landmark, travel photography, realistic, 4K"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


async def get_best_hotel_image(name: str, area: str) -> str:
    """获取酒店最佳真实图片URL，失败时返回text_to_image兜底"""
    queries = [f"{name} hotel {area}", f"{name} hotel", f"{name} {area}"]
    for q in queries[:2]:
        imgs = await search_wikimedia(q, 5)
        if imgs:
            return imgs[0]["url"]
    prompt = f"{name} hotel facade, {area}, luxury hotel exterior, realistic, 4K"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


async def search_images(query: str, limit: int = 5) -> dict:
    """综合图片搜索：Wikimedia + DeepSeek辅助筛选"""
    imgs = await search_wikimedia(query, limit)
    if imgs:
        return {"success": True, "images": imgs, "source": "wikimedia"}
    # 兜底：text_to_image
    prompt = f"{query}, travel photography, realistic, 4K, high quality"
    return {
        "success": True,
        "images": [{"url": f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9",
                     "quality": 50, "source": "text_to_image"}],
        "source": "text_to_image",
    }