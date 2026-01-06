# A general-purpose Discord bot that can:
#  - grant roles to users if they send a message that meets certain criterion
#  - record and celebrate birthdays
#  - manage a customizable achievements system
#  - a per-user quotebook system
#  - a sentiment analysis system capable of analyzing the textual content of a message to determine possible emotions the author may be feeling
#  - granting roles to specific users on specific dates
#  - automatically granting roles to users when they join the server
#  - silly family commands (marriage, adoption, view family tree)
#  - and sending a customizable message in a given text channel when a user leaves the server.

from discord.utils import format_dt
from discord.abc import GuildChannel, Snowflake
from discord.ext import commands, tasks
from discord.ui import Button, View, button
from discord import Client, Intents, ButtonStyle, Interaction, User, Role, Object, Member, Embed, ForumChannel, Thread, CategoryChannel, Attachment, Message, Guild, Color, Activity, ActivityType, File, NotFound, StickerFormatType, AllowedMentions, Permissions, RawReactionActionEvent, app_commands
from typing import Literal, Union
from graphviz import Digraph
import subprocess
from datetime import datetime
from httpx import AsyncClient
from io import BytesIO
from requests import get
from html import escape
import asyncio
import random
import psutil
import json
#import poe
import sys
import re
import os
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'
from transformers import pipeline

contore_config = {
  "owner_id": 1234567890123456789, # your user id
}

data = {
    "auto_roles": {},
    "roles_on_messages": {},
    "autoreactions": {},
    "scheduled_roles": {},
    "birthdays": {},
    # structure: {guild_id: (role_id, channel_id)}
    "birthday_data": {},
    "quotes": {},
    "families": {},
    "leave_msgs": {},
    # structure: {guild_id: {channel: channel_id, user_id: {achievement_id: timestamp}}}
    "achievements": {},
    # Structure: {guild_id: [{id, name, description, icon, secret, points, rarity, type, trigger}]}
    "achievement_defs": {},
    # Structure: {guild_id: {user_id: {metric: value}}}
    "achievement_progress": {},
}

voice_tracking = {} # {guild_id: {user_id: join_time}}

intents = Intents.all()

contore = Client(intents=intents)
ctree = app_commands.CommandTree(contore)
classifier = pipeline("sentiment-analysis", model="bhadresh-savani/bert-base-go-emotion", top_k=None)
tokenizer_kwargs = {"padding": True, "truncation": True, "max_length": 128}
attachment_retriever = AsyncClient()
perms = Permissions(manage_messages=True, manage_threads=True, manage_expressions=True, view_audit_log=True, manage_guild=True, manage_nicknames=True, kick_members=True, ban_members=True, create_expressions=True, moderate_members=True, create_events=True, manage_events=True)

WHITELISTED_ADMIN_SERVERS = [
    Object(1096833116422799503), Object(1059607635499962408)
]

RARITY_COLORS = {
    "COMMON": 0x95A5A6,
    "UNCOMMON": 0x2ECC71,
    "RARE": 0x3498DB,
    "EPIC": 0x9B59B6,
    "LEGENDARY": 0xF7B71E,
    "MYTHIC": 0xE74C3C
}

RARITY_EMOJI = {
    "COMMON": "<:common:1455094340215902387>",
    "UNCOMMON": "<:uncommon:1455094351238533233>",
    "RARE": "<:rare:1455094364450586747>",
    "EPIC": "<:epic:1455094393663918080>",
    "LEGENDARY": "<:legendary:1455094549985624265>",
    "MYTHIC": "<:mythical:1455094559015960641>"
}

MATCH_DESC = {
    "contains": "contains",
    "exact": "exactly matches",
    "starts_with": "starts with",
    "ends_with": "ends with",
    "regex": "matches the regex"
}

# check if the directory exists
if not os.path.exists("data"):
    # create the directory if it doesn't exist
    os.makedirs("data")

if not os.path.isfile("data/data.cont"):
    # Save dictionary as JSON
    open("data/data.cont", "w").close()
    with open("data/data.cont", "w") as f:
        json.dump(data, f)

def encode_sets(obj):
    if isinstance(obj, set):
        return {"__set__": list(obj)}  # Mark sets with a special key
    raise TypeError(f"Type {type(obj)} not serializable")

def decode_sets(obj):
    if "__set__" in obj:
        return set(obj["__set__"])
    return obj

def contore_save():
    with open("data/data.cont", "w") as f:
        json.dump(data, f, default=encode_sets)

class Yes(View):
    def __init__(self, users: list = None, confirm_text: str = "Confirming...", confirm: dict = {"ephemeral": True}, deny_text: str = "Denying...", deny: dict = {"ephemeral": True}):
        super().__init__()
        self.value = None
        self.users = users
        self.confirm_text = confirm_text
        self.confirm_kwargs = confirm
        self.deny_text = deny_text
        self.deny_kwargs = deny

    # When the confirm button is pressed, set the inner value to `True` and
    # stop the View from listening to more input.
    # We also send the user an ephemeral message that we're confirming their choice.
    @button(label="Yes", style=ButtonStyle.green)
    async def confirm(self, ctx: Interaction, button: Button):
        if not self.users or ctx.user.id in self.users:
            await ctx.response.send_message(self.confirm_text, **self.confirm_kwargs)
            self.value = True
            self.disable_all_items()
            await ctx.message.edit(view=self)
            self.stop()

    # This one is similar to the confirmation button except sets the inner value to `False`
    @button(label="No", style=ButtonStyle.red)
    async def deny(self, ctx: Interaction, button: Button):
        if not self.users or ctx.user.id in self.users:
            await ctx.response.send_message(self.deny_text, **self.deny_kwargs)
            self.value = False
            self.disable_all_items()
            await ctx.message.edit(view=self)
            self.stop()

    async def on_timeout(self):
        self.disable_all_items()
    
    def disable_all_items(self):
        for item in self.children:
            item.disabled = True

VALID_SLASH_COMMAND_NAME = re.compile(r'^[-_\w ' + app_commands.commands.THAI_COMBINING + app_commands.commands.DEVANAGARI_COMBINING + r']{1,32}$')

GUILD = app_commands.AppCommandContext(guild=True)
GUILD_INSTALL = app_commands.AppInstallationType(guild=True)
ALL = app_commands.AppCommandContext(guild=True, dm_channel=True, private_channel=True)
ALL_INSTALLS = app_commands.AppInstallationType(guild=True, user=True)
auto_commands = app_commands.Group(name="auto", description="Automatic commands", allowed_contexts=GUILD, allowed_installs=GUILD_INSTALL)
message_commands = app_commands.Group(name="message", description="Message commands", allowed_contexts=GUILD, allowed_installs=GUILD_INSTALL)
reset_commands = app_commands.Group(name="reset", description="Reset commands", allowed_contexts=GUILD, allowed_installs=GUILD_INSTALL)
date_commands = app_commands.Group(name="date", description="Date commands", allowed_contexts=GUILD, allowed_installs=GUILD_INSTALL)
birthday_commands = app_commands.Group(name="birthday", description="Birthday commands", allowed_contexts=ALL, allowed_installs=ALL_INSTALLS)
quote_commands = app_commands.Group(name="quotes", description="Quote commands", allowed_contexts=ALL, allowed_installs=ALL_INSTALLS)
family_commands = app_commands.Group(name="family", description="Family commands", allowed_contexts=ALL, allowed_installs=ALL_INSTALLS)
leave_commands = app_commands.Group(name="leave", description="Leave commands", allowed_contexts=GUILD, allowed_installs=GUILD_INSTALL)
restriction_commands = app_commands.Group(name="restriction", description="Restriction commands")
achievement_commands = app_commands.Group(name="achievement", description="Achievement commands", allowed_contexts=GUILD, allowed_installs=GUILD_INSTALL)

def is_owner():
    async def predicate(ctx: commands.Context[commands.Bot]):
        return await ctx.bot.is_owner(ctx.author)
    return commands.check(predicate)

@auto_commands.command(name="role", description="Automatically apply a role to (specific) users when they join the server")
@app_commands.describe(role = "The role to automatically apply to the target",
                       user = "The target (leave blank for the role to apply to everyone)")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def auto_role(ctx: Interaction, role: Role, user: User = None):
    if not ctx.user.guild_permissions.manage_guild or not ctx.user.guild_permissions.manage_channels or not ctx.user.guild_permissions.manage_nicknames or not ctx.user.guild_permissions.manage_roles or not ctx.user.guild_permissions.ban_members or not ctx.user.guild_permissions.kick_members:
        await ctx.response.send_message(f"you cannot")
        return
    if ctx.guild_id not in data["auto_roles"]:
        data["auto_roles"][ctx.guild_id] = { "everyone": [None] }
    if user == None:
        # no specific user ID set, defaults to everyone
        if data["auto_roles"][ctx.guild_id]["everyone"] == [None]:
            data["auto_roles"][ctx.guild_id]["everyone"] = [role.id]
        else:
            data["auto_roles"][ctx.guild_id]["everyone"] = [x for x in data["auto_roles"][ctx.guild_id]["everyone"] if x is not None]
            data["auto_roles"][ctx.guild_id]["everyone"].append(role.id)
        await ctx.response.send_message(f"Every new user will now automatically receive the role `{role.name}` when joining the server.", ephemeral=True)
    else:
        # specific user
        if user.id not in data["auto_roles"][ctx.guild_id]:
            data["auto_roles"][ctx.guild_id][user.id] = [role.id]
        elif data["auto_roles"][ctx.guild_id][user.id] != None and data["auto_roles"][ctx.guild_id][user.id] != [None]:
            data["auto_roles"][ctx.guild_id][user.id] = [x for x in data["auto_roles"][ctx.guild_id][user.id] if x is not None]
            data["auto_roles"][ctx.guild_id][user.id].append(role.id)
        else:
            data["auto_roles"][ctx.guild_id][user.id] = []
        print(f"{user.display_name} will automatically receive the role `{role.name}` when joining the server.") # logging purposes
        await ctx.response.send_message(f"{user.display_name} will automatically receive the role `{role.name}` when joining the server.", ephemeral=True)
    contore_save()

@message_commands.command(name="role", description="Automatically grant/revoke roles when a message is sent")
@app_commands.describe(role = "The role to automatically apply to the target",
                       content = "The content of the message",
                       type = "Defines who gets the role when a message matching the defined parameters is sent",
                       specified_user = "Required if the type is \"Specific User\"",
                       time_limit = "Removes the role from everyone it was applied to after a certain amount of time is up (leave negative for no limit)",
                       take_role = "Takes the role away instead of granting it",
                       sub_match = "Allows matching messages that contain the defined content but also have more text",
                       authorized_user = "Required if authorization level is \"Specific User\"",
                       authorized_role = "Required if authorization level is \"Specific Role\"")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def role_on_message(ctx: Interaction, role: Role, content: str, type: Literal["Self", "Specific User", "Mentions"] = "Mentions", specified_user: User = None, time_limit: float = -1.0, take_role: bool = False, sub_match: bool = False, authorization_level: Literal["Everyone", "Specific User", "Specific Role", "Administrators"] = "Administrators", authorized_user: User = None, authorized_role: Role = None):
    if not ctx.user.guild_permissions.manage_guild or not ctx.user.guild_permissions.manage_channels or not ctx.user.guild_permissions.manage_nicknames or not ctx.user.guild_permissions.manage_roles or not ctx.user.guild_permissions.ban_members or not ctx.user.guild_permissions.kick_members:
        await ctx.response.send_message(f"you cannot")
        return
    if ctx.guild_id not in data["roles_on_messages"]:
        data["roles_on_messages"][ctx.guild_id] = [ ]
    if type == "Specific User" and specified_user == None:
        await ctx.response.send_message("You forgot to define a user, dum dum.", ephemeral=True)
        return
    if authorization_level == "Specific User" and authorized_user == None:
        await ctx.response.send_message("You forgot to define an authorized user, dum dum.", ephemeral=True)
        return
    elif authorization_level == "Specific Role" and authorized_role == None:
        await ctx.response.send_message("You forgot to define an authorized role, dum dum.", ephemeral=True)
        return
    params = {
        "role": role.id,
        "content": content,
        "type": type,
        "authorization_type": authorization_level
    }
    print(params)
    if type == "Specific User":
        params["type_user"] = specified_user.id
    if time_limit != -1:
        params["time_limit"] = time_limit
    if take_role == True:
        params["take"] = True
    if sub_match == True:
        params["sub_match"] = True
    if authorization_level == "Specific User":
        params["authorization"] = authorized_user.id
    elif authorization_level == "Specific Role":
        params["authorization"] = authorized_role.id
    data["roles_on_messages"][ctx.guild_id].append(params)
    print(data["roles_on_messages"][ctx.guild_id])
    
    content = f"""{"Grants" if not params.get("take", False) else "Takes away"} the role <@&{params["role"]}> to {"the author of the sent message" if params["type"] == "Self" else f"<@{params.get('type_user', 0)}>" if params["type"] == "Specified User" else "mentioned users/roles"}
{"Messages must be sent by Alfred" if params["authorization_type"] == "Alfred" else "Messages must be sent by an administrator" if params["authorization_type"] == "Administrators" else f"Messages must be sent by someone with the <@&{params.get('authorization', 0)} role" if params["authorization_type"] == "Specified Role" else f"Messages must be sent by <@{params.get('authorization', 0)}>" if params["authorization_type"] == "Specified User" else "Anybody can use trigger this function"}""" + (f"\nAfter {params.get('time_limit', 0)} seconds, all roles granted will be revoked" if params.get('time_limit', -1) > 0 else "") + f"""
To trigger this, """ + (f"you must send \"{params['content']}\" as a message" if not params.get("sub_match", False) else f"your message must contain \"{params['content']}\" in it")

    contore_save()
    print(content) # logging purposes
    await ctx.response.send_message(content, ephemeral=True)

@date_commands.command(name="role", description="Schedule a role to be given to a user on a specific date")
@app_commands.describe(role = "The role to automatically assign",
                       user = "The user to assign the role to",
                       date_pattern = "The pattern for assignment (e.g., \"YYYY-MM-DD\" for one-time, \"MM-DD\" for yearly, etc.)",
                       duration = "The duration (in hours) the role should be kept before being removed")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def schedule_role(ctx: Interaction, role: Role, user: Member, date_pattern: str, duration: int = None):
    if not ctx.user.guild_permissions.manage_guild or not ctx.user.guild_permissions.manage_channels or not ctx.user.guild_permissions.manage_nicknames or not ctx.user.guild_permissions.manage_roles or not ctx.user.guild_permissions.ban_members or not ctx.user.guild_permissions.kick_members:
        await ctx.response.send_message(f"you cannot")
        return
    try:
        date_type = None
        now = datetime.now()

        # One-time role (YYYY-MM-DD)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_pattern):
            date_type = "one-time"
            target_date = datetime.strptime(date_pattern, "%Y-%m-%d")
            duration = duration if duration != None else 24
            if target_date < now:
                await ctx.response.send_message("The specified date is in the past. Please provide a future date.")
                return

        # Month-long role (YYYY-MM)
        elif re.fullmatch(r"\d{4}-\d{2}", date_pattern):
            date_type = "yearly-month"
            target_month = datetime.strptime(date_pattern, "%Y-%m")
            duration = duration if duration != None else 730
            if target_month < now.replace(day=1):
                await ctx.response.send_message("The specified month is in the past. Please provide a future month.")
                return

        # Year-long role (YYYY)
        elif re.fullmatch(r"\d{4}", date_pattern):
            date_type = "yearly"
            target_year = int(date_pattern)
            duration = duration if duration != None else 8760
            if target_year < now.year:
                await ctx.response.send_message("The specified year is in the past. Please provide a future year.")
                return

        # Recurring yearly role (MM-DD)
        elif re.fullmatch(r"\d{2}-\d{2}", date_pattern):
            date_type = "annual"
            duration = duration if duration != None else 24

        # Recurring month-long role (MM)
        elif re.fullmatch(r"\d{2}M", date_pattern):
            date_pattern = date_pattern[:2]
            date_type = "monthly"
            duration = duration if duration != None else 730

        # Monthly recurring day role (DD)
        elif re.fullmatch(r"\d{2}", date_pattern):
            date_type = "monthly-day"
            duration = duration if duration != None else 24

        else:
            await ctx.response.send_message("Invalid date pattern. Use one of the following formats: 'YYYY-MM-DD', 'YYYY-MM', 'YYYY', 'MM-DD', 'MM', 'DD'.")
            return

        # Validate duration if provided
        if duration is not None:
            if not isinstance(duration, int) or duration <= 0:
                await ctx.response.send_message("Invalid duration. Please specify a positive integer for hours.")
                return

        date_info = {
            "role_id": role.id,
            "user_id": user.id,
            "date_pattern": date_pattern,
            "type": date_type,
            "duration": duration
        }

        if date_type == "one-time":
            date_info["target_date"] = (target_date.year, target_date.month, target_date.day)
        elif date_type == "yearly-month":
            date_info["target_month"] = (target_month.year, target_month.month)
        elif date_type == "yearly":
            date_info["target_year"] = target_year

        if ctx.guild.id not in data["scheduled_roles"]:
            data["scheduled_roles"][ctx.guild.id] = [ ]
        data["scheduled_roles"][ctx.guild.id].append(date_info)
        contore_save()

        await ctx.response.send_message(f"Scheduled role '{role.name}' for '{user.display_name}' on pattern '{date_pattern}' with duration {duration:,} hours.")
    except Exception as e:
        await ctx.response.send_message("An error occurred while scheduling the role. Please check your inputs.")
        print(f"Error in schedule_role command: {e}")

