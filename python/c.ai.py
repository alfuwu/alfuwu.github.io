# A Discord bot capable of mediating between Discord and character.ai to add artificial intelligences to Discord.
# It can run multiple of these AI bots concurrently.

from logging import Formatter, StreamHandler, getLogger, INFO
from typing import Literal
from traceback import format_exception
#from characterai import PyAsyncCAI # characterai==0.8.0, websockets==11.0.3
from PyCharacterAI import Client as PyAsyncCAI
from PyCharacterAI.types.chat import Chat, Turn
from PyCharacterAI.exceptions import SessionClosedError, CreateError, ActionError, AuthenticationError
from discord import Client, Interaction, ButtonStyle, Colour, Guild, DMChannel, Thread, Intents, Attachment, Member, Embed, Message, AllowedMentions, PartialEmoji, Object, Forbidden, NotFound, Permissions, Activity, ActivityType, errors
from discord.ui import View, Button
from discord.abc import GuildChannel, PrivateChannel, Messageable
from discord.utils import _ColourFormatter, get, stream_supports_colour
from discord.app_commands import CommandTree, Group, describe, default_permissions
from datetime import datetime, timezone
from random import choice, uniform as randfloat, random, randint
from asyncio import Task, Queue, TimeoutError as AsyncTimeoutError, sleep, get_event_loop
from re import compile as re_compile, sub, findall, search, IGNORECASE
from sys import exc_info, platform, exit as sys_exit
from os import path, makedirs, system, remove
from subprocess import Popen
from json import JSONDecodeError, dump, dumps, load, loads
from uuid import uuid4
has_spacy = True
try:
    from spacy import load as load_model
    try:
        nlp = load_model("en_core_web_sm")
    except Exception:
        system("python -m spacy download en_core_web_sm")
        nlp = load_model("en_core_web_sm")
except ImportError:
    has_spacy = False

clients = []

global_enabled = True

perms = Permissions(manage_messages=True, manage_threads=True, manage_expressions=True, view_audit_log=True, manage_guild=True, manage_nicknames=True, kick_members=True, ban_members=True, create_expressions=True, moderate_members=True, create_events=True, manage_events=True)

WHITELISTED_ADMIN_SERVERS = []

STALKING_QUIPS = [
    "okay"
]

CONFIG = {
    "owner": 123456789012345678, # your user ID
    "random_reply": 0.00069, # chance is a random float from 0 to 1. set to negative (or zero) for no random responses
    "lingering": {
        "chance": 100, # this is the base chance that the AI will linger, from 0 to 100
        "timeout": 10, # chance to linger becomes 0 after this amount of time (in seconds) has passed
        "exponent_curve": 4, # the amount that the exponential dropoffs curve
        "dropoff_type": "plateau" # available: linear, plateau, slide
        # dropoff types and how they affect dropoff:
        # linear
        #  - straightforward, chance to linger will decrease by a defined amount each second that will not deviate.
        #  - equation: y = b - b/c * x, where y equals chance, b equals the base offset, c equals timeout, and x equals the current time since the last message. base: y = 100 - 100/69 * x
        # plateau
        #  - exponential dropoff where chance to linger stays higher the closer you are to zero, but drops off more drastically near the timeout period. increasing the exponent curve makes this more and more noticeable. recommended exponent curve: 2-3, default 2.25
        #  - equation: y = b * (1 - (x/c)^g) where g equals exponent curve. base: y = 100 * (1 - (x/69)^2.25)
        # slide
        #  - opposite of plateau, where chance to linger drastically falls off at the start but starts falling off slower and slower as x approaches the timeout period. recommended exponent curve: 3-4, default 3.41
        #  - equation: y = b * (1 - x/c)^g. base: y = 100 * (1 - x/69)^3.41
    },
    "typing_delay": [0.1, 0.2],
    "status_update": [600, 3600],
    "mention": True,
    "message_format": "{name}: {message}",
    "dm_message_format": "{message}",
    "filtered_message": "[filtered]",
    "quote_format": "(In response to [{quote}])\n{message}",
    "random_talk_channel": 0,
    "dead_chat_prompt": "{SYSTEM}: Nobody has said anything in a while. Think of a topic to talk about and try to engage them!",
    "now_stalking_prompt": "{SYSTEM}: You now receive every single message from {user}. This means that every message they send will be directed to you automatically, whether they meant it to or not. This message is simply for context, and as such, your reply to it will not be displayed. If you see any message that looks out of context and not related to your chat, it probably isn't related to your chat.",
    "use_display_name": True,
    "blacklisted_random_reply_channels": [ ],
    "blacklisted_random_reply_categories": [ ]
}

ARGS_MATCH = r"^<[aA][rR][gG][sS]>title=['\"](.+)['\"]</[aA][rR][gG][sS]>"

def custom_hash(text: str):
    hash_value = 0
    for char in text:
        hash_value = (hash_value * 69 + ord(char)) & 0xFFFFFFFF

    return hash_value

def get_name_color(text: str):
    hash_value = custom_hash(text)
    r = (hash_value & 0xFF0000) >> 16
    g = (hash_value & 0x00FF00) >> 8
    b = hash_value & 0x0000FF

    return Colour.from_rgb(r, g, b)

def is_directed_at(subject, text: str):
    subject = [subject] if isinstance(subject, str) else subject
    doc = nlp(text)
    for p_subject in subject:
        if p_subject.lower() in [tok.text.lower() for tok in doc if (tok.dep_ in ["advcl", "npadvmod", "pobj", "advmod", "nsubjpass", "ROOT"] and tok.pos_ in ["PROPN", "NOUN"]) or tok.dep_ == "nsubj"]:
            return True
    return False

def replace_case_insensitive(text: str, replacee: str, replacement: str):
    return sub(re_compile(replacee, IGNORECASE), replacement, text)

def split_string(text: str, max_length: int = 4000):
    return [text[i:i+max_length] for i in range(0, len(text), max_length)]

def split_string_by_new_line(text: str, max_length: int = 4000):
    split_texts = []
    while len(text) > max_length:
        idx = text.rfind('\n', 0, max_length)
        if idx == -1:
            split_texts.append(text[:max_length])
            text = text[max_length:]
        else:
            split_texts.append(text[:idx+1])
            text = text[idx+1:]
    if text:
        split_texts.append(text)
    return split_texts

