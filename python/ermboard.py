# A Discord bot inspired by the similar bot on Discord named "Starboard", which functionally works the same as the Starboard bot, barring the fact that it is intended for "Erm" messages rather than "starred" messages.

import discord
from discord import app_commands
from discord.ext import commands
from os import system, remove
from shutil import rmtree
from os.path import exists
from json import load
import re
from emoji import emoji_list
from io import BytesIO
from httpx import AsyncClient
from sys import exit as sexit, platform
from subprocess import Popen
import sqlite3

intents = discord.Intents.all()
perms = discord.Permissions(manage_messages=True, manage_threads=True, manage_expressions=True, view_audit_log=True, manage_guild=True, manage_nicknames=True, kick_members=True, ban_members=True, create_expressions=True, moderate_members=True, create_events=True, manage_events=True)
DEFAULT_ERM = discord.PartialEmoji(name="Erm", id=1250449074977771674)
DATABASE_FILE = "data/ermboard.db"

class Client(discord.Client):
    def __init__(self, *, intents: discord.Intents, **options):
        super().__init__(intents=intents, options=options)
        self.tree = app_commands.CommandTree(self)
        self.attachment_retriever = AsyncClient()

    async def on_ready(self):
        print(f"Logged in as {self.user.display_name}")
        # Register slash commands
        await self.tree.sync()
        await self.tree.sync(guild=discord.Object(1225102857431420988))
        await self.change_presence(activity=discord.Activity(name="for Erms 🗣️", type=discord.ActivityType.watching))

        if exists("data/ermboard/ermboard_messages.json"):
            print("old messages file exists, rebasing...")
            with sqlite3.connect(DATABASE_FILE) as conn:
                cursor = conn.cursor()
                with open("data/ermboard/ermboard_messages.json", "r") as f:
                    msgs = load(f)
                    for key, val in msgs.items():
                        message_id = int(key.split(",")[0])
                        channel_id = int(key.split(",")[1])
                        try:
                            message = await (client.get_channel(channel_id) or await client.fetch_channel(channel_id)).fetch_message(message_id)
                        except discord.NotFound:
                            message = None
                        cursor.execute("""
                        INSERT INTO ermboard_messages (message_id, channel_id, author_id, ermboard_message_id, ermboard_channel_id, erm_count)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """, (message_id, channel_id, message.author.id if message else None, val[0], val[1], 3))
            await (await client.fetch_channel(1250463063140990978)).send(file=discord.File("data/ermboard.db"))
            remove("data/ermboard/ermboard_messages.json")
        if exists("data/ermboard"):
            rmtree("data/ermboard")

client = Client(intents=intents)
tree = client.tree

class GuildSettings:
    def __init__(self, min_erms=3, allow_self_reacting=True, ermboard_channel_id=None, blacklisted_users=None, ping_authors=True, erm_emojis=None):
        self.min_erms = min_erms
        self.allow_self_reacting = allow_self_reacting
        self.ermboard_channel_id = ermboard_channel_id
        self.blacklisted_users = blacklisted_users if blacklisted_users is not None else set()
        self.ping_authors = ping_authors
        self.erm_emojis: set[discord.PartialEmoji | discord.Emoji] = set(erm_emojis) if erm_emojis is not None else set()

def init_db():
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        # Table for guild settings
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS guild_settings (
            guild_id INTEGER PRIMARY KEY,
            min_erms INTEGER DEFAULT 3,
            allow_self_reacting BOOLEAN DEFAULT 1,
            ermboard_channel_id INTEGER,
            ping_authors BOOLEAN DEFAULT 1,
            blacklisted_users TEXT,
            erm_emojis TEXT
        )
        """)
        # Table for ermboard messages
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS ermboard_messages (
            message_id INTEGER,
            channel_id INTEGER,
            author_id INTEGER,
            ermboard_message_id INTEGER,
            ermboard_channel_id INTEGER,
            erm_count INTEGER,
            on_hall_of_erm BOOLEAN DEFAULT 0,
            PRIMARY KEY (message_id, channel_id)
        )
        """)