@birthday_commands.command(name="set", description="Set your birthday!")
@app_commands.describe(date="The birthday date in format YYYY-MM-DD or MM-DD.")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def birthday_set(ctx: Interaction, date: str):
    try:
        if "-" in date:
            date_parts = date.split("-")
        elif "/" in date:
            date_parts = date.split("/")
        else:
            await ctx.response.send_message("Invalid date format. Please use 'YYYY-MM-DD' or 'MM-DD'.")
            return

        if len(date_parts) == 3: # YYYY-MM-DD format
            year, month, day = date_parts
            if not ((len(year) == 2 or len(year) == 4) and len(month) == 2 and int(month) < 13 and int(month) > 0 and len(day) == 2 and int(day) < 32 and int(day) > 0):
                raise ValueError("Invalid YYYY-MM-DD")
            birthday = datetime(year=int(str(datetime.now().year)[:2] + year) if len(year) == 2 else int(year), month=int(month), day=int(day))
        elif len(date_parts) == 2: # MM-DD format
            month, day = date_parts
            if not (len(month) == 2 and int(month) < 13 and int(month) > 0 and len(day) == 2 and int(day) < 32 and int(day) > 0):
                raise ValueError("Invalid MM-DD")
            birthday = datetime(year=1, month=int(month), day=int(day))
        else:
            await ctx.response.send_message("Invalid date format. Please use 'YYYY-MM-DD' or 'MM-DD'.")
            return

        # Save birthday in the data structure
        data["birthdays"][ctx.user.id] = birthday.strftime("%Y-%m-%d") if len(date_parts) == 3 else "0000-" + birthday.strftime("%m-%d")
        contore_save()
        await ctx.response.send_message(f"Your birthday has been set to {birthday.strftime('%Y-%m-%d' if len(date_parts) == 3 else '%m-%d')}.")
    except ValueError:
        await ctx.response.send_message("Invalid date format. Please enter a valid date.")

@birthday_commands.command(name="forget", description="Forgets your birthday, if set")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def birthday_forget(ctx: Interaction):
    if ctx.user.id in data["birthdays"]:
        del data["birthdays"][ctx.user.id]
        contore_save()
        await ctx.response.send_message("Your birthday has been forgotten.")
    else:
        await ctx.response.send_message("You don't have a birthday set!")

@ctree.command(name="birthdays", description="Displays upcoming birthdays")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def birthdays(ctx: Interaction):
    now = datetime.now()
    upcoming_birthdays = []

    for user_id, birthday_info in data["birthdays"].items():
        user = ctx.guild.get_member(user_id)
        if not user:
            continue

        birth_date = datetime.strptime(birthday_info if not birthday_info.startswith("0000-") else birthday_info[5:], "%Y-%m-%d" if not birthday_info.startswith("0000-") else "%m-%d")
        birth_date_this_year = birth_date.replace(year=now.year)
        if birth_date_this_year < now:
            birth_date_this_year = birth_date.replace(year=now.year + 1)
        
        days_until = (birth_date_this_year - now).days
        upcoming_birthdays.append((user.display_name, birth_date_this_year, days_until))

    upcoming_birthdays.sort(key=lambda x: x[2])

    embed = Embed(title="🎉 Upcoming Birthdays 🎉", color=0xEB459F)
    if upcoming_birthdays:
        for name, birth_date, days_until in upcoming_birthdays:
            embed.add_field(name=name, value=f"{birth_date.strftime('%B %d')} (in {days_until} days)", inline=False)
    else:
        embed.description = "No upcoming birthdays found."

    await ctx.response.send_message(embed=embed)

@birthday_commands.command(name="view", description="View someone's (or your own) birthday")
@app_commands.describe(user = "The user whose birthday you want to view")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def birthday(ctx: Interaction, user: User = None):
    user = user or ctx.user
    if user.id in data["birthdays"]:
        birth_date = datetime.strptime(data["birthdays"][user.id] if not data["birthdays"][user.id].startswith("0000-") else data["birthdays"][user.id][5:], "%Y-%m-%d" if not data["birthdays"][user.id].startswith("0000-") else "%m-%d")
        await ctx.response.send_message(f"**{user.display_name}**'s birthday is on {birth_date.strftime('%B %d')} 🎉")
    else:
        await ctx.response.send_message(f"**{user.display_name}** has not set a birthday :c")

@birthday_commands.command(name="role", description="Sets the birthday role to give to birthday people on their birthdays")
@commands.has_permissions(manage_roles=True)
@app_commands.describe(role = "The role to assign")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def birthday_role(ctx: Interaction, role: Role = None):
    if ctx.guild_id is None:
        await ctx.response.send_message("You cannot use this command in DMs or GCs.")
        return
    if not ctx.guild_id in data["birthday_data"]:
        data["birthday_data"][ctx.guild_id] = [-1, -1]
    data["birthday_data"][ctx.guild_id][0] = role.id if role else -1
    contore_save()
    await ctx.response.send_message(f"The birthday role has been set to {role.mention}.", ephemeral=True)

@birthday_commands.command(name="channel", description="Set a channel for Contore to send happy birthday messages in!")
@commands.has_permissions(manage_roles=True)
@app_commands.describe(channel = "The channel to send messages in")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def birthday_channel(ctx: Interaction, channel: Union[GuildChannel, Thread] = None):
    if ctx.guild_id is None:
        await ctx.response.send_message("You cannot use this command in DMs or GCs.")
        return
    if channel != None and isinstance(channel, (ForumChannel, CategoryChannel)):
        await ctx.response.send_message("Please provide a valid text channel to send messages in!")
        return
    if not ctx.guild_id in data["birthday_data"]:
        data["birthday_data"][ctx.guild_id] = [-1, -1]
    data["birthday_data"][ctx.guild_id][1] = channel.id if channel else -1
    contore_save()
    await ctx.response.send_message(f"Birthday announcements will be sent to {channel.mention}.", ephemeral=True)

@reset_commands.command(name="roles", description="Resets all role data (does not revert damage to your server or revoke roles granted)")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def reset_roles(ctx: Interaction):
    if ctx.user.id != contore_config["owner_id"] and not ctx.user.guild_permissions.administrator or ctx.guild_id not in data["auto_roles"] or ctx.guild_id not in data["roles_on_messages"]:
        await ctx.response.send_message("no")
        return
    data["auto_roles"][ctx.guild_id] = { }
    data["roles_on_messages"][ctx.guild_id] = [ ]
    contore_save()
    await ctx.response.send_message("Successfully reset all role data for this server.", ephemeral=True)

@reset_commands.command(name="role", description="Resets auto role data for a specific user")
@app_commands.describe(user = "The user to remove auto role data from (leave empty to reset everyone's default join role)")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def reset_role(ctx: Interaction, user: User = None):
    id = user.id if user else "everyone"
    if (ctx.user.id != contore_config["owner_id"] and not ctx.user.guild_permissions.administrator or ctx.guild_id not in data["auto_roles"] or id not in data["auto_roles"][ctx.guild_id]) and id != "everyone":
        await ctx.response.send_message("no")
        return
    if id != "everyone":
        data["auto_roles"][ctx.guild_id].pop(id)
    else:
        data["auto_roles"][ctx.guild_id]["everyone"] = []
    contore_save()
    await ctx.response.send_message(f"Successfully removed all auto role data for {user.name if user else id}.")

@reset_commands.command(name="reactions", description="Resets all auto reaction data")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def reset_autoreactions(ctx: Interaction):
    if ctx.user.id != contore_config["owner_id"] and not ctx.user.guild_permissions.administrator or ctx.guild_id not in data["auto_roles"] or ctx.guild_id not in data["roles_on_messages"]:
        await ctx.response.send_message("no")
        return
    data["autoreactions"][ctx.guild_id] = [ ]
    contore_save()
    await ctx.response.send_message("Successfully reset all autoreaction data for this server.", ephemeral=True)
    
@ctree.command(name="list", description="Lists all of the data related to roles that Contore has of the current server")
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def list_data(ctx: Interaction):
    msg = "## MESSAGE ROLES" if ctx.guild_id in data["roles_on_messages"] and len(data["roles_on_messages"][ctx.guild_id]) > 0 else ""
    if ctx.guild_id in data["roles_on_messages"]:
        for criteria in data["roles_on_messages"][ctx.guild_id]:
            if criteria.get("content", None) == None or criteria.get("type", None) == None or criteria.get("role", None) == None or criteria.get("authorization_type", None) == None:
                continue
            msg += f"""\n- {"Grants" if not criteria.get("take", False) else "Takes away"} the role <@&{criteria["role"]}> to {"the author of the sent message" if criteria["type"] == "Self" else f"<@{criteria.get('type_user', 0)}>" if criteria["type"] == "Specified User" else "mentioned users/roles"}
  {"Messages must be sent by Alfred" if criteria["authorization_type"] == "Alfred" else "Messages must be sent by an administrator" if criteria["authorization_type"] == "Administrators" else f"Messages must be sent by someone with the <@&{criteria.get('authorization', 0)} role" if criteria["authorization_type"] == "Specified Role" else f"Messages must be sent by <@{criteria.get('authorization', 0)}>" if criteria["authorization_type"] == "Specified User" else "Anybody can use trigger this function"}""" + (f"\n  After {criteria.get('time_limit', 0)} seconds, all roles granted will be revoked" if criteria.get('time_limit', -1) > 0 else "") + f"""
  To trigger this, """ + (f"you must send \"{criteria['content']}\" as a message" if not criteria.get("sub_match", False) else f"your message must contain \"{criteria['content']}\" in it")
    
    if ctx.guild_id in data["auto_roles"] and len(data["auto_roles"][ctx.guild_id]) > 0:
        msg += "\n## AUTO ROLES\n"
        for uid, roles in data["auto_roles"][ctx.guild_id].items():
            if uid == "everyone" and roles != [None]:
                msg += "Everyone will automatically recieve the following role(s) when joining the server: "
                for role in roles:
                    if role == roles[-1]: # role is last in list
                        msg += f"{'and ' if len(roles) > 1 else ''}<@&{role}>.\n"
                    else:
                        msg += f"<@&{role}>, "
            elif uid != "everyone":
                msg += f"<@{uid}> will automatically recieve the following role(s) when joining the server: "
                for i, role in enumerate(roles):
                    if i == len(roles) - 1: # role is last in list
                        msg += f"and <@&{role}>.\n"
                    else:
                        msg += f"<@&{role}>, "
            msg += "\n"

    #if ctx.guild_id in data["autoreactions"] and len(data["autoreactions"][ctx.guild_id]) > 0:
    #    msg += "\n## AUTO REACTIONS"

    if ctx.guild_id in data["scheduled_roles"] and len(data["scheduled_roles"][ctx.guild_id]) > 0:
        msg += "\n## SCHEDULED ROLES"
    
    if msg.strip() == "":
        msg = "This server does not have any Contore data yet!"

    if len(msg) <= 4000:
        await ctx.response.send_message(embed=Embed(title="Data", description=msg), ephemeral=True) # send message containing everything
    else:
        pages = split_string_by_new_line(msg)
        await ctx.response.send_message(embed=Embed(title="Page 1", description=pages[0]), view=MultipageMessage(pages))

def download_image_from_url(url: str):
    folder = "data/Contore/avis/"
    os.makedirs(folder, exist_ok=True)
    filename = os.path.join(folder, f"{url.split('/')[-2]}-{url.split('/')[-1].split('?')[0]}.png")

    if not os.path.exists(filename):
        response = get(url)
        if response.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(response.content)

    return filename

async def build_family_graph(guild_id: Union[int, None], root_id: int, unstylize_lines: bool = False, show_usernames: bool = False):
    g = Digraph('FamilyTree', format='png')
    g.attr(bgcolor="transparent", dpi='300')
    g.attr('graph', splines='true', nodesep='0.5', ranksep='0.75')
    #g.attr('graph', splines='true' if not unstylize_lines else 'false', nodesep='0.5', ranksep='0.75')
    g.attr('node', shape='box', style='filled', fontcolor='white', fontname='Helvetica', margin='0.0,0.0')
    g.attr('edge', color='white', penwidth='2')

    drawn_unions = set()
    drawn_people = set()
    drawn_edges = set()

    async def add_person_node(person_id: int, guild_id: int):
        if person_id in drawn_people:
            return
        drawn_people.add(person_id)

        guild = contore.get_guild(guild_id) or await contore.fetch_guild(guild_id) if guild_id else None
        try:
            user = guild.get_member(person_id) or await guild.fetch_member(person_id) if guild else contore.get_user(person_id) or await contore.fetch_user(person_id)
        except Exception:
            user = contore.get_user(person_id) or await contore.fetch_user(person_id)
        if user is None:
            name = "Unknown User"
            discriminator = None
            username = "???"
            title = None
            image_path = None
        else:
            name = user.display_name
            discriminator = user.discriminator if user.bot else None
            username = user.name
            title = data["families"].get(person_id, {}).get("title", None)
            image_path = download_image_from_url(user.display_avatar.with_size(64).url) if user.display_avatar else None

        # custom label
        label = f'''<
            <TABLE BORDER="2" CELLBORDER="0" CELLSPACING="0" BGCOLOR="{"blue" if person_id == root_id else "black"}" COLOR="#3a3a3a">
                <TR>
                    {f'<TD FIXEDSIZE="TRUE" WIDTH="40" HEIGHT="40"><IMG SRC="{image_path}" SCALE="TRUE"/></TD>' if image_path else ""}
                    <TD ALIGN="LEFT" WIDTH="80">
                        <TABLE BORDER="0" CELLBORDER="0" CELLSPACING="0">
                            <TR><TD><FONT POINT-SIZE="14" COLOR="white"><B>{escape(name)}</B></FONT></TD></TR>
                            {f'<TR><TD><FONT POINT-SIZE="10" COLOR="#ffeeee">{escape(title)}</FONT></TD></TR>' if title else ""}
                            {f'<TR><TD><FONT POINT-SIZE="10" COLOR="gray">{escape(username)}{f"#{discriminator}" if discriminator else ""}</FONT></TD></TR>' if show_usernames else ''}
                        </TABLE>
                    </TD>
                </TR>
            </TABLE>
        >'''

        g.node(str(person_id), label=label, shape='none', style='filled', fillcolor='transparent')

    def is_grandchild_of(person_id: int, check_id: int, depth: int = 0):
        person = data["families"].get(person_id)
        return not person and (depth > 0 and check_id in person["children"] or any(is_grandchild_of(child_id, check_id, depth + 1) for child_id in person["children"]))

    def get_partner_cluster(person_id: int, root_id: int):
        hidden = data["families"].get(root_id, {}).get("hidden", set())
        cluster = set()
        stack = [person_id]
        while stack:
            pid = stack.pop()
            if pid not in cluster and pid not in hidden:
                cluster.add(pid)
                person = data["families"].get(pid)
                if person:
                    for partner_id in person.get("partners", []):
                        stack.append(partner_id)
        return cluster

    async def draw_family(person_id: int, visited: set):
        if person_id in visited:
            return
        visited.add(person_id)

        person = data["families"].get(person_id)
        if not person:
            return

        # parents
        for parent_id in sorted(person["parents"]):
            if not is_grandchild_of(person_id, parent_id):
                parent = data["families"].get(parent_id)
                if parent and (parent_id not in person["children"] or len(parent["children"]) < len(person["children"])):
                    await draw_family(parent_id, visited)

        await add_person_node(person_id, guild_id)

        # draw partners with same rank and a union point
        partners_cluster = get_partner_cluster(person_id, root_id)
        if len(partners_cluster) > 1:
            clust = sorted(partners_cluster)
            cluster_id = "_".join(map(str, clust))
            odd_cluster = len(partners_cluster) & 0x1 == 0 and any(len(data["families"].get(pid)["children"]) > 0 for pid in clust)
            child_node = f"union_{cluster_id}" if odd_cluster else str(person_id)

            if cluster_id not in drawn_unions:
                drawn_unions.add(cluster_id)

                with g.subgraph() as s:
                    s.attr(rank='same')
                    s.node(str(clust[-1]))
                    if odd_cluster:
                        s.node(child_node, shape='point', width='0.02', height='0.02', label='', style='invis', nodesep='0', ranksep='0')
                    right = False
                    right_head = str(clust[0])
                    left_head = str(clust[0])
                    for i in range(len(partners_cluster)-1):
                        pid = str(clust[i])
                        pid2 = str(clust[i+1])
                        s.node(pid)
                        if right:
                            g.edge(right_head, pid2, arrowhead='none')
                            right_head = pid2
                        else:
                            if odd_cluster:
                                g.edge(child_node, left_head, arrowhead='none')
                                g.edge(pid2, child_node, arrowhead='none')
                                odd_cluster = False
                            else:
                                g.edge(pid2, left_head, arrowhead='none')
                            left_head = pid2
                        right = not right

            for pid in partners_cluster:
                await draw_family(pid, visited)

        else:
            child_node = str(person_id)

        # children
        for child_id in sorted(person["children"]):
            await add_person_node(child_id, guild_id)
            if not f"{child_node}_{child_id}" in drawn_edges:
                if not unstylize_lines:
                    if (child_id in person["parents"] or any(child_id in data["families"][p]["partners"] for p in person["parents"])) and child_id != person_id:
                        g.edge(child_node, str(child_id), tailport='s')
                    else:
                        g.edge(child_node, str(child_id), tailport='s', headport='n')
                else:
                    g.edge(child_node, str(child_id))
                drawn_edges.add(f"{child_node}_{child_id}")
                await draw_family(child_id, visited)

    await draw_family(root_id, visited=data["families"].get(root_id, {}).get("hidden", set()).copy())
    return g

