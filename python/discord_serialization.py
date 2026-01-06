# A utility program that converts all Discord.py objects into pure JSON.
# Used by the Eternalizer to download Discord servers locally.

from collections.abc import AsyncIterator
from unicodedata import category
from discord import User, Member, Role, RoleTags, ScheduledEvent, Reaction, ForumTag, Asset, MessageFlags, Message, CategoryChannel, TextChannel, VoiceChannel, StageChannel, ForumChannel, Thread, Guild, Embed, Emoji, PartialEmoji
from discord.abc import GuildChannel
from inspect import signature, iscoroutinefunction, iscoroutine, Signature
from json import dumps
from typing import Literal

indices = {
    "users": {},
    "roles": {},
    "emojis": {},
    "channels": {},
}

def add_to_index(index_name: Literal["users", "roles", "emojis", "channels"], item_id, item_data):
    if item_id not in indices[index_name]:
        indices[index_name][item_id] = item_data
    return item_id

async def iterate_users(generator: AsyncIterator[User | Member]) -> list[User]:
    users = []
    async for user in generator:
        users.append(user)
    return users

def is_async(func):
    return iscoroutinefunction(func) or iscoroutine(func)

def get_func_args(func):
    try:
        return [param for param in signature(func).parameters.values() if param.default == param.empty]
    except Exception:
        return []

def is_variable(func):
    try:
        return signature(func).return_annotation != Signature.empty
    except Exception:
        return False

def is_json_serializable(variable):
    try:
        dumps(variable)
        return True
    except Exception:
        return False

def serialize_bool_class(bool_class):
    if bool_class == None: return None
    return {key: getattr(bool_class, key) for key in dir(bool_class) if not callable(getattr(bool_class, key)) and not key.startswith("_") and isinstance(getattr(bool_class, key), bool)}

def serialize_iterable(iterable):
    if iterable == None: return None
    return {key: value for key, value in iter(iterable)}

def serialize_role_tags(role_tags: RoleTags):
    if not isinstance(role_tags, RoleTags): return None
    data = {key: getattr(role_tags, key) for key in dir(role_tags) if not callable(getattr(role_tags, key)) and not key.startswith("_")}
    callables = {key: getattr(role_tags, key)() for key in dir(role_tags) if callable(getattr(role_tags, key)) and not key.startswith("_")}
    return {**data, **callables}

def serialize_asset(asset: Asset):
    if not isinstance(asset, Asset): return None
    return {
        "key": asset.key,
        "url": asset.url
    }

async def serialize_reaction(reaction: Reaction):
    if not isinstance(reaction, Reaction): return None
    emoji = reaction.emoji if isinstance(reaction.emoji, Emoji) else (Emoji(guild=reaction.message.guild, state=reaction.emoji._state, data=reaction.emoji.to_dict()) if reaction.emoji._state != None else reaction.emoji.__repr__()) if isinstance(reaction.emoji, PartialEmoji) else reaction.emoji
    return {
        "count": reaction.count,
        "emoji": add_to_index("emojis", reaction.emoji.id, {
            "animated": emoji.animated,
            "available": emoji.available,
            "created_at": emoji.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "guild_id": emoji.guild_id,
            "name": emoji.name,
            "user": serialize_user(emoji.user) if emoji.user is not None else None
        }) if isinstance(reaction.emoji, (PartialEmoji, Emoji)) else reaction.emoji.__repr__(),
        "users": [serialize_user(user) for user in await iterate_users(reaction.users())]
    }

def serialize_forum_tag(forum_tag: ForumTag):
    if not isinstance(forum_tag, ForumTag): return None
    return {
        "emoji": forum_tag.emoji,
        "id": forum_tag.id,
        "moderated": forum_tag.moderated,
        "name": forum_tag.name
    }

def serialize_message_flags(flags: MessageFlags):
    if not isinstance(flags, MessageFlags): return None
    return {
        "crossposted": flags.crossposted,
        "ephemeral": flags.ephemeral,
        "failed_to_mention_some_roles_in_thread": flags.failed_to_mention_some_roles_in_thread,
        "has_thread": flags.has_thread,
        "is_crossposted": flags.is_crossposted,
        "loading": flags.loading,
        "silent": flags.silent,
        "source_message_deleted": flags.source_message_deleted,
        "suppress_embeds": flags.suppress_embeds,
        "suppress_notifications": flags.suppress_notifications,
        "urgent": flags.urgent,
        "value": flags.value,
        "voice": flags.voice
    }

