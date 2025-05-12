import re, os, asyncio, tempfile, yt_dlp, discord, random, aiohttp
from discord.ext import commands

TOKEN  = os.getenv("DISCORD_BOT_TOKEN")

URL_RE = re.compile(
    r"https?://(?:www\.)?(?:tiktok\.com|vm\.tiktok\.com|instagram\.com/(?:reel|p))/[^\s]+"
)

def build_ydl_opts():
    return {
        "quiet": True,
        "noplaylist": True,
        "no-check-certificate": True,
        "compat-option": "no-certifi",
        "format": "mp4",
        "outtmpl": "%(id)s.%(ext)s",
        "socket_timeout": 20,            # <- longer
        "cookies": "/root/discord-bot/cookies.txt",
        "http_headers": {
            "User-Agent":
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
        },
    }

bot = commands.Bot(command_prefix="!")

@bot.event
async def on_message(msg):
    if msg.author.bot:
        return
    m = URL_RE.search(msg.content)
    if not m:
        return

    url = m.group(0)
    await msg.channel.typing()

    opts  = build_ydl_opts()

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info  = ydl.extract_info(url, download=False)
            size  = info.get("filesize") or info.get("filesize_approx") or 0

            if size and size < 8 * 1024 * 1024:
                filename = ydl.prepare_filename(info)
                ydl.download([url])
                await msg.reply(file=discord.File(filename), mention_author=False)
                os.remove(filename)
            else:
                embed = discord.Embed(title=info.get("title", "Video"), url=url)
                embed.set_image(url=info.get("thumbnail"))
                # note: Discord will not play arbitrary MP4 links in an embed,
                # but users can click through.
                await msg.reply(embed=embed, mention_author=False)

    except Exception as e:
        await msg.reply(f"**Download failed** ({e})", mention_author=False)

bot.run(TOKEN)
