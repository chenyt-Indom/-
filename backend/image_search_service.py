"""图片搜索服务：真实照片搜索链 — Wikimedia Commons → Wikipedia → Flickr → 无图标记"""
import asyncio
import httpx
import urllib.parse
import re


async def search_wikipedia_image(query: str, lang: str = "zh") -> list:
    """通过Wikipedia API搜索页面主图，返回真实图片URL列表"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            search_url = f"https://{lang}.wikipedia.org/w/api.php"
            resp = await client.get(search_url, params={
                "action": "query", "list": "search",
                "srsearch": query, "srlimit": "3", "format": "json",
            })
            data = resp.json()
            pages = data.get("query", {}).get("search", [])
            if not pages:
                return images
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


async def search_wikimedia(query: str, limit: int = 8) -> list:
    """搜索Wikimedia Commons真实图片，按质量评分排序"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_url = "https://commons.wikimedia.org/w/api.php"
            # 搜索图片文件
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
                # 过滤非照片文件（图标、标志、SVG等）
                mime = info.get("mime", "")
                if "svg" in mime or "gif" in mime:
                    continue
                meta = info.get("extmetadata", {})
                # 质量评分
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
                # 图片描述相关性加分
                desc = meta.get("ImageDescription", {}).get("value", "")
                if any(kw in desc.lower() for kw in ["china", "landmark", "building", "temple", "mountain"]):
                    quality += 10
                images.append({
                    "url": url, "title": pg.get("title", ""),
                    "width": w, "height": info.get("height", 0),
                    "quality": quality, "source": "wikimedia",
                })
            images.sort(key=lambda x: x["quality"], reverse=True)
    except Exception:
        pass
    return images


async def search_flickr(query: str, limit: int = 5) -> list:
    """搜索Flickr公开图片（通过网页搜索，无需API key）"""
    images = []
    try:
        # 使用Flickr的公开搜索页面
        search_url = f"https://www.flickr.com/search/?text={urllib.parse.quote(query)}&license=4,5,6,7,8,9,10"
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            # 提取图片URL
            html = resp.text
            img_urls = re.findall(r'//live\.staticflickr\.com/\d+/\d+_[a-f0-9]+_[a-z]\.jpg', html)
            seen = set()
            for url in img_urls:
                full_url = "https:" + url
                if full_url not in seen:
                    seen.add(full_url)
                    images.append({
                        "url": full_url, "quality": 60,
                        "source": "flickr",
                    })
                    if len(images) >= limit:
                        break
    except Exception:
        pass
    return images


async def _multi_source_search(queries: list, limit: int = 8) -> list:
    """多源真实照片搜索：Wikimedia → Wikipedia(zh) → Wikipedia(en) → Flickr"""
    for q in queries:
        # 并行搜索所有源，取最快返回结果
        results = await asyncio.gather(
            search_wikimedia(q, limit),
            search_wikipedia_image(q, "zh"),
            search_wikipedia_image(q, "en"),
            search_flickr(q, limit),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list) and r:
                return r
    return []


async def get_best_spot_image(name: str, city: str) -> str:
    """获取景点最佳真实照片URL（多源搜索，找不到真实照片时返回空字符串）"""
    queries = [
        f"{name} {city}",
        f"{name} 景点",
        f"{name} China landmark",
        f"{name}",
    ]
    imgs = await _multi_source_search(queries, 8)
    if imgs:
        return imgs[0]["url"]
    return ""  # 找不到真实照片，返回空字符串让前端用占位图


async def get_best_hotel_image(name: str, area: str) -> str:
    """获取酒店最佳真实照片URL（多源搜索，找不到真实照片时返回空字符串）"""
    queries = [
        f"{name} hotel {area}",
        f"{name} 酒店",
        f"{name} {area}",
        f"{name}",
    ]
    imgs = await _multi_source_search(queries, 8)
    if imgs:
        return imgs[0]["url"]
    return ""  # 找不到真实照片，返回空字符串让前端用占位图


async def search_images(query: str, limit: int = 5) -> dict:
    """综合图片搜索API：多源搜索真实照片"""
    imgs = await _multi_source_search([query], limit)
    if imgs:
        return {"success": True, "images": imgs, "source": imgs[0].get("source", "unknown")}
    return {"success": True, "images": [], "source": "none"}