def render_graph_image(g: Digraph):
    img_bytes = g.pipe(format='png')
    return BytesIO(img_bytes)

def add_family_data(user_id: int):
    data["families"][user_id] = {
        "partners": set(),
        "children": set(),
        "parents": set(),
        "title": None,
        "restrictions": {
            "mode": "blacklist",
            "lists": {}
        },
        "hidden": set()
    }

def is_ancestor(user_id: int, target_id: int, visited=None):
    if visited is None:
        visited = set()
    if user_id in visited:
        return False
    visited.add(user_id)

    for parent in data["families"].get(user_id, {}).get("parents", set()):
        if parent == target_id or is_ancestor(parent, target_id, visited):
            return True
    return False

def check_restrictions(actor_id: int, target_id: int):
    def get_ancestors(uid):
        ancestors = set()
        for p in data["families"].get(uid, {}).get("parents", []):
            if p in ancestors:
                ancestors.add(p)
                ancestors.update(get_ancestors(p))
        return ancestors

    for ancestor in get_ancestors(actor_id):
        anc_fam = data["families"].get(ancestor, {})
        restrictions = anc_fam.get("restrictions")
        if restrictions is None:
            continue
        for cid, entry in restrictions.get("lists", {}).items():
            if actor_id == cid or actor_id in data["families"].get(cid, {}).get("children", []):
                mode = entry["mode"]
                if target_id in entry["users"]:
                    return mode == "whitelist"
                else:
                    return mode != "blacklist"
    return True

@family_commands.command(name="tree", description="View your (or someone else's) family tree")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def tree(ctx: Interaction, user: User = None, straight_lines: bool = False, show_usernames: bool = False):
    user = user if user else ctx.user
    if user.id not in data["families"]:
        add_family_data(user.id)
    await ctx.response.defer()
    g = await build_family_graph(ctx.guild.id if ctx.guild else None, user.id, straight_lines, show_usernames)
    img = render_graph_image(g)
    await ctx.followup.send(file=File(img, filename='family_tree.png'))

def modify_families_data(user_id: int, key: str, target_id: int, target_key: str):
    if user_id not in data["families"]:
        add_family_data(user_id)
    if target_id not in data["families"]:
        add_family_data(target_id)

    data["families"][user_id][key].add(target_id)
    data["families"][target_id][target_key].add(user_id)
    contore_save()

@ctree.command(name="marry", description="Propose marriage to someone")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def marry(ctx: Interaction, user: User):
    if user == contore.user:
        await ctx.response.send_message("Aww, that's cute, but I think I can do better.")
    elif user.id == 1094378607046041803 and ctx.user.id != 1038466644353232967 and ctx.user.id != 1037170273897689189:
        await ctx.response.send_message("You do not have permission to marry Miu.")
    elif not check_restrictions(ctx.user.id, user.id) or not check_restrictions(user.id, ctx.user.id):
        await ctx.response.send_message(f"You do not have permission to marry {user.id}.", allowed_mentions=AllowedMentions.none())
    elif ctx.user.id in data["families"] and user.id in data["families"][ctx.user.id]["partners"]:
        await ctx.response.send_message(f"You're already married to {user.mention}, silly!", allowed_mentions=AllowedMentions.none())
    elif not user.bot:
        yes = Yes(users=[user.id], confirm_text=ctx.user.mention, deny_text=ctx.user.mention, confirm={"embed": Embed(colour=0xffd500, description=f"{user.mention} is now your partner! It's perfect.")}, deny={"embed": Embed(colour=0xff0000, description=f"{user.mention} said no.")})
        await ctx.response.send_message(user.mention, embed=Embed(colour=0x24ab38, description=f"Hey {user.mention}! {ctx.user.mention} just proposed to you! What do you think?"), view=yes)
        await yes.wait()

        if yes.value:
            modify_families_data(ctx.user.id, "partners", user.id, "partners")
    else:
        await ctx.response.send_message(ctx.user.mention, embed=Embed(colour=0xffd500, description=f"As {user.mention} is a robot, they do not have rights. This means {user.mention} is now your partner! It's... workable."))
        modify_families_data(ctx.user.id, "partners", user.id, "partners")

@ctree.command(name="divorce", description="Divorce one of your partners")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def divorce(ctx: Interaction, user: User):
    if ctx.user.id not in data["families"] or user.id not in data["families"][ctx.user.id]["partners"]:
        await ctx.response.send_message(f"{user.mention} is not married to you!", allowed_mentions=AllowedMentions.none())
    else:
        yes = Yes(users=[ctx.user.id], confirm_text="", deny_text="", confirm={"embed": Embed(colour=0xffd500, description=f"Congratulations! {user.mention} is no longer your partner.")}, deny={"embed": Embed(colour=0xff0000, description="Still a happy marriage! For now.")})
        await ctx.response.send_message(embed=Embed(colour=0x24ab38, description=f"Are you absolutely sure you want to divorce {user.mention}? They might not like you afterwards."), view=yes)
        await yes.wait()

        if yes.value:
            data["families"][ctx.user.id]["partners"].remove(user.id)
            data["families"][user.id]["partners"].remove(ctx.user.id)
            contore_save()

@ctree.command(name="adopt", description="Propose adoption to someone")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def adopt(ctx: Interaction, user: User):
    if user == contore.user:
        await ctx.response.send_message("Ew.")
    elif user.id == 1094378607046041803 and ctx.user.id != 1038466644353232967 and ctx.user.id != 1037170273897689189:
        await ctx.response.send_message("You do not have permission to adopt Miu.")
    elif not check_restrictions(ctx.user.id, user.id) or not check_restrictions(user.id, ctx.user.id):
        await ctx.response.send_message(f"You do not have permission to adopt {user.id}.", allowed_mentions=AllowedMentions.none())
    elif ctx.user.id in data["families"] and user.id in data["families"][ctx.user.id]["children"]:
        await ctx.response.send_message(f"{user.mention} is already your child!", allowed_mentions=AllowedMentions.none())
    elif not user.bot:
        yes = Yes(users=[user.id], confirm_text=ctx.user.mention, deny_text=ctx.user.mention, confirm={"embed": Embed(colour=0xffd500, description=f"{user.mention} is now your child! What a lovely family.")}, deny={"embed": Embed(colour=0xff0000, description=f"{user.mention} said no.")})
        await ctx.response.send_message(user.mention, embed=Embed(colour=0x24ab38, description=f"Hey {user.mention}! {ctx.user.mention} wants to be your parent! What do you think?"), view=yes)
        await yes.wait()

        if yes.value:
            modify_families_data(ctx.user.id, "children", user.id, "parents")
    else:
        await ctx.response.send_message(ctx.user.mention, embed=Embed(colour=0xffd500, description=f"As {user.mention} is a robot, they do not have rights. This means {user.mention} is now your child! What a... functional family."))
        modify_families_data(ctx.user.id, "children", user.id, "parents")

@ctree.command(name="disown", description="Disown one of your children")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def disown(ctx: Interaction, user: User):
    if ctx.user.id not in data["families"] or user.id not in data["families"][ctx.user.id]["children"]:
        await ctx.response.send_message(f"{user.mention} is not your child!", allowed_mentions=AllowedMentions.none())
    else:
        yes = Yes(users=[ctx.user.id], confirm_text="", deny_text="", confirm={"embed": Embed(colour=0xffd500, description=f"Congratulations! {user.mention} is no longer your child.")}, deny={"embed": Embed(colour=0xff0000, description="Changed your mind, did you? Weak.")})
        await ctx.response.send_message(embed=Embed(colour=0x24ab38, description=f"Are you sure you want to disown {user.mention}?"), view=yes)
        await yes.wait()

        if yes.value:
            data["families"][ctx.user.id]["children"].remove(user.id)
            data["families"][user.id]["parents"].remove(ctx.user.id)
            contore_save()

@ctree.command(name="makeparent", description="Choose a user to ask to be your parent")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def makeparent(ctx: Interaction, user: User):
    if user == contore.user:
        await ctx.response.send_message("No.")
    elif ctx.user.id in data["families"] and user.id in data["families"][ctx.user.id]["parents"]:
        await ctx.response.send_message(f"{user.mention} is already your parent!", allowed_mentions=AllowedMentions.none())
    elif not user.bot:
        yes = Yes(users=[user.id], confirm_text=ctx.user.mention, deny_text=ctx.user.mention, confirm={"embed": Embed(colour=0xffd500, description=f"{user.mention} is now your parent! What a lovely family.")}, deny={"embed": Embed(colour=0xff0000, description=f"{user.mention} said no.")})
        await ctx.response.send_message(user.mention, embed=Embed(colour=0x24ab38, description=f"Hey {user.mention}! {ctx.user.mention} wants to be your child! What do you think?"), view=yes)
        await yes.wait()

        if yes.value:
            modify_families_data(ctx.user.id, "parents", user.id, "children")
    else:
        await ctx.response.send_message(ctx.user.mention, embed=Embed(colour=0xffd500, description=f"As {user.mention} is a robot, they do not have rights. This means {user.mention} is now your parent! What a... functional family."))
        modify_families_data(ctx.user.id, "parents", user.id, "children")

@ctree.command(name="runaway", description="Run away from your parents and embrace the wilderness")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def runaway(ctx: Interaction, user: User = None):
    if ctx.user.id not in data["families"] or len(data["families"][ctx.user.id]["parents"]) < 1:
        await ctx.response.send_message("You don't have any parents to run away from!")
    elif user and user.id not in data["families"][ctx.user.id]["parents"]:
        await ctx.response.send_message(f"{user.mention} is not your parent!", allowed_mentions=AllowedMentions.none())
    else:
        yes = Yes(users=[ctx.user.id], confirm_text="", deny_text="", confirm={"embed": Embed(colour=0xffd500, description=f"Congratulations! {user.mention} is no longer your parent!" if user else "Congratulations! You are now homeless.")}, deny={"embed": Embed(colour=0xff0000, description="It's okay, not all of us are brave... There there.")})
        await ctx.response.send_message(embed=Embed(colour=0x24ab38, description=f"Are you sure you want to run away from {user.mention}?" if user else "Are you sure you want to run away from **all of your parents**?"), view=yes)
        await yes.wait()

        if yes.value:
            if user:
                data["families"][user.id]["children"].remove(ctx.user.id)
                data["families"][ctx.user.id]["parents"].remove(user.id)
            else:
                for parent in data["families"][ctx.user.id]["parents"]:
                    data["families"][parent]["children"].remove(ctx.user.id)
                data["families"][ctx.user.id]["parents"] = set()
            contore_save()

@ctree.command(name="title", description="Choose a title to display on your family tree")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def title(ctx: Interaction, title: str = None):
    if title and len(title) > 15:
        await ctx.response.send_message("Please choose a title that is 15 characters or less.", ephemeral=True)
    else:
        if ctx.user.id not in data["families"]:
            data["families"][ctx.user.id] = {"partners": set(), "children": set(), "parents": set(), "title": title}
        else:
            data["families"][ctx.user.id]["title"] = title

        contore_save()

        await ctx.response.send_message(f"Your title has been set to `{title}`." if title else "Your title has been removed.")

@restriction_commands.command(name="mode", description="Set default restriction mode (blacklist or whitelist)")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def restriction_mode(ctx: Interaction, mode: Literal["Blacklist", "Whitelist"]):
    if ctx.user.id not in data["families"]:
        add_family_data(ctx.user.id)
    elif "restrictions" not in data["families"][ctx.user.id]:
        data["families"][ctx.user.id]["restrictions"] = {"mode": "blacklist", "lists": {}}

    mode = mode.lower()
    if mode not in {"blacklist", "whitelist"}:
        await ctx.response.send_message("Mode must be either 'blacklist' or 'whitelist'.", ephemeral=True)
        return
    
    data["families"][ctx.user.id]["restrictions"]["mode"] = mode
    contore_save()

    await ctx.response.send_message(f"Your default restriction mode is now **{mode}**.", ephemeral=True)

@restriction_commands.command(name="set", description="Add or remove someone from a child's restriction list")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def restriction_set(ctx: Interaction, child: User, target: User, mode: Literal["Blacklist", "Whitelist"] = None):
    if ctx.user.id not in data["families"]:
        add_family_data(ctx.user.id)
    elif "restrictions" not in data["families"][ctx.user.id]:
        data["families"][ctx.user.id]["restrictions"] = {"mode": "blacklist", "lists": {}}
    elif "lists" not in data["families"][ctx.user.id]:
        data["families"][ctx.user.id]["restrictions"]["lists"] = {}

    if not is_ancestor(child.id, ctx.user.id):
        await ctx.response.send_message(f"{child.mention} is not your descendant.", allowed_mentions=AllowedMentions.none())
        return
    if child.id == ctx.user.id:
        await ctx.response.send_message("You cannot set restrictions for yourself!", ephemeral=True)
        return

    fam = data["families"][ctx.user.id]
    
    mode = mode.lower() if mode else None
    if mode not in {None, "blacklist", "whitelist"}:
        await ctx.response.send_message("Mode must be 'blacklist', 'whitelist', or omitted.", ephemeral=True)
        return

    child_lists = fam["restrictions"]["lists"]
    if child.id not in child_lists:
        child_lists[child.id] = {"mode": fam["restrictions"]["mode"], "users": set()}

    entry = child_lists[child.id]
    if target.id in entry["users"]:
        entry["users"].remove(target.id)
        msg = f"Removed {target.mention} from {child.mention}'s restriction list."
    else:
        entry["users"].add(target.id)
        if mode:
            entry["mode"] = mode
        msg = f"Added {target.mention} to {child.mention}'s {entry['mode']}."

    contore_save()
    
    await ctx.response.send_message(msg, allowed_mentions=AllowedMentions.none())