async def serialize_event(event: ScheduledEvent):
    if not isinstance(event, ScheduledEvent): return None
    return {
        "channel": event.channel.id if event.channel is not None else None,
        "channel_name": event.channel.name if event.channel is not None else None,
        "cover_image": serialize_asset(event.cover_image) if event.cover_image is not None else None,
        "creator": serialize_user(event.creator) if event.creator is not None else None,
        "creator_id": event.creator_id,
        "description": event.description,
        "end_time": event.end_time.strftime("%Y-%m-%d %H:%M:%S.%f") if event.end_time is not None else None,
        "entity_id": event.entity_id,
        "entity_type": str(event.entity_type),
        "id": event.id,
        "location": event.location,
        "name": event.name,
        "privacy_level": str(event.privacy_level),
        "start_time": event.start_time.strftime("%Y-%m-%d %H:%M:%S.%f") if event.start_time is not None else None,
        "status": str(event.status),
        "url": event.url,
        "user_count": event.user_count,
        "users": [serialize_user(user) for user in await iterate_users(event.users())]
    }

def serialize_role(role: Role):
    if not isinstance(role, Role): return None
    return add_to_index("roles", role.id, {
        "color": {
            "r": role.color.r,
            "g": role.color.g,
            "b": role.color.b
        },
        "created_at": role.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "display_icon": role.display_icon,
        "hoist": role.hoist,
        "icon": serialize_asset(role.icon),
        "id": role.id,
        "is_assignable": role.is_assignable(),
        "is_bot_managed": role.is_bot_managed(),
        "is_default": role.is_default(),
        "is_integration": role.is_integration(),
        "is_premium_subscriber": role.is_premium_subscriber(),
        "managed": role.managed,
        "members": [serialize_user(user) for user in role.members],
        "mention": role.mention,
        "mentionable": role.mentionable,
        "name": role.name,
        "permissions": serialize_bool_class(role.permissions),
        "position": role.position,
        "tags": serialize_role_tags(role.tags),
        "unicode_emoji": role.unicode_emoji
    })

def serialize_user(user: User | Member):
    if not isinstance(user, (User, Member)): return None
    data = {
        "accent_color": {
            "r": user.accent_color.r,
            "g": user.accent_color.g,
            "b": user.accent_color.b
        } if user.accent_color != None else None,
        "avatar": serialize_asset(user.avatar),
        "banner": serialize_asset(user.banner),
        "bot": user.bot,
        "color": {
            "r": user.color.r,
            "g": user.color.g,
            "b": user.color.b
        },
        "created_at": user.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "default_avatar": serialize_asset(user.default_avatar),
        "discriminator": user.discriminator,
        "display_avatar": serialize_asset(user.display_avatar),
        "display_name": user.display_name,
        "global_name": user.global_name,
        "id": user.id,
        "mention": user.mention,
        "name": user.mention,
        "public_flags": serialize_bool_class(user.public_flags),
        "system": user.system
    }
    if isinstance(user, Member):
        data = dict(sorted({**data,
            "desktop_status": str(user.desktop_status),
            "flags": serialize_bool_class(user.flags),
            "guild_avatar": serialize_asset(user.guild_avatar),
            "guild_permissions": serialize_bool_class(user.guild_permissions),
            "joined_at": user.joined_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "mobile_status": str(user.mobile_status),
            "nick": user.nick,
            "pending": user.pending,
            "premium_since": user.premium_since.strftime("%Y-%m-%d %H:%M:%S.%f") if user.premium_since is not None else None,
            "raw_status": user.raw_status,
            "resolved_permissions": serialize_bool_class(user.resolved_permissions) if user.resolved_permissions is not None else None,
            "roles": [{
                "name": role.name,
                "id": role.id
            } for role in user.roles],
            "status": str(user.status),
            "timed_out_until": user.timed_out_until.strftime("%Y-%m-%d %H:%M:%S.%f") if user.timed_out_until is not None else None,
            "top_role": {
                "name": user.top_role.name,
                "id": user.top_role.id
            },
            "voice": str(user.voice),
            "web_status": str(user.web_status)
        }.items()))
    return add_to_index("users", user.id, data)

def reference_loop(message: Message, cached_message: Message):
    if message == None or cached_message == None:
        return False
    elif message.reference == None or cached_message.reference == None:
        return False
    elif message.reference.cached_message != cached_message or cached_message.reference.cached_message != message:
        return False
    elif message.reference.cached_message == message or cached_message.reference.cached_message == cached_message:
        return True
    return True