async def get_guild_settings(guild: discord.Guild):
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM guild_settings WHERE guild_id = ?", (guild.id,))
        result = cursor.fetchone()
        if result:
            return GuildSettings(
                min_erms=result[1],
                allow_self_reacting=bool(result[2]),
                ermboard_channel_id=result[3],
                ping_authors=bool(result[4]),
                blacklisted_users=[int(id) for id in result[5].split(",") if id.strip() != ''],
                erm_emojis=[discord.PartialEmoji.from_str(id) for id in result[6].split(",") if id.strip() != '']
            )
        return None

def save_guild_settings(guild_id: int, settings: GuildSettings):
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT OR REPLACE INTO guild_settings (guild_id, min_erms, allow_self_reacting, ermboard_channel_id, ping_authors, blacklisted_users, erm_emojis)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (guild_id, settings.min_erms, settings.allow_self_reacting, settings.ermboard_channel_id, settings.ping_authors, ",".join([str(id) for id in settings.blacklisted_users]), ",".join([str(emoji) for emoji in settings.erm_emojis])))

def get_message_erm_count(message_id: int, channel_id: int):
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT erm_count FROM ermboard_messages WHERE message_id = ? AND channel_id = ?",
                    (message_id, channel_id))
        result = cursor.fetchone()
        return result[0] if result else 0

def update_message_erm_count(message_id: int, channel_id: int, erm_count: int):
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE ermboard_messages SET erm_count = ? WHERE message_id = ? AND channel_id = ?",
                    (erm_count, message_id, channel_id))

def get_ermboard_message_id(message_id: int, channel_id: int):
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT ermboard_message_id, ermboard_channel_id FROM ermboard_messages WHERE message_id = ? AND channel_id = ?",
                    (message_id, channel_id))
        result = cursor.fetchone()
        return (result[0], result[1]) if result else (None, None)

def get_message_id_from_ermboard_message_id(ermboard_message_id: int, ermboard_channel_id: int):
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT message_id, channel_id FROM ermboard_messages WHERE ermboard_message_id = ? AND ermboard_channel_id = ?",
                    (ermboard_message_id, ermboard_channel_id))
        result = cursor.fetchone()
        return (result[0], result[1]) if result else (None, None)

def save_ermboard_message(message_id: int, channel_id: int, author_id: int, ermboard_message_id: int, ermboard_channel_id: int, erm_count: int):
    with sqlite3.connect(DATABASE_FILE) as conn:
        try:
            cursor = conn.cursor()
            cursor.execute("""
            INSERT INTO ermboard_messages (message_id, channel_id, author_id, ermboard_message_id, ermboard_channel_id, erm_count)
            VALUES (?, ?, ?, ?, ?, ?)
            """, (message_id, channel_id, author_id, ermboard_message_id, ermboard_channel_id, erm_count))
            return True
        except sqlite3.IntegrityError:
            return False

def delete_ermboard_message(message_id: int, channel_id: int):
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM ermboard_messages WHERE message_id = ? AND channel_id = ?",
                    (message_id, channel_id))

def is_mod():
    def predicate(ctx: discord.Interaction):
        return ctx.user.guild_permissions.manage_channels or ctx.user.guild_permissions.manage_guild or ctx.user.guild_permissions.manage_roles or ctx.user.guild_permissions.administrator
    return app_commands.check(predicate)

def is_owner():
    async def predicate(ctx: commands.Context[commands.Bot]):
        return await ctx.bot.is_owner(ctx.author)
    return commands.check(predicate)

@client.event
async def on_guild_join(guild: discord.Guild):
    settings = GuildSettings()
    for channel in guild.text_channels:
        if channel.name == "ermboard":
            settings.ermboard_channel_id = channel.id
            break
    if settings.ermboard_channel_id == None:
        for channel in guild.text_channels:
            if channel.name == "starboard": # settle for starboard if it cant find ermboard
                settings.ermboard_channel_id = channel.id
                break
    settings.erm_emojis = [str(emoji) for emoji in guild.emojis if emoji.name in ["erm", "Erm"]]
    save_guild_settings(guild.id, settings)
    return settings