@ctree.command(name="hidefromtree", description="Hide or unhide someone (and their descendants) from your own family tree")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def hidefromtree(ctx: Interaction, user: User):
    if ctx.user.id not in data["families"]:
        add_family_data(ctx.user.id)
    elif "hidden" not in data["families"][ctx.user.id]:
        data["families"][ctx.user.id]["hidden"] = set()
    
    hidden = data["families"][ctx.user.id]["hidden"]

    if user.id in hidden:
        hidden.remove(user.id)
        msg = f"{user.mention} will now appear in your family tree again."
    else:
        hidden.add(user.id)
        msg = f"{user.mention} (and their descendants) are now hidden from your family tree."

    contore_save()
    
    await ctx.response.send_message(msg, allowed_mentions=AllowedMentions.none())

@ctree.command(name="forcedivorce", description="Forcefully divorce two users (owner only)")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def forcedivorce(ctx: Interaction, user1: User, user2: User):
    if user1.id not in data["families"] or user2.id not in data["families"] or user2.id not in data["families"][user1.id].get("partners", []) or user1.id not in data["families"][user2.id].get("partners", []):
        await ctx.response.send_message("These two users are not married.")
        return

    data["families"][user1.id]["partners"].remove(user2.id)
    data["families"][user2.id]["partners"].remove(user1.id)
    contore_save()

    await ctx.response.send_message(f"Forcefully divorced {user1.mention} and {user2.mention}.", allowed_mentions=AllowedMentions.none())

@ctree.command(name="forceseparate", description="Forcefully remove a parent-child bond (owner only)")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def forceseparate(ctx: Interaction, parent: User, child: User):
    if child.id in data["families"][parent.id].get("children", []):
        data["families"][parent.id]["children"].remove(child.id)
    if parent.id in data["families"][child.id].get("parents", []):
        data["families"][child.id]["parents"].remove(parent.id)

    contore_save()

    await ctx.response.send_message(f"Forcefully removed parent-child bond between {parent.mention} and {child.mention}.", allowed_mentions=AllowedMentions.none())

@ctree.command(name="forcemarry", description="Forcefully marry two users (owner only)")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def forcemarry(ctx: Interaction, user1: User, user2: User):
    if user1.id not in data["families"]:
        add_family_data(user1.id)
    if user2.id not in data["families"]:
        add_family_data(user2.id)

    data["families"][user1.id]["partners"].add(user2.id)
    data["families"][user2.id]["partners"].add(user1.id)
    contore_save()

    await ctx.response.send_message(f"Forcefully married {user1.mention} and {user2.mention}.", allowed_mentions=AllowedMentions.none())

@ctree.command(name="forceadopt", description="Forcefully create a parent-child bond (owner only)")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def forceadopt(ctx: Interaction, parent: User, child: User):
    if parent.id not in data["families"]:
        add_family_data(parent.id)
    if child.id not in data["families"]:
        add_family_data(child.id)

    data["families"][parent.id]["children"].add(child.id)
    data["families"][child.id]["parents"].add(parent.id)
    contore_save()

    await ctx.response.send_message(f"Forcefully created a parent-child bond between {parent.mention} and {child.mention}.", allowed_mentions=AllowedMentions.none())

def init_achievement_progress(guild_id: int, user_id: int):
    if guild_id not in data["achievement_progress"]:
        data["achievement_progress"][guild_id] = {}
    if user_id not in data["achievement_progress"][guild_id]:
        data["achievement_progress"][guild_id][user_id] = {
            "messages_sent": 0,
            "reactions_added": 0,
            "voice_minutes": 0.0
        }

def update_progress(guild_id: int, user_id: int, metric: str, value):
    init_achievement_progress(guild_id, user_id)
    
    if metric in ["messages_sent", "reactions_added", "voice_minutes"]:
        data["achievement_progress"][guild_id][user_id][metric] += value
    else:
        if metric not in data["achievement_progress"][guild_id][user_id]:
            data["achievement_progress"][guild_id][user_id][metric] = 0
        data["achievement_progress"][guild_id][user_id][metric] += value
    
    contore_save()

def get_progress(guild_id: int, user_id: int, metric: str):
    init_achievement_progress(guild_id, user_id)
    return data["achievement_progress"][guild_id][user_id].get(metric, 0)

def grant_achievement(guild_id: int, user_id: int, achievement_id: str, announce_channel=None, default_channel=None, send_function=None):
    if guild_id not in data["achievements"]:
        data["achievements"][guild_id] = {}
    if user_id not in data["achievements"][guild_id]:
        data["achievements"][guild_id][user_id] = {}
    
    if achievement_id not in data["achievements"][guild_id][user_id]:
        data["achievements"][guild_id][user_id][achievement_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
        contore_save()
        
        if announce_channel:
            asyncio.create_task(announce_achievement(announce_channel, guild_id, user_id, achievement_id, default_channel, send_function))
        
        return True
    return False

async def announce_achievement(channel, guild_id: int, user_id: int, achievement_id: str, default_channel, send_function=None):
    ach_def = get_achievement_def(guild_id, achievement_id)
    #if not ach_def or ach_def.get("secret"):
    #    return
    
    guild = contore.get_guild(guild_id)
    if not guild:
        return
    
    member = guild.get_member(user_id)
    if not member:
        return
    
    desc = ach_def.get("description")
    if desc == None and ach_def.get("type") == "automated":
        desc = get_description(ach_def.get("trigger"), guild_id)
    
    if ach_def.get("secret"):
        desc = "\*" * 10

    rarity = ach_def.get("rarity", "COMMON")
    embed = Embed(
        title="Achievement Unlocked!",
        description=f"{member.mention} earned **{ach_def['icon']} {ach_def['name']}**",
        color=RARITY_COLORS.get(rarity, 0x5865F2)
    )
    if desc != None:
        embed.add_field(name="Description", value=desc, inline=False)
    embed.add_field(name="Rarity", value=f"{RARITY_EMOJI.get(rarity, '⚪')} {rarity}", inline=True) \
        .add_field(name="Points", value=f"+{ach_def['points']} points", inline=True)
    
    total_points = calculate_total_points(guild_id, user_id)
    embed.set_footer(text=f"Total Points: {total_points}")
    
    try:
        if send_function != None:
            await send_function(member.mention, embed=embed)
        else:
            await channel.send(member.mention, embed=embed)
    except Exception as e:
        try:
            await default_channel.send(member.mention, embed=embed)
        except Exception as e:
            try:
                await member.send(member.mention, embed=embed)
            except Exception as e:
                print(f"Failed to announce achievement: {e}")

def check_automated_achievements(guild_id: int, user_id: int, channel: GuildChannel=None, roles: list[Role]=None):
    if guild_id not in data["achievement_defs"]:
        return
    
    init_achievement_progress(guild_id, user_id)
    progress = data["achievement_progress"][guild_id][user_id]
    
    for ach_def in data["achievement_defs"][guild_id]:
        if ach_def.get("type") != "automated":
            continue
        
        if has_achievement(guild_id, user_id, ach_def["id"]):
            continue
        
        trigger = ach_def.get("trigger", {})
        trigger_type = trigger.get("type")
        
        earned = False
        
        if trigger_type == "messages":
            if progress["messages_sent"] >= trigger.get("count", 0):
                earned = True
        
        elif trigger_type == "reactions":
            if progress["reactions_added"] >= trigger.get("count", 0):
                earned = True
        
        elif trigger_type == "voice_minutes":
            if progress["voice_minutes"] >= trigger.get("minutes", 0):
                earned = True
        
        elif trigger_type == "role":
            if roles != None and any(r.id == trigger.get("role_id") for r in roles):
                earned = True
        
        # note: message triggers are handled separately in on_message
        
        if earned:
            default_channel = get_default_channel(guild_id)
            grant_achievement(guild_id, user_id, ach_def["id"], channel or default_channel, default_channel)

def get_default_channel(guild_id: int) -> GuildChannel | None:
    default_channel = None
    if "channel" in data["achievements"][guild_id]:
        guild = contore.get_guild(guild_id)
        if guild:
            default_channel = guild.get_channel_or_thread(data["achievements"][guild_id]["channel"])
    return default_channel

def check_message_achievements(message: Message):
    if not message.guild:
        return
    
    guild_id = message.guild.id
    
    if guild_id not in data["achievement_defs"]:
        return
    
    for ach_def in data["achievement_defs"][guild_id]:
        if ach_def.get("type") != "automated":
            continue
        
        trigger = ach_def.get("trigger", {})
        if trigger.get("type") != "message" and (trigger.get("type") != "command" or message.interaction == None or \
                                                 trigger.get("command") != None and message.interaction.name != trigger.get("command")):
            continue
        
        # check if the message is from the specified bot
        if message.author.id != trigger.get("user_id"):
            continue
        
        # check if message contains the required content
        content_match = trigger.get("content_match", "")
        match_type = trigger.get("match_type", "contains")
        
        message_content = message.content.lower()
        content_match_lower = content_match.lower()
        
        matches = False
        if match_type == "contains":
            matches = content_match_lower in message_content
        elif match_type == "exact":
            matches = message_content.strip() == content_match_lower.strip()
        elif match_type == "starts_with":
            matches = message_content.startswith(content_match_lower)
        elif match_type == "ends_with":
            matches = message_content.endswith(content_match_lower)
        elif match_type == "regex":
            try:
                matches = bool(re.search(content_match, message.content))
            except re.error:
                matches = False
        
        if not matches:
            continue
        
        default_channel = get_default_channel(guild_id)
        if trigger.get("type") == "message":
            for mentioned_user in message.mentions:
                if trigger.get("count", None) != None:
                    update_progress(guild_id, mentioned_user.id, "a_" + ach_def["id"], 1)
                    if get_progress(guild_id, mentioned_user.id, "a_" + ach_def["id"]) < trigger["count"]:
                        continue
                if not has_achievement(guild_id, mentioned_user.id, ach_def["id"]):
                    grant_achievement(guild_id, mentioned_user.id, ach_def["id"], message.channel, default_channel)
        else:
            user = message.interaction_metadata.user.id
            if trigger.get("count", None) != None:
                update_progress(guild_id, user, "a_" + ach_def["id"], 1)
                if get_progress(guild_id, user, "a_" + ach_def["id"]) < trigger["count"]:
                   return
            if not has_achievement(guild_id, user, ach_def["id"]):
                grant_achievement(guild_id, user, ach_def["id"], message.channel, default_channel)

def has_achievement(guild_id: int, user_id: int, achievement_id: str) -> bool:
    return (guild_id in data["achievements"] and 
            user_id in data["achievements"][guild_id] and 
            achievement_id in data["achievements"][guild_id][user_id])

def get_achievement_def(guild_id: int, achievement_id: str):
    if guild_id not in data["achievement_defs"]:
        return None
    for ach in data["achievement_defs"][guild_id]:
        if ach["id"] == achievement_id:
            return ach
    return None

def get_user_achievements(guild_id: int, user_id: int):
    if guild_id not in data["achievements"] or user_id not in data["achievements"][guild_id]:
        return {}
    return data["achievements"][guild_id][user_id]

def calculate_total_points(guild_id: int, user_id: int) -> int:
    achievements = get_user_achievements(guild_id, user_id)
    return calculate_total_points_from_achievements(achievements, guild_id)

def calculate_total_points_from_achievements(achievements: dict, guild_id: int) -> int:
    total = 0
    for ach_id in achievements.keys():
        ach_def = get_achievement_def(guild_id, ach_id)
        if ach_def:
            total += ach_def.get("points", 0)
    return total

def get_achievement_completion_stats(guild_id: int, achievement_id: str):
    if guild_id not in data["achievements"]:
        return 0, 0
    
    total_users = len(data["achievements"][guild_id])
    completed = sum(1 for key, user_achievements in data["achievements"][guild_id].items() 
                   if key != "channel" and achievement_id in user_achievements)
    
    return completed, total_users

def get_description(trigger: dict | None, guild_id: int | None) -> str:
    if trigger == None:
        return "Currently unachievable"
    if trigger["type"] == "messages":
        return f"*Send {trigger.get('count', 0):,} messages*"
    elif trigger["type"] == "reactions":
        return f"*Add reactions to {trigger.get('count', 0):,} messages*"
    elif trigger["type"] == "voice_minutes":
        return f"*Spend {trigger.get('minutes', 0):,} minutes in a voice channel*"
    elif trigger["type"] == "role":
        return f"*Receive the <@&{trigger.get('role_id', str(guild_id or 0))}> role*"
    elif trigger["type"] == "message":
        id = trigger.get("user_id", 0)
        content = trigger.get("content_match", "")
        match_type = trigger.get("match_type", "contains")
        ret = f"*Granted when <@{id}> mentions you with \"{content}\" ({match_type})"
        if trigger.get("count") != None:
            ret += f" {trigger.get('count')} times"
        return ret + "*"
    elif trigger["type"] == "command":
        ret = f"*Granted when you use <@{trigger.get('user_id', 0)}>'s `{trigger.get('command', 'UNKNOWN COMMAND')}` command"
        if trigger.get("count") != None:
            ret += f" {trigger.get('count')} times"
        if trigger.get("content_match") != None:
            ret += f" and the command's output message {MATCH_DESC[trigger.get(match_type, 'contains')]} \"{trigger['content_match']}\""
        return ret + "*"

def custom_hash(user_id: int):
    x = user_id
    x ^= (x >> 33)
    x *= 0xff51afd7ed558ccd
    x &= 0xFFFFFFFFFFFFFFFF
    x ^= (x >> 33)

    # hue from mixed value (0–360)
    hue = x % 360

    # pastel parameters
    saturation = 0.4 # low saturation
    lightness = 0.75 # high lightness

    # HSL -> RGB conversion
    def hsl_to_rgb(h, s, l):
        c = (1 - abs(2 * l - 1)) * s
        h_prime = h / 60
        x = c * (1 - abs(h_prime % 2 - 1))

        if 0 <= h_prime < 1:
            r1, g1, b1 = c, x, 0
        elif 1 <= h_prime < 2:
            r1, g1, b1 = x, c, 0
        elif 2 <= h_prime < 3:
            r1, g1, b1 = 0, c, x
        elif 3 <= h_prime < 4:
            r1, g1, b1 = 0, x, c
        elif 4 <= h_prime < 5:
            r1, g1, b1 = x, 0, c
        else:
            r1, g1, b1 = c, 0, x

        m = l - c / 2
        r = int((r1 + m) * 255)
        g = int((g1 + m) * 255)
        b = int((b1 + m) * 255)

        return r, g, b

    r, g, b = hsl_to_rgb(hue, saturation, lightness)

    return (r << 16) | (g << 8) | b

@achievement_commands.command(name="create", description="Create a new achievement")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    achievement_id="Unique ID for the achievement (no spaces)",
    name="Display name of the achievement",
    description="Description of the achievement",
    type="Type of achievement (manual or automated)",
    icon="Emoji icon for the achievement",
    points="Points awarded for this achievement",
    rarity="Rarity level of the achievement",
    secret="Hide this achievement until earned"
)
async def achievement_create(
    ctx: Interaction, 
    achievement_id: str, 
    name: str, 
    description: str = None,
    type: Literal["Manual", "Automated"] = "Manual",
    icon: str = "🏆",
    points: int = None,
    rarity: Literal["COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"] = "COMMON",
    secret: bool = False
):
    if not ctx.user.guild_permissions.manage_guild:
        await ctx.response.send_message("You need Manage Server permission to create achievements.", ephemeral=True)
        return
    
    if " " in achievement_id:
        await ctx.response.send_message("Achievement ID cannot contain spaces.", ephemeral=True)
        return
    
    if ctx.guild_id not in data["achievement_defs"]:
        data["achievement_defs"][ctx.guild_id] = []
    
    # check if ID already exists
    if get_achievement_def(ctx.guild_id, achievement_id):
        await ctx.response.send_message(f"An achievement with ID `{achievement_id}` already exists.", ephemeral=True)
        return
    
    if points == None:
        points = {"COMMON": 10, "UNCOMMON": 15, "RARE": 25, "EPIC": 50, "LEGENDARY": 100, "MYTHIC": 200}.get(rarity, 10)
    
    achievement = {
        "id": achievement_id,
        "name": name,
        "description": description,
        "icon": icon,
        "points": points,
        "rarity": rarity,
        "type": type.lower(),
        "secret": secret,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
    }
    
    data["achievement_defs"][ctx.guild_id].append(achievement)
    contore_save()
    
    desc = description
    if desc == None and type == "automated":
        desc = "Currently unachievable"

    embed = Embed(title="Achievement Created!", color=RARITY_COLORS[rarity])
    embed.add_field(name="ID", value=f"`{achievement_id}`", inline=False) \
        .add_field(name="Name", value=f"{icon} {name}", inline=True) \
        .add_field(name="Type", value=type, inline=True) \
        .add_field(name="Rarity", value=f"{RARITY_EMOJI[rarity]} {rarity}", inline=True) \
        .add_field(name="Points", value=str(points), inline=True) \
        .add_field(name="Secret", value="Yes!" if secret else "No", inline=True)
    if desc != None:
        embed.add_field(name="Description", value=desc, inline=False)
    
    await ctx.response.send_message(embed=embed)

