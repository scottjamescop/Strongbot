import re, os, asyncio, tempfile, yt_dlp, discord, random, aiohttp
from discord.ext import commands

TOKEN  = os.getenv("DISCORD_BOT_TOKEN")

URL_RE = re.compile(
    r"https?://(?:www\.)?(?:tiktok\.com|vm\.tiktok\.com|instagram\.com/(?:reel|p))/[^\s]+"
)

def build_ydl_opts():
    return {
        "cookies": "/root/discord-bot/www.tiktok.com_cookies.txt",
        "no-check-certificate": True,
        "compat-option": "no-certifi",
    }

bot = commands.Bot(command_prefix="!")

@bot.command(name="strongversion")
async def version(ctx):
    import sys, os, yt_dlp, ssl
    await ctx.reply(
        f"```python\n"
        f"Exec : {sys.executable}\n"
        f"yt-dlp: {yt_dlp.__version__}\n"
        f"SSL_CERT_FILE:\n  {os.getenv('SSL_CERT_FILE')}\n"
        f"```",
        mention_author=False,
    )

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