@client.event
async def on_message(message: discord.Message):
    if message.author == client.user:
        return

    settings = await get_guild_settings(message.guild)
    if not settings:
        settings = await on_guild_join(message.guild)
    if message.content.strip().strip("*_|.!?") in ["Erm", "erm", "ERM", str(DEFAULT_ERM), *[str(emoji) for emoji in settings.erm_emojis]]:
        async for msg in message.channel.history(before=message.created_at, oldest_first=False, limit=None):
            if not msg.content.strip().strip("*_|.!?") in ["Erm", "erm", "ERM", str(DEFAULT_ERM), *[str(emoji) for emoji in settings.erm_emojis]]:
                break
        ermboard_message_id, ermboard_channel_id = get_ermboard_message_id(msg.id, msg.channel.id)
        if ermboard_message_id is None and ermboard_channel_id is None:
            erm_count = await count_erms(settings, msg)
            if erm_count >= settings.min_erms:
                await send_to_ermboard(msg, settings, erm_count)
        else:
            ermboard_message = await (client.get_channel(ermboard_channel_id) or await client.fetch_channel(ermboard_channel_id)).fetch_message(ermboard_message_id)
            await update_erm_count_in_ermboard(msg, ermboard_message, settings)

@client.event
async def on_raw_message_delete(payload: discord.RawMessageDeleteEvent):
    if get_message_id_from_ermboard_message_id(payload.message_id, payload.channel_id) != (None, None): # is an ermboard message
        delete_ermboard_message(payload.message_id, payload.channel_id)
    guild = client.get_guild(payload.guild_id) if payload.guild_id else None
    if guild:
        settings = await get_guild_settings(guild)
        if not settings:
            settings = await on_guild_join(guild)
    else:
        return

    channel = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
    async for msg in channel.history(limit=None, before=discord.Object(id=payload.message_id)):
        if msg.content.strip().strip("*_|.!?") not in ["Erm", "erm", "ERM", str(DEFAULT_ERM), *[str(emoji) for emoji in settings.erm_emojis]]:
            break

    ermboard_message_id, ermboard_channel_id = get_ermboard_message_id(msg.id, msg.channel.id)
    erm_count = await count_erms(settings, msg)
    if ermboard_message_id is not None and ermboard_channel_id is not None:
        ermboard_channel = client.get_channel(ermboard_channel_id) or await client.fetch_channel(ermboard_channel_id)
        try:
            ermboard_message = await ermboard_channel.fetch_message(ermboard_message_id)

            if erm_count < settings.min_erms:
                await remove_from_ermboard(msg, ermboard_message)
            else:
                await update_erm_count_in_ermboard(msg, ermboard_message, settings, erm_count)
        except discord.NotFound:
            delete_ermboard_message(msg.id, msg.channel.id)
    elif erm_count >= settings.min_erms:
        await send_to_ermboard(msg, settings, erm_count)

