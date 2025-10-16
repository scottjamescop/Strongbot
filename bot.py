import re, os, asyncio, tempfile, yt_dlp, discord, random, aiohttp, subprocess, datetime, pathlib, ffmpeg, sqlite3, aiosqlite
from discord.ext import commands

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
    # Normalize handle
    handle = handle if handle.startswith("@") else f"@{handle}"
    live_url = f"https://www.youtube.com/{handle}/live"
    streams_url = f"https://www.youtube.com/{handle}/streams"

    headers = {
        # Realistic UA helps avoid odd responses
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }

    async with aiohttp.ClientSession() as session:
        # A) Try the classic: no-redirect GET; check Location
        try:
            async with session.get(live_url, allow_redirects=False, headers=headers, timeout=10) as resp:
                loc = resp.headers.get("Location")
                if resp.status in (301, 302, 303, 307, 308) and loc and "/watch" in loc:
                    return f"https://www.youtube.com{loc}" if loc.startswith("/") else loc
        except Exception:
            pass

        # B) Follow redirects and check final URL (sometimes YT does internal hops)
        try:
            async with session.get(live_url, allow_redirects=True, headers=headers, timeout=12) as resp:
                # If we ended up on a watch page, great
                if "/watch" in str(resp.url):
                    return str(resp.url)
                # Sometimes the page HTML includes a meta/client redirect; check for a watch URL in HTML
                text = await resp.text()
                m = re.search(r'https?://www\.youtube\.com/watch\?v=[\w-]{8,}', text)
                if m:
                    return m.group(0)
                # Also look for isLiveContent JSON hint with a videoId nearby
                vid = re.search(r'"videoId"\s*:\s*"([\w-]{8,})".{0,200}?"isLiveContent"\s*:\s*true', text)
                if vid:
                    return f"https://www.youtube.com/watch?v={vid.group(1)}"
        except Exception:
            pass

        # C) Fallback: parse the Streams tab and grab the first LIVE video
        try:
            async with session.get(streams_url, headers=headers, timeout=12) as resp:
                if resp.status == 200:
                    html = await resp.text()
                    # Look for a LIVE badge nearby, then a watch link; minimal parsing to avoid heavy JSON parsing
                    # First, directly scan for watch URLs
                    watches = re.findall(r'/watch\?v=([\w-]{8,})', html)
                    # Heuristic: prefer the first unique watch id visible; optionally look for "LIVE NOW" markers
                    if watches:
                        # Optional: try to pick one with a LIVE signal around it
                        for vid in watches:
                            # check a small window around the first occurrence
                            idx = html.find(vid)
                            window = html[max(0, idx-500): idx+500]
                            if re.search(r'LIVE\s+NOW|badge.+live|aria-label="Live"', window, re.I):
                                return f"https://www.youtube.com/watch?v={vid}"
                        # If we didn't find a live badge, still return the first (often the current or recent stream)
                        return f"https://www.youtube.com/watch?v={watches[0]}"
        except Exception:
            pass

    return None

async def debug_live_probe(channel, handle: str = YOUTUBE_HANDLE):
    handle = handle if handle.startswith("@") else f"@{handle}"
    live_url = f"https://www.youtube.com/{handle}/live"
    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    }
    async with aiohttp.ClientSession() as session:
        async with session.get(live_url, allow_redirects=False, headers=headers) as r1:
            loc = r1.headers.get("Location")
            s1 = f"A) {live_url} -> {r1.status} Location={loc or '—'}"
        async with session.get(live_url, allow_redirects=True, headers=headers) as r2:
            hist = " → ".join([str(h.headers.get('Location') or h.url) for h in r2.history] + [str(r2.url)])
            s2 = f"B) follow redirects: {hist}"
        await channel.send(f"```{s1}\n{s2}\n```")


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
        
    if ANNOUNCE_CH:
        ch = bot.get_channel(ANNOUNCE_CH)
        #if ch:
            #await ch.send(f"🟢 StrongBot online!  `{VERSION}`")
    print(f"[BOOT] {bot.user} {VERSION}")

def mentioned_with_keyword(message: discord.Message, bot_user: discord.User | discord.ClientUser, keyword: str) -> bool:
    # Detect @bot mention (any format) + keyword as a whole word (case-insensitive)
    mentioned = (bot_user in message.mentions) or bool(re.search(rf"<@!?{bot_user.id}>", message.content))
    has_word = bool(re.search(rf"\b{re.escape(keyword)}\b", message.content, flags=re.IGNORECASE))
    return mentioned and has_word

@bot.event
async def on_message(message):
        if message.author == bot.user:
                return

        await log_message(
            username=str(message.author),
            channel=str(message.channel),
            message=message.content
        )

        if mentioned_with_keyword(message, bot.user, "pigsdebug"):
            await debug_live_probe(message.channel)

        if mentioned_with_keyword(message, bot.user, "pigs"):
            try:
                async with message.channel.typing():
                    link = await fetch_live_link_via_redirect()
                if link:
                    await message.channel.send(f"🐷 Live now! {link}")
                else:
                    await message.channel.send("🐷 Not live right now. Try again later.")
            except Exception as e:
                await message.channel.send(f"🐷 Oink—something went sideways: `{e}`")
        # Don’t return; let other handlers (like TikTok) still run if present
        # If you prefer to stop further processing when pigs matches, uncomment:
        # return

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
