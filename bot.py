import re, os, asyncio, tempfile, yt_dlp, discord, random, aiohttp, subprocess, datetime, pathlib, ffmpeg, sqlite3, aiosqlite
from discord.ext import commands
from discord import app_commands

conn = sqlite3.connect("bot_messages.db")
c = conn.cursor()

c.execute('''
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    username TEXT NOT NULL,
    message TEXT NOT NULL
)
''')

conn.commit()
conn.close()

TOKEN  = os.getenv("DISCORD_BOT_TOKEN")
ANNOUNCE_CH = int(os.getenv("BOT_ANNOUNCE_CHANNEL", "0"))

TIKTOK_PATTERN = re.compile(r"https?://(?:\w+\.)?tiktok\.com/.*|https?://(?:\w+\.)?vt\.tiktok\.com/.*")
#INSTAGRAM_PATTERN = re.compile(r"https?://(?:\w+\.)?instagram\.com/.*")

YOUTUBE_HANDLE = "@scottjamescop"  # changeable via env if you want

def get_version() -> str:
    try:
        with open(pathlib.Path(__file__).parent / "version.txt") as f:
            return f.read().strip()
    except FileNotFoundError:
        return "dev"

VERSION = get_version()

ydl_options = {
    "cookies": "/root/discord-bot/www.tiktok.com_cookies.txt",
    "no-check-certificate": True,
    "compat-option": "no-certifi",
}

intents = discord.Intents.default()
intents.message_content = True  

bot = commands.Bot(command_prefix="!", intents=intents)

async def log_message(username, channel, message):
    timestamp = datetime.datetime.utcnow().isoformat()
    async with aiosqlite.connect("bot_messages.db") as db:
        await db.execute(
            "INSERT INTO messages (timestamp, username, message) VALUES (?, ?, ?)",
            (timestamp, username, message)
        )
        await db.commit()

async def fetch_live_link_via_redirect(handle: str = YOUTUBE_HANDLE) -> str | None:
    url = f"https://www.youtube.com/{handle}/live"
    # We want to see if YT redirects us to /watch?v=... when live.
    async with aiohttp.ClientSession() as session:
        # Use GET not HEAD because YT sometimes treats HEAD oddly; disable redirects.
        async with session.get(url, allow_redirects=False, headers={
            "User-Agent": "Mozilla/5.0 (DiscordBot; +https://github.com/scottjamescop/Strongbot)"
        }) as resp:
            loc = resp.headers.get("Location")
            if resp.status in (301, 302, 303, 307, 308) and loc and "/watch" in loc:
                # Normalize full URL
                if loc.startswith("/"):
                    return f"https://www.youtube.com{loc}"
                return loc
            return None

class Pigs(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="pigs", description="If Scott is live on YouTube, return the live link.")
    async def pigs(self, interaction):
        await interaction.response.defer(thinking=True, ephemeral=False)

        link = await fetch_live_link_via_redirect()
        if link:
            await interaction.followup.send(f"🐷 Live now! {link}")
        else:
            await interaction.followup.send("🐷 Not live right now. Try again later.")

async def setup(bot: commands.Bot):
    await bot.add_cog(Pigs(bot))