@client.event
async def on_raw_message_edit(payload: discord.RawMessageUpdateEvent):
    guild = client.get_guild(payload.guild_id) if payload.guild_id else None
    if guild:
        settings = await get_guild_settings(guild)
        if not settings:
            settings = await on_guild_join(guild)
    else:
        return

    channel = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
    async for msg in channel.history(limit=None, before=discord.Object(id=payload.message_id)):
        if msg.content.strip().strip("*_|.!?") not in ["Erm", "erm", "ERM", str(DEFAULT_ERM), *[str(emoji) for emoji in settings.erm_emojis]]:
            break

    ermboard_message_id, ermboard_channel_id = get_ermboard_message_id(msg.id, msg.channel.id)
    if ermboard_message_id is not None and ermboard_channel_id is not None:
        ermboard_channel = client.get_channel(ermboard_channel_id) or await client.fetch_channel(ermboard_channel_id)
        ermboard_message = await ermboard_channel.fetch_message(ermboard_message_id)
        erm_count = await count_erms(settings, msg, ermboard_message)
        if erm_count < settings.min_erms:
            await remove_from_ermboard(msg, ermboard_message)
        else:
            await update_erm_count_in_ermboard(msg, ermboard_message, settings, erm_count)
    elif await count_erms(settings, msg) >= settings.min_erms:
        await send_to_ermboard(msg, settings, erm_count)
    
    try:
        message = await channel.fetch_message(payload.message_id)
    except discord.NotFound:
        return
    ermboard_message_id, ermboard_channel_id = get_ermboard_message_id(message.id, message.channel.id)
    if ermboard_message_id is not None and ermboard_channel_id is not None:
        ermboard_channel = client.get_channel(ermboard_channel_id) or await client.fetch_channel(ermboard_channel_id)
        try:
            ermboard_message = await ermboard_channel.fetch_message(ermboard_message_id)
        except discord.NotFound:
            delete_ermboard_message(message.id, message.channel.id)
            return
        embeds, _ = await format_erm_embed(message, colour=discord.Colour(0xEEE2A0))
        attachments = await copy_attachments(message)

        if message.reference:
            ref_message = await message.channel.fetch_message(message.reference.message_id)
            ref_embeds, _ = await format_erm_embed(ref_message, prefix="Replying to ")
            embeds.extend(ref_embeds)
            #filenames.extend(ref_filenames)
            attachments.extend(await copy_attachments(ref_message))
        await ermboard_message.edit(embeds=embeds, attachments=attachments)

async def count_erms(settings: GuildSettings, *messages: discord.Message):
    l: list[discord.Reaction] = []
    primary_message = None
    for message in messages:
        if message is not None:
            if primary_message == None:
                primary_message = message
            l.extend(message.reactions)
    erm_count = 0
    reacted_users = []
    erm_emoji_ids = [emoji.id if isinstance(emoji, (discord.PartialEmoji, discord.Emoji)) else emoji for emoji in settings.erm_emojis]
    for reaction in l:
        if reaction.emoji.id if isinstance(reaction.emoji, (discord.PartialEmoji, discord.Emoji)) else reaction.emoji in erm_emoji_ids:
            for user in [user async for user in reaction.users(type=discord.enums.ReactionType.normal)] + [user async for user in reaction.users(type=discord.enums.ReactionType.burst)]:
                if user.id not in reacted_users and user.id not in settings.blacklisted_users and user != client.user:
                    erm_count += 1
                    reacted_users.append(user.id)
    async for msg in primary_message.channel.history(after=primary_message.created_at, oldest_first=True, limit=None):
        if msg.content.strip().strip("*_|.!?") in ["Erm", "erm", "ERM", str(DEFAULT_ERM), *[str(emoji) for emoji in settings.erm_emojis]] and msg.author.id not in reacted_users and msg.author.id not in settings.blacklisted_users and msg.author != client.user:
            erm_count += 1
            reacted_users.append(msg.author.id)
        elif not msg.author.id in reacted_users:
            break
    del reacted_users
    return erm_count

