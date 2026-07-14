"""图片搜索服务：真实照片搜索链 — 高德POI(多策略) → Bing → Wikimedia → Wikipedia → Flickr → text_to_image兜底"""
import asyncio
import httpx
import urllib.parse
import re
from config import AMAP_KEY, AMAP_POI_URL, IMG_BASE


async def search_amap_photos(name: str, city: str) -> list:
    """高德POI照片搜索：多策略尝试（精确名→简化名→去括号→加景区后缀）"""
    images = []
    # 生成多种搜索关键词
    clean = re.sub(r'[（(].*?[）)]', '', name).strip()  # 去括号内容
    simple = re.sub(r'(风景区|景区|公园|博物馆|寺|庙|塔|阁|楼)$', '', clean).strip()
    keywords_list = [name]
    if clean != name: keywords_list.append(clean)
    if simple and simple != clean and len(simple) >= 2: keywords_list.append(simple)
    if city and len(city) > 0: keywords_list.append(f"{name} {city}")
    seen = set()
    async with httpx.AsyncClient(timeout=8.0) as client:
        for kw in keywords_list[:5]:
            if kw in seen: continue
            seen.add(kw)
            try:
                resp = await client.get(AMAP_POI_URL, params={
                    "key": AMAP_KEY, "keywords": kw, "offset": 10, "extensions": "all",
                })
                data = resp.json()
                if data.get("status") != "1": continue
                for poi in data.get("pois", []):
                    for pic in (poi.get("photos", []) or []):
                        url = pic.get("url", "")
                        if url and url.startswith("http"):
                            images.append({"url": url, "title": poi.get("name", name),
                                           "quality": 85, "source": "amap"})
                            if len(images) >= 5: return images
            except Exception:
                continue
    return images


async def search_wikipedia_image(query: str, lang: str = "zh") -> list:
    """Wikipedia API搜索页面主图"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            search_url = f"https://{lang}.wikipedia.org/w/api.php"
            resp = await client.get(search_url, params={
                "action": "query", "list": "search", "srsearch": query,
                "srlimit": "3", "format": "json",
            })
            data = resp.json()
            pages = data.get("query", {}).get("search", [])
            if not pages: return images
            titles = "|".join([p["title"] for p in pages])
            resp2 = await client.get(search_url, params={
                "action": "query", "titles": titles,
                "prop": "pageimages", "format": "json", "pithumbsize": "800",
            })
            data2 = resp2.json()
            for page_id, page_data in data2.get("query", {}).get("pages", {}).items():
                thumb = page_data.get("thumbnail", {}).get("source", "")
                if thumb: images.append({"url": thumb, "title": page_data.get("title", ""),
                                         "quality": 70, "source": f"wikipedia_{lang}"})
    except Exception: pass
    return images


async def search_wikimedia(query: str, limit: int = 8) -> list:
    """Wikimedia Commons图片搜索，按质量评分排序"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            search_url = "https://commons.wikimedia.org/w/api.php"
            resp = await client.get(search_url, params={
                "action": "query", "list": "search", "srsearch": query,
                "srnamespace": "6", "srlimit": str(limit), "format": "json",
            })
            data = resp.json()
            pages = data.get("query", {}).get("search", [])
            if not pages: return images
            titles = "|".join([p["title"] for p in pages])
            resp2 = await client.get(search_url, params={
                "action": "query", "titles": titles,
                "prop": "imageinfo|pageassessments",
                "iiprop": "url|size|extmetadata", "iiurlwidth": "800", "format": "json",
            })
            for page_id, page_data in resp2.json().get("query", {}).get("pages", {}).items():
                if "missing" in page_data or "imageinfo" not in page_data: continue
                info = page_data["imageinfo"][0]
                url = info.get("thumburl") or info.get("url", "")
                if not url: continue
                mime = info.get("mime", "")
                if "svg" in mime or "gif" in mime: continue
                meta = info.get("extmetadata", {})
                quality = 0
                qa = (meta.get("QualityAssessment") or {}).get("value", "")
                if "featured" in qa.lower(): quality = 100
                elif "quality" in qa.lower(): quality = 80
                elif "valued" in qa.lower(): quality = 60
                img_width = int(info.get("width", 0))
                if img_width >= 2000: quality += 30
                elif img_width >= 1000: quality += 20
                elif img_width >= 500: quality += 10
                images.append({"url": url, "title": page_data.get("title", ""),
                               "width": img_width, "height": info.get("height", 0),
                               "quality": quality, "source": "wikimedia"})
            images.sort(key=lambda x: x["quality"], reverse=True)
    except Exception: pass
    return images


