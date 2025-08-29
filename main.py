import os
import asyncio
import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import aiofiles
import aiofiles.os
from pathlib import Path

intents = discord.Intents.default()
intents.voice_states = True
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix='!', intents=intents)

ytdl_format_options = {
    'format': 'bestaudio/best',
    'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0',
}

ffmpeg_options = {
    'options': '-vn',
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
}

ytdl = yt_dlp.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = data.get('url')
        self.duration = data.get('duration', 0)

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            data = data['entries'][0]
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return cls(discord.FFmpegPCMAudio(filename, **ffmpeg_options), data=data)

class GuildQueue:
    def __init__(self):
        self.queue = []
        self.loop_track = False
        self.loop_queue = False
        self.current = None
        self.volume = 0.5

queues = {}

def get_queue(guild_id):
    if guild_id not in queues:
        queues[guild_id] = GuildQueue()
    return queues[guild_id]

PLAYLISTS_DIR = Path("playlists")

async def ensure_playlists_dir():
    await aiofiles.os.makedirs(PLAYLISTS_DIR, exist_ok=True)

async def create_playlist(user_id, name):
    user_dir = PLAYLISTS_DIR / str(user_id)
    await aiofiles.os.makedirs(user_dir, exist_ok=True)
    playlist_path = user_dir / f"{name}.txt"
    if await aiofiles.os.path.exists(playlist_path):
        return False
    async with aiofiles.open(playlist_path, 'w') as f:
        pass
    return True

async def add_to_playlist(user_id, name, url):
    user_dir = PLAYLISTS_DIR / str(user_id)
    playlist_path = user_dir / f"{name}.txt"
    if not await aiofiles.os.path.exists(playlist_path):
        return False
    async with aiofiles.open(playlist_path, 'a') as f:
        await f.write(f"{url}\n")
    return True

async def get_playlist(user_id, name):
    user_dir = PLAYLISTS_DIR / str(user_id)
    playlist_path = user_dir / f"{name}.txt"
    if not await aiofiles.os.path.exists(playlist_path):
        return None
    async with aiofiles.open(playlist_path, 'r') as f:
        content = await f.read()
    return [line.strip() for line in content.split('\n') if line.strip()]