@client.event
async def on_raw_reaction_add(payload: discord.RawReactionActionEvent):
    guild = client.get_guild(payload.guild_id) or await client.fetch_guild(payload.guild_id)
    settings = await get_guild_settings(guild)
    if not settings:
        settings = await on_guild_join(guild)
    if payload.user_id in settings.blacklisted_users or payload.user_id == client.user.id:
        return

    if payload.emoji in [DEFAULT_ERM, *settings.erm_emojis]:
        channel = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
        reacted_message = await channel.fetch_message(payload.message_id)
        message = None
        isnt_ermboard = get_ermboard_message_id(payload.message_id, payload.channel_id) != (None, None) # true if the message is on ermboard and isn't an ermboard message
        mid, cid = get_message_id_from_ermboard_message_id(payload.message_id, payload.channel_id) if not isnt_ermboard else get_ermboard_message_id(payload.message_id, payload.channel_id)
        if mid is not None and cid is not None:
            message = await (client.get_channel(cid) or await client.fetch_channel(cid)).fetch_message(mid)
        if message != None or isnt_ermboard: # message is in ermboard
            await update_erm_count_in_ermboard(message if not isnt_ermboard else reacted_message, reacted_message if not isnt_ermboard else message, settings)
        elif not isnt_ermboard: # message isn't in ermboard
            erm_count = await count_erms(settings, reacted_message)
            if erm_count >= settings.min_erms:
                await send_to_ermboard(reacted_message, settings, erm_count)

@client.event
async def on_raw_reaction_remove(payload: discord.RawReactionActionEvent, *, clear=False, fullclear=False):
    guild = client.get_guild(payload.guild_id) or await client.fetch_guild(payload.guild_id)
    settings = await get_guild_settings(guild)
    if not settings:
        settings = await on_guild_join(guild)
    if not clear and (payload.user_id in settings.blacklisted_users or payload.user_id == client.user.id):
        return

    if fullclear or payload.emoji in [DEFAULT_ERM, *settings.erm_emojis]:
        channel = client.get_channel(payload.channel_id) or await client.fetch_channel(payload.channel_id)
        reacted_message = await channel.fetch_message(payload.message_id)
        message = None
        isnt_ermboard = get_ermboard_message_id(payload.message_id, payload.channel_id) != (None, None)
        mid, cid = get_message_id_from_ermboard_message_id(payload.message_id, payload.channel_id) if not isnt_ermboard else get_ermboard_message_id(payload.message_id, payload.channel_id)
        if mid is not None and cid is not None:
            message = await (client.get_channel(cid) or await client.fetch_channel(cid)).fetch_message(mid)
        erm_count = await count_erms(settings, message, reacted_message)
        if erm_count < settings.min_erms:
            await remove_from_ermboard(message if not isnt_ermboard else reacted_message, reacted_message if not isnt_ermboard else message)
        elif message != None or isnt_ermboard:
            await update_erm_count_in_ermboard(message if not isnt_ermboard else reacted_message, reacted_message if not isnt_ermboard else message, settings, erm_count)

@client.event
async def on_raw_reaction_clear_emoji(payload: discord.RawReactionClearEmojiEvent):
    await on_raw_reaction_remove(payload, clear=True)

@client.event
async def on_raw_reaction_clear(payload: discord.RawReactionClearEvent):
    await on_raw_reaction_remove(payload, clear=True, fullclear=True)

async def format_erm_embed(message: discord.Message, prefix="", colour=discord.Colour(0x2B2D31)):
    filenames = []
    embeds = []
    embed = discord.Embed(description=message.system_content, colour=colour, timestamp=message.created_at)
    embed.set_author(name=f"{prefix}{message.author.display_name}{' 🤖' if message.author.bot or message.author.system else ''}", url=message.jump_url, icon_url=message.author.display_avatar.url)
    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type.startswith('image/'):
                if getattr(embed, "_image", None) is None:
                    embed.set_image(url=attachment.url)
                else:
                    embeds.append(discord.Embed().set_image(url=attachment.url))
    if message.stickers:
        for sticker in message.stickers:
            if sticker.format is discord.StickerFormatType.apng:
                embed.description += f"\n*Sent a sticker: {sticker.name}*"
            else:
                if getattr(embed, "_image", None) is None:
                    embed.set_image(url=sticker.url)
                else:
                    embeds.append(discord.Embed().set_image(url=sticker.url))
    embeds.append(embed)
    embeds.extend(message.embeds)
    return embeds, filenames