async def search_flickr(query: str, limit: int = 5) -> list:
    """Flickr公开图片搜索"""
    images = []
    try:
        search_url = f"https://www.flickr.com/search/?text={urllib.parse.quote(query)}&license=4,5,6,7,8,9,10"
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(search_url, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            })
            img_urls = re.findall(r'//live\.staticflickr\.com/\d+/\d+_[a-f0-9]+_[a-z]\.jpg', resp.text)
            seen = set()
            for url in img_urls:
                full_url = "https:" + url
                if full_url not in seen:
                    seen.add(full_url)
                    images.append({"url": full_url, "quality": 60, "source": "flickr"})
                    if len(images) >= limit: break
    except Exception: pass
    return images


async def search_bing_images(query: str, limit: int = 8) -> list:
    """Bing图片搜索（通过网页抓取，对中文景点覆盖好）"""
    images = []
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
            resp = await client.get(
                f"https://www.bing.com/images/search?q={urllib.parse.quote(query)}&first=0",
                headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            )
            # 提取图片URL
            urls = re.findall(r'https?://[^"\s]+\.(?:jpg|jpeg|png|webp)(?:\?[^"\s]*)?', resp.text)
            seen = set()
            for url in urls:
                # 过滤掉小图标和Bing自身域名
                if any(skip in url.lower() for skip in ['bing.com', 'icon', 'logo', 'favicon', 'avatar', 'th?id=']):
                    continue
                if url not in seen:
                    seen.add(url)
                    images.append({"url": url, "quality": 55, "source": "bing"})
                    if len(images) >= limit: break
    except Exception: pass
    return images


def _make_text_to_image_url(name: str, city: str) -> str:
    """生成text_to_image API兜底URL"""
    prompt = urllib.parse.quote(f"{name} {city}, travel photography, realistic, high quality, 4K")
    return f"{IMG_BASE}?prompt={prompt}&image_size=landscape_16_9"


async def _multi_source_search(name: str, city: str, queries: list, limit: int = 8) -> list:
    """多源搜索：高德POI → Bing → Wikimedia → Wikipedia → Flickr → text_to_image兜底"""
    # 1. 高德POI（多策略，国内景点最可靠）
    imgs = await search_amap_photos(name, city)
    if imgs: return imgs
    # 2. 国际源并行搜索（含Bing）
    for q in queries[:6]:
        results = await asyncio.gather(
            search_bing_images(q, limit),
            search_wikimedia(q, limit),
            search_wikipedia_image(q, "zh"),
            search_wikipedia_image(q, "en"),
            search_flickr(q, limit),
            return_exceptions=True,
        )
        for r in results:
            if isinstance(r, list) and r: return r
    # 3. 所有真实源都失败，用text_to_image兜底
    fallback_url = _make_text_to_image_url(name, city)
    return [{"url": fallback_url, "quality": 30, "source": "text_to_image"}]


async def get_best_spot_image(name: str, city: str) -> str:
    """获取景点最佳真实照片（多源搜索+兜底，确保始终有图）"""
    clean = re.sub(r'[（(].*?[）)]', '', name).strip()
    queries = [
        f"{name} {city}",
        f"{name} 景点 旅游",
        f"{clean} {city} 旅游",
        f"{name} China travel landmark",
        f"{name} 风景",
        name,
    ]
    imgs = await _multi_source_search(name, city, queries, 8)
    return imgs[0]["url"] if imgs else ""


async def get_best_hotel_image(name: str, area: str) -> str:
    """获取酒店最佳真实照片（多源搜索+兜底，确保始终有图）"""
    clean = re.sub(r'[（(].*?[）)]', '', name).strip()
    queries = [
        f"{name} hotel {area}",
        f"{name} 酒店 外观",
        f"{clean} 酒店",
        f"{name} {area}",
        f"{name} hotel exterior",
        name,
    ]
    imgs = await _multi_source_search(name, area, queries, 8)
    return imgs[0]["url"] if imgs else ""


async def search_images(query: str, limit: int = 5) -> dict:
    """综合图片搜索API"""
    imgs = await _multi_source_search(query, "", [query], limit)
    if imgs: return {"success": True, "images": imgs, "source": imgs[0].get("source", "unknown")}
    return {"success": True, "images": [], "source": "none"}