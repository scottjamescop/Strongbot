# proxy_manager.py  – validated HTTPS/SOCKS pool
import aiohttp, asyncio, random, time, logging

FREE_APIS = [
    # ask ProxyScrape for *only* HTTPS proxies and <= 3000 ms latency
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&ssl=yes&timeout=3000",
    # api.getproxylist.com returns JSON one-by-one
    "https://api.getproxylist.com/proxy?allowsHttps=1&maxConnectTime=3000",
]

CACHE_TTL   = 600          # refresh every 10 min
TEST_URL    = "https://www.tiktok.com/"   # we test against TikTok homepage
TEST_TIMEOUT = 5

_good: list[str] = []
_stamp = 0.0


async def _is_alive(session: aiohttp.ClientSession, proxy: str) -> bool:
    try:
        async with session.get(TEST_URL, proxy=proxy, timeout=TEST_TIMEOUT) as r:
            return r.status < 500
    except Exception:
        return False


async def _refill():
    global _good, _stamp
    _good.clear()
    async with aiohttp.ClientSession() as session:
        for api in FREE_APIS:
            try:
                async with session.get(api, timeout=10) as r:
                    if r.headers.get("content-type", "").startswith("application/json"):
                        data = await r.json()
                        ip   = data["ip"]
                        port = data["port"]
                        proxy = f"http://{ip}:{port}"
                        if await _is_alive(session, proxy):
                            _good.append(proxy)
                    else:
                        txt = await r.text()
                        for line in txt.splitlines():
                            line = line.strip()
                            if not line:
                                continue
                            proxy = f"http://{line}"
                            if await _is_alive(session, proxy):
                                _good.append(proxy)
            except Exception as e:
                logging.warning(f"Proxy API failed ({api}): {e}")
    random.shuffle(_good)
    _stamp = time.time()
    logging.info(f"[proxy] pool filled with {len(_good)} working proxies")


async def get_proxy() -> str | None:
    global _good, _stamp
    if time.time() - _stamp > CACHE_TTL or not _good:
        await _refill()
    return _good.pop() if _good else None