def serialize_embed(embed: Embed):
    if not isinstance(embed, Embed):
        return None
    return {
        "title": embed.title,
        "description": embed.description,
        "url": embed.url,
        "timestamp": embed.timestamp.isoformat() if embed.timestamp else None,
        "color": embed.color.value if embed.color else None,
        "fields": [
            {
                "name": field.name,
                "value": field.value,
                "inline": field.inline
            } for field in embed.fields
        ],
        "footer": {
            "text": embed.footer.text,
            "icon_url": embed.footer.icon_url
        } if embed.footer else None,
        "image": {
            "url": embed.image.url
        } if embed.image else None,
        "thumbnail": {
            "url": embed.thumbnail.url
        } if embed.thumbnail else None,
        "video": {
            "url": embed.video.url
        } if embed.video else None,
        "author": {
            "name": embed.author.name,
            "url": embed.author.url,
            "icon_url": embed.author.icon_url
        } if embed.author else None
    }

async def serialize_message(message: Message, channel_id: int = None):
    if not isinstance(message, Message): return None
    return {
        "activity": message.activity,
        "application": {
            "id": message.application.id,
            "description": message.application.description,
            "name": message.application.name,
            "icon": message.application._icon,
            "cover_image": message.application._cover_image
        } if message.application else None,
        "application_id": message.application_id,
        "attachments": [attachment.url for attachment in message.attachments],
        "author": serialize_user(message.author),
        "channel": await serialize_channel(message.channel) if channel_id is None else channel_id,
        "channel_mentions": [mention.name for mention in message.channel_mentions],
        "clean_content": message.clean_content,
        "components": [str(component) for component in message.components],
        "content": message.content,
        "created_at": message.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
        "edited_at": message.edited_at.strftime("%Y-%m-%d %H:%M:%S.%f") if message.edited_at else None,
        "embeds": [serialize_embed(embed) for embed in message.embeds],
        "flags": serialize_message_flags(message.flags),
        "guild": message.guild.name if message.guild else None,
        "id": message.id,
        #"interaction": message.interaction.name if message.interaction else None,
        "interaction_metadata": {
            "id": message.interaction_metadata.id,
            "created_at": message.interaction_metadata.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "interacted_message_id": message.interaction_metadata.interacted_message_id
        } if message.interaction_metadata else None,
        "jump_url": message.jump_url,
        "mention_everyone": message.mention_everyone,
        "mentions": [serialize_user(mention) for mention in message.mentions],
        "nonce": message.nonce,
        "pinned": message.pinned,
        "position": message.position,
        "raw_channel_mentions": message.raw_channel_mentions,
        "raw_mentions": message.raw_mentions,
        "raw_role_mentions": message.raw_role_mentions,
        "reactions": [await serialize_reaction(reaction) for reaction in message.reactions],
        "reference": {
            "url": message.reference.jump_url,
            "id": message.reference.message_id,
            #"message": await serialize_message(message.reference.cached_message) if not reference_loop(message, message.reference.cached_message) else None
        } if message.reference else None,
        #"message_snapshots": [message],
        "role_mentions": [serialize_role(mention) for mention in message.role_mentions],
        "role_subscription": message.role_subscription.tier_name if message.role_subscription else None,
        "stickers": [{"url": sticker.url, "id": sticker.id, "name": sticker.name} for sticker in message.stickers],
        "system_content": message.system_content,
        "tts": message.tts,
        "type": message.type.name,
        "webhook_id": message.webhook_id
    }

async def serialize_category(category: CategoryChannel):
    if not isinstance(category, CategoryChannel): return None
    return add_to_index("channels", category.id, {
        "changed_roles": [serialize_role(role) for role in category.changed_roles],
        "channels": [await serialize_channel(channel) for channel in category.channels if isinstance(channel, (TextChannel, VoiceChannel, StageChannel, ForumChannel, Thread))],
        "created_at": category.created_at.strftime("%Y-%m-%d %H:%M:S"),
        "id": category.id,
        "jump_url": category.jump_url,
        "mention": category.mention,
        "name": category.name,
        "nsfw": category.nsfw,
        "overwrites": {key.id: serialize_iterable(value) for key, value in category.overwrites.items()},
        "permissions_synced": category.permissions_synced,
        "position": category.position,
        "type": str(category.type)
    })