class PlayerView(discord.ui.View):
    def __init__(self, interaction, player, queue):
        super().__init__(timeout=None)
        self.interaction = interaction
        self.player = player
        self.queue = queue
        self.message = None
        self.task = asyncio.create_task(self.update_loop())

    async def update_loop(self):
        while self.interaction.guild.voice_client and self.interaction.guild.voice_client.is_playing():
            await asyncio.sleep(5)
            await self.refresh()

    async def refresh(self):
        if not self.message:
            return
        duration = self.player.duration
        pos = 0
        bar_length = 20
        filled = int((pos / duration) * bar_length) if duration else 0
        bar = "▬" * filled + "🔘" + "▬" * (bar_length - filled)
        embed = discord.Embed(title="🎶 Now Playing", color=0x1DB954)
        embed.add_field(name="Track", value=self.player.title, inline=False)
        embed.add_field(name="Progress", value=f"{bar} 0:00 / {duration//60}:{duration%60:02d}", inline=False)
        embed.add_field(name="Loop", value="✅" if self.queue.loop_track else "❌", inline=True)
        embed.add_field(name="Volume", value=f"{int(self.queue.volume*100)}%", inline=True)
        await self.message.edit(embed=embed, view=self)

    @discord.ui.button(label="⏯ Pause/Resume", style=discord.ButtonStyle.secondary)
    async def pause_resume(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.pause()
            await interaction.response.send_message("⏸ Paused", ephemeral=True)
        else:
            vc.resume()
            await interaction.response.send_message("▶️ Resumed", ephemeral=True)

    @discord.ui.button(label="⏭ Skip", style=discord.ButtonStyle.primary)
    async def skip(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.stop()
        await interaction.response.send_message("⏭ Skipped!", ephemeral=True)

    @discord.ui.button(label="⏹ Stop", style=discord.ButtonStyle.danger)
    async def stop(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc.is_playing():
            vc.stop()
        self.queue.queue.clear()
        await interaction.response.send_message("⏹ Stopped & cleared queue.", ephemeral=True)

    @discord.ui.button(label="🔁 Loop", style=discord.ButtonStyle.success)
    async def loop(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.queue.loop_track = not self.queue.loop_track
        await interaction.response.send_message(f"Loop {'enabled ✅' if self.queue.loop_track else 'disabled ❌'}", ephemeral=True)
        await self.refresh()

async def play_next(interaction: discord.Interaction):
    queue = get_queue(interaction.guild.id)
    if not queue.queue:
        return
    if queue.loop_track and queue.current:
        queue.queue.insert(0, queue.current)
    if queue.queue:
        url = queue.queue.pop(0)
        queue.current = url
        try:
            player = await YTDLSource.from_url(url, loop=bot.loop, stream=True)
            player.volume = queue.volume
            def after_playing(error):
                if error:
                    print(f"Player error: {error}")
                fut = asyncio.run_coroutine_threadsafe(play_next(interaction), bot.loop)
                try:
                    fut.result()
                except Exception as e:
                    print(f"Error in after_playing: {e}")
            interaction.guild.voice_client.play(player, after=after_playing)
            view = PlayerView(interaction, player, queue)
            embed = discord.Embed(title="🎶 Now Playing", color=0x1DB954)
            embed.add_field(name="Track", value=player.title, inline=False)
            msg = await interaction.followup.send(embed=embed, view=view)
            view.message = msg
        except Exception as e:
            await interaction.followup.send(f"Error playing track: {e}", ephemeral=True)
            await play_next(interaction)

@bot.event
async def on_ready():
    await ensure_playlists_dir()
    print(f'Logged in as {bot.user.name}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

@bot.tree.command(name="join", description="Join a voice channel")
async def join(interaction: discord.Interaction):
    if not interaction.user.voice:
        await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
        return
    channel = interaction.user.voice.channel
    await channel.connect()
    await interaction.response.send_message(f"Joined {channel.name}", ephemeral=True)

@bot.tree.command(name="leave", description="Disconnect and clear queue")
async def leave(interaction: discord.Interaction):
    if interaction.guild.voice_client:
        queue = get_queue(interaction.guild.id)
        queue.queue = []
        queue.current = None
        await interaction.guild.voice_client.disconnect()
        await interaction.response.send_message("Disconnected and queue cleared.", ephemeral=True)
    else:
        await interaction.response.send_message("Bot is not connected to any voice channel.", ephemeral=True)

@bot.tree.command(name="play", description="Play or add a track to the queue")
@app_commands.describe(url="YouTube URL")
async def play(interaction: discord.Interaction, url: str):
    await interaction.response.defer(ephemeral=False)
    if not interaction.user.voice:
        await interaction.followup.send("You must be in a voice channel.", ephemeral=True)
        return
    if not interaction.guild.voice_client:
        channel = interaction.user.voice.channel
        await channel.connect()
    queue = get_queue(interaction.guild.id)
    queue.queue.append(url)
    await interaction.followup.send(f"Added to queue: {url}", ephemeral=False)
    if not interaction.guild.voice_client.is_playing():
        await play_next(interaction)

@bot.tree.command(name="stop", description="Stop playback and clear queue")
async def stop(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        queue = get_queue(interaction.guild.id)
        queue.queue = []
        queue.current = None
        await interaction.response.send_message("Playback stopped and queue cleared.", ephemeral=True)
    else:
        await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

@bot.tree.command(name="skip", description="Skip the current track")
async def skip(interaction: discord.Interaction):
    if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
        interaction.guild.voice_client.stop()
        await interaction.response.send_message("Skipped.", ephemeral=True)
    else:
        await interaction.response.send_message("Nothing is currently playing.", ephemeral=True)

@bot.tree.command(name="create_playlist", description="Create a playlist")
@app_commands.describe(name="Playlist name")
async def create_playlist_cmd(interaction: discord.Interaction, name: str):
    success = await create_playlist(interaction.user.id, name)
    if success:
        await interaction.response.send_message(f"Playlist created: {name}", ephemeral=True)
    else:
        await interaction.response.send_message("Playlist already exists.", ephemeral=True)

@bot.tree.command(name="add_to_playlist", description="Add URL to playlist (owner only)")
@app_commands.describe(name="Playlist name", url="URL")
async def add_to_playlist_cmd(interaction: discord.Interaction, name: str, url: str):
    success = await add_to_playlist(interaction.user.id, name, url)
    if success:
        await interaction.response.send_message(f"Added to playlist {name}", ephemeral=True)
    else:
        await interaction.response.send_message("Playlist does not exist (or you are not the owner).", ephemeral=True)

@bot.tree.command(name="playlist", description="Load playlist and add tracks to queue")
@app_commands.describe(name="Playlist name", owner="Owner ID (optional)")
async def playlist_cmd(interaction: discord.Interaction, name: str, owner: str = None):
    user_id = owner or str(interaction.user.id)
    urls = await get_playlist(user_id, name)
    if urls is None:
        await interaction.response.send_message("Playlist does not exist.", ephemeral=True)
        return
    if not interaction.user.voice:
        await interaction.response.send_message("You must be in a voice channel.", ephemeral=True)
        return
    if not interaction.guild.voice_client:
        channel = interaction.user.voice.channel
        await channel.connect()
    queue = get_queue(interaction.guild.id)
    for url in urls:
        queue.queue.append(url)
    await interaction.response.send_message(f"Loaded {len(urls)} tracks to queue.", ephemeral=True)
    if not interaction.guild.voice_client.is_playing():
        await play_next(interaction)

if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Please set the DISCORD_TOKEN environment variable")
        exit(1)
    bot.run(token)
@bot.tree.command(name="add_to_playlist", description="Přidá URL do playlistu (jen owner)")
@app_commands.describe(name="Název playlistu", url="URL")
async def add_to_playlist_cmd(interaction: discord.Interaction, name: str, url: str):
    success = await add_to_playlist(interaction.user.id, name, url)
    if success:
        await interaction.response.send_message(f"Přidáno do playlistu {name}", ephemeral=True)
    else:
        await interaction.response.send_message("Playlist neexistuje (nebo nejsi owner).", ephemeral=True)

@bot.tree.command(name="playlist", description="Načte playlist a přidá skladby do fronty")
@app_commands.describe(name="Název playlistu", owner="Owner ID (volitelné)")
async def playlist_cmd(interaction: discord.Interaction, name: str, owner: str = None):
    user_id = owner or str(interaction.user.id)
    urls = await get_playlist(user_id, name)
    
    if urls is None:
        await interaction.response.send_message("Playlist neexistuje.", ephemeral=True)
        return
    
    if not interaction.user.voice:
        await interaction.response.send_message("Musíš být v hlasovém kanálu.", ephemeral=True)
        return
    
    if not interaction.guild.voice_client:
        channel = interaction.user.voice.channel
        await channel.connect()
    
    queue = get_queue(interaction.guild.id)
    for url in urls:
        queue.queue.append(url)
    
    await interaction.response.send_message(f"Načteno {len(urls)} skladeb do fronty.", ephemeral=True)
    
    if not interaction.guild.voice_client.is_playing():
        await play_next(interaction)

# Run the bot
if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        print("Please set the DISCORD_TOKEN environment variable")
        exit(1)
    
    bot.run(token)