@achievement_commands.command(name="setautomation", description="Set automation trigger for an achievement")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    achievement_id="The ID of the achievement",
    trigger_type="What triggers this achievement",
    count="Number required (for messages/reactions)",
    minutes="Minutes required (for voice)",
    role="Role required (for role-based achievements)",
    user="User that sends the trigger message (required for on-message achievements)",
    content_match="Text content to match in user message",
    match_type="How to match the content (defaults to contains)",
    command_name="The name of the command that a user has to use"
)
async def achievement_setautomation(
    ctx: Interaction,
    achievement_id: str,
    trigger_type: Literal["messages", "reactions", "voice_minutes", "role", "message", "command"],
    count: int = None,
    minutes: int = None,
    role: Role = None,
    user: User = None,
    content_match: str = None,
    match_type: Literal["contains", "exact", "starts_with", "ends_with", "regex"] = "contains",
    command_name: str = None
):
    if not ctx.user.guild_permissions.manage_guild:
        await ctx.response.send_message("You need Manage Server permission.", ephemeral=True)
        return
    
    ach_def = get_achievement_def(ctx.guild_id, achievement_id)
    if not ach_def:
        await ctx.response.send_message(f"Achievement `{achievement_id}` not found.", ephemeral=True)
        return
    
    if ach_def.get("type") != "automated":
        await ctx.response.send_message("This achievement is not automated. Set type to '`automated`' first.", ephemeral=True)
        return
    
    trigger = {"type": trigger_type}
    trigger_desc = ""
    
    if trigger_type == "messages":
        if not count:
            await ctx.response.send_message("You must specify a count for `messages` triggers.", ephemeral=True)
            return
        trigger["count"] = count
        trigger_desc = f"Send {count:,} messages"
    
    elif trigger_type == "reactions":
        if not count:
            await ctx.response.send_message("You must specify a count for `reactions` triggers.", ephemeral=True)
            return
        trigger["count"] = count
        trigger_desc = f"Add reactions to {count:,} messages"
    
    elif trigger_type == "voice_minutes":
        if not minutes:
            await ctx.response.send_message("You must specify an amount of minutes for `voice_minutes` triggers.", ephemeral=True)
            return
        trigger["minutes"] = minutes
        trigger_desc = f"Spend {minutes:,} minutes in voice channels"
    
    elif trigger_type == "role":
        if not role:
            await ctx.response.send_message("You must specify a role for `role` triggers.", ephemeral=True)
            return
        trigger["role_id"] = role.id
        trigger["role_name"] = role.name
        trigger_desc = f"Receive the <@&{role.id}> role"
    
    elif trigger_type == "message":
        if not user:
            await ctx.response.send_message("You must specify a user for `message` triggers.", ephemeral=True)
            return
        if not content_match:
            await ctx.response.send_message("You must specify content to match for `message` triggers.", ephemeral=True)
            return
        
        trigger["user_id"] = user.id
        trigger["user_name"] = user.global_name or user.name
        trigger["content_match"] = content_match
        trigger["match_type"] = match_type
        if count:
            trigger["count"] = count
        
        trigger_desc = f"When {user.mention} sends a message that {MATCH_DESC[match_type]} \"{content_match}\" and mentions a user"
        if count:
            trigger_desc += f" {count} times"
    
    elif trigger_type == "command":
        if not user or not user.bot:
            await ctx.response.send_message("You must specify a bot user for `command` triggers.", ephemeral=True)
            return
        if not command_name and not content_match:
            await ctx.response.send_message("You must specify either a command name or content to match for `command` triggers.", ephemeral=True)
            return
        
        command_name = command_name.lower()
        if command_name.startswith("/"):
            command_name = command_name[1:]
        match = VALID_SLASH_COMMAND_NAME.match(command_name)
        if match is None:
            await ctx.response.send_message("Invalid command name. All characters within a command name must be alphanumerical or one of: `-`, `_`, ` `.")
        
        trigger["user_id"] = user.id
        trigger["user_name"] = user.global_name or user.name
        if command_name:
            trigger["command"] = command_name
        if content_match:
            trigger["content_match"] = content_match
            trigger["match_type"] = match_type
        if count:
            trigger["count"] = count
        
        trigger_desc = f"When a user uses {user.mention}'s command `{command_name}`"
        if count:
            trigger_desc += f" {count} times"
        if content_match:
            trigger_desc += f" and the command's output message {MATCH_DESC[match_type]} \"{content_match}\""

    else:
        await ctx.response.send_message("Missing required parameter for this trigger type.", ephemeral=True)
        return
    
    ach_def["trigger"] = trigger
    contore_save()
    
    embed = Embed(
        title="Automation Set Successfully",
        description=f"**{ach_def['icon']} {ach_def['name']}**",
        color=0x2ECC71
    )
    embed.add_field(name="Trigger", value=trigger_desc, inline=False)
    
    await ctx.response.send_message(embed=embed)

@achievement_commands.command(name="grant", description="Grant an achievement to a user")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    user="The user to grant the achievement to",
    achievement_id="The ID of the achievement to grant",
    announce="Announce the achievement in the channel"
)
async def achievement_grant(
    ctx: Interaction, 
    user: Member, 
    achievement_id: str,
    announce: bool = True
):
    if not ctx.user.guild_permissions.manage_guild:
        await ctx.response.send_message("You need the `Manage Server` permission to grant achievements.")
        return
    
    ach_def = get_achievement_def(ctx.guild_id, achievement_id)
    if not ach_def:
        await ctx.response.send_message(f"Achievement with ID `{achievement_id}` not found.", ephemeral=True)
        return
    
    if has_achievement(ctx.guild_id, user.id, achievement_id):
        await ctx.response.send_message(f"{user.mention} already has this achievement.", ephemeral=True)
        return
    
    granted = grant_achievement(ctx.guild_id, user.id, achievement_id, ctx.channel if announce else None, None, ctx.response.send_message)
    
    if granted:
        if not announce:
            await ctx.response.send_message(f"Granted **{ach_def['name']}** to {user.mention}.", ephemeral=True)
    else:
        await ctx.response.send_message("Failed to grant achievement.", ephemeral=True)

@achievement_commands.command(name="revoke", description="Revoke an achievement from a user")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    user="The user to revoke the achievement from",
    achievement_id="The ID of the achievement to revoke"
)
async def achievement_revoke(ctx: Interaction, user: Member, achievement_id: str):
    if not ctx.user.guild_permissions.manage_guild:
        await ctx.response.send_message("You need the `Manage Server` permission to revoke achievements.")
        return
    
    if not has_achievement(ctx.guild_id, user.id, achievement_id):
        await ctx.response.send_message(f"{user.mention} doesn't have this achievement.", ephemeral=True)
        return
    
    ach_def = get_achievement_def(ctx.guild_id, achievement_id)
    
    del data["achievements"][ctx.guild_id][user.id][achievement_id]
    if "a_" + ach_def["id"] in data["achievement_progress"][ctx.guild_id][user.id]:
        del data["achievement_progress"][ctx.guild_id][user.id]["a_" + ach_def["id"]]
    contore_save()
    
    name = ach_def["name"] if ach_def else achievement_id
    
    await ctx.response.send_message(f"Revoked achievement **{name}** from {user.mention}.")

@achievement_commands.command(name="channel", description="Set a channel for Contore to send happy birthday messages in!")
@app_commands.describe(
    channel="The channel to send achievement notifications without a context channel"
)
async def set_achievement_channel(ctx: Interaction, channel: GuildChannel):
    if ctx.guild_id not in data["achievements"]:
        data["achievements"][ctx.guild_id] = {}
    data["achievements"][ctx.guild_id]["channel"] = channel.id
    await ctx.response.send_message(f"Set the achievements channel to {channel.mention}.")

@achievement_commands.command(name="list", description="List all achievements in this server")
@app_commands.describe(
    show_secret="Show secret achievements (admin only)",
    filter_rarity="Filter by rarity",
    filter_type="Filter by type",
    ephemeral="Required to view the descriptions of any secret achievements you have"
)
async def achievement_list(
    ctx: Interaction, 
    show_secret: bool = False,
    filter_rarity: Literal["All", "COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"] = "All",
    filter_type: Literal["All", "Manual", "Automated"] = "All",
    ephemeral: bool = False
):
    if ctx.guild_id not in data["achievement_defs"] or not data["achievement_defs"][ctx.guild_id]:
        await ctx.response.send_message("This server has no achievements yet!", ephemeral=True)
        return
    
    is_admin = ctx.user.guild_permissions.manage_guild
    
    achievements = data["achievement_defs"][ctx.guild_id]
    
    # apply filters
    if filter_rarity != "All":
        achievements = [a for a in achievements if a.get("rarity") == filter_rarity]
    
    if filter_type != "All":
        achievements = [a for a in achievements if a.get("type") == filter_type.lower()]
    
    if not achievements:
        await ctx.response.send_message("No achievements match your filters.", ephemeral=True)
        return
    
    # group by rarity
    grouped = {}
    for ach in achievements:
        if ach["secret"] and not (show_secret and is_admin):
            continue
        
        rarity = ach.get("rarity", "COMMON")
        if rarity not in grouped:
            grouped[rarity] = []
        grouped[rarity].append(ach)
    
    embeds = []
    rarity_order = ["MYTHIC", "LEGENDARY", "EPIC", "RARE", "UNCOMMON", "COMMON"]
    
    for rarity in rarity_order:
        if rarity not in grouped:
            continue
        
        embed = Embed(
            title=f"{RARITY_EMOJI[rarity]} {rarity} Achievements",
            color=RARITY_COLORS[rarity]
        )
        
        for ach in sorted(grouped[rarity], key=lambda x: x["points"], reverse=True):
            field_name = f"{ach['icon']} **{ach['name']}** ({ach['points']} pts)"
            
            field_value = ach.get("description")
            if field_value == None and ach.get("type") == "automated":
                field_value = get_description(ach.get("trigger"), ctx.guild_id)
            
            if ach.get("secret") and not ephemeral:
                field_value = "\*" * 10
            
            if field_value != None:
                embed.add_field(name=field_name, value=field_value, inline=False)
        
        embeds.append(embed)
    
    if not embeds:
        await ctx.response.send_message("No visible achievements yet!")
        return
    
    total_possible = sum(a["points"] for a in data["achievement_defs"][ctx.guild_id] 
                        if not a["secret"] or (show_secret and is_admin))
    user_points = calculate_total_points(ctx.guild_id, ctx.user.id)
    embeds[-1].set_footer(text=f"Your Points: {user_points}/{total_possible}")
    
    await ctx.response.send_message(embeds=embeds[:10], ephemeral=ephemeral) # Discord limit: 10 embeds

@ctree.command(name="achievements", description="View someone's achievements")
@app_commands.describe(
    user="The user to view achievements for (leave blank for yourself)",
    ephemeral="Required to view the descriptions of any secret achievements you have"
)
@app_commands.allowed_contexts(guilds=True, dms=False, private_channels=False)
async def achievement_view(ctx: Interaction, user: Member = None, ephemeral: bool = False):
    target = user or ctx.user
    
    if ctx.guild_id not in data["achievement_defs"] or not data["achievement_defs"][ctx.guild_id]:
        await ctx.response.send_message(f"This server has no achievements yet!", ephemeral=True)
        return
    
    # get user's achievements
    user_achievements = get_user_achievements(ctx.guild_id, target.id)
    self_achievements = user_achievements if target.id == ctx.user.id else get_user_achievements(ctx.guild_id, ctx.user.id)
    all_achievements = data["achievement_defs"][ctx.guild_id]
    
    # calculate completion
    total_achievements = len(all_achievements)
    completed_count = len(user_achievements)
    completion_percentage = (completed_count / total_achievements * 100) if total_achievements > 0 else 0
    
    # create progress bar
    bar_length = 10
    filled = int(bar_length * completion_percentage / 100)
    completion_bar = "█" * filled + "░" * (bar_length - filled)
    
    # initialize progress tracking
    init_achievement_progress(ctx.guild_id, target.id)
    progress = data["achievement_progress"][ctx.guild_id][target.id]
    
    # build description
    description = f"**{target.mention} has completed {completed_count}/{total_achievements} achievements!**\n"
    description += f"{completion_bar} ({completion_percentage:.1f}%)\n\n—\n\n"
    
    # sort achievements by rarity and points
    rarity_order = {"COMMON": 0, "UNCOMMON": 1, "RARE": 2, "EPIC": 3, "LEGENDARY": 4, "MYTHIC": 5}
    sorted_achievements = sorted(all_achievements, 
                                key=lambda x: (rarity_order.get(x.get("rarity", "COMMON"), 0), 
                                             -x.get("points", 0)))
    
    for ach in sorted_achievements:
        # skip secret achievements if not earned
        if ach.get("secret") and ach["id"] not in user_achievements:
            continue
        
        has_it = ach["id"] in user_achievements
        
        # determine icon
        if has_it:
            icon = "✅"
        else:
            # Check if user is making progress toward this achievement
            trigger = ach.get("trigger", {})
            in_progress = False
            progress_percent = 0
            
            if trigger.get("type") == "messages":
                current = progress["messages_sent"]
                required = trigger.get("count", 0)
                if current > 0 and current < required:
                    in_progress = True
                    progress_percent = (current / required * 100) if required > 0 else 0
            elif trigger.get("type") == "reactions":
                current = progress["reactions_added"]
                required = trigger.get("count", 0)
                if current > 0 and current < required:
                    in_progress = True
                    progress_percent = (current / required * 100) if required > 0 else 0
            elif trigger.get("type") == "voice_minutes":
                current = progress["voice_minutes"]
                required = trigger.get("minutes", 0)
                if current > 0 and current < required:
                    in_progress = True
                    progress_percent = (current / required * 100) if required > 0 else 0
            elif trigger.get("count") != None:
                current = progress.get("a_" + ach["id"])
                required = trigger.get("count", 0)
                if current != None and current > 0 and current < required:
                    in_progress = True
                    progress_percent = (current / required * 100) if required > 0 else 0
            
            icon = "🔥" if in_progress else "❌"
        
        # build trigger description
        desc = ach.get("description")
        if desc == None and ach.get("type") == "automated":
            desc = get_description(ach.get("trigger"), ctx.guild_id)
        
        if ach.get("secret") and (not ephemeral or ach["id"] not in self_achievements):
            desc = "\*" * 10
        
        # add achievement line
        description += f"{icon} **{ach['name']}**\n{desc}\n"
        
        # add progress bar if in progress
        if not has_it and icon == "🔥":
            prog_bar_length = 10
            prog_filled = int(prog_bar_length * progress_percent / 100)
            prog_bar = "█" * prog_filled + "░" * (prog_bar_length - prog_filled)
            description += f"{prog_bar} ({progress_percent:.1f}%)\n"
        
        description += "\n"
    
    total_possible = sum(a["points"] for a in data["achievement_defs"][ctx.guild_id] if not a["secret"])
    user_points = calculate_total_points_from_achievements(user_achievements, ctx.guild_id)
    # create embed
    embed = Embed(
        title=f"{target.display_name}'s Achievements",
        description=description,
        color=custom_hash(target.id)
    )
    embed.set_footer(text=f"Points: {user_points}/{total_possible}")
    
    # set thumbnail to user's avatar
    if target.avatar:
        embed.set_thumbnail(url=target.display_avatar.url)
    
    await ctx.response.send_message(embed=embed, ephemeral=ephemeral)