async def copy_attachments(message: discord.Message):
    attachments = []
    if message.attachments:
        for attachment in message.attachments:
            if not attachment.content_type.startswith('image/'):
                async with client.attachment_retriever as h:
                    response = await h.get(attachment.url)
                    if response.status_code == 200:
                        attachment_bytes = response.read()
                        file = discord.File(BytesIO(attachment_bytes), filename=attachment.filename, spoiler=attachment.is_spoiler(), description=attachment.description)
                        attachments.append(file)
    return attachments

async def send_to_ermboard(message: discord.Message, settings: GuildSettings, erm_count: int = None):
    ermboard_channel = client.get_channel(settings.ermboard_channel_id) or await client.fetch_channel(settings.ermboard_channel_id)
    if not ermboard_channel or message.author == client.user:
        return

    embeds, _ = await format_erm_embed(message, colour=discord.Colour(0xEEE2A0))
    attachments = await copy_attachments(message)

    if message.reference:
        try:
            ref_message = await message.channel.fetch_message(message.reference.message_id)
            ref_embeds, _ = await format_erm_embed(ref_message, prefix="Replying to ")
            embeds.extend(ref_embeds)
            #filenames.extend(ref_filenames)
            attachments.extend(await copy_attachments(ref_message))
        except discord.NotFound:
            pass

    erm_count = erm_count or await count_erms(settings, message)
    additional_text = f"{DEFAULT_ERM} **{erm_count}** | {message.jump_url}"
    if settings.ping_authors:
        additional_text += f" ({message.author.mention})"
    ermboard_message = await ermboard_channel.send(content=additional_text, embeds=embeds[::-1], files=attachments)
    save_ermboard_message(message.id, message.channel.id, message.author.id, ermboard_message.id, settings.ermboard_channel_id, erm_count)
    await ermboard_message.add_reaction(DEFAULT_ERM)

async def remove_from_ermboard(message: discord.Message, ermboard_message: discord.Message):
    if message is None:
        return
    delete_ermboard_message(message.id, message.channel.id)
    await ermboard_message.delete()

async def update_erm_count_in_ermboard(message: discord.Message, ermboard_message: discord.Message, settings: GuildSettings, erm_count: int = None):
    erm_count = erm_count or await count_erms(settings, message, ermboard_message) # this is so fucked
    additional_text = f"{DEFAULT_ERM} **{erm_count}** | {message.jump_url}"
    if settings.ping_authors:
        additional_text += f" ({message.author.mention})"
    with sqlite3.connect(DATABASE_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM ermboard_messages WHERE message_id = ? AND channel_id = ? AND ermboard_message_id = ? AND ermboard_channel_id = ?",
                    (message.id, message.channel.id, ermboard_message.id, ermboard_message.channel.id))
        data = cursor.fetchone()
        if data:
            cursor.execute("UPDATE ermboard_messages SET erm_count = ? WHERE message_id = ? AND channel_id = ?", (erm_count, data[0], data[1]))
            if bool(data[6]): # on hall of erm
                additional_text += " 🏆"
            if data[5] != erm_count:
                await ermboard_message.edit(content=additional_text)

@tree.command(name="set-min-erms", description="Set the minimum amount of Erms required for a message to be sent to the Ermboard")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def set_min_erm(interaction: discord.Interaction, amount: int):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)

    settings.min_erms = amount
    save_guild_settings(interaction.guild_id, settings)
    await interaction.response.send_message(f"Minimum Ermness required set to {amount}", ephemeral=True)

@tree.command(name="set-ermboard-channel", description="Set the Ermboard channel")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def set_ermboard_channel(interaction: discord.Interaction, channel: discord.TextChannel):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)

    settings.ermboard_channel_id = channel.id
    save_guild_settings(interaction.guild_id, settings)
    await interaction.response.send_message(f"Ermboard channel set to {channel.mention}", ephemeral=True)

@tree.command(name="blacklist-user", description="Blacklist a user from Ermboard")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def blacklist_user(interaction: discord.Interaction, user: discord.User):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)

    settings.blacklisted_users.add(user.id)
    save_guild_settings(interaction.guild_id, settings)
    await interaction.response.send_message(f"User `{user.display_name}` is now blacklisted from the Ermboard", ephemeral=True)