async def serialize_channel(channel: GuildChannel | Thread):
    if not isinstance(channel, (GuildChannel, Thread)): return None
    if isinstance(channel, GuildChannel):
        data = {
            "category_id": channel.category.id if channel.category != None else None,
            "changed_roles": [serialize_role(role) for role in channel.changed_roles],
            "created_at": channel.created_at.strftime("%Y-%m-%d %H:%M:S"),
            "jump_url": channel.jump_url,
            "mention": channel.mention,
            "name": channel.name,
            "id": channel.id,
            "overwrites": {key.id: serialize_iterable(value) for key, value in channel.overwrites.items()},
            "permissions_synced": channel.permissions_synced,
            "position": channel.position
        }
        if isinstance(channel, (TextChannel, VoiceChannel, StageChannel)):
            data = {**data,
                "last_message": await serialize_message(channel.last_message, channel.id),
                "members": [serialize_user(user) for user in channel.members]
            }
        if isinstance(channel, (TextChannel, VoiceChannel, StageChannel, ForumChannel)):
            data = {**data,
                "last_message_id": channel.last_message_id,
                "nsfw": channel.nsfw,
                "slowmode_delay": channel.slowmode_delay,
                "type": str(channel.type)
            }
        if isinstance(channel, (TextChannel, ForumChannel)):
            data = {**data,
                "default_auto_archive_duration": channel.default_auto_archive_duration,
                "default_thread_slowmode_delay": channel.default_thread_slowmode_delay,
                "threads": [await serialize_channel(thread) for thread in channel.threads],
                "topic": channel.topic
            }
        elif isinstance(channel, (VoiceChannel, StageChannel)):
            data = {**data,
                "bitrate": channel.bitrate,
                "rtc_region": channel.rtc_region,
                "scheduled_events": [await serialize_event(event) for event in channel.scheduled_events],
                "user_limit": channel.user_limit,
                "video_quality_mode": str(channel.video_quality_mode)
            }
        elif isinstance(channel, CategoryChannel):
            return await serialize_category(channel)
        elif isinstance(channel, StageChannel):
            data = {**data,
                "instance": {
                    "discoverable_disabled": channel.instance.discoverable_disabled,
                    "id": channel.instance.id,
                    "privacy_level": str(channel.instance.privacy_level),
                    "scheduled_event": await serialize_event(channel.instance.scheduled_event),
                    "topic": channel.instance.topic
                },
                "listeners": [serialize_user(user) for user in channel.listeners],
                "moderators": [serialize_user(user) for user in channel.moderators],
                "requesting_to_speak": [serialize_user(user) for user in channel.requesting_to_speak],
                "speakers": [serialize_user(user) for user in channel.speakers],
                "topic": channel.topic
            }
        elif isinstance(channel, ForumChannel):
            data = {**data,
                "available_tags": [serialize_forum_tag(forum_tag) for forum_tag in channel.available_tags],
                "default_layout": str(channel.default_layout),
                "default_reaction_emoji": str(channel.default_reaction_emoji),
                "default_sort_order": str(channel.default_sort_order),
                "flags": serialize_bool_class(channel.flags)
            }
    elif isinstance(channel, Thread):
        return add_to_index("channels", channel.id, {
            "applied_tags": [serialize_forum_tag(tag) for tag in channel.applied_tags],
            "archive_timestamp": channel.archive_timestamp.strftime("%Y-%m-%d %H:%M:S") if channel.archive_timestamp is not None else None,
            "archived": channel.archived,
            "archiver_id": channel.archiver_id,
            "auto_archive_duration": channel.auto_archive_duration,
            "category_id": channel.category_id,
            "created_at": channel.created_at.strftime("%Y-%m-%d %H:%M:S"),
            "flags": serialize_iterable(channel.flags),
            "id": channel.id,
            "invitable": channel.invitable,
            "jump_url": channel.jump_url,
            "last_message": await serialize_message(channel.last_message, channel.id),
            "last_message_id": channel.last_message_id,
            "locked": channel.locked,
            "member_count": channel.member_count,
            "members": [serialize_user(user) for user in channel.members],
            "mention": channel.mention,
            "message_count": channel.message_count,
            "name": channel.name,
            "owner": serialize_user(channel.owner),
            "owner_id": channel.owner_id,
            "parent_id": channel.parent_id,
            "slowmode_delay": channel.slowmode_delay,
            "starter_message": await serialize_message(channel.starter_message, channel.id),
            "type": str(channel.type)
        })
    return add_to_index("channels", channel.id, dict(sorted(data.items())))