async def compress_video(video_full_path, size_upper_bound, two_pass=True, filename_suffix='cps_'):

    filename, extension = os.path.splitext(video_full_path)
    extension = '.mp4'
    output_file_name = filename + filename_suffix + extension

    # Adjust them to meet your minimum requirements (in bps), or maybe this function will refuse your video!
    total_bitrate_lower_bound = 11000
    min_audio_bitrate = 32000
    max_audio_bitrate = 256000
    min_video_bitrate = 100000

    try:
        # Bitrate reference: https://en.wikipedia.org/wiki/Bit_rate#Encoding_bit_rate
        probe = ffmpeg.probe(video_full_path)
        # Video duration, in s.
        duration = float(probe['format']['duration'])
        # Audio bitrate, in bps.
        audio_bitrate = float(next((s for s in probe['streams'] if s['codec_type'] == 'audio'), None)['bit_rate'])
        # Target total bitrate, in bps.
        target_total_bitrate = (size_upper_bound * 1024 * 8) / (1.073741824 * duration)
        if target_total_bitrate < total_bitrate_lower_bound:
            print('Bitrate is extremely low! Stop compress!')
            return False

        # Best min size, in kB.
        best_min_size = (min_audio_bitrate + min_video_bitrate) * (1.073741824 * duration) / (8 * 1024)
        if size_upper_bound < best_min_size:
            print('Quality not good! Recommended minimum size:', '{:,}'.format(int(best_min_size)), 'KB.')
            # return False

        # Target audio bitrate, in bps.
        audio_bitrate = audio_bitrate

        # target audio bitrate, in bps
        if 10 * audio_bitrate > target_total_bitrate:
            audio_bitrate = target_total_bitrate / 10
            if audio_bitrate < min_audio_bitrate < target_total_bitrate:
                audio_bitrate = min_audio_bitrate
            elif audio_bitrate > max_audio_bitrate:
                audio_bitrate = max_audio_bitrate

        # Target video bitrate, in bps.
        video_bitrate = target_total_bitrate - audio_bitrate
        if video_bitrate < 1000:
            print('Bitrate {} is extremely low! Stop compress.'.format(video_bitrate))
            return False

        i = ffmpeg.input(video_full_path)
        if two_pass:
            ffmpeg.output(i, os.devnull,
                          **{'c:v': 'libx264', 'b:v': video_bitrate, 'pass': 1, 'f': 'mp4'}
                          ).overwrite_output().run()
            ffmpeg.output(i, output_file_name,
                          **{'c:v': 'libx264', 'b:v': video_bitrate, 'pass': 2, 'c:a': 'aac', 'b:a': audio_bitrate}
                          ).overwrite_output().run()
        else:
            ffmpeg.output(i, output_file_name,
                          **{'c:v': 'libx264', 'b:v': video_bitrate, 'c:a': 'aac', 'b:a': audio_bitrate}
                          ).overwrite_output().run()

        if os.path.getsize(output_file_name) <= size_upper_bound * 1024:
            return output_file_name
        elif os.path.getsize(output_file_name) < os.path.getsize(video_full_path):  # Do it again
            return compress_video(output_file_name, size_upper_bound)
        else:
            return False
    except FileNotFoundError as e:
        print('You do not have ffmpeg installed!', e)
        print('You can install ffmpeg by reading https://github.com/kkroening/ffmpeg-python/issues/251')
        return False

@bot.event
async def on_ready():
    if "Pigs" not in bot.cogs:
        await bot.add_cog(Pigs(bot))
        
    if ANNOUNCE_CH:
        ch = bot.get_channel(ANNOUNCE_CH)
        #if ch:
            #await ch.send(f"🟢 StrongBot online!  `{VERSION}`")
    print(f"[BOOT] {bot.user} {VERSION}")

@bot.event
async def on_message(message):
        if message.author == bot.user:
                return

        await log_message(
            username=str(message.author),
            channel=str(message.channel),
            message=message.content
        )

        await bot.process_commands(message)

        tiktok_match = TIKTOK_PATTERN.search(message.content)
        #instagram_match = INSTAGRAM_PATTERN.search(message.content)

        if tiktok_match:# or instagram_match:
                url = tiktok_match.group(0) #if tiktok_match# else instagram_match.group(0)
                await message.channel.send("Downloading the video!!...")

                try:
                        with yt_dlp.YoutubeDL(ydl_options) as ydl:
                                info = ydl.extract_info(url, download=True)
                                video_file = ydl.prepare_filename(info)

                        if os.path.getsize(video_file) <= 8 * 1024 * 1024:
                                await message.channel.send(f"Video from {message.author}")
                                await message.channel.send(file=discord.File(video_file))
                                await message.delete()

                        else:
                                await message.channel.send("compressing video...")

                                compressed_file = await compress_video(video_file, 8 * 1000)

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