def format_text(data: Turn, guild: Guild):
    text: str = data.get_candidates()[0].text.replace("\n\n", "\n")

    if guild is not None:
        for member in guild.members:
            if member.nick is not None and f"@{member.nick.lower()}" in text.lower():
                text = replace_case_insensitive(text, f"@{member.nick}", member.mention)
            if member.global_name is not None and f"@{member.global_name.lower()}" in text.lower():
                text = replace_case_insensitive(text, f"@{member.global_name}", member.mention)
            if f"@{member.name}" in text.lower():
                text = replace_case_insensitive(text, f"@{member.name}", member.mention)

        for role in guild.roles:
            if f"@{role.name}" in text:
                text = replace_case_insensitive(text, f"@{role.name}", role.mention)

        for channel in guild.text_channels:
            if f"#{channel.name}" in text:
                text = replace_case_insensitive(text, f"#{channel.name}", channel.mention)
    return text

aliases = {} # user_id: alias OR (user_id, char_id): alias
try:
    with open("data/ai/aliases.json", "r") as f:
        aliases = load(f)
except FileNotFoundError:
    pass

def save_aliases():
    with open("data/ai/aliases.json", "w") as f:
        dump(aliases, f)

class CharacterAI():
    def __init__(self,
                 intents: Intents,
                 token: str,
                 char: str,
                 *,
                 status: list = None,
                 name: str = None,
                 greeting: str = None,
                 allow_reviving_chat: bool = False,
                 bot_aliases: list = [],
                 autonomous_response_scope: Literal["ALL", "ALIASES_ONLY", "NONE"] = "ALL"
    ):
        self.client = Client(intents=intents)
        clients.append(self.client)
        self.tree = CommandTree(self.client)
        self.ai = PyAsyncCAI()
        #self.non_async_ai = PyCAI("YOUR_CHARACTER_AI_TOKEN")

        self.status = status
        self.name = name
        self.greeting = greeting
        self.enabled = True
        self.token = token
        self.char = char
        self.last_message_data = { }

        self.logged_in = False

        self.can_revive_chat = allow_reviving_chat
        self.aliases = bot_aliases
        self.autonomous_response_scope = autonomous_response_scope

        self.histories = {
            "servers": { },
            "dms": { }
        }

        self.stalking = {
            "globals": [ ], # [user.ids]
            "servers": { }, # guild.id: [user.ids]
            "channels": { } # (channel.id, guild.id): [user.ids]
        }

        self.bg_status: Task = None

        self.queue = Queue()
        
        #self.non_async_ai.character.info(self.char)["character"]["name"].lower()
        self.commands = Group(name="ai", description="All of the program's commands")
        self.global_commands = Group(name="global", description="Commands that affect all AIs", guild_ids=[1225102857431420988], default_permissions=perms)
        self.new_commands = Group(name="new", description="Commands creating something", parent=self.commands)
        self.load_commands = Group(name="load", description="Commands loading something", parent=self.commands)
        self.list_commands = Group(name="list", description="Commands displaying something", parent=self.commands)
        self.unsafe_commands = Group(name="unsafe", description="Unsafe commands", parent=self.commands)

        self.raw = {}
        self.respond_to_bots = set()

        self.author = { }
        self.author_dict = { "author_id": None, "is_human": False, "name": "" }
        self.ai_dict = { "author_id": self.char }

        async def attempt_send_message(mid: str, history_id: str, message: Message, content: str):
            channel = message.channel
            id = f"server-{message.guild.id}" if channel.guild is not None else f"private-{channel.id}"
            async with channel.typing():
                data = await self.send_message(content, history_id)
                if channel.guild:
                    self.client.loop.create_task(linger_handler(message)) # handle lingering
                self.queue.task_done()
                
                s = not isinstance(message.author, Member) or message.author.guild_permissions.mention_everyone
                allowed = AllowedMentions(everyone=s, users=s, roles=s)
                if data.get_candidates()[0].is_filtered:
                    self.raw[id] = CONFIG["filtered_message"]
                    response = await message.reply(CONFIG["filtered_message"], mention_author=CONFIG["mention"] and not isinstance(channel, DMChannel) and (not message.author.bot or id in self.respond_to_bots)) if await self.message_exists(mid, channel) else await channel.send(CONFIG["filtered_message"])
                else:
                    self.raw[id] = data.get_candidates()[0].text
                    text = format_text(data, message.guild)
                    if text.strip() == "":
                        return
                    response = await message.reply(text[:2000], allowed_mentions=allowed, mention_author=CONFIG["mention"] and not isinstance(channel, DMChannel) and (not message.author.bot or id in self.respond_to_bots)) if await self.message_exists(mid, channel) else await channel.send(CONFIG["filtered_message"])#, view=view)
                self.last_message_data[id] = {
                    "sent_message": response,
                    "message_responded_to": {
                        "channel": channel,
                        "content": content,
                        "history_id": history_id
                    }, # sever connections by transforming into dict, preventing original message from being deleted to remove data
                    "a": allowed
                }

        async def message_handler():
            while True:
                mid, history_id, message, content = await self.queue.get()
                try:
                    # 5 attempts
                    for _ in range(5):
                        try:
                            await attempt_send_message(mid, history_id, message, content)
                            break
                        except AuthenticationError:
                            logger.info("auth failed for " + self.name)
                        except ActionError as e:
                            logger.warning(e.args)
                except (Forbidden, NotFound): # forbidden access
                    pass
                except BaseException as e:
                    _, exc_value, exc_tb = exc_info()
                    err = "".join(format_exception(e, exc_value, exc_tb)).replace("\\", "/")
                    print(f"Error sending message: {err}")
                    await message.reply(embed=Embed(title="Error occurred", description=f"```\n{err.replace('D:/', '/root/')}\n```"))
                    #raise e

        def linear_dropoff(x, base, timeout, strength) -> float:
            return base - base/timeout * x * strength
        def plateau_dropoff(x, base, timeout, strength) -> float:
            return base * (1 - (x/timeout)**strength)
        def slope_dropoff(x, base, timeout, strength) -> float:
            return base * (1 - x/timeout)**strength

        async def linger_handler(message: Message):
            dropoff = linear_dropoff if CONFIG["lingering"]["dropoff_type"] == "linear" else plateau_dropoff if CONFIG["lingering"]["dropoff_type"] == "plateau" else slope_dropoff
            def check(msg: Message):
                try:
                    if msg.author == message.author: print(message.content, str(dropoff((datetime.now(timezone.utc) - message.created_at).total_seconds(), CONFIG["lingering"]["chance"], CONFIG["lingering"]["timeout"], CONFIG["lingering"]["exponent_curve"])))
                    return msg.author == message.author and msg.channel == message.channel and dropoff((datetime.now(timezone.utc) - message.created_at).total_seconds(), CONFIG["lingering"]["chance"], CONFIG["lingering"]["timeout"], CONFIG["lingering"]["exponent_curve"]) > 30 and msg.content.strip() != "" and not self.client.user.mentioned_in(msg)
                except Exception:
                    return False
            timeout = CONFIG["lingering"]["timeout"]
            try:
                while True: # grab mani messages
                    start = datetime.now()
                    new_msg = await self.client.wait_for("message", check=check, timeout=timeout)
                    timeout -= (datetime.now() - start).total_seconds()
                    content = CONFIG["message_format" if not isinstance(message.channel, DMChannel) else "dm_message_format"].replace("{display_name}", message.author.display_name).replace("{global_name}", message.author.global_name if message.author.global_name is not None else message.author.name).replace("{name}", self.format_user_name(message.author)).replace("{message}", new_msg.content)
                    chid = await self.get_history_id(new_msg.channel)
                    items = list(self.queue._queue)
                    for item in items:
                        if item[0] == new_msg.id and item[1] == chid:
                            continue
                    await self.queue.put((new_msg.id, chid, new_msg, content))
            except AsyncTimeoutError:
                pass

        @self.client.event
        async def on_message(message: Message):
            if not self.logged_in or not self.enabled or not global_enabled:
                return
            if isinstance(message.channel, PrivateChannel) and str(message.channel.id) not in self.histories["dms"].keys():
                history_id, _ = await self.create_new_chat()
                self.histories["dms"][str(message.channel.id)] = history_id
                #print(f"{self.client.user.name}:", message.content, message.author.name)
                self.save_histories()
            elif message.guild and not str(message.guild.id) in self.histories["servers"].keys():
                history_id, _ = await self.create_new_chat()
                self.histories["servers"][str(message.guild.id)] = history_id
                #print(f"{self.client.user.name}:", message.content, message.guild.name)
                self.save_histories()

            skip = self.in_stalk_list(message.author.id, (str(message.channel.id), str(message.guild.id)) if message.guild != None else None) or (isinstance(message.channel, DMChannel) and message.author != self.client.user)

            if skip != True and random() < CONFIG["random_reply"]:
                skip = (message.channel.category_id not in CONFIG["blacklisted_random_reply_categories"] if isinstance(message.channel, GuildChannel) else True) and message.channel.id not in CONFIG["blacklisted_random_reply_channels"]
            
            if skip != True and has_spacy:
                autonomous_search_content = message.content
            
                for name in [self.client.user.name, self.client.user.display_name, *self.aliases]:
                    autonomous_search_content = replace_case_insensitive(autonomous_search_content, name, name.title())
                if self.autonomous_response_scope == "ALL":
                    if is_directed_at([self.client.user.name, self.client.user.display_name, *self.aliases], autonomous_search_content):
                        skip = True
                elif self.autonomous_response_scope == "ALIASES_ONLY":
                    if is_directed_at(self.aliases, autonomous_search_content):
                        skip = True

            member = message.guild.get_member(self.client.user.id) if message.guild is not None else None
            if (self.client.user.mentioned_in(message) or skip == True or member is not None and any(role.mention in message.content for role in member.roles)) and message.author != self.client.user and message.content.strip() != "":
                mention_regex = re_compile(r"<(@(&|!)?|#)(\d+)>") # define a regular expression to match mention strings
                message_content = message.content # get the message content
                for match in mention_regex.finditer(message_content): # find all mention instances using the regular expression
                    mention = match.group() # get the mention string
                    mention_id = int(match.group(3)) # extract the object ID from the mention string
                    mention_type = match.group(1)
                    if mention_type.startswith("@"):
                        if "&" not in mention_type: # user
                            try:
                                user = await message.guild.fetch_member(mention_id) # get the user from the guild members
                            except NotFound:
                                try:
                                    user = self.client.get_user(mention_id) or await self.client.fetch_user(mention_id)
                                except NotFound:
                                    user = None
                            if user is not None:
                                username = user.nick if isinstance(user, Member) and user.nick is not None else user.display_name # get the user's username
                                formatted_mention = f"@{username}" # format the mention string
                            else:
                                formatted_mention = "@unknown-user"
                        else: # role
                            role = message.guild.get_role(mention_id)
                            if role is not None:
                                formatted_mention = f"@{role.name}"
                            else:
                                formatted_mention = "@unknown-role"
                    else: # channel
                        try:
                            channel = message.guild.get_channel_or_thread(mention_id) or await message.guild.fetch_channel(mention_id)
                            if channel is not None:
                                formatted_mention = f"#{channel.name}"
                            else:
                                formatted_mention = "#unknown-channel"
                        except NotFound:
                            formatted_mention = "#unknown-channel"
                        except Forbidden:
                            formatted_mention = "#No Access"
                                
                    message_content = message_content.replace(mention, formatted_mention) # replace the mention string with the formatted mention string in the message content
                if (message.guild is None or member is None or member.nick is None) and message_content.startswith("@" + self.client.user.display_name):
                    message_content = message_content[len(self.client.user.display_name) + 1:]
                elif member is not None and member.nick is not None and message_content.startswith("@" + member.nick):
                    message_content = message_content[len(member.nick) + 1:]
                #emoji_regex = re_compile(PartialEmoji._CUSTOM_EMOJI_RE)
                #for match in emoji_regex.finditer(message_content):
                #    message_content = message_content.replace(match.group(), f":{match.group('name')}:")
                
                await sleep((CONFIG["typing_delay"][1] - CONFIG["typing_delay"][0]) * random() + CONFIG["typing_delay"][0])
                content = CONFIG["message_format" if not isinstance(message.channel, DMChannel) else "dm_message_format"].replace("{display_name}", message.author.display_name).replace("{global_name}", message.author.global_name if message.author.global_name is not None else message.author.name).replace("{name}", self.format_user_name(message.author)).replace("{message}", message_content)
                #history_id = await self.get_history_id(message.channel)
                #mid = message.id
                #if {"id": mid, "channel": message.channel} in self.queue:
                #    await message.reply("So, uh, some bullshit happened and something would've broke if I let this run through. You can ignore this.\n-# Probably.")
                #    return
                chid = await self.get_history_id(message.channel)
                items = list(self.queue._queue)  # Access the internal queue representation
                for item in items:
                    if item[0] == message.id and item[1] == chid:
                        return
                await self.queue.put((message.id, chid, message, content))

        @self.client.event
        async def on_message_delete(message: Message):
            id = f"server-{message.guild.id}" if message.guild is not None else f"private-{message.channel.id}"
            if id in self.last_message_data:
                if message == self.last_message_data[id]["sent_message"]: # wipe data if character's message was deleted
                    self.last_message_data[id]["sent_message"] = None
                
        @self.commands.command(name="delete", description="Deletes messages from the chat")
        @describe(
            amount="The amount of messages to delete"
        )
        async def delete(ctx: Interaction, amount: int = 1):
            if ctx.user.id == CONFIG["owner"] or not ctx.guild:
                await ctx.response.defer()
                history_id = await self.get_history_id(ctx.channel)
                await self.delete_messages(history_id, amount)
                await ctx.followup.send(f"Deleted {amount} message{'s' if amount != 1 else ''} from the current chat's history.")
            else:
                await ctx.response.send_message("you cannot.")

        @self.commands.command(name="rate", description="Rates the most recent message")
        @describe(
            rating="The rating to give the message"
        )
        async def rate(ctx: Interaction, rating: Literal["Terrible", "Bad", "Good", "Fantastic"]):
            await ctx.response.defer()
            amount = 0 if rating == "Terrible" else 1 if rating == "Bad" else 2 if rating == "Good" else 3
            history_id = await self.get_history_id(ctx.channel)
            message = (await self.get_history(history_id))[0]
            await self.rate_message(amount, message.turn_id, history_id, str(message.candidates[0].candidate_id))
            await ctx.followup.send(f"Rated {amount + 1} star{'s' if amount != 0 else ''}.")
        
        @self.new_commands.command(name="chat", description="Creates a new chat, a blank slate (does not delete previous chat)")
        @describe(
            with_greeting="Whether or not the AI should start with their greeting"
        )
        async def chat(ctx: Interaction, with_greeting: bool = True):
            await ctx.response.defer(ephemeral=not with_greeting)
            history_id, turn = await self.create_new_chat(with_greeting)
            if with_greeting:
                await ctx.followup.send(self.greeting.replace("\n\n", "\n") if self.greeting != None else "No greeting found.")
            else:
                await ctx.followup.send("Created a new chat.")
            self.histories["dms" if isinstance(ctx.channel, PrivateChannel) else "servers"][str(ctx.guild.id) if isinstance(ctx.channel, GuildChannel) else str(ctx.channel.id)] = history_id
            self.save_histories()
            return history_id, turn
        
        @self.commands.command(name="enable", description="Enables the AI, if it was disabled")
        async def enable(ctx: Interaction):
            await ctx.response.send_message("The AI has been turned online." if self.enabled == False else "The AI is currently already online.", ephemeral=True)
            self.enabled = True
            
        @self.commands.command(name="disable", description="Disables the AI, if it was enabled")
        async def disable(ctx: Interaction):
            if ctx.user.id == CONFIG["owner"]:
                await ctx.response.send_message("Powering down..." if self.enabled == True else "...\n...\n...\n...\n..\n...*(the AI is off)*...\n...", ephemeral=True)
                self.enabled = False
            else:
                await ctx.response.send_message("you cannot")
        
        @self.unsafe_commands.command(name="enable", description="Allows the AI to respond to other AIs")
        async def respond_to_bots_enable(ctx: Interaction):
            id = f"server-{ctx.guild_id}" if ctx.guild_id is not None else f"private-{ctx.channel_id}"
            await ctx.response.send_message("The AI will now respond to pings by other AIs." if id in self.respond_to_bots else "The AI is currently responding to other AIs already.", ephemeral=True)
            self.respond_to_bots.add(id)
            
        @self.unsafe_commands.command(name="disable", description="Stops the AI from responding to other AIs")
        async def respond_to_bots_disable(ctx: Interaction):
            id = f"server-{ctx.guild_id}" if ctx.guild_id is not None else f"private-{ctx.channel_id}"
            await ctx.response.send_message("The AI will no longer respond to pings by other AIs." if id in self.respond_to_bots else "The AI is currently not responding to other AIs.", ephemeral=True)
            if id in self.respond_to_bots:
                self.respond_to_bots.remove(id)

        @self.commands.command(name="retry", description="Resends the last message (doesn't work if the last message was deleted)")
        async def retry(ctx: Interaction):
            can_respond = True
            try:
                await ctx.response.defer(ephemeral=True)
            except errors.HTTPException:
                can_respond = False
            id = f"server-{ctx.guild_id}" if ctx.guild_id is not None else f"private-{ctx.channel_id}"
            if id in self.last_message_data:
                message_data = self.last_message_data[id]
                if message_data["message_responded_to"]["channel"] is not None and message_data["message_responded_to"]["history_id"] is not None and message_data["message_responded_to"]["content"] is not None:
                    if message_data["sent_message"] is not None: await message_data["sent_message"].edit(content="<a:catrave:1172958911347822622>")
                    message = message_data["message_responded_to"]
                    try:
                        await self.delete_messages(message["history_id"], 2) # delete last user-sent message and ai response message
                        data = await self.send_message(message["content"], message["history_id"])
                        if data.get_candidates()[0].is_filtered:
                            self.raw[id] = CONFIG["filtered_message"]
                            if message_data["sent_message"] is not None: await message_data["sent_message"].edit(content=CONFIG["filtered_message"])
                            else: await message_data["message_responded_to"]["channel"].send(content=CONFIG["filtered_message"])
                        else:
                            self.raw[id] = data.get_candidates()[0].text
                            text = format_text(data, ctx.guild)
                            if message_data["sent_message"] is not None: await message_data["sent_message"].edit(content=text, allowed_mentions=message_data["a"])
                            else: await message_data["message_responded_to"]["channel"].send(content=text, allowed_mentions=message_data["a"])
                    except:
                        pass
                    if can_respond:
                        await ctx.followup.send("Retrieved new message.")
            elif can_respond:
                await ctx.followup.send("Last sent message was deleted.")

        @self.commands.command(name="edit", description="Edits the last message sent by the AI")
        @describe(
            new_message="The edited AI message"
        )
        async def edit(ctx: Interaction, new_message: str):
            can_respond = True
            try:
                await ctx.response.defer(ephemeral=True)
            except errors.HTTPException:
                can_respond = False
            id = f"server-{ctx.guild_id}" if ctx.guild_id is not None else f"private-{ctx.channel_id}"
            try:
                message_data = self.last_message_data[id]
            except KeyError:
                if can_respond:
                    await ctx.followup.send("Last sent message was deleted/cannot be found.")
                    return
            if message_data["sent_message"] is not None and message_data["message_responded_to"]["history_id"] is not None:
                await self.edit_last_message(new_message, message_data["message_responded_to"]["history_id"])
                self.raw[id] = new_message
                await message_data["sent_message"].edit(content=new_message)
                if can_respond: await ctx.followup.send("Edited message.")
            elif message_data["message_responded_to"]["history_id"] is not None:
                data = await self.edit_last_message(new_message, message_data["message_responded_to"]["history_id"])
                self.raw[id] = CONFIG["filtered_message"] if data.get_candidates()[0].is_filtered else data.get_candidates()[0].text
                if message_data["message_responded_to"]["channel"] is not None:
                    message_data["message_responded_to"]["channel"].send(new_message)
                elif can_respond:
                    await ctx.followup.send(f"Last sent message was deleted/cannot be found.", ephemeral=True)
            elif can_respond:
                await ctx.followup.send("Last sent message was deleted/cannot be found.", ephemeral=True)

        @self.commands.command(name="unstalk", description="Stops stalking a poor soul")
        @describe(
            victim=f"The ill-fated sod who had {self.name} set upon them"
        )
        async def unstalk(ctx: Interaction, victim: Member):
            if isinstance(ctx.channel, DMChannel):
                await ctx.response.send_message("You can't stop me from stalking you here!")
            else:
                await ctx.response.send_message("Awww, it was so much fun tho....", ephemeral=True)
                self.remove_user_from_stalk_list(victim, str(ctx.guild_id), True)

        @self.commands.command(name="stalk", description="Sets the AI to stalk somebody")
        @describe(
            target="The object of the stalking",
            scope="The scope of stalking (global means everywhere, server is server-wide, channel is only in that specific channel)"
        )
        async def stalk(ctx: Interaction, target: Member, scope: Literal["Global", "Server", "Channel"] = "Server", notify_ai: bool = True):
            print(self.in_stalk_list(str(target.id), (ctx.channel_id if scope == "Channel" else None, ctx.guild_id) if scope != "Global" else None))
            if isinstance(ctx.channel, DMChannel) or self.in_stalk_list(target, (ctx.channel_id if scope == "Channel" else None, ctx.guild_id) if scope != "Global" else None):
                await ctx.response.send_message("I'm already stalking you here!")
            else:
                quip = choice(STALKING_QUIPS)
                await ctx.response.send_message(quip.replace("{user}", target.mention))
                #self.remove_user_from_stalk_list(target, str(ctx.guild_id), False) # remove user from 
                if scope == "Server" and str(ctx.guild_id) not in self.stalking["servers"]:
                    self.stalking["servers"][str(ctx.guild_id)] = []
                elif scope == "Channel" and (str(ctx.channel_id), str(ctx.guild_id)) not in self.stalking["channels"]:
                    self.stalking["channels"][f"{ctx.channel_id}|{ctx.guild_id}"] = []
                user_list = self.stalking["globals"] if scope == "Global" else self.stalking["servers"][str(ctx.guild_id)] if scope == "Server" else self.stalking["channels"][f"{ctx.channel_id}|{ctx.guild_id}"]
                if target.id not in user_list:
                    user_list.append(target.id)
                self.save_stalk_list()
                #if self.ai_dict["name"] != None:
                #    await self.send_message(quip.replace("{user}", target.display_name if CONFIG["use_display_name"] else target.name), await self.get_history_id(ctx.channel), self.ai_dict)
                #else:
                await self.send_message(CONFIG["now_stalking_prompt"].replace("{user}", target.display_name if CONFIG["use_display_name"] else target.name), await self.get_history_id(ctx.channel), self.author_dict)

        @self.tree.command(name="alias", description="Set or clear your global alias")
        @describe(
            alias="The alias to set (leave blank to clear your alias)"
        )
        async def global_alias(ctx: Interaction, alias: str = None):
            user_id = ctx.user.id
            if alias:
                aliases[str(user_id)] = alias
                save_aliases()
                await ctx.response.send_message(f"Your global alias is now set to '{alias}'.", ephemeral=True)
            elif user_id in aliases:
                aliases.pop(str(user_id), None)
                save_aliases()
                await ctx.response.send_message("Your global alias has been cleared.", ephemeral=True)
            else:
                await ctx.response.send_message("You do not have a global alias currently set.", ephemeral=True)

        # Local alias commands
        @self.commands.command(name="alias", description=f"Set or clear your alias for {name}")
        @describe(
            alias="The alias to set (leave blank to clear your alias)"
        )
        async def local_alias(ctx: Interaction, alias: str = None):
            key = f"{ctx.user.id},{self.char}"
            if alias:
                aliases[key] = alias
                save_aliases()
                await ctx.response.send_message(f"Your alias for {self.name} is now set to '{alias}'.", ephemeral=True)
            elif key in aliases:
                aliases.pop(key, None)
                save_aliases()
                await ctx.response.send_message(f"Your alias for {self.name} has been cleared.", ephemeral=True)
            else:
                await ctx.response.send_message(f"You do not have an alias currently set for {self.name}.", ephemeral=True)

        @self.commands.command(name="ping", description="Makes the AI ping someone")
        @describe(
            target="The pingee",
            text="Defaults to the character's greeting"
        )
        async def ping(ctx: Interaction, target: Member, text: str = None):
            await ctx.response.defer(ephemeral=True)
            await ctx.channel.send(f"{target.mention} {text if text != None else self.greeting if self.greeting != None else ''}")
            await ctx.followup.send("Sent.")
            #await ctx.response.send_message(f"{target.mention} {text if text != None else self.greeting if self.greeting != None else ''}")

        @self.commands.command(name="raw", description="Displays the raw text of the previous message")
        async def raw(ctx: Interaction):
            id = f"server-{ctx.guild_id}" if ctx.guild_id is not None else f"private-{ctx.channel_id}"
            await ctx.response.send_message("There is no raw text available." if id not in self.raw else self.raw[id])

        @self.commands.command(name="link", description="Provides a link to the character's C.AI page")
        async def link(ctx: Interaction):
            await ctx.response.send_message(f"[Here](https://character.ai/chat/{self.char}) is a link to this character.", ephemeral=True)
            
        @self.load_commands.command(name="history", description="Loads a history ID")
        @describe(
            history_id="The history ID to switch to",
            force_id="Whether or not to create a new chat using the ID if it doesn't exist"
        )
        async def history(ctx: Interaction, history_id: str, force_id: bool = False):
            if ctx.user.id == CONFIG["owner"]:
                if force_id and history_id not in await self.get_history_ids():
                    self.create_new_chat(history_id=history_id)
                if history_id in await self.get_history_ids() or force_id:
                    self.histories["dms" if isinstance(ctx.channel, PrivateChannel) else "servers"][str(ctx.guild.id) if isinstance(ctx.channel, GuildChannel) else str(ctx.channel.id)] = history_id
                    ctx.response.send_message(f"Loaded \"{history_id}\".", ephemeral=True)
                else:
                    ctx.response.send_message(f"The history ID \"{history_id}\" does not exist.", ephemeral=True)
            else:
                ctx.response.send_message("you cannot")
            
        @self.list_commands.command(name="histories", description="List all history IDs")
        async def histories(ctx: Interaction):
            await ctx.response.defer(ephemeral=True)
            text = ""
            for hid in await self.get_history_ids():
                msgs = len(await self.get_history(hid))
                text += f"* `{hid}` - {msgs} message{'s' if msgs != 1 else ''}\n"
            if len(text) <= 4000: # maximum for embed desc
                await ctx.followup.send(embed=Embed(title="Histories", description=text))
            else:
                pages = split_string_by_new_line(text)
                color = get_name_color(self.name)
                await ctx.followup.send(embed=Embed(title="Page 1", description=pages[0], colour=color), view=MultipageMessage(pages, color=color))
        
        @self.global_commands.command(name="update", description="Provide an update to the bot's code")
        @describe(
            program="The updated version of the program"
        )
        async def update(ctx: Interaction, program: Attachment):
            if ctx.user.id == CONFIG["owner"] and program.filename.endswith(".py"):
                path = __file__.replace("\\", "/")
                await ctx.response.send_message("Updating and restarting...", ephemeral=True)
                await program.save(path.split("/")[-1])
                print("Opening updated file...", end="\n\n")
                if platform.startswith("win"):
                    Popen(f"start python -c \"from time import sleep; from subprocess import run; sleep(5); run('python \\\"{path.split('/')[-1]}\\\"')\"", shell=True)
                else:
                    system(f"lxterminal --title='c.ai.py' -e \"source venv/bin/activate; python './{path.split('/')[-1]}'\"")
                for client in clients:
                    await client.close()
                sys_exit()
            else:
                await ctx.response.send_message("you cannot")
        
        @self.global_commands.command(name="open", description="Downloads a file to the server and opens it")
        @describe(
            program="The Python program"
        )
        async def open_python(ctx: Interaction, program: Attachment):
            if ctx.user.id == CONFIG["owner"] and program.filename.endswith(".py") and program.filename != __file__.replace("\\", "/").split("/")[-1]:
                path = __file__.replace("\\", "/")[:1] +  program.filename
                await ctx.response.send_message("Starting new file...", ephemeral=True)
                await program.save(program.filename)
                if platform.startswith("win"):
                    Popen(f"start python -c \"from time import sleep; from subprocess import run; sleep(5); run('python \\\"{program.filename}\\\"')\"", shell=True)
                else:
                    system(f"lxterminal --title={program.filename} -e \"source venv/bin/activate; python './{program.filename}'\"")
            else:
                await ctx.response.send_message("you cannot")
        
        @self.global_commands.command(name="install", description="Installs a Python package onto root")
        @describe(
            package="The package name"
        )
        async def install(ctx: Interaction, package: str):
            if ctx.user.id == CONFIG["owner"]:
                await ctx.response.defer(ephemeral=True)
                try:
                    if platform.startswith("win"):
                        Popen(f"pip install {package}", shell=True)
                    else:
                        system(f"pip install {package}")
                    await ctx.followup.send(f"Installation success.")
                except Exception as e:
                    await ctx.followup.send(f"Installation failed: {e}")
            else:
                await ctx.response.send_message("you cannot")
        
        @self.global_commands.command(name="stop", description="Turns off all AIs")
        async def stop(ctx: Interaction):
            if ctx.user.id == CONFIG["owner"]:
                await ctx.response.send_message("Done.", ephemeral=True)
                for client in clients:
                    await client.close()
                sys_exit()
            else:
                await ctx.response.send_message("you cannot")

        @self.global_commands.command(name="restart", description="Restarts all AIs")
        async def restart(ctx: Interaction):
            if ctx.user.id == CONFIG["owner"]:
                path = __file__.replace("\\", "/")
                await ctx.response.send_message("Restarting...", ephemeral=True)
                for client in clients:
                    await client.close()
                if platform.startswith("win"):
                    Popen(f"start python -c \"from time import sleep; from subprocess import run; sleep(5); run('python \\\"{path.split('/')[-1]}\\\"')\"", shell=True)
                else:
                    system(f"lxterminal --title=\"c.ai\" -e \"source venv/bin/activate; python './{path.split('/')[-1]}'\"")
                sys_exit()
            else:
                await ctx.response.send_message("you cannot")
        
        @self.global_commands.command(name="enable", description="Enables all AIs, if they were disabled")
        async def global_enable(ctx: Interaction):
            global global_enabled
            await ctx.response.send_message("The AIs have been turned online." if global_enabled == False else "The AIs are currently online already.", ephemeral=True)
            global_enabled = True
            
        @self.global_commands.command(name="disable", description="Disables all AIs, if they were enabled")
        async def global_disable(ctx: Interaction):
            global global_enabled
            if ctx.user.id == CONFIG["owner"]:
                await ctx.response.send_message("Powering down all AI..." if global_enabled == True else "...", ephemeral=True)
                global_enabled = False
            else:
                await ctx.response.send_message("you cannot")
                
        @self.client.event
        async def on_ready():
            if not self.logged_in:
                await self.ai.authenticate("9912bd86846346c083cf48cd88f7300a114cf5c7")
                self.load_data()

                character_data = await self.ai.character.fetch_character_info(self.char)
                self.name = self.name if self.name != None else character_data.name or "unknown"
                self.greeting = self.greeting if self.greeting != None else character_data.greeting or "[error: greeting inaccessible]"

                self.commands.name = self.name.split(" ")[0].lower()
                self.tree.add_command(self.commands)
                self.tree.add_command(self.global_commands)

                self.author = await self.ai.account.fetch_me()
                personas = await self.ai.account.fetch_my_personas()
                persona_data = await self.ai.account.fetch_my_settings()
                for persona in personas:
                    if persona.name == "Discord API" and persona.persona_id != persona_data["default_persona_id"]:
                        await self.ai.account.set_persona(self.char, persona.persona_id)
                    elif persona.persona_id == persona_data["default_persona_id"]:
                        break
                self.author_dict = {"author_id": str(self.author.account_id), "is_human": True, "name": self.author.name}

                self.ai_dict = {"author_id": self.char, "name": character_data.name or self.name}

                await self.tree.sync()
                await self.tree.sync(guild=Object(1225102857431420988))
                print(f"{self.client.user.name} has connected to Discord!")
                self.logged_in = True
                self.client.loop.create_task(message_handler())
            if self.status != None and self.bg_status is None or self.bg_status.done():
                self.bg_status = self.client.loop.create_task(self.change_status_periodically())
                
    async def change_status_periodically(self):
        await self.client.wait_until_ready()
        while not self.client.is_closed():
            new_status = choice(self.status)
            try:
                await self.client.change_presence(activity=Activity(name="custom", state=new_status if isinstance(new_status, str) else new_status[0], type=ActivityType.custom))
            except:
                pass
            wait_time = randint(CONFIG["status_update"][0], CONFIG["status_update"][1])
            await sleep(wait_time)

    async def create_new_chat(self, with_greeting: bool = True, history_id: str = None, model_type: Literal["MODEL_TYPE_FAST", "MODEL_TYPE_BALANCED", "MODEL_TYPE_SMART", "MODEL_TYPE_FAMILY_FRIENDLY"] = None):
        try:
            if not history_id:
                chat, turn = await self.ai.chat.create_chat(self.char, with_greeting)
                return chat.chat_id, turn
            else:
                # before you ask, future alfy, yes, this is literally just the self.ai.chat.create_chat function copied and pasted so i can modify the history id
                request_id = str(uuid4())

                request = self.ai.chat.__requester.ws_send_and_receive_async(
                    {
                        "command": "create_chat",
                        "request_id": request_id,
                        "payload": {
                            "chat": {
                                "chat_id": history_id,
                                "creator_id": self.ai.chat.__client.get_account_id(),
                                "visibility": "VISIBILITY_PRIVATE",
                                "character_id": self.char,
                                "type": "TYPE_ONE_ON_ONE",
                                # optional key
                                **({"preferred_model_type": model_type} if model_type else {}),
                            },
                            "with_greeting": with_greeting,
                        },
                    },
                    token=self.ai.chat.__client.get_token(),
                )
                chat, turn = None, None
                async for raw_response in request:
                    if raw_response is None:
                        raise SessionClosedError
                    if raw_response["command"] == "create_chat_response":
                        chat = Chat(raw_response.get("chat", None))
                        if with_greeting:
                            continue
                        break
                    if raw_response["command"] == "add_turn":
                        turn = Turn(raw_response.get("turn", None))
                        break
                    if raw_response["command"] == "neo_error":
                        error_comment = raw_response.get("comment", "")
                        raise CreateError(f"Cannot create a new chat. {error_comment}")
                if chat is None or (with_greeting is True and turn is None):
                    raise CreateError("Cannot create a new chat.")
                return chat.chat_id, turn
        except JSONDecodeError:
            print("Could not decode returned JSON - probably a cloudflare error, waiting 30 secon (typo is intentional)")
            await sleep(30)
            return await self.create_new_chat(with_greeting, history_id)

    def save_histories(self):
        if not path.exists(f"data/ai/{self.client.user.name}"):
            makedirs(f"data/ai/{self.client.user.name}")
        with open(f"data/ai/{self.client.user.name}/histories.json", "w") as file:
            dump(self.histories, file)

    def save_stalk_list(self):
        if not path.exists(f"data/ai/{self.client.user.name}"):
            makedirs(f"data/ai/{self.client.user.name}")
        with open(f"data/ai/{self.client.user.name}/stalk_list.json", "w") as file:
            dump(self.stalking, file)

    def load_histories(self):
        if not path.exists(f"data/ai/{self.client.user.name}"):
            makedirs(f"data/ai/{self.client.user.name}")
        try:
            with open(f"data/ai/{self.client.user.name}/histories.json", "r") as file:
                self.histories = load(file)
        except FileNotFoundError:
            pass
        except JSONDecodeError:
            remove(f"data/ai/{self.client.user.name}/histories.json")

    def load_stalk_list(self):
        if not path.exists(f"data/ai/{self.client.user.name}"):
            makedirs(f"data/ai/{self.client.user.name}")
        try:
            with open(f"data/ai/{self.client.user.name}/stalk_list.json", "r") as file:
                self.stalking = load(file)
        except FileNotFoundError:
            pass
        except JSONDecodeError:
            remove(f"data/ai/{self.client.user.name}/stalk_list.json")

    def load_data(self):
        self.load_histories()
        self.load_stalk_list()

    def in_stalk_list(self, user_id: str, key = None):
        return user_id in self.stalking["globals"] or (user_id in self.stalking["servers"][key] if isinstance(key, str) and key in self.stalking["servers"] else user_id in self.stalking["servers"][key[1]] if isinstance(key, tuple) and key[1] in self.stalking["servers"] else False) or (user_id in self.stalking["channels"][f"{key[0]}|{key[1]}"] if isinstance(key, tuple) and key in self.stalking["channels"] else False)
        
    def format_user_name(self, user: Member):
        key = f"{user.id},{self.char}"
        if key in aliases:
            return aliases[key]
        if str(user.id) in aliases:
            return aliases[str(user.id)]
        return user.name

    async def get_history_ids(self):
        try:
            id_list = []
            histories = (await self.ai.chat.fetch_chats(self.char))
            for history in histories:
                id_list.append(history.chat_id)
            return id_list
        except JSONDecodeError:
            await sleep(30)
            return await self.get_history_ids()

    async def get_history_id(self, item):
        if isinstance(item, (PrivateChannel, Guild, GuildChannel, Thread)):
            try:
                return self.histories["dms" if isinstance(item, PrivateChannel) else "servers"][str(item.guild.id) if isinstance(item, GuildChannel) else (str(item.guild.id) if item.guild is not None else str(item.parent_id)) if isinstance(item, Thread) else str(item.id)]
            except KeyError:
                history_id, _ = await self.create_new_chat()
                if isinstance(item, PrivateChannel):
                    self.histories["dms"][str(item.id)] = history_id
                elif item.guild:
                    self.histories["servers"][str(item.guild.id)] = history_id
                self.save_histories()
                return history_id
        return None

    async def get_history(self, history_id: str):
        try:
            return await self.ai.chat.fetch_all_messages(history_id)
        except JSONDecodeError:
            await sleep(30)
            return await self.get_history(history_id)

    async def get_character_data(self):
        try:
            return await self.ai.character.fetch_character_info(self.char)
        except JSONDecodeError:
            await sleep(30)
            return await self.get_character_data()

    async def get_current_chat(self):
        try:
            return (await self.ai.chat.fetch_chats(self.char))[0].chat_id
        except JSONDecodeError:
            await sleep(30)
            return await self.get_current_chat()

    async def rate_message(self, rating: int, message_id: str, history_id: str, candidate_id: str):
        try:
            return await self.ai.chat.rate(rating, history_id, message_id, candidate_id)
        except JSONDecodeError:
            await sleep(30)
            return await self.rate_message(rating, message_id, history_id, candidate_id)

    async def send_message(self, message: str, history_id: str):
        try:
            return await self.ai.chat.send_message(self.char, history_id, message)
        except JSONDecodeError:
            await sleep(30)
            return await self.send_message(message, history_id)

    async def edit_message(self, message: str, history_id: str, message_id: str):
        try:
            return await self.ai.chat.edit_message(history_id, message_id, '', message)
        except JSONDecodeError:
            await sleep(30)
            return await self.edit_message(message, history_id, message_id)

    async def edit_last_message(self, message: str, history_id: str):
        msg = None
        for p_message in await self.get_history(history_id):
            if not p_message.author_is_human:
                msg = p_message
                break
        if msg != None:
            return await self.edit_message(message, history_id, msg.turn_id)
        return None
    
    async def delete_messages_uuid(self, message_uuids: list, history_id: str):
        try:
            if len(message_uuids) > 0:
                await self.ai.chat.delete_messages(history_id, message_uuids)
        except JSONDecodeError:
            await sleep(30)
            await self.delete_messages_uuid(message_uuids, history_id)

    async def delete_messages(self, history_id: str, amount: int = 1):
        await self.delete_messages_uuid([i.turn_id for i in (await self.get_history(history_id))[:amount]], history_id)

    async def delete_message(self, history_id: str):
        await self.delete_messages_uuid([(await self.get_history(history_id))[0].turn_id], history_id)

    async def message_exists(self, message_id: int, channel: Messageable):
        try:
            await channel.fetch_message(message_id)
        except Exception: # couldn't find message, http error, message access forbidden, etc
            return False
        return True
    
    def remove_user_from_stalk_list(self, user: Member, specific_guild: str = None, remove_from_channels: bool = False):
        try:
            self.stalking["globals"].remove(user.id)
        except ValueError:
            pass
        if specific_guild != None and specific_guild in self.stalking["servers"]:
            try:
                self.stalking["servers"][specific_guild].remove(user.id)
            except ValueError:
                pass
        else:
            for guild_id in self.stalking["servers"]:
                try:
                    self.stalking["servers"][guild_id].remove(user.id)
                except ValueError:
                    pass
        if remove_from_channels:
            for channel_id, guild_id in self.stalking["channels"]:
                if specific_guild == None or (guild_id == specific_guild):
                    try:
                        self.stalking["channels"][f"{channel_id}|{guild_id}"].remove(user.id)
                    except ValueError:
                        pass
        self.save_stalk_list()

    async def run(self):
        await self.client.start(self.token)

