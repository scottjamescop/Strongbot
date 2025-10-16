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
    handle = handle if handle.startswith("@") else f"@{handle}"
    live_url = f"https://www.youtube.com/{handle}/live"
    streams_url = f"https://www.youtube.com/{handle}/streams"

    headers = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }

    async def is_watch_live(session: aiohttp.ClientSession, watch_url: str) -> bool:
        # Fetch the watch page and look for strong live signals
        async with session.get(watch_url, headers=headers, timeout=12) as r:
            if r.status != 200:
                return False
            html = await r.text()
            # Strong signals that this specific watch page is live *now*:
            if re.search(r'"isLiveNow"\s*:\s*true', html):
                return True
            if re.search(r'"isLiveContent"\s*:\s*true', html) and re.search(r'"viewCountText".*?watching', html, re.I | re.S):
                return True
            # Badge/style flags that mark the *current* stream:
            if re.search(r'LIVE\s+NOW', html, re.I) and "playerResponse" in html:
                return True
            # Thumbnail overlay live style
            if re.search(r'"thumbnailOverlayTimeStatusRenderer".*?"style"\s*:\s*"LIVE"', html, re.S):
                return True
            return False

    async with aiohttp.ClientSession() as session:
        # A) Try the official live redirect and validate the final watch page
        try:
            async with session.get(live_url, allow_redirects=True, headers=headers, timeout=12) as resp:
                final = str(resp.url)
                if "/watch" in final and await is_watch_live(session, final):
                    return final
                # Sometimes the HTML has the watch link without proper 30x; try to extract, then validate
                html = await resp.text()
                m = re.search(r'https?://www\.youtube\.com/watch\?v=([\w-]{8,})', html)
                if m:
                    candidate = f"https://www.youtube.com/watch?v={m.group(1)}"
                    if await is_watch_live(session, candidate):
                        return candidate
        except Exception:
            pass

        # B) Fallback: Streams tab—pick the first tile explicitly marked LIVE
        try:
            async with session.get(streams_url, headers=headers, timeout=12) as resp:
                if resp.status == 200:
                    html = await resp.text()

                    # Prefer entries with a LIVE badge near the videoId
                    live_ids = set()
                    for vid in re.findall(r'"videoId"\s*:\s*"([\w-]{8,})"', html):
                        idx = html.find(vid)
                        if idx == -1:
                            continue
                        window = html[max(0, idx-800): idx+800]
                        if re.search(r'LIVE\s+NOW|badge[^}]+live|thumbnailOverlayTimeStatusRenderer[^}]+LIVE', window, re.I | re.S):
                            live_ids.add(vid)

                    # Validate each live-marked candidate by fetching its watch page
                    for vid in list(live_ids):
                        candidate = f"https://www.youtube.com/watch?v={vid}"
                        if await is_watch_live(session, candidate):
                            return candidate

                    # Absolute last resort: scan for watch links and validate each until one is truly live
                    for vid in re.findall(r'/watch\?v=([\w-]{8,})', html):
                        candidate = f"https://www.youtube.com/watch?v={vid}"
                        if await is_watch_live(session, candidate):
                            return candidate
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
