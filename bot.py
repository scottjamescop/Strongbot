import re, os, asyncio, tempfile, yt_dlp, discord
from discord.ext import commands

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
URL_RE = re.compile(r"https?://(?:www\.)?(?:tiktok\.com|vm\.tiktok\.com|instagram\.com/(?:reel|p))/[^\s]+")

ydl_opts = {
    "quiet": True,
    "noplaylist": True,
    "format": "mp4",
    "outtmpl": "%(id)s.%(ext)s",
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

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        size = info.get("filesize", 0) or info.get("filesize_approx", 0)

        # Try direct re-upload first, keep under 8 MB
        if size and size < 8 * 1024 * 1024:
            filename = ydl.prepare_filename(info)
            ydl.download([url])
            await msg.reply(file=discord.File(filename), mention_author=False)
            os.remove(filename)
        else:
            # Fallback: hot-link embed
            embed = discord.Embed(title=info.get("title", "Video"), url=url)
            embed.set_image(url=info.get("thumbnail"))
            embed.set_video(url=info["url"])        # CDN mp4
            await msg.reply(embed=embed, mention_author=False)

bot.run(TOKEN)