@tree.command(name="ping-author", description="Set whether to ping the author of messages sent to the Ermboard")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def set_ping_author(interaction: discord.Interaction, should_ping: bool):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)

    settings.ping_authors = should_ping
    save_guild_settings(interaction.guild_id, settings)
    status = "enabled" if should_ping else "disabled"
    await interaction.response.send_message(f"Pinging authors has been {status}", ephemeral=True)

@tree.command(name="set-erm-emojis", description="Add new Erm emojis by scanning a string")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def set_erm_emojis(interaction: discord.Interaction, emojis: str):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)

    emoji_strs = re.findall(discord.PartialEmoji._CUSTOM_EMOJI_RE, emojis)
    erm_emojis = [discord.PartialEmoji.from_str(f"<{s[0]}:{s[1]}:{s[2]}>") for s in emoji_strs] + [discord.PartialEmoji(name=emoji["emoji"]) for emoji in emoji_list(emojis)]
    settings.erm_emojis = erm_emojis
    save_guild_settings(interaction.guild_id, settings)
    await interaction.response.send_message(f"Set {', '.join([str(e) for e in erm_emojis])} as {'an ' if abs(len(erm_emojis)) == 1 else ''}Erm emoji{'s' if abs(len(erm_emojis)) != 1 else ''}", ephemeral=True)

@tree.command(name="help", description="Show help for Ermboard commands")
async def help_command(interaction: discord.Interaction):
    help_text = (
        "`/set-min-erms` - Set the minimum amount of Erms required\\n"
        "`/set-ermboard-channel` - Set the Ermboard channel\\n"
        "`/blacklist-user` - Blacklist a user from Ermboard\\n"
        "`/ping-author` - Set whether to ping the author of messages sent to the Ermboard\\n"
        "`/set-erm-emojis` - Add new Erm emojis by scanning a string\\n"
        "`/help` - Show this help message\\n"
    )
    await interaction.response.send_message(help_text, ephemeral=True)

# Context menu commands
@tree.context_menu(name="Send to Ermboard")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def send_to_ermboard_context(interaction: discord.Interaction, message: discord.Message):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)
    await send_to_ermboard(message, settings)
    await interaction.response.send_message(f"Message sent to Ermboard", ephemeral=True)

@tree.context_menu(name="Add to Hall of Erm")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def add_to_hall_of_erm(interaction: discord.Interaction, message: discord.Message):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)
    if settings and settings.ermboard_channel_id:
        try:
            with sqlite3.connect(DATABASE_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE ermboard_messages SET on_hall_of_erm = ? WHERE message_id = ? AND channel_id = ?", (True, message.id, message.channel.id))

            if not message.content.endswith(" 🏆"):
                await message.edit(content=message.content + " 🏆")
                await interaction.response.send_message(f"Message added to Hall of Erm", ephemeral=True)
            else:
                await interaction.response.send_message(f"Message could not be added to the Hall of Erm", ephemeral=True)
        except:
            await interaction.response.send_message(f"Message could not be added to the Hall of Erm (is this an Ermboard message?)", ephemeral=True)

@tree.context_menu(name="Remove From Hall of Erm")
@is_mod()
@app_commands.default_permissions(manage_guild=True)
async def remove_from_hall_of_erm(interaction: discord.Interaction, message: discord.Message):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)
    if settings and settings.ermboard_channel_id:
        try:
            with sqlite3.connect(DATABASE_FILE) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE ermboard_messages SET on_hall_of_erm = ? WHERE message_id = ? AND channel_id = ?", (False, message.id, message.channel.id))

            if message.content.endswith(" 🏆"):
                await message.edit(content=message.content[:-2])
                await interaction.response.send_message(f"Message removed from Hall of Erm", ephemeral=True)
            else:
                await interaction.response.send_message(f"Message could not be removed from the Hall of Erm", ephemeral=True)
        except:
            await interaction.response.send_message(f"Message could not be removed from the Hall of Erm (is this an Ermboard message?)", ephemeral=True)