async def serialize_guild(guild: Guild):
    if not isinstance(guild, Guild): return None
    return {
        "afk_channel": await serialize_channel(guild.afk_channel),
        "afk_timeout": guild.afk_timeout,
        "approximate_member_count": guild.approximate_member_count,
        "approximate_presence_count": guild.approximate_presence_count,
        "banner": serialize_asset(guild.banner),
        "bitrate_limit": guild.bitrate_limit,
        "categories": [await serialize_category(category) for category in guild.categories],
        "channels": [await serialize_channel(channel) for channel in guild.channels],
        "chunked": guild.chunked,
        "created_at": guild.created_at.strftime("%Y-%m-%d %H:%M:S"),
        "default_notifications": str(guild.default_notifications),
        "default_role": serialize_role(guild.default_role),
        "description": guild.description,
        "discovery_splash": serialize_asset(guild.discovery_splash),
        "emoji_limit": guild.emoji_limit,
        "emojis": [add_to_index("emojis", emoji.id, {
            "animated": emoji.animated,
            "available": emoji.available,
            "created_at": emoji.created_at.strftime("%Y-%m-%d %H:%M:%S.%f"),
            "guild_id": emoji.guild_id,
            "name": emoji.name,
            "user": serialize_user(emoji.user) if emoji.user is not None else None
        }) for emoji in guild.emojis],
        "explicit_content_filter": str(guild.explicit_content_filter),
        "features": guild.features,
        "filesize_limit": guild.filesize_limit,
        "forums": [await serialize_channel(forum) for forum in guild.forums],
        "icon": serialize_asset(guild.icon),
        "id": guild.id,
        "large": guild.large,
        "max_members": guild.max_members,
        "max_presences": guild.max_presences,
        "max_stage_video_users": guild.max_stage_video_users,
        "max_video_channel_users": guild.max_video_channel_users,
        "member_count": guild.member_count,
        "members": [serialize_user(user) for user in guild.members],
        "mfa_level": str(guild.mfa_level),
        "name": guild.name,
        "nsfw_level": str(guild.nsfw_level),
        "owner": serialize_user(guild.owner),
        "owner_id": guild.owner_id,
        "preferred_locale": str(guild.preferred_locale),
        "premium_progress_bar_enabled": guild.premium_progress_bar_enabled,
        "premium_subscriber_role": serialize_role(guild.premium_subscriber_role),
        "premium_subscribers": [serialize_user(user) for user in guild.premium_subscribers],
        "premium_subscription_count": guild.premium_subscription_count,
        "premium_tier": guild.premium_tier,
        "public_updates_channel": await serialize_channel(guild.public_updates_channel),
        "roles": [serialize_role(role) for role in guild.roles],
        "rules_channel": await serialize_channel(guild.rules_channel),
        "safety_alerts_channel": await serialize_channel(guild.safety_alerts_channel),
        "scheduled_events": [await serialize_event(event) for event in guild.scheduled_events],
        "shard_id": guild.shard_id,
        "splash": serialize_asset(guild.splash),
        "stage_channels": [await serialize_channel(stage_channel) for stage_channel in guild.stage_channels],
        "stage_instances": [{
            "channel": await serialize_channel(stage_instance.channel),
            "discoverable_disabled": stage_instance.discoverable_disabled,
            "id": stage_instance.id,
            "privacy_level": str(stage_instance.privacy_level),
            "scheduled_event": await serialize_event(stage_instance.scheduled_event),
            "topic": stage_instance.topic
        } for stage_instance in guild.stage_instances],
        "sticker_limit": guild.sticker_limit,
        "stickers": [{
            "url": sticker.url,
            "id": sticker.id,
            "name": sticker.name
        } for sticker in guild.stickers],
        "system_channel": await serialize_channel(guild.system_channel),
        "system_channel_flags": serialize_bool_class(guild.system_channel_flags),
        "text_channels": [await serialize_channel(text_channel) for text_channel in guild.text_channels],
        "threads": [await serialize_channel(thread) for thread in guild.threads],
        "unavailable": guild.unavailable,
        "vanity_url": guild.vanity_url,
        "vanity_url_code": guild.vanity_url_code,
        "verification_level": str(guild.verification_level),
        "voice_channels": [await serialize_channel(voice_channel) for voice_channel in guild.voice_channels],
        "widget_channel": await serialize_channel(guild.widget_channel),
        "widget_enabled": guild.widget_enabled
    }