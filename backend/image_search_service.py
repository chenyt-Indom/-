"""图片搜索服务：Wikipedia API → Wikimedia Commons → DeepSeek → text_to_image 四级兜底，确保必定有图"""
import asyncio
import httpx
import urllib.parse
from config import IMG_BASE
from deepseek_service import deepseek_search_images


async def search_wikipedia_image(query: str, lang: str = "zh") -> list:
    """通过Wikipedia API搜索页面主图，返回真实图片URL列表"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_url = f"https://{lang}.wikipedia.org/w/api.php"
            # 第一步：搜索页面
            resp = await client.get(search_url, params={
                "action": "query", "list": "search",
                "srsearch": query, "srlimit": "3", "format": "json",
            })
            data = resp.json()
            pages = data.get("query", {}).get("search", [])
            if not pages:
                return images
            # 第二步：批量获取页面主图
            titles = "|".join([p["title"] for p in pages])
            resp2 = await client.get(search_url, params={
                "action": "query", "titles": titles,
                "prop": "pageimages", "format": "json",
                "pithumbsize": "800",
            })
            data2 = resp2.json()
            pgs = data2.get("query", {}).get("pages", {})
            for pid, pg in pgs.items():
                thumb = pg.get("thumbnail", {}).get("source", "")
                if thumb:
                    images.append({
                        "url": thumb, "title": pg.get("title", ""),
                        "quality": 70, "source": f"wikipedia_{lang}",
                    })
    except Exception:
        pass
    return images


async def search_wikimedia(query: str, limit: int = 5) -> list:
    """搜索Wikimedia Commons真实图片，返回按评分排序的图片URL列表"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
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
                url = info.get("thumburl") or info.get("url", "")
                if not url:
                    continue
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
                w = int(info.get("width", 0))
                if w >= 2000: quality += 30
                elif w >= 1000: quality += 20
                elif w >= 500: quality += 10
                images.append({
                    "url": url, "title": pg.get("title", ""),
                    "width": w, "height": info.get("height", 0),
                    "quality": quality, "source": "wikimedia",
                })
            images.sort(key=lambda x: x["quality"], reverse=True)
    except Exception:
        pass
    return images


async def _multi_source_search(queries: list, limit: int = 5) -> list:
    """多源图片搜索：Wikipedia(zh+en) → Wikimedia → DeepSeek"""
    for q in queries:
        # 1. Wikipedia 中文
        imgs = await search_wikipedia_image(q, "zh")
        if imgs: return imgs
        # 2. Wikipedia 英文
        imgs = await search_wikipedia_image(q, "en")
        if imgs: return imgs
        # 3. Wikimedia Commons
        imgs = await search_wikimedia(q, limit)
        if imgs: return imgs
        # 4. DeepSeek（补充源）
        imgs = await deepseek_search_images(q, limit)
        if imgs: return imgs
    return []


def _text_to_image_url(query: str) -> str:
    """text_to_image API 兜底URL，确保100%有图"""
    prompt = f"{query}, travel photography, realistic, 4K, high quality"
    return f"{IMG_BASE}?prompt={urllib.parse.quote(prompt)}&image_size=landscape_16_9"


async def get_best_spot_image(name: str, city: str) -> str:
    """获取景点最佳图片URL（多源搜索，确保必定返回有效URL）"""
    queries = [
        f"{name} {city}",
        f"{name} 景点",
        f"{name} China landmark",
        f"{name}",
    ]
    imgs = await _multi_source_search(queries, 5)
    if imgs:
        return imgs[0]["url"]
    # 最终兜底：text_to_image
    return _text_to_image_url(f"{name} {city} landmark")


async def get_best_hotel_image(name: str, area: str) -> str:
    """获取酒店最佳图片URL（多源搜索，确保必定返回有效URL）"""
    queries = [
        f"{name} hotel {area}",
        f"{name} 酒店",
        f"{name} {area}",
        f"{name}",
    ]
    imgs = await _multi_source_search(queries, 5)
    if imgs:
        return imgs[0]["url"]
    return _text_to_image_url(f"{name} hotel {area} facade")


async def search_images(query: str, limit: int = 5) -> dict:
    """综合图片搜索API：多源搜索，确保必定返回图片"""
    imgs = await _multi_source_search([query], limit)
    if imgs:
        return {"success": True, "images": imgs, "source": imgs[0].get("source", "unknown")}
    return {
        "success": True,
        "images": [{"url": _text_to_image_url(query), "quality": 50, "source": "text_to_image"}],
        "source": "text_to_image",
    }