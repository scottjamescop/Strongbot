import discord
import re
import os
import asyncio
import subprocess
import yt_dlp
import random
from discord.ext import commands

MAX_DISCORD_FILESIZE = 8 * 1024 * 1024

PROXIES = [
        "http://24.144.87.235:8088",
        "http://107.172.208.184:1080",
        "http://52.194.186.70:1080"
]

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TIKTOK_PATTERN = re.compile(r"https?://(?:\w+\.)?tiktok\.com/.*|https?://(?:\w+\.)?vt\.tiktok\.com/.*")
INSTAGRAM_PATTERN = re.compile(r"https?://(?:\w+\.)?instagram\.com/.*")

def get_ydl_options():
        #PROXY = random.choice(PROXIES)

        return  {
                "format": "best",
                "outtmpl": "videos/%(id)s.%(ext)s",
                "quiet": True,
                #"proxy": PROXY,
                "http_headers": {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                        "Accept-Language": "en-US,en;q=0.9"
                }
        }


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

                if os.path.getsize(compressed_path) <= MAX_DISCORD_FILESIZE:
                        return compressed_path
                else:
                        os.remove(compressed_path)
                        return None
        except subprocess.CalledProcessError:
                return None

@bot.event
async def on_ready():
        print(f"Bot {bot.user} is ready and online.")

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

                        if os.path.getsize(video_file) <= MAX_DISCORD_FILESIZE:
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

bot.run(os.getenv("DISCORD_BOT_TOKEN"))