class SwipeMessage(View):
    def __init__(self, characterai: CharacterAI, timeout: float = None):
        super().__init__(timeout=timeout)
        self.messages = []
        self.current_message = 0
        self.message_id = 0
        self.characterai = characterai

        self.left_button = Button(label="←", style=ButtonStyle.gray, disabled=True)
        self.right_button = Button(label="→", style=ButtonStyle.gray, disabled=False)
        self.left_button.callback = self.left
        self.right_button.callback = self.right
        self.add_item(self.left_button)
        self.add_item(self.right_button)

    def start(self, start_message: str, message_id: int):
        self.messages = [start_message]
        self.message_id = message_id

    def update_buttons(self):
        self.left_button.disabled = self.current_message - 1 < 0

    async def left(self, ctx: Interaction):
        if self.current_message - 1 >= 0:
            self.current_message -= 1
            self.update_buttons()
            
            await ctx.response.edit_message(content=self.messages[self.current_message], view=self)
        else:
            await ctx.response.defer()

    async def right(self, ctx: Interaction):
        self.current_message += 1
        self.update_buttons()

        new_msg = ""
        
        await ctx.response.defer(ephemeral=True)

        if self.current_message >= len(self.messages) - 1:
            history_id = await self.characterai.get_history_id(ctx.channel)
            last_msg = None
            for p_message in (await self.characterai.get_history(history_id))["turns"]:
                if "is_human" not in p_message["candidates"][0]["candidate_id"] or not p_message["candidates"][0]["candidate_id"]["is_human"]:
                    last_msg = p_message
                    break
            async with self.characterai.ai.connect() as chat:
                data = await chat.next_message(self.characterai.char, history_id, last_msg["turn_key"]["turn_id"])
            new_msg = data["text"]
            self.messages.append(new_msg)
        else:
            new_msg = self.messages[self.current_message]
        
        await ctx.followup.edit_message(self.message_id, content=new_msg, view=self)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