@tree.command(name="leaderboard", description="Show the Erm leaderboard")
async def leaderboard_command(interaction: discord.Interaction):
    # TODO: do
    await interaction.response.send_message("Erm leaderboard coming soon!", ephemeral=True)

@tree.command(name="hall-of-erm", description="View the Hall of Erm")
async def view_hall_of_erm(interaction: discord.Interaction):
    settings = await get_guild_settings(interaction.guild)
    if not settings:
        settings = await on_guild_join(interaction.guild)
    if settings and settings.ermboard_channel_id:
        channel = client.get_channel(settings.ermboard_channel_id) or await client.fetch_channel(settings.ermboard_channel_id)
        with sqlite3.connect(DATABASE_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT ermboard_message_id, erm_count FROM ermboard_messages WHERE ermboard_channel_id = ? AND on_hall_of_erm = 1",
                        (settings.ermboard_channel_id,))
            hall_of_erm = [(await channel.fetch_message(msg[0]), msg[1]) for msg in cursor.fetchall()]
        hall_text = "\n".join([f"{'🥇' if i == 0 else '🥈' if i == 1 else '🥉' if i == 2 else '🏅'} {msg[0].jump_url} | **{msg[1]}** {DEFAULT_ERM} | by *{msg[0].embeds[-1].author.name}*" for i, msg in enumerate(hall_of_erm)])
        await interaction.response.send_message(f"Hall of Erm:\n{hall_text}", ephemeral=True)

@tree.command(name="update", description="Provide an update to the bot's code")
@app_commands.describe(program="The updated version of the program")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def update(ctx: discord.Interaction, program: discord.Attachment):
    if program.filename.endswith(".py"):
        path = __file__.replace("\\", "/")
        await ctx.response.send_message("Updating and restarting...", ephemeral=True)
        await program.save(path.split("/")[-1])
        print("Opening updated file...", end="\n\n")
        if platform.startswith("win"):
            Popen(f"start python -c \"from time import sleep; from subprocess import run; sleep(5); run('python \\\"{path.split('/')[-1]}\\\"')\"", shell=True)
        else:
            system(f"lxterminal --title='ermboard.py' -e \"source venv/bin/activate; python './{path.split('/')[-1]}'\"")
        await client.close()
        sexit()
    else:
        await ctx.response.send_message("nuh")

@tree.command(name="open", description="Downloads a file to the server and opens it")
@app_commands.describe(program="The Python program")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def open_python(ctx: discord.Interaction, program: discord.Attachment):
    if program.filename.endswith(".py") and program.filename != __file__.replace("\\", "/").split("/")[-1]:
        await ctx.response.send_message("Starting new file...", ephemeral=True)
        await program.save(program.filename)
        if platform.startswith("win"):
            Popen(f"start python -c \"from time import sleep; from subprocess import run; sleep(5); run('python \\\"{program.filename}\\\"')\"", shell=True)
        else:
            system(f"lxterminal --title=\"{program.filename}\" -e \"source venv/bin/activate; python './{program.filename}'\"")
    else:
        await ctx.response.send_message("nuh")

@tree.command(name="install", description="Installs a Python package onto root")
@app_commands.describe(package="The package name")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def install(ctx: discord.Interaction, package: str):
    await ctx.response.defer(ephemeral=True)
    try:
        if platform.startswith("win"):
            Popen(f"pip install {package}", shell=True)
        else:
            system(f"pip install {package}")
        await ctx.followup.send(f"Installation success.")
    except Exception as e:
        await ctx.followup.send(f"Installation failed: {e}")

@tree.command(name="stop", description="Kills Ermboard")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def stop(ctx: discord.Interaction):
    await ctx.response.send_message("Exiting...", ephemeral=True)
    await client.close()
    sexit()

init_db()
client.run('DISCORD_BOT_TOKEN')