import re, os, asyncio, tempfile, yt_dlp, discord, random, aiohttp, subprocess, datetime, pathlib
from discord.ext import commands

TOKEN  = os.getenv("DISCORD_BOT_TOKEN")
ANNOUNCE_CH = int(os.getenv("BOT_ANNOUNCE_CHANNEL", "0"))

TIKTOK_PATTERN = re.compile(r"https?://(?:\w+\.)?tiktok\.com/.*|https?://(?:\w+\.)?vt\.tiktok\.com/.*")
INSTAGRAM_PATTERN = re.compile(r"https?://(?:\w+\.)?instagram\.com/.*")

def get_version() -> str:
    try:
        with open(pathlib.Path(__file__).parent / "version.txt") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"

VERSION = get_version()

def get_ydl_options():
    return {
        "cookies": "/root/discord-bot/www.tiktok.com_cookies.txt",
        "no-check-certificate": True,
        "compat-option": "no-certifi",
    }

intents = discord.Intents.default()
intents.message_content = True  

bot = commands.Bot(command_prefix="!", intents=intents)

async def compress_video(original_path):
        compressed_path = original_path.replace(".", "_compressed.")

        command = [
                "ffmpeg",
                "-i", original_path,
                "-vcodec", "libx264",
                "-crf", "32",
                compressed_path
        ]
        try:
                subprocess.run(command, check=True)

                if os.path.getsize(compressed_path) <= 8 * 1024 * 1024:
                        return compressed_path
                else:
                        os.remove(compressed_path)
                        return None
        except subprocess.CalledProcessError:
                return None

@bot.event
async def on_ready():
    if ANNOUNCE_CH:
        ch = bot.get_channel(ANNOUNCE_CH)
        if ch:
            await ch.send(f"🟢 StrongBot online!  `{VERSION}`")
    print(f"[BOOT] {bot.user} {VERSION}")

@bot.event
async def on_message(message):
        if message.author == bot.user:
                return

        tiktok_match = TIKTOK_PATTERN.search(message.content)
        instagram_match = INSTAGRAM_PATTERN.search(message.content)

        if tiktok_match or instagram_match:
                url = tiktok_match.group(0) if tiktok_match else instagram_match.group(0)
                await message.channel.send("Downloading the video!!...")

                try:
                        with yt_dlp.YoutubeDL(get_ydl_options()) as ydl:
                                info = ydl.extract_info(url, download=True)
                                video_file = ydl.prepare_filename(info)

                        if os.path.getsize(video_file) <= 8 * 1024 * 1024:
                                await message.channel.send(f"Video from {message.author}")
                                await message.channel.send(file=discord.File(video_file))
                                await message.delete()

                                os.remove(video_file)

                        else:
                                await message.channel.send("compressing video...")

                                compressed_file = await compress_video(video_file)

                                if compressed_file:
                                        await message.channel.send(file=discord.File(compressed_file))
                                        await message.delete()
                                        os.remove(compressed_file)
                                else:
                                        await message.channel.send("Video too big. Tell Scott to pay for Nitro")

                        os.remove(video_file)

                except Exception as e:
                        await message.channel.send(f"Failed to download video {str(e)}")

        await bot.process_commands(message)

bot.run(TOKEN)
