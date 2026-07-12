"""配置常量：API密钥和URL"""
import os

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
AMAP_KEY = os.getenv("AMAP_API_KEY", "")
AMAP_POI_URL = "https://restapi.amap.com/v3/place/text"
AMAP_WEATHER_URL = "https://restapi.amap.com/v3/weather/weatherInfo"
AMAP_GEO_URL = "https://restapi.amap.com/v3/geocode/geo"
IMG_BASE = "https://trae-api-cn.mchost.guru/api/ide/v1/text_to_image"