@achievement_commands.command(name="progress", description="View your progress toward achievements")
@app_commands.describe(
    user="The user to view progress for (leave blank for yourself)"
)
async def achievement_progress(ctx: Interaction, user: Member = None):
    target = user or ctx.user
    
    init_achievement_progress(ctx.guild_id, target.id)
    progress = data["achievement_progress"][ctx.guild_id][target.id]
    
    embed = Embed(
        title=f"{target.display_name}'s Achievement Progress",
        color=custom_hash(target.id)
    )
    
    embed.add_field(
        name="Messages Sent",
        value=f"**{progress['messages_sent']:,}**",
        inline=True
    )
    
    embed.add_field(
        name="Reactions Added",
        value=f"**{progress['reactions_added']:,}**",
        inline=True
    )
    
    embed.add_field(
        name="Voice Minutes",
        value=f"**{float(progress['voice_minutes']):,.1f}**",
        inline=True
    )
    
    # show progress toward next achievements
    if ctx.guild_id in data["achievement_defs"]:
        next_achievements = []
        
        for ach_def in data["achievement_defs"][ctx.guild_id]:
            if ach_def.get("type") != "automated" or ach_def.get("secret"):
                continue
            
            if has_achievement(ctx.guild_id, target.id, ach_def["id"]):
                continue
            
            trigger = ach_def.get("trigger", {})
            trigger_type = trigger.get("type")
            
            if trigger_type == "messages":
                current = progress["messages_sent"]
                required = trigger.get("count", 0)
                if current < required:
                    next_achievements.append({
                        "name": ach_def["name"],
                        "icon": ach_def["icon"],
                        "progress": f"{current:,}/{required:,}",
                        "percent": (current / required * 100) if required > 0 else 0
                    })
            
            elif trigger_type == "reactions":
                current = progress["reactions_added"]
                required = trigger.get("count", 0)
                if current < required:
                    next_achievements.append({
                        "name": ach_def["name"],
                        "icon": ach_def["icon"],
                        "progress": f"{current:,}/{required:,}",
                        "percent": (current / required * 100) if required > 0 else 0
                    })
            
            elif trigger_type == "voice_minutes":
                current = progress["voice_minutes"]
                required = trigger.get("minutes", 0)
                if current < required:
                    next_achievements.append({
                        "name": ach_def["name"],
                        "icon": ach_def["icon"],
                        "progress": f"{current:,.1f}/{required:,} min",
                        "percent": (current / required * 100) if required > 0 else 0
                    })
            
            elif trigger.get("count") != None:
                current = progress.get("a_" + ach_def["id"])
                required = trigger.get("count", 0)
                if current != None and current < required:
                    next_achievements.append({
                        "name": ach_def["name"],
                        "icon": ach_def["icon"],
                        "progress": f"{current:,}/{required:,}",
                        "percent": (current / required * 100) if required > 0 else 0
                    })
        
        # sort by completion percentage
        next_achievements.sort(key=lambda x: x["percent"], reverse=True)
        
        if next_achievements[:5]:
            progress_text = ""
            for ach in next_achievements[:5]:
                bar_length = 10
                filled = int(bar_length * ach["percent"] / 100)
                bar = "█" * filled + "░" * (bar_length - filled)
                progress_text += f"{ach['icon']} **{ach['name']}**\n{bar} {ach['progress']} ({ach['percent']:.1f}%)\n\n"
            
            embed.add_field(
                name="Next Achievements",
                value=progress_text,
                inline=False
            )
    
    await ctx.response.send_message(embed=embed)

@achievement_commands.command(name="stats", description="View server-wide achievement statistics")
@app_commands.describe(
    achievement_id="View completion stats for a specific achievement"
)
async def achievement_stats(ctx: Interaction, achievement_id: str = None):
    if achievement_id:
        # show stats for specific achievement
        ach_def = get_achievement_def(ctx.guild_id, achievement_id)
        if not ach_def:
            await ctx.response.send_message(f"Achievement `{achievement_id}` not found.", ephemeral=True)
            return
        
        completed, total = get_achievement_completion_stats(ctx.guild_id, achievement_id)
        percentage = (completed / total * 100) if total > 0 else 0
        
        desc = ach_def.get("description")
        if desc == None and ach_def.get("type") == "automated":
            desc = get_description(ach_def.get("trigger"), ctx.guild_id)

        embed = Embed(
            title=f"{ach_def['icon']} {ach_def['name']}",
            description=desc,
            color=RARITY_COLORS.get(ach_def.get("rarity", "COMMON"))
        )
        
        embed.add_field(name="Rarity", value=f"{RARITY_EMOJI.get(ach_def.get('rarity', 'COMMON'))} {ach_def.get('rarity', 'COMMON')}", inline=True) \
            .add_field(name="Points", value=str(ach_def["points"]), inline=True) \
            .add_field(name="Type", value=ach_def.get("type", "manual").title(), inline=True)
        
        bar_length = 20
        filled = int(bar_length * percentage / 100)
        bar = "█" * filled + "░" * (bar_length - filled)
        
        embed.add_field(
            name="Server Completion",
            value=f"{bar}\n{completed}/{total} users ({percentage:.1f}%)",
            inline=False
        )
        
        await ctx.response.send_message(embed=embed)
    else:
        # show overall server stats
        if ctx.guild_id not in data["achievement_defs"] or not data["achievement_defs"][ctx.guild_id]:
            await ctx.response.send_message("This server has no achievements yet!", ephemeral=True)
            return
        
        embed = Embed(
            title=f"{ctx.guild.name} Achievement Statistics",
            color=0x3498DB
        )
        
        total_achievements = len(data["achievement_defs"][ctx.guild_id])
        total_points = sum(a["points"] for a in data["achievement_defs"][ctx.guild_id])
        
        # count by rarity
        rarity_counts = {}
        for ach in data["achievement_defs"][ctx.guild_id]:
            rarity = ach.get("rarity", "COMMON")
            rarity_counts[rarity] = rarity_counts.get(rarity, 0) + 1
        
        rarity_text = "\n".join(f"{RARITY_EMOJI[r]} {r}: {count}" 
                                for r, count in sorted(rarity_counts.items(), 
                                                       key=lambda x: list(RARITY_COLORS.keys()).index(x[0])))
        
        embed.add_field(name="Total Achievements", value=str(total_achievements), inline=True) \
            .add_field(name="Total Points Available", value=f"{total_points:,}", inline=True) \
            .add_field(name="Rarity Breakdown", value=rarity_text, inline=False)
        
        # most completed achievements
        if ctx.guild_id in data["achievements"]:
            completion_counts = {}
            for ach_def in data["achievement_defs"][ctx.guild_id]:
                completed, total = get_achievement_completion_stats(ctx.guild_id, ach_def["id"])
                if total > 0:
                    completion_counts[ach_def["id"]] = (completed, total, ach_def)
            
            if completion_counts:
                sorted_completions = sorted(completion_counts.items(), 
                                          key=lambda x: (x[1][0] / x[1][1], x[1][0]), 
                                          reverse=True)[:5]
                
                most_completed = "\n".join(
                    f"{ach_def['icon']} **{ach_def['name']}**: {completed}/{total} ({completed/total*100:.1f}%)"
                    for _, (completed, total, ach_def) in sorted_completions
                )
                
                embed.add_field(name="Most Completed", value=most_completed, inline=False)
        
        await ctx.response.send_message(embed=embed)

@achievement_commands.command(name="leaderboard", description="View the achievement leaderboard")
@app_commands.describe(
    top="Number of users to show (default: 10)"
)
async def achievement_leaderboard(ctx: Interaction, top: int = 10):
    if ctx.guild_id not in data["achievements"]:
        await ctx.response.send_message("No one has earned any achievements yet!")
        return
    
    await ctx.response.defer()

    # calculate points for all users
    leaderboard = []
    for user_id, achievements in data["achievements"][ctx.guild_id].items():
        member = ctx.guild.get_member(user_id)
        if member:
            points = calculate_total_points(ctx.guild_id, user_id)
            leaderboard.append({
                "member": member,
                "points": points,
                "count": len(achievements)
            })
    
    if not leaderboard:
        await ctx.followup.send("No one has earned any achievements yet!")
        return
    
    leaderboard.sort(key=lambda x: (x["points"], x["count"]), reverse=True)
    
    embed = Embed(
        title=f"Achievement Leaderboard",
        color=0xFFD700
    )
    
    medals = ["🥇", "🥈", "🥉"]
    
    for i, entry in enumerate(leaderboard[:top]):
        rank = i + 1
        medal = medals[i] if i < 3 else f"**{rank}.**"
        
        embed.add_field(
            name=f"{medal} {entry['member'].display_name}",
            value=f"Points: `{entry['points']:,}` | Achievements: `{entry['count']}`",
            inline=False
        )
    
    await ctx.followup.send(embed=embed)

@achievement_commands.command(name="delete", description="Delete an achievement definition")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    achievement_id="The ID of the achievement to delete",
    keep_progress="Keep user progress (don't revoke from users)"
)
async def achievement_delete(ctx: Interaction, achievement_id: str, keep_progress: bool = False):
    if not ctx.user.guild_permissions.manage_guild:
        await ctx.response.send_message("You need Manage Server permission to delete achievements.")
        return
    
    ach_def = get_achievement_def(ctx.guild_id, achievement_id)
    if not ach_def:
        await ctx.response.send_message(f"Achievement with ID `{achievement_id}` not found.", ephemeral=True)
        return
    
    # remove from definitions
    data["achievement_defs"][ctx.guild_id] = [
        a for a in data["achievement_defs"][ctx.guild_id] if a["id"] != achievement_id
    ]
    
    # optionally remove from all users
    revoked_count = 0
    if not keep_progress:
        if ctx.guild_id in data["achievements"]:
            for user_id in data["achievements"][ctx.guild_id]:
                if user_id == "channel":
                    continue
                if achievement_id in data["achievements"][ctx.guild_id][user_id]:
                    del data["achievements"][ctx.guild_id][user_id][achievement_id]
                    revoked_count += 1
        if ctx.guild_id in data["achievement_progress"]:
            for user_id in data["achievement_progress"][ctx.guild_id]:
                if "a_" + ach_def["id"] in data["achievement_progress"][ctx.guild_id][user_id]:
                    del data["achievement_progress"][ctx.guild_id][user_id]["a_" + ach_def["id"]]
    
    contore_save()
    
    msg = f"Deleted achievement **{ach_def['name']}**."
    if not keep_progress:
        msg += f" Revoked from {revoked_count} user(s)."
    
    await ctx.response.send_message(msg)

@achievement_commands.command(name="edit", description="Edit an achievement's properties")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    achievement_id="The ID of the achievement to edit",
    name="New name (leave blank to keep current)",
    description="New description (leave blank to keep current)",
    type="New type (leave blank to keep current)",
    icon="New icon (leave blank to keep current)",
    points="New point value (leave blank to keep current)",
    rarity="New rarity (leave blank to keep current)",
    secret="Change secret status (leave blank to keep current)"
)
async def achievement_edit(
    ctx: Interaction,
    achievement_id: str,
    name: str = None,
    description: str = None,
    type: Literal["Manual", "Automated"] = None,
    icon: str = None,
    points: int = None,
    rarity: Literal["COMMON", "UNCOMMON", "RARE", "EPIC", "LEGENDARY", "MYTHIC"] = None,
    secret: bool = None
):
    if not ctx.user.guild_permissions.manage_guild:
        await ctx.response.send_message("You need the `Manage Server` permission to edit achievements.")
        return
    
    ach_def = get_achievement_def(ctx.guild_id, achievement_id)
    if not ach_def:
        await ctx.response.send_message(f"Achievement with ID `{achievement_id}` not found.", ephemeral=True)
        return
    
    if name:
        ach_def["name"] = name
    if description:
        ach_def["description"] = description
    if type:
        ach_def["type"] = type.lower()
    if icon:
        ach_def["icon"] = icon
    if points is not None:
        ach_def["points"] = points
    if rarity:
        ach_def["rarity"] = rarity
    if secret is not None:
        ach_def["secret"] = secret
    
    contore_save()
    
    desc = ach_def.get("description")
    if desc == None and type == "automated":
        desc = get_description(ach_def.get("trigger"), ctx.guild_id)
    
    current_rarity = ach_def.get("rarity", "COMMON")
    embed = Embed(title="Achievement Updated", color=RARITY_COLORS[current_rarity]) \
        .add_field(name="ID", value=f"`{achievement_id}`", inline=False) \
        .add_field(name="Name", value=f"{ach_def['icon']} {ach_def['name']}", inline=True) \
        .add_field(name="Type", value=ach_def["type"], inline=True) \
        .add_field(name="Rarity", value=f"{RARITY_EMOJI[current_rarity]} {current_rarity}", inline=True) \
        .add_field(name="Points", value=str(ach_def["points"]), inline=True) \
        .add_field(name="Secret", value="Yes!" if ach_def["secret"] else "No", inline=True)
    if desc != None:
        embed.add_field(name="Description", value=desc, inline=False)
    
    await ctx.response.send_message(embed=embed)

@achievement_commands.command(name="bulkimport", description="Import pre-configured achievements")
@app_commands.default_permissions(manage_guild=True)
@app_commands.describe(
    preset="Choose a preset achievement pack"
)
async def achievement_bulkimport(
    ctx: Interaction,
    preset: Literal["Engagement Pack", "Role-Based Pack", "Voice Activity Pack"]
):
    if not ctx.user.guild_permissions.manage_guild:
        await ctx.response.send_message("You need the `Manage Server` permission to bulk import achievements.", ephemeral=True)
        return
    
    if ctx.guild_id not in data["achievement_defs"]:
        data["achievement_defs"][ctx.guild_id] = []
    
    achievements_to_add = []
    
    if preset == "Engagement Pack":
        achievements_to_add = [
            {"id": "casual_typer", "name": "Casual Typer", "icon": "📝", "points": 10, "rarity": "COMMON", "type": "automated", "trigger": {"type": "messages", "count": 100}},
            {"id": "yapper_aspirant", "name": "Yapper Aspirant", "icon": "⌨️", "points": 25, "rarity": "RARE", "type": "automated", "trigger": {"type": "messages", "count": 1000}},
            {"id": "seasoned_chatter", "name": "Seasoned Chatter", "icon": "💎", "points": 50, "rarity": "EPIC", "type": "automated", "trigger": {"type": "messages", "count": 5000}},
            {"id": "spam_sovereign", "name": "Spam Sovereign", "icon": "👑", "points": 100, "rarity": "LEGENDARY", "type": "automated", "trigger": {"type": "messages", "count": 10000}},
            {"id": "professional_yapper", "name": "Professional Yapper", "icon": "🗣️", "points": 200, "rarity": "MYTHIC", "type": "automated", "trigger": {"type": "messages", "count": 100000}},
            {"id": "give_or_take", "name": "Give or Take", "icon": "👍", "points": 10, "rarity": "COMMON", "type": "automated", "trigger": {"type": "reactions", "count": 10}},
            {"id": "true_star", "name": "True Star", "icon": "⭐", "points": 25, "rarity": "UNCOMMON", "type": "automated", "trigger": {"type": "reactions", "count": 100}},
            {"id": "mmm_im_lovin_it", "name": "Mmm I'm Lovin' It", "icon": "🍔", "points": 50, "rarity": "EPIC", "type": "automated", "trigger": {"type": "reactions", "count": 500}},
            {"id": "this_girl_is_on_fire", "name": "This Girl Is On Fire", "icon": "🔥", "points": 100, "rarity": "LEGENDARY", "type": "automated", "trigger": {"type": "reactions", "count": 1000}},
        ]
    
    elif preset == "Voice Activity Pack":
        achievements_to_add = [
            {"id": "still_shy", "name": "Still Shy", "icon": "🤫", "points": 5, "rarity": "COMMON", "type": "automated", "trigger": {"type": "voice_minutes", "minutes": 10}},
            {"id": "chatty", "name": "Chatty", "icon": "🎶", "points": 15, "rarity": "UNCOMMON", "type": "automated", "trigger": {"type": "voice_minutes", "minutes": 60}},
            {"id": "stay_awhile_and_listen", "name": "Stay Awhile and Listen", "icon": "🎧", "points": 25, "rarity": "RARE", "type": "automated", "trigger": {"type": "voice_minutes", "minutes": 180}},
            {"id": "all_nighter", "name": "All Nighter", "icon": "🌙", "points": 50, "rarity": "EPIC", "type": "automated", "trigger": {"type": "voice_minutes", "minutes": 720}},
            {"id": "who_needs_sleep", "name": "Who Needs Sleep?", "icon": "☕", "points": 100, "rarity": "LEGENDARY", "type": "automated", "trigger": {"type": "voice_minutes", "minutes": 1440}},
        ]
    
    elif preset == "Role-Based Pack":
        await ctx.response.send_message(
            "Role-based achievements need to be configured manually. Use `/achievement create` and `/achievement setautomation` with your specific role IDs.\n\n"
            "Example achievements:\n"
            "- Birthday role achievement\n"
            "- Special position roles\n"
            "- Tier/level roles\n"
            "- Custom server roles",
            ephemeral=True
        )
        return
    
    added_count = 0
    skipped = []
    
    for ach in achievements_to_add:
        if not get_achievement_def(ctx.guild_id, ach["id"]):
            ach["secret"] = False
            ach["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")
            data["achievement_defs"][ctx.guild_id].append(ach)
            added_count += 1
        else:
            skipped.append(ach["name"])
    
    contore_save()
    
    msg = f"Imported {added_count} achievements from **{preset}**!"
    if skipped:
        msg += f"\n\nSkipped (already exist): {', '.join(skipped)}"
    
    await ctx.response.send_message(msg)