class MultipageMessage(View):
    def __init__(self, pages: list, title: str = "Page {pagenum}", color: hex = 0x111111, timeout: float = None):
        super().__init__(timeout=timeout)
        self.pages = pages
        self.title = title
        self.color = color
        self.current_page = 0
        
        self.left_button = Button(label="←", style=ButtonStyle.gray, disabled=True)
        self.right_button = Button(label="→", style=ButtonStyle.gray, disabled=len(pages) < 2)
        self.left_button.callback = self.left
        self.right_button.callback = self.right
        self.add_item(self.left_button)
        self.add_item(self.right_button)

    def update_buttons(self):
        self.right_button.disabled = self.current_page >= len(self.pages) - 1
        self.left_button.disabled = self.current_page - 1 < 0

    async def left(self, ctx: Interaction):
        if self.current_page - 1 >= 0:
            self.current_page -= 1
            self.update_buttons()
            args = search(ARGS_MATCH, self.pages[self.current_page])
            
            embed = Embed(title=self.title.replace("{pagenum}", str(self.current_page + 1)).replace("{pagetitle}", args.group(1) if args != None else ""), description=self.pages[self.current_page].replace(args.group(0) if args != None else "{pagetitle}", ""), color=self.color)
            await ctx.response.edit_message(embed=embed, view=self)
        else:
            await ctx.response.defer()

    async def right(self, ctx: Interaction):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self.update_buttons()
            args = search(ARGS_MATCH, self.pages[self.current_page])
            
            embed = Embed(title=self.title.replace("{pagenum}", str(self.current_page + 1)).replace("{pagetitle}", args.group(1) if args != None else ""), description=self.pages[self.current_page].replace(args.group(0) if args != None else "{pagetitle}", ""), color=self.color)
            await ctx.response.edit_message(embed=embed, view=self)
        else:
            await ctx.response.defer()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

intents = Intents.default()
intents.members = True
intents.message_content = True

miunull = CharacterAI(
    intents,
    "DISCORD_BOT_TOKEN",
    "mB0pRucyl2P2LDomw13HB8Hs3VR0exNFq8Fr4A5uIVQ",
    bot_aliases=[ "Miu" ]
)
alfred = CharacterAI(
    intents,
    "OTHER_DISCORD_BOT_TOKEN",
    "yT3yD8vHkIZ9jSJX-eyapMa1crKPEy8zIlZTSaJK6vo",
    bot_aliases=[ "Jarvis", "jarvis" ],
    autonomous_response_scope="ALIASES_ONLY"
)

loop = get_event_loop()

logger = getLogger()
level = INFO
handler = StreamHandler()
if isinstance(handler, StreamHandler) and stream_supports_colour(handler.stream):
    formatter = _ColourFormatter()
else:
    dt_fmt = '%Y-%m-%d %H:%M:%S'
    formatter = Formatter('[{asctime}] [{levelname:<8}] {name}: {message}', dt_fmt, style='{')
handler.setFormatter(formatter)
logger.setLevel(level)
logger.addHandler(handler)

loop.create_task(miunull.run())
loop.create_task(alfred.run())
loop.run_forever()