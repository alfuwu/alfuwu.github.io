# A utility program that downloads a Discord server to the local machine.

from contextlib import suppress
from json import dump
from typing import Literal
from asyncio import get_event_loop, sleep as asleep
from discord import Client, Intents, PartialMessageable
from discord.abc import Snowflake
from discord.errors import Forbidden
from discord.utils import stream_supports_colour
from datetime import datetime
from schedule import run_pending, every
from time import sleep
from zipfile import ZipFile, ZIP_DEFLATED
from os import path, makedirs, walk
from re import search, findall, compile as rcomp
from sys import stdout, stderr
from discord_serialization import * # this is the Discord Serializer
from pydrive.auth import GoogleAuth
from pydrive.drive import GoogleDrive
from aiohttp import ClientSession, ClientPayloadError
from mimetypes import guess_extension
from traceback import format_exception

EMOJI = rcomp(r'<(?P<animated>:a)?:(?P<name>[A-Za-z0-9\_]{2,}):(?P<id>[0-9]{13,20})>')

RESET = "\033[0m"
class Color():
    def __init__(self, text: str, r: int = None, g: int = None, b: int = None, bold: bool = False, italic: bool = False, underlined: bool = False, reset: bool = True):
        self.text = text
        self.r = r
        self.g = g
        self.b = b
        self.bold = bold
        self.italic = italic
        self.underlined = underlined
        self.reset = reset

    def __str__(self) -> str:
        return ("\033[1m" if self.bold else "") + ("\33[3m" if self.italic else "") + ("\033[4m" if self.underlined else "") + (f"\033[38;2;{self.r};{self.g};{self.b}m" if self.r != None and self.g != None and self.b != None else "") + f"{self.text}{RESET if self.reset == True else ''}"
    
    def __repr__(self) -> str:
        return self.__str__()

def fix_file_name(string: str):
    invalid_strings = r"(?i)^aux$|^co(?:n|m[0-9])$|^prn$|^nul$|^lpt[0-9]$"
    substitute_characters = {
        "a": "а", "c": "ϲ", "l": "", "m": "", "n": "ո", "o": "", "p": "р", "r": "", "u": "ս",  "x": "х",
        "A": "", "C": "С", "L": "Ⳑ", "M": "Μ", "N": "Ν", "O": "", "P": "Ρ", "R": "ꓣ", "T": "Τ", "U": "Ս", "X": "Χ"
    }
    invalid_characters = {
        "<": "˂", ">": "˃", ":": "։", "\"": "\'", "/": "⧸", "\\": "⧹", "|": "︱", "?": "？", "*": "⁎"
    }
    new_string = list(string)
    for key, sub in invalid_characters.items():
        for i in range(len(new_string)):
            new_string[i] = sub if len(sub) != 0 and new_string[i] == key else new_string[i] # change invalid characters into valid characters
    if search(invalid_strings, string):
        for key, sub in substitute_characters.items():
            for i in range(len(new_string)):
                new_string[i] = sub if len(sub) != 0 and new_string[i] == key else new_string[i]
    return "".join(new_string)

def is_hidden(file_path):
    return path.isfile(file_path + "/hidden")

def hidden(item: Snowflake):
    if not isinstance(member_view, int) and not isinstance(role_view, int) and isinstance(item, (GuildChannel, Thread)) and not isinstance(item, CategoryChannel):
        return (item.id in channel_id_ignore_list or item.name in channel_id_ignore_list) and not item.id in always_include_channel_ids and not item.name in always_include_channels
    elif isinstance(item, (GuildChannel, Thread)) and not isinstance(item, CategoryChannel):
        view = item.guild.get_member(member_view) if isinstance(member_view, int) else item.guild.get_role(role_view)
        return not item.permissions_for(view).read_messages
    else:
        return False