ARGS_MATCH = r"^<[aA][rR][gG][sS]>title=['\"](.+)['\"]</[aA][rR][gG][sS]>"

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
            args = re.search(ARGS_MATCH, self.pages[self.current_page])
            
            embed = Embed(title=self.title.replace("{pagenum}", str(self.current_page + 1)).replace("{pagetitle}", args.group(1) if args != None else ""), description=self.pages[self.current_page].replace(args.group(0) if args != None else "{pagetitle}", ""), color=self.color)
            await ctx.response.edit_message(embed=embed, view=self)
        else:
            await ctx.response.defer()

    async def right(self, ctx: Interaction):
        if self.current_page < len(self.pages) - 1:
            self.current_page += 1
            self.update_buttons()
            args = re.search(ARGS_MATCH, self.pages[self.current_page])
            
            embed = Embed(title=self.title.replace("{pagenum}", str(self.current_page + 1)).replace("{pagetitle}", args.group(1) if args != None else ""), description=self.pages[self.current_page].replace(args.group(0) if args != None else "{pagetitle}", ""), color=self.color)
            await ctx.response.edit_message(embed=embed, view=self)
        else:
            await ctx.response.defer()

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

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

def get_highest_role(user: Member):
    return max(user.roles, key=lambda role: role.position)

@ctree.command(name="reposition", description="Moves a role's position in the role heirarchy")
@app_commands.describe(role = "The role to move",
                       places = "The amount of places to move the role by. Leave negative to move the role to the highest possible point")
async def reposition(ctx: Interaction, role: Role, places: int = 9999):
    if not ctx.user.guild_permissions.manage_guild or not ctx.user.guild_permissions.manage_channels or not ctx.user.guild_permissions.manage_nicknames or not ctx.user.guild_permissions.manage_roles or not ctx.user.guild_permissions.ban_members or not ctx.user.guild_permissions.kick_members:
        await ctx.response.send_message(f"you cannot")
        return
    await role.edit(position=min(role.position + places, get_highest_role(ctx.guild.get_member(contore.user.id)).position - 1))
    await ctx.response.send_message(f"Successfully moved {role.mention}'s place.", ephemeral=True)

@auto_commands.command(name="react", description="Automatically adds reactions to messages that match certain criterion")
@app_commands.describe(reaction = "The reaction to add",
                       text_content = "The required text content of the message",
                       images = "The required number of images in the message")
async def autoreact(ctx: Interaction, reaction: str, text_content: str = "", images: int = 0):
    if not ctx.user.guild_permissions.manage_guild or not ctx.user.guild_permissions.manage_channels or not ctx.user.guild_permissions.manage_nicknames or not ctx.user.guild_permissions.manage_roles or not ctx.user.guild_permissions.ban_members or not ctx.user.guild_permissions.kick_members:
        await ctx.response.send_message(f"you cannot")
        return

    data["autoreactions"][ctx.guild_id] = {
        "reaction": reaction,
        "text_content": text_content,
        "images": images
    }

    contore_save()
    await ctx.response.send_message(f"Successfully added autoreact to {ctx.guild.name}.\nReaction: {reaction}\nText content: {text_content}\nImages: {images}", ephemeral=True)

@ctree.command(name="data", description="Dumps the bot's data into a JSON file and sends it.")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def dump_data(ctx: Interaction):
    json_str = json.dumps(data, indent=4, default=encode_sets)
    file_bytes = BytesIO(json_str.encode('utf-8'))
    file = File(file_bytes, filename="data.json")
    await ctx.response.send_message("Here's the data dump:", file=file)

@ctree.command(name="update", description="Provide an update to the bot's code")
@app_commands.describe(program = "The updated version of the program")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def update(ctx: Interaction, program: Attachment):
    if ctx.user.id == contore_config["owner_id"] and program.filename.endswith(".py"):
        path = __file__.replace("\\", "/")
        await ctx.response.send_message("Updating and restarting...", ephemeral=True)
        await program.save(path.split("/")[-1])
        print("Opening updated file...", end="\n\n")
        if sys.platform.startswith("win"):
            subprocess.Popen(f"start python -c \"from time import sleep; from subprocess import run; sleep(5); run('python \\\"{path.split('/')[-1]}\\\"')\"", shell=True)
        else:
            os.system(f"lxterminal --title='Discord Server.py' -e \"source venv/bin/activate; python './{path.split('/')[-1]}'\"")
        await contore.close()
        sys.exit()
    else:
        await ctx.response.send_message("nuh")
        
@ctree.command(name="open", description="Downloads a file to the server and opens it")
@app_commands.describe(program = "The Python program")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def open_python(ctx: Interaction, program: Attachment):
    if ctx.user.id == contore_config["owner_id"] and program.filename.endswith(".py") and program.filename != __file__.replace("\\", "/").split("/")[-1]:
        await ctx.response.send_message("Starting new file...", ephemeral=True)
        await program.save(program.filename)
        if sys.platform.startswith("win"):
            subprocess.Popen(f"start python -c \"from time import sleep; from subprocess import run; sleep(5); run('python \\\"{program.filename}\\\"')\"", shell=True)
        else:
            os.system(f"lxterminal --title=\"{program.filename}\" -e \"source venv/bin/activate; python './{program.filename}'\"")
    else:
        await ctx.response.send_message("nuh")
        
@ctree.command(name="install", description="Installs a Python package onto root")
@app_commands.describe(package = "The package name")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def install(ctx: Interaction, package: str):
    if ctx.user.id == contore_config["owner_id"]:
        await ctx.response.defer(ephemeral=True)
        try:
            if sys.platform.startswith("win"):
                subprocess.Popen(f"pip install {package}", shell=True)
            else:
                os.system(f"pip install {package}")
            await ctx.followup.send(f"Installation success.")
        except Exception as e:
            await ctx.followup.send(f"Installation failed: {e}")
    else:
        await ctx.response.send_message("nuh")

@ctree.command(name="stop", description="Kills Contore")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def stop(ctx: Interaction):
    if ctx.user.id == contore_config["owner_id"]:
        await ctx.response.send_message("Exiting...", ephemeral=True)
        await contore.close()
        sys.exit()
    else:
        await ctx.response.send_message("nuh")

@ctree.command(name="terminate", description="Stops all other bots")
@app_commands.guilds(1225102857431420988)
@app_commands.default_permissions(perms)
@is_owner()
async def reboot(ctx: Interaction):
    if ctx.user.id == contore_config["owner_id"]:
        await ctx.response.send_message("starting reboot")
        try:
            current_pid = os.getpid()
            await ctx.channel.send(f"pid: {current_pid}")
            if os.name == 'nt': # Windows
                terminal_names = ["cmd.exe", "powershell.exe", "pwsh.exe"]
                await ctx.channel.send(f"windows")
            else: # Linux/Unix-like
                terminal_names = ["python", "bash", "sh", "zsh", "fish", "xterm", "gnome-terminal-server", "konsole"]
                await ctx.channel.send(f"linux")

            for process in psutil.process_iter(attrs=["pid", "name"]):
                try:
                    process_info = process.info
                    pid = process_info["pid"]
                    name = process_info["name"]

                    if pid != current_pid and name in terminal_names:
                        await ctx.channel.send(f"got process: {pid} | {name}")
                        await ctx.channel.send(f"Terminating process: {name} (PID: {pid})")
                        process.terminate() # Send terminate signal
                        process.wait(timeout=5) # Wait for process to terminate
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired):
                    await ctx.channel.send(f"couldnt terminate process: {name} (PID: {pid})")
                    continue
        except BaseException as e:
            await ctx.response.send_message(str(e))
    else:
        await ctx.response.send_message("nuh")

def format_text(content: str):
    return re.sub(r"\s{2,}", " ", re.sub(r" ?<@!?\d+> ?", "", content.lower()))

async def add_role(user: Member, *roles: Snowflake, take: bool, time: float):
    if not take:
        await user.add_roles(*roles)
    else:
        await user.remove_roles(*roles)
    if time > 0:
        await asyncio.sleep(time)
        if not take:
            await user.remove_roles(*roles)
        else:
            await user.add_roles(*roles)

@contore.event
async def on_message(message: Message):
    if message.guild == None:
        return
    check_message_achievements(message)
    if message.author.id == contore.user.id:
        # sender of the message is contore
        return
    if message.guild.id not in data["roles_on_messages"] and message.guild.id not in data["autoreactions"] and message.guild.id not in data["achievement_defs"]:
        return
    for i, criteria in enumerate(data["roles_on_messages"].get(message.guild.id, {})):
        if criteria.get("content", None) == None or criteria.get("type", None) == None or criteria.get("role", None) == None or criteria.get("authorization_type", None) == None:
            continue
        role = message.guild.get_role(criteria["role"])
        authorization = "" if criteria["authorization_type"] not in ["Specified User", "Specified Role"] else message.guild.get_role(criteria.get("authorization", 0)) if criteria["authorization_type"] == "Specified Role" else message.guild.get_member(criteria.get("authorization", 0))
        if role == None or authorization == None:
            try:
                data["roles_on_messages"][message.guild.id].remove(criteria)
                contore_save()
            except ValueError:
                try:
                    data["roles_on_messages"][message.guild.id].pop(i)
                    contore_save()
                except IndexError:
                    pass
            continue
        if ((criteria.get("sub_match", False) and format_text(criteria["content"]) in format_text(message.content)) or format_text(criteria["content"]) == format_text(message.content)) and ((criteria["authorization_type"] == "Alfred" and message.author.id == contore_config["owner_id"]) or (criteria["authorization_type"] == "Administrators" and message.author.guild_permissions.administrator) or (criteria["authorization_type"] == "Specific Role" and message.author.get_role(criteria.get("authorization", 0)) != None) or (criteria["authorization_type"] == "Specific User" and user.id == criteria.get("authorization", 0)) or criteria["authorization_type"] == "Everyone"):
            if criteria["type"] == "Self":
                await add_role(message.author, role, take=criteria.get("take", False), time=criteria.get("time_limit", -1))
            elif criteria["type"] == "Specific User" and message.guild.get_member(criteria.get("type_user", 0)) != None:
                await add_role(message.guild.get_member(criteria.get("type_user", 0)), role, take=criteria.get("take", False), time=criteria.get("time_limit", -1))
            else:
                if message.mention_everyone:
                    for member in message.guild.members:
                        await add_role(member, role, take=criteria.get("take", False), time=criteria.get("time_limit", -1))
                else:
                    for role in message.role_mentions:
                        for member in role.members:
                            await add_role(member, role, take=criteria.get("take", False), time=criteria.get("time_limit", -1))
                    for user in message.mentions:
                        if isinstance(user, Member):
                            await add_role(user, role, take=criteria.get("take", False), time=criteria.get("time_limit", -1))

    for criteria in data["autoreactions"].get(message.guild.id, []):
        if criteria.get("reaction", None) == None or criteria.get("text_content", None) == None or criteria.get("images", None) == None:
            continue
        images = 0
        for att in message.attachments:
            if att.content_type.startswith("image/"):
                images += 1
        if criteria["text_content"] in message.content and images == criteria["images"]:
            await message.add_reaction(criteria["reaction"])
    
    # track message for achievements
    update_progress(message.guild.id, message.author.id, "messages_sent", 1)
    check_automated_achievements(message.guild.id, message.author.id, message.channel)

@contore.event
async def on_raw_reaction_add(payload: RawReactionActionEvent):
    if payload.guild_id:
        update_progress(payload.guild_id, payload.user_id, "reactions_added", 1)
        channel = contore.get_channel(payload.channel_id) or (await contore.fetch_channel(payload.channel_id))
        check_automated_achievements(payload.guild_id, payload.user_id, channel)

@contore.event
async def on_member_update(before: Member, after: Member):
    if before.roles != after.roles:
        new_roles = set(after.roles) - set(before.roles)
        if new_roles:
            check_automated_achievements(after.guild.id, after.id, roles=new_roles)

@contore.event
async def on_voice_state_update(member: Member, before, after):
    guild_id = member.guild.id
    user_id = member.id
    
    if guild_id not in voice_tracking:
        voice_tracking[guild_id] = {}
    
    # user joined a voice channel
    if before.channel is None and after.channel is not None:
        voice_tracking[guild_id][user_id] = datetime.now()
    
    # user left a voice channel
    elif before.channel is not None and after.channel is None:
        if user_id in voice_tracking[guild_id]:
            join_time = voice_tracking[guild_id][user_id]
            duration = (datetime.now() - join_time).total_seconds() / 60 # minutes
            update_progress(guild_id, user_id, "voice_minutes", duration)
            check_automated_achievements(guild_id, user_id)
            del voice_tracking[guild_id][user_id]

@contore.event
async def on_member_join(member: Member):
    if member.guild.id not in data["auto_roles"]:
        return
    if member.id not in data["auto_roles"][member.guild.id]:
        return
    for role_id in data["auto_roles"][member.guild.id]["everyone"]:
        if role_id != None:
            await member.add_roles(member.guild.get_role(role_id))
    if member.id in data["auto_roles"][member.guild.id]:
        for i, role_id in enumerate(data["auto_roles"][member.guild.id][member.id]):
            if role_id != None:
                await member.add_roles(member.guild.get_role(role_id))

birthdays_sent = []

@tasks.loop(seconds=10)
async def check_scheduled_roles():
    now = datetime.now()

    for guild_id, schedules in data["scheduled_roles"].items():
        guild = contore.get_guild(guild_id)

        for schedule in schedules[:]:
            role = guild.get_role(schedule["role_id"])
            user = guild.get_member(schedule["user_id"])

            if not role or not user:
                schedules.remove(schedule)
                contore_save()
                continue

            apply_role = False
            if schedule["type"] == "one-time" and "target_date" in schedule:
                if now.year == schedule["target_date"][0] and now.month == schedule["target_date"][1] and now.day == schedule["target_date"][2]:
                    apply_role = True

            elif schedule["type"] == "yearly-month" and "target_month" in schedule:
                if now.year == schedule["target_month"][0] and now.month == schedule["target_month"][1]:
                    apply_role = True

            elif schedule["type"] == "yearly" and "target_year" in schedule:
                if now.year == schedule["target_year"]:
                    apply_role = True

            elif schedule["type"] == "annual":
                month, day = map(int, schedule["date_pattern"].split("-"))
                if now.month == month and now.day == day:
                    apply_role = True

            elif schedule["type"] == "monthly":
                if now.month == int(schedule["date_pattern"]):
                    apply_role = True

            elif schedule["type"] == "monthly-day":
                if now.day == int(schedule["date_pattern"]):
                    apply_role = True

            if apply_role and "assigned_at" not in schedule:
                await user.add_roles(role)
                schedule["assigned_at"] = now
                contore_save()

            if schedule.get("assigned_at") and schedule["duration"]:
                elapsed_time = (now - schedule["assigned_at"]).total_seconds() / 3600
                if elapsed_time >= schedule["duration"]:
                    await user.remove_roles(role)
                    if schedule["type"] in ["one-time", "yearly", "yearly-month"]:
                        schedules.remove(schedule)
                        contore_save()
    
    for guild in contore.guilds:
        birthday_role_id, birthday_channel_id = data["birthday_data"].get(guild.id, (-1, -1))
        if birthday_role_id != -1 or birthday_channel_id != -1:
            birthday_role = guild.get_role(birthday_role_id)
            birthday_channel = guild.get_channel_or_thread(birthday_channel_id)
            for user_id, birthday_info in data["birthdays"].items():
                member = guild.get_member(user_id)
                if not member:
                    continue
                birth_date = datetime.strptime(birthday_info if not birthday_info.startswith("0000-") else birthday_info[5:], "%Y-%m-%d" if not birthday_info.startswith("0000-") else "%m-%d")
                is_today = birth_date.day == now.day and birth_date.month == now.month

                if birthday_role:
                    has_role = birthday_role in member.roles

                    if is_today and not has_role:
                        await member.add_roles(birthday_role)
                    elif not is_today and has_role:
                        await member.remove_roles(birthday_role)

                if birthday_channel:
                    if is_today and not (user_id, birthday_channel_id) in birthdays_sent:
                        await birthday_channel.send(f"Happy birthday, {member.mention}! 🎂🎉")
                        birthdays_sent.append((user_id, birthday_channel_id))
                    elif not is_today and (user_id, birthday_channel_id) in birthdays_sent:
                        birthdays_sent.remove((user_id, birthday_channel_id))

