# proxy_manager.py
import aiohttp, random, asyncio, os, time, logging

FREE_APIS = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=8000&country=all&ssl=all",
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt"
]

#PAID_ENDPOINT = os.getenv("PAID_PROXY")   # set in your VPS env if you have one
CACHE_TTL     = 300                      # seconds – refetch every 5 min

_proxy_cache: list[str] = []
_cache_stamp = 0.0

async def _refill_cache() -> None:
    global _proxy_cache, _cache_stamp
    agg: list[str] = []
    async with aiohttp.ClientSession() as session:
        for api in FREE_APIS:
            try:
                async with session.get(api, timeout=10) as resp:
                    txt = await resp.text()
                    agg.extend(f"http://{p.strip()}" for p in txt.splitlines() if p.strip())
            except Exception as e:
                logging.warning(f"Proxy API failed ({api}): {e}")
    random.shuffle(agg)
    _proxy_cache = agg
    _cache_stamp = time.time()

async def get_proxy() -> str | None:
    global _proxy_cache, _cache_stamp
    # prefer paid endpoint if configured
    #if PAID_ENDPOINT:
        #return PAID_ENDPOINT
    # else use a cached free proxy
    if time.time() - _cache_stamp > CACHE_TTL or not _proxy_cache:
        await _refill_cache()
    return _proxy_cache.pop() if _proxy_cache else None