def zip_folder(folder_path: str, zip_path: str, see_hidden: bool = False, *additional_files):
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zipf:
        for root, dirs, files in walk(folder_path):
            dirs[:] = [d for d in dirs]
            
            for file in files:
                if not file.startswith("[hidden] ") or see_hidden: # ignore hidden indicator
                    zipped_file_name = file
                    if zipped_file_name.startswith("[hidden] "):
                        zipped_file_name = zipped_file_name[9:]
                    file_path = path.join(root, file)
                    arcname = path.relpath(path.join(root, zipped_file_name), folder_path)
                    zipf.write(file_path, arcname=arcname)
            for file, zipped_location in additional_files:
                if path.isfile(file): # make sure file exists
                    zipf.write(file, arcname=zipped_location)
                elif path.exists(file): # is a directory
                    for folder_root, folder_dirs, folder_files in walk(file):
                        for folder_file in folder_files:
                            if not folder_file.startswith("[hidden] ") or see_hidden:
                                zipped_file_name = file
                                if zipped_file_name.startswith("[hidden] "):
                                    zipped_file_name = zipped_file_name[9:]
                                file_path = path.join(folder_root, folder_file)
                                arcname = path.relpath(path.join(folder_root, zipped_file_name), folder_root)
                                zipf.write(file_path, arcname=arcname)
                else:
                    print("Could not find file:", file)

def channel_file_exists(base: str, channel: GuildChannel):
    return (path.exists(f"{base}/{fix_file_name(channel.name)}.json") and \
            path.exists(f"{base}/{fix_file_name(channel.name)}-log.txt")) or \
            (path.exists(f"{base}/[hidden] {fix_file_name(channel.name)}.json") and \
            path.exists(f"{base}/[hidden] {fix_file_name(channel.name)}-log.txt"))

# Function to fetch and save images
async def fetch_and_save_image(session: ClientSession, url: str, filename_base: str, log=None):
    async with session.get(url) as resp:
        if resp.status == 200:
            content_type = resp.headers.get('Content-Type')
            ext = guess_extension(content_type.split(';')[0]) or ".png" # default to .png if extension cannot be determined
            with open(f"{filename_base}{ext}", "wb") as f:
                f.write(await resp.read())
        elif log:
            log(f"Failed to fetch {filename_base} from {url}", beg="\n[{date}] [{type}] ", typ="ERROR")

async def save_all_emojis(session: ClientSession, base_path: str, saved_emojis: list, message: Message, log=None):
    emojis = findall(EMOJI, message.content)

    # Save emojis
    for animated, emoji_name, emoji_id in emojis:
        if int(emoji_id) not in saved_emojis:
            makedirs(base_path, exist_ok=True)
            emoji_url = f"https://cdn.discordapp.com/emojis/{emoji_id}.{'gif' if bool(animated) else 'png'}?size=1024&quality=lossless"
            await fetch_and_save_image(session, emoji_url, f"{base_path}/{fix_file_name(emoji_name)} ({emoji_id})", log)
            saved_emojis.append(int(emoji_id))

async def retry_serialize_message(message, retries=5, delay=2, log=None):
    for attempt in range(retries):
        try:
            return await serialize_message(message)
        except ClientPayloadError as e:
            if log:
                log(f"Payload error on message {message.id} (Attempt {attempt+1}/{retries}): {e}", beg = ('\n' if previous_log.startswith("\r") or previous_log.endswith("\r") else '') + "[{date}] [{type}] ", typ="WARNING")
            await asleep(delay * (attempt + 1))
        except Exception as e:
            if log:
                log(f"Unhandled error on message {message.id} (Attempt {attempt+1}/{retries}): {e}", beg = ('\n' if previous_log.startswith("\r") or previous_log.endswith("\r") else '') + "[{date}] [{type}] ", typ="ERROR")
            await asleep(delay)
    if log:
        log(f"Failed to serialize message {message.id} after {retries} attempts", beg = ('\n' if previous_log.startswith("\r") or previous_log.endswith("\r") else '') + "[{date}] [{type}] ", typ="ERROR")
    return None

async def get_threads(channel: TextChannel, log, private: bool = None):
    if private is not None:
        return [(log(f"Retrieved {th.name}", std=True, beg="\r[{date}] [{type}] "), th)[1] async for th in channel.archived_threads(private=private, limit=None)]
    else:
        return [(log(f"Retrieved {th.name}", std=True, beg="\r[{date}] [{type}] "), th)[1] async for th in channel.archived_threads(limit=None)]

if not path.exists("other/logs"):
    makedirs("other/logs")