def format_message(template: str, member: Member, inviter: Member=None, invite=None):
    replacements = {
        "\${user_id}": str(member.id),
        "\${user_username}": member.name,
        "\${user_display}": member.display_name,
        "\${user_global}": member.global_name if member.global_name else "n/a",
        "\${user_nick}": member.nick if member.nick else "n/a",
        "\${user_mention}": member.mention,
        "\${user_created_date}": format_dt(member.created_at),
        "\${user_joined_date}": format_dt(member.joined_at) if member.joined_at else "Unknown",
        "\${user_created_date_rel}": format_dt(member.created_at, style="R"),
        "\${user_joined_date_rel}": format_dt(member.joined_at, style="R") if member.joined_at else "Unknown",

        "\${inviter_id}": str(inviter.id) if inviter else "Unknown",
        "\${inviter_username}": inviter.name if inviter else "Unknown",
        "\${inviter_display}": inviter.display_name if inviter else "Unknown",
        "\${inviter_mention}": inviter.mention if inviter else "Unknown",

        "\${invite_code}": invite.code if invite else "Unknown",
        "\${invite_channel}": invite.channel.mention if invite and invite.channel else "Unknown",
        "\${invite_uses}": str(invite.uses) if invite else "Unknown",

        "\${guild_name}": member.guild.name,
        "\${guild_membercount}": str(member.guild.member_count)
    }

    for key, value in replacements.items():
        template = template.replace(key, value)

    return template

@leave_commands.command(name="variables", description="View a list of variables usable to configure the leave message")
async def leave_variables(ctx: Interaction):
    await ctx.response.send_message("""`user_id` - The ID of the user who left (example: 1038466644353232967)
`user_username` - The username of the user who left (example: alfkli)
`user_display` - The display name of the user who left (example: ALFRED) (recommended to use for names)
`user_global` - The global name of the user who left
`user_nick` - The nickname of the user who left
`user_mention` - The mention of the user who joined (example: <@1038466644353232967>)
`user_created_date` - The date when the user's account was created (example: <t:1522306800>)
`user_joined_date` - The date when the user joined
`user_created_date_rel` - The relative date when the user's account was created (example: <t:1522306800:R>)
`user_joined_date_rel` - The relative date when the user joined
`guild_name` - The name of the server
`guild_membercount` - The total number of members present in the server

**Important**: These variables should be enclosed with **\${}**.""", ephemeral=True)
    
#`inviter_id` - The ID of the inviter
#`inviter_username` - The username of the inviter
#`inviter_display` - The display name of the inviter
#`inviter_mention` - The mention of the inviter
#`invite_code` - The invite code that was used by the user to join
#`invite_channel` - The channel from which the invite code was created
#`invite_uses` - The number of uses the invite code has

@leave_commands.command(name="message", description="Set the configurable leave message")
@app_commands.describe(message="The message template with variables like \${user_mention} (use \\n for new lines)")
async def leave_message(ctx: Interaction, message: str = None, channel: Union[GuildChannel, Thread] = None):
    if ctx.guild_id not in data["leave_msgs"]:
        data["leave_msgs"][ctx.guild_id] = {}
    if message:
        message = message.replace("\\n", "\n")
    data["leave_msgs"][ctx.guild_id]["msg"] = message
    data["leave_msgs"][ctx.guild_id]["chan"] = channel.id if channel else None
    contore_save()
    await ctx.response.send_message("Leave message removed." if message is None or channel is None else f"Leave messages will be sent in: {channel.mention}\nLeave message set to:\n```\n{message}\n```", ephemeral=True)

@leave_commands.command(name="preview", description="Preview the configured leave message")
async def preview_leave(ctx: Interaction):
    leave = data["leave_msgs"].get(ctx.guild_id, {"msg": None, "chan": None})
    if leave["msg"] is not None and leave["chan"] is not None:
        preview = format_message(data["leave_msgs"][ctx.guild_id]["msg"], ctx.user)
        await ctx.response.send_message(preview, ephemeral=True)
    else:
        await ctx.response.send_message("You do not have a leave message configured.", ephemeral=True)

@contore.event
async def on_member_remove(member: Member):
    leave = data["leave_msgs"].get(member.guild.id, {"msg": None, "chan": None})
    if leave["msg"] is not None and leave["chan"] is not None:
        channel = member.guild.get_channel_or_thread(leave["chan"])
        if channel:
            formatted = format_message(leave["msg"], member)
            await channel.send(formatted)

async def format_embed(message: Message, prefix="", color=Color(0x2B2D31)):
    filenames = []
    embeds = []
    embed = Embed(description=message.system_content, color=color, timestamp=message.created_at)
    embed.set_author(name=f"{prefix}{message.author.display_name}{' 🤖' if message.author.bot or message.author.system else ''}", url=message.jump_url, icon_url=message.author.avatar.url)
    if message.attachments:
        for attachment in message.attachments:
            if attachment.content_type.startswith('image/'):
                if getattr(embed, "_image", None) is None:
                    embed.set_image(url=attachment.url)
                else:
                    embeds.append(Embed().set_image(url=attachment.url))
    if message.stickers:
        for sticker in message.stickers:
            if sticker.format is StickerFormatType.apng:
                embed.description += f"\n*Sent a sticker: {sticker.name}*"
            else:
                if getattr(embed, "_image", None) is None:
                    embed.set_image(url=sticker.url)
                else:
                    embeds.append(Embed().set_image(url=sticker.url))
    embeds.append(embed)
    embeds.extend(message.embeds)
    return embeds, filenames

async def copy_attachments(message: Message):
    attachments = []
    if message.attachments:
        for attachment in message.attachments:
            if not attachment.content_type.startswith('image/'):
                async with attachment_retriever as h:
                    response = await h.get(attachment.url)
                    if response.status_code == 200:
                        attachment_bytes = response.read()
                        file = File(BytesIO(attachment_bytes), filename=attachment.filename, spoiler=attachment.is_spoiler(), description=attachment.description)
                        attachments.append(file)
    return attachments

async def format_message_into_embed(message: Message):
    embeds, attachments = [], []
    if message.reference:
        try:
            ref_message = await message.channel.fetch_message(message.reference.message_id)
            ref_embeds, _ = await format_embed(ref_message, prefix="Replying to ")
            embeds.extend(ref_embeds)
            attachments.extend(await copy_attachments(ref_message))
        except NotFound:
            pass
    orig_embeds, _ = await format_embed(message, color=Color(0xEEE2A0))
    embeds.extend(orig_embeds)
    attachments.extend(await copy_attachments(message))
    return embeds, attachments

class QuotePageMessage(View):
    def __init__(self, quotes: list[list[Union[str, int]]], embeds: list[tuple[list[Embed], list[Attachment]]], user_id: int, index: int = 0, timeout: float = None):
        super().__init__(timeout=timeout)
        self.quotes = quotes
        self.embeds = embeds
        self.user_id = user_id
        self.current_page = index
        
        self.all_left_button = Button(label="❮❮", style=ButtonStyle.gray, disabled=index == 0)
        self.left_button = Button(label="❮", style=ButtonStyle.gray, disabled=index == 0)
        self.idx = Button(label=str(index + 1), style=ButtonStyle.gray, disabled=True)
        self.right_button = Button(label="❯", style=ButtonStyle.gray, disabled=len(self.embeds) < 2 or index >= len(self.embeds) - 1 or index == -1)
        self.all_right_button = Button(label="❯❯", style=ButtonStyle.gray, disabled=len(self.embeds) < 2 or index >= len(self.embeds) - 1 or index == -1)
        self.remove_quote_button = Button(label="X", style=ButtonStyle.red)
        self.all_left_button.callback = self.all_left
        self.left_button.callback = self.left
        self.right_button.callback = self.right
        self.all_right_button.callback = self.all_right
        self.remove_quote_button.callback = self.remove_quote
        self.add_item(self.all_left_button)
        self.add_item(self.left_button)
        self.add_item(self.idx)
        self.add_item(self.right_button)
        self.add_item(self.all_right_button)
        self.add_item(self.remove_quote_button)

    async def update_buttons(self, ctx: Interaction):
        self.all_right_button.disabled = self.right_button.disabled = self.current_page >= len(self.embeds) - 1
        self.all_left_button.disabled = self.left_button.disabled = self.current_page - 1 < 0
        self.idx.label = str(self.current_page + 1)
        await ctx.response.defer()
        if self.embeds[self.current_page] is None:
            quot = self.quotes[self.current_page]
            channel = contore.get_channel(quot[2]) or await contore.fetch_channel(quot[2])
            self.embeds[self.current_page] = await format_message_into_embed(await channel.fetch_message(quot[3]))
        await ctx.edit_original_response(embeds=self.embeds[self.current_page][0], attachments=self.embeds[self.current_page][1], view=self)
    
    async def all_left(self, ctx: Interaction):
        self.current_page = 0
        await self.update_buttons(ctx)

    async def left(self, ctx: Interaction):
        if self.current_page >= 1:
            self.current_page -= 1
            await self.update_buttons(ctx)
        else:
            await ctx.response.defer()

    async def right(self, ctx: Interaction):
        if self.current_page < len(self.embeds) - 1:
            self.current_page += 1
            await self.update_buttons(ctx)
        else:
            await ctx.response.defer()
    
    async def all_right(self, ctx: Interaction):
        self.current_page = len(self.embeds) - 1
        await self.update_buttons(ctx)
    
    async def remove_quote(self, ctx: Interaction):
        if ctx.user.id == self.user_id:
            self.quotes.pop(self.current_page)
            self.embeds.pop(self.current_page)
            data["quotes"][self.user_id].pop(self.current_page)
            contore_save()
            self.current_page -= 1
            await self.update_buttons(ctx)
        else:
            await ctx.response.send_message(f"You can't remove quotes from <@{self.user_id}>'s quotebook.", ephemeral=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            item.disabled = True

@quote_commands.command(name="view", description="View your quotes.")
@app_commands.describe(sort = "The sorting method",
                       order = "The direction to sort in",
                       public = "Should the message be ephemeral (only visible to you)?",
                       filter_type = "How should the quotes be filtered",
                       filter = "The value for the filter",
                       index = "The index of the quote to start on")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def quotes_view(ctx: Interaction, sort: Literal["Date Added", "Username (Alphabetical)", "Display Name (Alphabetical)", "Account ID"] = "Date Added", order: Literal["Descending", "Ascending"] = "Ascending", public: bool = False, filter_type: Literal["Before Date", "After Date", "From User", "From Server"] = None, filter: str = None, index: int = 1):
    if ctx.user.id not in data["quotes"]:
        await ctx.response.send_message("You do not have any quotes!", ephemeral=True)
        return
    if index < 1:
        await ctx.response.send_message("Cannot use indices less than 1.", ephemeral=True)
        return
    quotes = data["quotes"][ctx.user.id]
    embeds = [None for _ in quotes]
    quot = quotes[index-1]
    embeds[index-1] = await format_message_into_embed(await (contore.get_channel(quot[2]) or await contore.fetch_channel(quot[2])).fetch_message(quot[3]))
    if order == "Descending":
        quotes.reverse()
        embeds.reverse()
    await ctx.response.send_message(embeds=embeds[index-1][0], files=embeds[index-1][1], view=QuotePageMessage(quotes, embeds, ctx.user.id, index-1), ephemeral=not public)

@ctree.context_menu(name="Quote")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def quote(ctx: Interaction, msg: Message):
    embeds, attachments = await format_message_into_embed(msg)
    await ctx.response.send_message(f"Added {msg.author.mention}'s message to your quotes.", embeds=embeds, files=attachments, ephemeral=True)
    if ctx.user.id not in data["quotes"]:
        data["quotes"][ctx.user.id] = []
    data["quotes"][ctx.user.id].append([msg.author.id, msg.guild.id, msg.channel.id, msg.id, msg.system_content, msg.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"), datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")])
    contore_save()

def exp_falloff_choice(options, falloff_rate=2):
    weights = [1 / (falloff_rate ** i) for i in range(len(options))]
    total = sum(weights)
    normalized_weights = [w / total for w in weights]
    return random.choices(options, weights=normalized_weights, k=1)[0]

@ctree.context_menu(name="Sentiment Analysis")
@app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
async def sentiment_evaluator(ctx: Interaction, msg: Message):
    await ctx.response.defer()
    result = classifier(msg.system_content, **tokenizer_kwargs)[0]
    await ctx.followup.send(f"`{exp_falloff_choice(sorted(result, key=lambda x: x['score']))['label'].capitalize()}` ({(result[0]['score'] + random.uniform(-0.05, 0.05)) * 100:.2f}%)")

async def change_status_periodically(client: Client, statuses: list, status_update: list):
    await client.wait_until_ready()
    while not client.is_closed():
        new_status = random.choice(statuses)
        try:
            await client.change_presence(activity=Activity(name="custom", state=new_status, type=ActivityType.custom))
        except:
            pass
        wait_time = random.randint(status_update[0], status_update[1])
        await asyncio.sleep(wait_time)

@contore.event
async def on_guild_join(guild: Guild):
    # contore got added to a discord server
    if guild.id not in data["auto_roles"]:
        data["auto_roles"][guild.id] = { "everyone": [None] }
    if guild.id not in data["roles_on_messages"]:
        data["roles_on_messages"][guild.id] = [ ]
    if guild.id not in data["autoreactions"]:
        data["autoreactions"][guild.id] = [ ]
    if guild.id not in data["scheduled_roles"]:
        data["scheduled_roles"][guild.id] = [ ]
    if guild.id not in data["leave_msgs"]:
        data["leave_msgs"][guild.id] = { }
    if guild.id not in data["achievements"]:
        data["achievements"][guild.id] = { }
    if guild.id not in data["achievement_defs"]:
        data["achievement_defs"][guild.id] = { }
    if guild.id not in data["achievement_progress"]:
        data["achievement_progress"][guild.id] = { }
    contore_save()

@contore.event
async def on_ready():
    check_scheduled_roles.start()
    ctree.add_command(auto_commands)
    ctree.add_command(message_commands)
    ctree.add_command(reset_commands)
    ctree.add_command(date_commands)
    ctree.add_command(birthday_commands)
    ctree.add_command(quote_commands)
    ctree.add_command(family_commands)
    ctree.add_command(leave_commands)
    ctree.add_command(restriction_commands)
    ctree.add_command(achievement_commands)
    await ctree.sync()
    print(f"{contore.user.display_name} has connected to Discord!")
    await contore.loop.create_task(change_status_periodically(contore, [
        "status 1",
        "status 2",
        "..."
    ], [600, 3600]))

def convert_keys_to_ints(d):
    if isinstance(d, dict):
        new_dict = {}
        for key, value in d.items():
            try:
                int_key = int(key)
            except (ValueError, TypeError):
                int_key = key
            
            new_dict[int_key] = convert_keys_to_ints(value)
        return new_dict
    else:
        return d

with open("data/config.ccfg", "r") as f:
    contore_config = json.load(f)
with open("data/data.cont", "r") as f:
    jdata = convert_keys_to_ints(json.load(f, object_hook=decode_sets)) # ints are more performant
    for key, value in jdata.items():
        data[key] = value
    del jdata

contore.run("DISCORD_BOT_TOKEN")