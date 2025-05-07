import discord, re, os, asyncio, subprocess, yt_dlp, random, socket
from discord.ext import commands
from proxy_manager import get_proxy

MAX_DISCORD_FILESIZE = 8 * 1024 * 1024  # 8 MB


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TIKTOK_PATTERN     = re.compile(r"https?://(?:\w+\.)?tiktok\.com/.*|https?://(?:\w+\.)?vt\.tiktok\.com/.*")
INSTAGRAM_PATTERN  = re.compile(r"https?://(?:\w+\.)?instagram\.com/.*")

def ydl_opts(proxy: str | None):
    """Return a fresh yt‑dlp options dict for a given proxy."""
    return {
        "format": "best",
        "outtmpl": "/tmp/%(id)s.%(ext)s",      # download into /tmp so leftover files vanish on reboot
        "quiet": True,
        "proxy": proxy,
        "socket_timeout": 10,                  # seconds
        "retries": 3,                          # a few internal retries before we switch proxy
        "http_headers": {
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9"
        },
        "geo_bypass": True
    }

async def compress_video(original_path: str) -> str | None:
    compressed = original_path.replace(".", "_compressed.")
    cmd = ["ffmpeg", "-y", "-i", original_path, "-vcodec", "libx264", "-crf", "32", compressed]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return compressed if os.path.getsize(compressed) <= MAX_DISCORD_FILESIZE else None
    except subprocess.CalledProcessError:
        return None

async def download_with_rotation(url: str) -> str:
    for _ in range(10):                       # max 10 attempts
        proxy = await get_proxy()
        try:
            with yt_dlp.YoutubeDL(ydl_opts(proxy)) as ydl:
                info = ydl.extract_info(url, download=True)
                return ydl.prepare_filename(info)
        except Exception:
            continue
    raise RuntimeError("all proxies failed")

@bot.event
async def on_ready():
    print(f"✅ Logged in as {bot.user} – ready!")

@bot.event
async def on_message(message: discord.Message):
    if message.author == bot.user:
        return

    match = TIKTOK_PATTERN.search(message.content) or INSTAGRAM_PATTERN.search(message.content)
    if not match:
        return

    url = match.group(0)
    status = await message.channel.send("📥 Downloading…")

    try:
        video_file = await download_with_rotation(url)

        # too big? try to compress
        if os.path.getsize(video_file) > MAX_DISCORD_FILESIZE:
            await status.edit(content="🔧 Compressing to fit 8 MB…")
            smaller = await compress_video(video_file)
            os.remove(video_file)
            if not smaller:
                await status.edit(content="❌ Still too large after compression.")
                return
            video_file = smaller

        await status.delete()
        await message.channel.send(file=discord.File(video_file))
        await message.delete()
    except Exception as e:
        await status.edit(content=f"❌ Failed: {e}")
    finally:
        # clean up any leftover file
        if 'video_file' in locals() and os.path.isfile(video_file):
            os.remove(video_file)

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