if not path.exists("other/eternalizations"):
    makedirs("other/eternalizations")

token = "DISCORD_BOT_TOKEN"

elapsed_seconds = 0
refresh = False
folderize = True
dated = True
upload_to_gdrive = False
server = input("Enter the name of the server you wish to Eternalize: ")
server_id = None if server != "" else input("Enter the ID of the server you wish to Eternalize: ")
channel_ignore_list = [ ]
channel_id_ignore_list = [ ]
private_category_names = [ ]
private_category_ids = []
always_include_channels = [ ]
always_include_channel_ids = [] # channels that are unaffected by member_view
member_view = None # replace with user id to replicate the server from their view (channels they cannot see will be skipped)
skip_invis_channels = True # skip channels the targeted user can't see
role_view = None # replace with role id to replicate the server from their view (overwrites member_view)
previous_log = ""

def main():
    client = Client(intents=Intents.all())
    loop = get_event_loop()
    unfixed_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    date = fix_file_name(unfixed_date)
    saved_emojis = []
    saved_stickers = []
    
    def log(*args, log = True, sep = " ", beg = "[{date}] [{type}] ", end = "\n", std = False, typ: Literal["INFO", "WARNING", "ERROR"] = "INFO"):
        global previous_log
        now_date = str(datetime.now())
        
        # Build formatted and plain outputs
        c_output = beg.replace("{date}", str(Color(now_date, r=128, g=128, b=128))).replace(
            "{type}", str(
                Color(typ, 200, 200, 255, bold=True) if typ == "INFO"
                else Color(typ, r=255, g=255, b=10, bold=True) if typ == "WARNING"
                else Color(typ, r=255, g=50, b=50, bold=True)
            )
        ) + sep.join(map(str, args)) + end

        output = beg.replace("{date}", now_date).replace("{type}", typ) + sep.join(map(str, args)) + end

        if std:
            stdout.write(c_output if stream_supports_colour(stderr) else output)
            stdout.flush()
        else:
            print(c_output if stream_supports_colour(stderr) else output, end="")

        if log:
            try:
                # jank stuff, doesn't really work
                with open(f"other/logs/log-{date}.txt", "a", encoding="utf-8") as log_file:
                    if end == "\r":
                        previous_log = output.rstrip("\r")
                    else:
                        if previous_log:
                            log_file.write(previous_log + "\n")
                            previous_log = ""
                        log_file.write(output)
            except Exception as e:
                print(e)
    try:
        start_time = datetime.now()
        log("Starting...")
        log(f" - Overwrite files: {refresh}")
        log(f" - Categorize channels: {folderize}")
        log(f" - Server: {server} ({server_id})")
        log(f" - Private channel names: {', '.join(channel_ignore_list)}")
        log(f" - Private channel IDs: {', '.join([str(i) for i in channel_id_ignore_list])}")
        log(f" - Private categories: {', '.join(private_category_names)}")
        log(f" - Private category IDs: {', '.join([str(i) for i in private_category_ids])}")
        log(f" - Public channels: {', '.join(always_include_channels)}")
        log(f" - Public channel IDs: {', '.join([str(i) for i in always_include_channel_ids])}")
        log(f" - Targeted member visibility: {member_view}")
        log(f" - Targeted role visibility: {role_view}")
        log(f" - Skip invisible channels (channels hidden by view): {skip_invis_channels}")
        log(f" - Should upload zip to Google Drive: {upload_to_gdrive}")
        log(f"{elapsed_seconds:,} second{'s' if elapsed_seconds != 1 else ''} ha{'ve' if elapsed_seconds != 1 else 's'} passed since the last eternalization.")
        
        @client.event
        async def on_ready():
            session = ClientSession()
            server_name = ""
            for guild in client.guilds:
                log(f"Discovered \"{guild.name}\".")
                if (server_id == None and guild.name.lower() == server.lower()) or guild.id == server_id: # favour server_id over server name
                    log(f"Found server ({guild.name})!")
                    server_name = guild.name
                    found_server = True

                    base_path = f"other/{fix_file_name(server_name)}"
                    if dated:
                        base_path = f"{base_path}/{date}"

                    makedirs(base_path, exist_ok=True)
                
                    if not path.exists(f"{base_path}/Server Info.json") or refresh:
                        with open(f"{base_path}/Server Info.json", "w") as file:
                            dump(await serialize_guild(guild), file)
                            log("Scraped basic server data.")

                    makedirs(f"{base_path}/Server Users", exist_ok=True)
                    makedirs(f"{base_path}/Server Emojis", exist_ok=True)
                    makedirs(f"{base_path}/Server Stickers", exist_ok=True)

                    if guild.icon:
                        await fetch_and_save_image(session, guild.icon.url, f"{base_path}/icon", log)
                    if guild.banner:
                        await fetch_and_save_image(session, guild.banner.url, f"{base_path}/banner", log)
                    
                    # Save profile pictures of all members
                    for member in guild.members:
                        # Get the member's profile picture URL
                        avatar_url = member.avatar.url if member.avatar else member.default_avatar.url
                        # Create the filename base
                        filename_base = f"{base_path}/Server Users/{fix_file_name(member.display_name)} ({fix_file_name(member.name)} - {member.id})"
                        await fetch_and_save_image(session, avatar_url, filename_base, log)

                    for emoji in await guild.fetch_emojis():
                        emoji_url = f"https://cdn.discordapp.com/emojis/{emoji.id}.{'gif' if bool(emoji.animated) else 'png'}?size=1024&quality=lossless"
                        await fetch_and_save_image(session, emoji_url, f"{base_path}/Server Emojis/{fix_file_name(emoji.name)} ({emoji.id})", log)
                        saved_emojis.append(emoji.id)

                    for sticker in await guild.fetch_stickers():
                        await fetch_and_save_image(session, sticker.url, f"{base_path}/Server Stickers/{fix_file_name(sticker.name)} ({sticker.id})", log)
                        saved_stickers.append(sticker.id)

                    log("Scraped server image data.")

                    if folderize:
                        for category in guild.categories:
                            if not hidden(category) or not skip_invis_channels or category.id in always_include_channel_ids or category.name in always_include_channels:
                                f_path = f"{base_path}/{fix_file_name(category.name)}"
                                if not path.exists(f_path):
                                    makedirs(f_path)
                                if not path.exists(f"{f_path}/Category Info.json") or refresh: # don't overwrite
                                    with open(f"{f_path}/Category Info.json", "w") as file:
                                        dump(await serialize_category(category), file)
                                if hidden(category):
                                    file = open(f"{f_path}/hidden", "w")
                                    file.close()

                    log("Scraped server categories.")

                    try:
                        channels = []
                        for text_channel in sorted([ch for ch in guild.channels if ch.category is None if not isinstance(ch, (CategoryChannel, VoiceChannel))], key=lambda ch: ch.position):
                            try:
                                if not isinstance(text_channel, ForumChannel):
                                    channels.append(text_channel)
                                log(f"Retrieving threads for {text_channel.name}...")
                                threads = text_channel.threads
                                for th in threads:
                                    log(f"Retrieved {th.name}", std=True, beg="\r[{date}] [{type}] ")
                                if isinstance(text_channel, TextChannel):
                                    threads.extend(await get_threads(text_channel, log, True))
                                threads.extend(await get_threads(text_channel, log))
                                channels.extend(sorted(threads, key=lambda th: th.created_at))
                                log(beg="")
                            except Forbidden:
                                pass
                        
                        channels.extend(sorted([ch for ch in guild.channels if ch.category is None and isinstance(ch, VoiceChannel)], key=lambda ch: ch.position))
                        for category in sorted(guild.categories, key=lambda c: c.position):
                            #channels.append(category)
                            for text_channel in sorted([ch for ch in category.channels if not isinstance(ch, VoiceChannel)], key=lambda ch: ch.position):
                                try:
                                    if not isinstance(text_channel, ForumChannel):
                                        channels.append(text_channel)
                                    log(f"Retrieving threads for {text_channel.name}...")
                                    threads = text_channel.threads
                                    for th in threads:
                                        log(f"Retrieved {th.name}", std=True, beg="\r[{date}] [{type}] ")
                                    if isinstance(text_channel, TextChannel):
                                        threads.extend(await get_threads(text_channel, log, True))
                                    threads.extend(await get_threads(text_channel, log))
                                    channels.extend(sorted(threads, key=lambda th: th.created_at))
                                    log(beg="")
                                except Forbidden:
                                    pass

                            channels.extend(sorted([ch for ch in category.channels if isinstance(ch, VoiceChannel)], key=lambda ch: ch.position))
                    except BaseException as e:
                        log(e, beg="\n[{date}] [{type}] ", typ="ERROR")
                        log("\n".join(format_exception(e)), typ="ERROR")
                        raise e

                    log("Retrieved all server channels.", end="\n\n")

                    for channel in channels:
                        try:
                            f_path = f"{base_path}/{fix_file_name(channel.category.name) if channel.category is not None else ''}" if folderize else base_path
                            if isinstance(channel, Thread) and folderize:
                                f_path += f"/{fix_file_name(channel.parent.name)}"
                                if not path.exists(f_path):
                                    makedirs(f_path)
                            if isinstance(channel, (TextChannel, VoiceChannel, StageChannel, Thread, PartialMessageable)) and \
                                    channel.name not in channel_ignore_list and channel.id not in channel_id_ignore_list and \
                                    (refresh or not channel_file_exists(f_path, channel)) and \
                                    (not hidden(channel) or not skip_invis_channels or channel.id in always_include_channel_ids or channel.name in always_include_channels):
                                
                                log(f"Scraping \"{channel.name}\"...")
                                messages = { }
                                iteration = 0
                                async for message in channel.history(limit=None):
                                    iteration += 1
                                    log(f"Processing message {iteration:,}", std=True, beg="\r[{date}] [{type}] ", end="")
                                    for reaction in message.reactions:
                                        if isinstance(reaction.emoji, PartialEmoji) and reaction.emoji._state is None:
                                            reaction.emoji = reaction.emoji.with_state(client._get_state())
                                    result = await retry_serialize_message(message)
                                    if result is not None:
                                        messages[message.created_at] = result
                                    else:
                                        messages[message.created_at] = {
                                            "error": "failed to fetch content",
                                            "content": "",
                                            "system_content": "[404 NOT FOUND]",
                                            "created_at": message.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
                                            "author": message.author.id,
                                            "id": message.id,
                                            "attachments": []
                                        }
                                    await save_all_emojis(session, f"{base_path}/Other Emojis", saved_emojis, message, log)
                                    for sticker in message.stickers:
                                        if sticker.id not in saved_stickers:
                                            makedirs(f"{base_path}/Other Stickers", exist_ok=True)
                                            try:
                                                await fetch_and_save_image(session, (await sticker.fetch()).url, f"{base_path}/Other Stickers/{fix_file_name(sticker.name)} ({sticker.id})", log)
                                            except:
                                                pass
                                            saved_stickers.append(sticker.id)
                                print()
                                sorted_messages = sorted(messages.items(), key=lambda x: x[0])
                                log(f"Sorted all messages in \"{channel.name}\".")
                
                                # extract the values in the sorted order
                                message_list = [item[1] for item in sorted_messages]
                                #if save:
                                with open(f"{f_path}/{'[hidden] ' if hidden(channel) else ''}{fix_file_name(channel.name)}-log.txt", "a", encoding="utf-8") as channel_log:
                                    channel_log.write(f"-- Beginning of {channel.name}'s history --\n")
                                    channel_log.write("\n".join((f"({message['created_at']}) {indices['users'][message['author']]['display_name']}: {message['system_content'] if message['system_content'] != '' else message['content']}")
                                                                + (("\n" + "\n".join(message["attachments"])) if len(message["attachments"]) > 0 else "") for message in message_list))
                                    log(f"Successfully wrote human readable log file for channel \"{channel.name}\".")
                                with open(f"{f_path}/{'[hidden] ' if hidden(channel) else ''}{fix_file_name(channel.name)}.json", "w", encoding="utf-8") as log_file:
                                    dump(message_list, log_file)
                                    log(f"Successfully wrote JSON file for channel \"{channel.name}\".")
                                log(f"Finished scraping \"{channel.name}\" (total messages scraped: {len(message_list):,}).", end="\n\n")
                        except Forbidden:
                            log(f"Could not access \"{channel.name}\" (missing permissions)\n", typ="ERROR")
                        except BaseException as e:
                            log(e, beg="\n[{date}] [{type}] ", typ="ERROR")
                            log("\n".join(format_exception(e)), typ="ERROR")
                            raise e
                    log("Scraped server channels.")
                    
                    for key, value in indices.items():
                        if not path.exists(f"{base_path}/Server {key.title()}.json") or refresh:
                            with open(f"{base_path}/Server {key.title()}.json", "w") as file:
                                dump(value, file)
                    log("Logged cached data.")
                    break
            log("Done fetching all previous messages." if found_server else "Could not find server.", typ="INFO" if found_server else "ERROR")
            
            file_path = f"other/{fix_file_name(server_name)}/"
            file_name = fix_file_name(f"{server_name} - {start_time.strftime('%b %d %Y')}.zip")
            zip_folder(f"{file_path}{date if dated else ''}", f"other/eternalizations/{fix_file_name(server_name)}/{file_name}")
            log("Created zip (archive) file.")
            zip_folder(f"{file_path}{date if dated else ''}", f"other/eternalizations/{fix_file_name(server_name)}/Unfiltered/{file_name}", True)
            log("Created unfiltered zip (archive) file.")

            if upload_to_gdrive:
                try:
                    auth = GoogleAuth()
                    if not path.exists("credentials.json"):
                        auth.GetFlow()
                        auth.flow.params.update({"access_type": "offline"})
                        auth.flow.params.update({"approval_prompt": "force"})
                        auth.LocalWebserverAuth()
                    else:
                        auth.LoadCredentialsFile("credentials.json")
                        if auth.access_token_expired:
                            auth.Refresh()
                        else:
                            auth.Authorize()
                    auth.SaveCredentialsFile("credentials.json")
                    drive = GoogleDrive(auth)
                    log("Successfully loaded Google Drive.")
                    
                    file = drive.CreateFile()
                    file.SetContentFile(f"eternalizations/{fix_file_name(server_name)}/{file_name}")
                    file["title"] = file_name
                    file.Upload()
                    
                    unfiltered_file = drive.CreateFile()
                    unfiltered_file.SetContentFile(f"eternalizations/{fix_file_name(server_name)}/Unfiltered/{file_name}")
                    unfiltered_file["title"] = file_name
                    unfiltered_file.Upload()
                    
                    log_upload = drive.CreateFile()
                    log_upload.SetContentFile(f"eternalizations/logs/log-{date}.txt")
                    log_upload["title"] = f"log-{date}.txt"
                    log_upload.Upload()
                except BaseException as e:
                    log(e, beg="\n[{date}] [{type}] ", typ="ERROR")
                    log("\n".join(format_exception(e)), typ="ERROR")
                    log("Failed to finish eternalization.", typ="ERROR")

            end_time = datetime.now()
            elapsed_time = end_time - start_time
            days = elapsed_time.days
            hours, remainder = divmod(elapsed_time.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            elapsed_time_str = f"""{f"{days} day{'s' if days != 1 else ''}{', ' if hours != 0 or minutes != 0 or seconds != 0 else ''}" if days != 0 else ""}{f"{'and ' if seconds == 0 and minutes == 0 and days != 0 else ''}{hours} hour{'s' if hours != 1 else ''}{', ' if minutes != 0 or seconds != 0 else ''}" if hours != 0 else ""}{f"{'and ' if seconds == 0 and (hours != 0 or days != 0) else ''}{minutes} minute{'s' if minutes != 1 else ''}{', ' if seconds != 0 else ''}" if minutes != 0 else ""}{"and " if days != 0 or hours != 0 or minutes != 0 else ""}{seconds} second{"s" if seconds != 1 else ""}"""

            log(f"Finished eternalizing {server_name}. Total time elapsed: {elapsed_time_str}.", beg="\n[{date}] [{type}] ")
            await client.close()
            
        loop.run_until_complete(client.start(token))
    except BaseException as e:
        log(e, beg="\n[{date}] [{type}] ", typ="ERROR")
        raise e

main()