import discord
from discord.ext import commands
import asyncio
import json
import os
from dotenv import load_dotenv
import aiohttp
from io import BytesIO

# =========================================================
# SETTINGS
# =========================================================

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN", "").strip()

if not TOKEN:
    raise RuntimeError("DISCORD_BOT_TOKEN was not found in .env")

CONFIG_FILE = "server_configs.json"
BACKUP_FOLDER = "backups"

MAX_CHANNELS = 35
MAX_ROLES = 35
MAX_CUSTOM_MESSAGES = 500
MAX_TOTAL_MESSAGES_PER_START = 65

CONCURRENCY = 70

os.makedirs(BACKUP_FOLDER, exist_ok=True)

# =========================================================
# AUTO EMOJIS
# =========================================================

CHANNEL_EMOJIS = {
    "general": "💬", "chat": "💭", "talk": "🗣️",
    "announcements": "📢", "announcement": "📣", "news": "📰",
    "rules": "📜", "info": "ℹ️", "information": "📚",
    "giveaways": "🎁", "giveaway": "🎉", "ogs": "🍓", "og": "🍓",
    "verified": "✅", "verification": "🔐", "tickets": "🎫", "ticket": "🎟️",
    "trading": "💱", "trade": "🤝", "market": "🛒", "shop": "🛍️",
    "support": "🆘", "help": "❓", "staff": "🛡️", "moderation": "🔨",
    "mods": "👮", "mod": "🔧", "admin": "👑", "admins": "🏛️", "owner": "⭐",
    "bot": "🤖", "bots": "🧩", "commands": "⚙️", "media": "📸",
    "pictures": "🖼️", "clips": "🎬", "videos": "📹", "suggestions": "💡",
    "suggestion": "💭", "logs": "📋", "log": "📝", "voice": "🔊", "music": "🎵",
    "events": "🎉", "event": "🎊", "applications": "📝", "apply": "📨",
    "duels": "⚔️", "duel": "🗡️", "gaming": "🎮", "game": "🕹️",
    "welcome": "👋", "goodbye": "🚪", "premium": "💎", "vip": "💠",
    "boost": "🚀", "boosts": "💨"
}

UNIQUE_CHANNEL_EMOJIS = [
    "💬", "💭", "🗣️", "📢", "📣", "📰", "📜", "ℹ️", "📚", "🎁", "🎉", "🍓",
    "✅", "🔐", "🎫", "🎟️", "💱", "🤝", "🛒", "🛍️", "🆘", "❓", "🛡️", "🔨",
    "👮", "🔧", "👑", "🏛️", "⭐", "🤖", "🧩", "⚙️", "📸", "🖼️", "🎬", "📹",
    "💡", "📋", "📝", "🔊", "🎵", "🎊", "📨", "⚔️", "🗡️", "🎮", "🕹️", "👋",
    "🚪", "💎", "💠", "🚀", "💨", "🔥", "✨", "🌟", "💫", "🔔", "📌", "🎯"
]


def get_channel_emoji(name, used_emojis=None):
    clean = name.lower().strip().replace("-", " ").replace("_", " ")
    preferred = CHANNEL_EMOJIS.get(clean)
    if preferred is None:
        for word in clean.split():
            if word in CHANNEL_EMOJIS:
                preferred = CHANNEL_EMOJIS[word]
                break

    # When building a server, NEVER reuse an emoji already assigned.
    if used_emojis is not None:
        if preferred and preferred not in used_emojis:
            used_emojis.add(preferred)
            return preferred
        for emoji in UNIQUE_CHANNEL_EMOJIS:
            if emoji not in used_emojis:
                used_emojis.add(emoji)
                return emoji
        # More channels than our emoji pool: use a numbered fallback.
        return UNIQUE_CHANNEL_EMOJIS[len(used_emojis) % len(UNIQUE_CHANNEL_EMOJIS)]

    return preferred or "💬"


def make_channel_name(name, emoji_mode, assigned_emoji=None):
    if not emoji_mode:
        return name
    emoji = assigned_emoji or get_channel_emoji(name)
    return f"{emoji}・{name}"


# =========================================================
# BOT SETUP
# =========================================================

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(
    command_prefix="!",
    intents=intents,
    help_command=None
)

semaphore = asyncio.Semaphore(CONCURRENCY)

# =========================================================
# CONFIG STORAGE
# =========================================================

def default_config():
    return {
        "channels": [],
        "roles": [],
        "messages": [],
        "channels_to_delete": [],
        "roles_to_delete": [],
        "server_name": None,
        "server_icon": None,
        "delete_all_channels": False,
        "delete_all_roles": False
    }


def load_data():

    if not os.path.exists(CONFIG_FILE):
        return {
            "servers": {},
            "templates": {}
        }

    try:

        with open(
            CONFIG_FILE,
            "r",
            encoding="utf-8"
        ) as f:

            data = json.load(f)

        data.setdefault("servers", {})
        data.setdefault("templates", {})

        return data

    except Exception:

        return {
            "servers": {},
            "templates": {}
        }


def save_data(data):

    with open(
        CONFIG_FILE,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            data,
            f,
            indent=4
        )


def get_server_config(guild_id):

    data = load_data()

    key = str(guild_id)

    if key not in data["servers"]:

        data["servers"][key] = default_config()

        save_data(data)

    return data["servers"][key]


def set_server_config(
    guild_id,
    config
):

    data = load_data()

    data["servers"][str(guild_id)] = config

    save_data(data)


# =========================================================
# PERMISSIONS
# =========================================================

def is_admin(member):

    return member is not None and (
        member.guild_permissions.administrator
        or member.id == member.guild.owner_id
    )


# =========================================================
# EMBEDS
# =========================================================

def config_embed(guild):

    config = get_server_config(guild.id)

    embed = discord.Embed(
        title="⚙️ Server Builder",
        description=(
            f"**Server:** {guild.name}\n\n"
            "Configure your server using the buttons below.\n\n"
            "💾 Save configurations as reusable templates.\n"
            "📂 Load a saved template into another server."
        )
    )

    embed.add_field(
        name="📊 Current Config",
        value=(
            f"Channels: `{len(config['channels'])}`\n"
            f"Roles: `{len(config['roles'])}`\n"
            f"Messages: `{len(config['messages'])}`\n"
            f"Channels to delete: `{len(config['channels_to_delete'])}`\n"
            f"Roles to delete: `{len(config['roles_to_delete'])}`"
        ),
        inline=False
    )

    return embed


def preview_embed(
    guild,
    config=None
):

    if config is None:
        config = get_server_config(guild.id)

    embed = discord.Embed(
        title="👀 Configuration Preview",
        description=f"Configuration for **{guild.name}**"
    )

    channels = config["channels"]
    roles = config["roles"]
    messages = config["messages"]

    channel_text = "\n".join(
        f"• `{x.get('name', 'Unnamed')}` "
        f"x{x.get('amount', 1)} "
        f"| Emoji: `{x.get('emoji_mode', False)}`"
        for x in channels[:15]
    ) or "None"

    role_text = "\n".join(
        f"• `{x.get('name', 'Unnamed')}` "
        f"x{x.get('amount', 1)}"
        for x in roles[:15]
    ) or "None"

    message_text = "\n".join(
        f"• `{x.get('target', 'Unknown')}` "
        f"— {x.get('amount', 1)} message(s)"
        for x in messages[:15]
    ) or "None"

    embed.add_field(
        name="📁 Channels",
        value=channel_text,
        inline=False
    )

    embed.add_field(
        name="🎭 Roles",
        value=role_text,
        inline=False
    )

    embed.add_field(
        name="💬 Messages",
        value=message_text,
        inline=False
    )

    embed.add_field(
        name="🗑️ Deletions",
        value=(
            f"All channels: "
            f"`{config.get('delete_all_channels', False)}`\n"
            f"All roles: "
            f"`{config.get('delete_all_roles', False)}`"
        ),
        inline=False
    )

    if config.get("server_name"):

        embed.add_field(
            name="🏷️ Server Name",
            value=config["server_name"],
            inline=False
        )

    return embed


# =========================================================
# CONFIRMATION
# =========================================================

class ConfirmView(discord.ui.View):

    def __init__(
        self,
        guild_id,
        action
    ):

        super().__init__(timeout=60)

        self.guild_id = guild_id
        self.action = action

    @discord.ui.button(
        label="Confirm",
        style=discord.ButtonStyle.danger,
        emoji="✅"
    )
    async def confirm(
        self,
        interaction,
        button
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:

            await interaction.response.send_message(
                "❌ Server not found."
            )

            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        if self.action == "all_channels":

            config = get_server_config(
                self.guild_id
            )

            config["delete_all_channels"] = True

            set_server_config(
                self.guild_id,
                config
            )

            await interaction.response.send_message(
                "✅ All channels marked for deletion."
            )

        elif self.action == "all_roles":

            config = get_server_config(
                self.guild_id
            )

            config["delete_all_roles"] = True

            set_server_config(
                self.guild_id,
                config
            )

            await interaction.response.send_message(
                "✅ All removable roles marked for deletion."
            )

        elif self.action == "reset":

            set_server_config(
                self.guild_id,
                default_config()
            )

            await interaction.response.send_message(
                "♻️ Configuration reset."
            )

        self.stop()

    @discord.ui.button(
        label="Cancel",
        style=discord.ButtonStyle.secondary,
        emoji="❌"
    )
    async def cancel(
        self,
        interaction,
        button
    ):

        await interaction.response.send_message(
            "❌ Cancelled."
        )

        self.stop()


# =========================================================
# CREATE CHANNEL MODAL
# =========================================================

class CreateChannelModal(
    discord.ui.Modal,
    title="Create Channels"
):

    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="1 - 35",
        required=True,
        max_length=2
    )

    name = discord.ui.TextInput(
        label="Channel name",
        placeholder="giveaways",
        required=True,
        max_length=90
    )

    emoji_mode = discord.ui.TextInput(
        label="Auto Emoji? YES / NO",
        placeholder="YES",
        required=True,
        max_length=3
    )

    category = discord.ui.TextInput(
        label="Category (optional)",
        placeholder="Trading",
        required=False,
        max_length=100
    )

    def __init__(self, guild_id):

        super().__init__()

        self.guild_id = guild_id

    async def on_submit(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:

            await interaction.response.send_message(
                "❌ Server not found."
            )

            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        try:

            amount = int(
                self.amount.value
            )

            if not 1 <= amount <= MAX_CHANNELS:
                raise ValueError

        except ValueError:

            await interaction.response.send_message(
                f"❌ Amount must be between 1 and {MAX_CHANNELS}."
            )

            return

        emoji_enabled = (
            self.emoji_mode.value.strip().lower()
            in ["yes", "y", "true", "on"]
        )

        config = get_server_config(
            self.guild_id
        )

        config["channels"].append({
            "amount": amount,
            "name": self.name.value.strip(),
            "emoji_mode": emoji_enabled,
            "category": (
                self.category.value.strip()
                or None
            )
        })

        set_server_config(
            self.guild_id,
            config
        )

        result_name = make_channel_name(
            self.name.value.strip(),
            emoji_enabled
        )

        await interaction.response.send_message(
            f"✅ Added `{amount}` channel(s).\n"
            f"Example: `{result_name}`"
        )


# =========================================================
# DELETE CHANNELS
# =========================================================

class DeleteChannelModal(
    discord.ui.Modal,
    title="Delete Channels"
):

    names = discord.ui.TextInput(
        label="Channel names",
        placeholder="general, trading, announcements",
        required=True,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, guild_id):

        super().__init__()

        self.guild_id = guild_id

    async def on_submit(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:
            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        names = [
            x.strip()
            for x in self.names.value.split(",")
            if x.strip()
        ]

        config = get_server_config(
            self.guild_id
        )

        config["channels_to_delete"].extend(
            names
        )

        set_server_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            f"🗑️ Added `{len(names)}` channel(s) to deletion list."
        )


# =========================================================
# CREATE ROLES
# =========================================================

class CreateRoleModal(
    discord.ui.Modal,
    title="Create Roles"
):

    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="1 - 35",
        required=True,
        max_length=2
    )

    name = discord.ui.TextInput(
        label="Role name",
        placeholder="Member",
        required=True,
        max_length=100
    )

    def __init__(self, guild_id):

        super().__init__()

        self.guild_id = guild_id

    async def on_submit(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:
            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        try:

            amount = int(
                self.amount.value
            )

            if not 1 <= amount <= MAX_ROLES:
                raise ValueError

        except ValueError:

            await interaction.response.send_message(
                f"❌ Amount must be between 1 and {MAX_ROLES}."
            )

            return

        config = get_server_config(
            self.guild_id
        )

        config["roles"].append({
            "amount": amount,
            "name": self.name.value.strip()
        })

        set_server_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            f"✅ Added `{amount}` role(s)."
        )


# =========================================================
# DELETE ROLES
# =========================================================

class DeleteRoleModal(
    discord.ui.Modal,
    title="Delete Roles"
):

    names = discord.ui.TextInput(
        label="Role names",
        placeholder="Member, Trial Mod, Old Role",
        required=True,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, guild_id):

        super().__init__()

        self.guild_id = guild_id

    async def on_submit(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:
            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        names = [
            x.strip()
            for x in self.names.value.split(",")
            if x.strip()
        ]

        config = get_server_config(
            self.guild_id
        )

        config["roles_to_delete"].extend(
            names
        )

        set_server_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            f"🗑️ Added `{len(names)}` role(s) to deletion list."
        )


# =========================================================
# MESSAGES
# =========================================================

class MessageModal(
    discord.ui.Modal,
    title="Add Messages"
):

    target = discord.ui.TextInput(
        label="Channel",
        placeholder="general OR ALL",
        required=True
    )

    amount = discord.ui.TextInput(
        label="Amount",
        placeholder="1 - 35",
        required=True
    )

    message = discord.ui.TextInput(
        label="Message",
        placeholder="Welcome!",
        required=True,
        style=discord.TextStyle.paragraph
    )

    def __init__(self, guild_id):

        super().__init__()

        self.guild_id = guild_id

    async def on_submit(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:
            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        try:

            amount = int(
                self.amount.value
            )

            if not 1 <= amount <= MAX_CUSTOM_MESSAGES:
                raise ValueError

        except ValueError:

            await interaction.response.send_message(
                f"❌ Amount must be between 1 and {MAX_CUSTOM_MESSAGES}."
            )

            return

        config = get_server_config(
            self.guild_id
        )

        config["messages"].append({
            "target": self.target.value.strip(),
            "amount": amount,
            "message": self.message.value
        })

        set_server_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            "💬 Message configuration saved."
        )


# =========================================================
# SERVER SETTINGS
# =========================================================

class ServerSettingsModal(
    discord.ui.Modal,
    title="Server Settings"
):

    server_name = discord.ui.TextInput(
        label="Server name",
        placeholder="Leave blank to keep current",
        required=False,
        max_length=100
    )

    icon_url = discord.ui.TextInput(
        label="Server icon URL",
        placeholder="https://example.com/icon.png",
        required=False
    )

    def __init__(self, guild_id):

        super().__init__()

        self.guild_id = guild_id

    async def on_submit(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:
            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        config = get_server_config(
            self.guild_id
        )

        if self.server_name.value.strip():

            config["server_name"] = (
                self.server_name.value.strip()
            )

        if self.icon_url.value.strip():

            config["server_icon"] = (
                self.icon_url.value.strip()
            )

        set_server_config(
            self.guild_id,
            config
        )

        await interaction.response.send_message(
            "✅ Server settings saved."
        )


# =========================================================
# SAVED CONFIG SELECT
# =========================================================

class SavedConfigSelect(
    discord.ui.Select
):

    def __init__(
        self,
        guild_id
    ):

        self.guild_id = guild_id

        data = load_data()

        templates = data["templates"]

        options = []

        for name in list(
            templates.keys()
        )[:25]:

            options.append(
                discord.SelectOption(
                    label=name[:100],
                    value=name
                )
            )

        if not options:

            options.append(
                discord.SelectOption(
                    label="No saved configs",
                    value="NONE"
                )
            )

        super().__init__(
            placeholder="Select a saved config...",
            options=options
        )

    async def callback(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:
            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        selected = self.values[0]

        if selected == "NONE":

            await interaction.response.send_message(
                "❌ No saved configs exist."
            )

            return

        data = load_data()

        template = data["templates"].get(
            selected
        )

        if template is None:

            await interaction.response.send_message(
                "❌ Saved config not found."
            )

            return

        set_server_config(
            self.guild_id,
            json.loads(
                json.dumps(template)
            )
        )

        await interaction.response.send_message(
            f"📂 Loaded **{selected}** into **{guild.name}**.\n"
            "Press 🚀 **START** to apply it."
        )


class SavedConfigView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id
    ):

        super().__init__(
            timeout=120
        )

        self.add_item(
            SavedConfigSelect(
                guild_id
            )
        )


# =========================================================
# SAVE TEMPLATE
# =========================================================

class SaveTemplateModal(
    discord.ui.Modal,
    title="Save Config"
):

    name = discord.ui.TextInput(
        label="Template name",
        placeholder="My Server Template",
        required=True,
        max_length=100
    )

    def __init__(self, guild_id):

        super().__init__()

        self.guild_id = guild_id

    async def on_submit(
        self,
        interaction
    ):

        guild = bot.get_guild(
            self.guild_id
        )

        if guild is None:
            return

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return

        data = load_data()

        config = get_server_config(
            self.guild_id
        )

        data["templates"][
            self.name.value.strip()
        ] = json.loads(
            json.dumps(config)
        )

        save_data(data)

        await interaction.response.send_message(
            f"💾 Saved **{self.name.value.strip()}**.\n"
            "You can reuse it in another server."
        )


# =========================================================
# BACKUP
# =========================================================

def backup_server(
    guild_id
):

    config = get_server_config(
        guild_id
    )

    path = os.path.join(
        BACKUP_FOLDER,
        f"{guild_id}.json"
    )

    with open(
        path,
        "w",
        encoding="utf-8"
    ) as f:

        json.dump(
            config,
            f,
            indent=4
        )

    return path


def restore_server(
    guild_id
):

    path = os.path.join(
        BACKUP_FOLDER,
        f"{guild_id}.json"
    )

    if not os.path.exists(path):
        return False

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as f:

        config = json.load(f)

    set_server_config(
        guild_id,
        config
    )

    return True


# =========================================================
# ICON
# =========================================================

async def download_icon(
    url
):

    try:

        async with aiohttp.ClientSession() as session:

            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(
                    total=15
                )
            ) as response:

                if response.status != 200:
                    return None

                data = await response.read()

                if len(data) > 10 * 1024 * 1024:
                    return None

                return BytesIO(data)

    except Exception:

        return None


# =========================================================
# CHANNEL CREATION
# =========================================================

async def create_channel_and_message(
    guild,
    item,
    message_configs,
    created_channels,
    assigned_emoji=None
):

    emoji_mode = item.get(
        "emoji_mode",
        False
    )

    channel_name = make_channel_name(
        item["name"],
        emoji_mode,
        assigned_emoji
    )

    category = None

    category_name = item.get(
        "category"
    )

    if category_name:

        category = discord.utils.find(
            lambda c:
            isinstance(
                c,
                discord.CategoryChannel
            )
            and c.name.lower()
            == category_name.lower(),
            guild.categories
        )

        if category is None:

            try:

                category = await guild.create_category(
                    category_name,
                    reason="Server Builder"
                )

            except Exception:

                category = None

    try:

        channel = await guild.create_text_channel(
            name=channel_name,
            category=category,
            reason="Server Builder"
        )

    except Exception:

        return None

    created_channels.append(
        channel
    )

    # -----------------------------------------------------
    # SEND MESSAGES IMMEDIATELY
    # AFTER THIS CHANNEL IS CREATED.
    # -----------------------------------------------------

    for message_config in message_configs:

        target = message_config[
            "target"
        ]

        target_clean = target.lower().strip()

        matches = (
            target_clean == "all"
            or target_clean == item["name"].lower()
            or target_clean == channel.name.lower()
        )

        if not matches:
            continue

        amount = min(
            int(
                message_config.get(
                    "amount",
                    1
                )
            ),
            MAX_CUSTOM_MESSAGES
        )

        for _ in range(amount):

            try:

                await channel.send(
                    message_config["message"],
                    allowed_mentions=discord.AllowedMentions(everyone=True)
                )

            except Exception:

                break

    return channel


# =========================================================
# ROLE CREATION
# =========================================================

async def create_role(
    guild,
    name
):

    try:

        return await guild.create_role(
            name=name,
            reason="Server Builder"
        )

    except Exception:

        return None


# =========================================================
# EXECUTE
# =========================================================

async def execute_config(
    guild
):

    config = get_server_config(
        guild.id
    )

    # -----------------------------------------------------
    # DELETE ALL CHANNELS
    # -----------------------------------------------------

    if config.get(
        "delete_all_channels"
    ):

        async def delete_channel(
            channel
        ):

            try:

                await channel.delete(
                    reason="Server Builder"
                )

            except Exception:
                pass

        await asyncio.gather(
            *[
                delete_channel(channel)
                for channel in list(
                    guild.channels
                )
            ],
            return_exceptions=True
        )

        await asyncio.sleep(1)

    # -----------------------------------------------------
    # DELETE SELECTED CHANNELS
    # -----------------------------------------------------

    for name in config.get(
        "channels_to_delete",
        []
    ):

        channel = discord.utils.find(
            lambda c:
            c.name.lower()
            == name.lower(),
            guild.channels
        )

        if channel:

            try:

                await channel.delete(
                    reason="Server Builder"
                )

            except Exception:
                pass

    # -----------------------------------------------------
    # DELETE ALL ROLES
    # -----------------------------------------------------

    if config.get(
        "delete_all_roles"
    ):

        me = guild.me

        if me:

            async def delete_role(
                role
            ):

                if role.is_default():
                    return

                if role.managed:
                    return

                if role >= me.top_role:
                    return

                try:

                    await role.delete(
                        reason="Server Builder"
                    )

                except Exception:
                    pass

            await asyncio.gather(
                *[
                    delete_role(role)
                    for role in list(
                        guild.roles
                    )
                ],
                return_exceptions=True
            )

    # -----------------------------------------------------
    # DELETE SELECTED ROLES
    # -----------------------------------------------------

    me = guild.me

    for name in config.get(
        "roles_to_delete",
        []
    ):

        role = discord.utils.find(
            lambda r:
            r.name.lower()
            == name.lower(),
            guild.roles
        )

        if (
            role
            and not role.is_default()
            and not role.managed
            and me
            and role < me.top_role
        ):

            try:

                await role.delete(
                    reason="Server Builder"
                )

            except Exception:
                pass

    # -----------------------------------------------------
    # SERVER NAME
    # -----------------------------------------------------

    if config.get(
        "server_name"
    ):

        try:

            await guild.edit(
                name=config[
                    "server_name"
                ],
                reason="Server Builder"
            )

        except Exception:
            pass

    # -----------------------------------------------------
    # SERVER ICON
    # -----------------------------------------------------

    if config.get(
        "server_icon"
    ):

        icon_data = await download_icon(
            config["server_icon"]
        )

        if icon_data:

            try:

                await guild.edit(
                    icon=icon_data.read(),
                    reason="Server Builder"
                )

            except Exception:
                pass

    # -----------------------------------------------------
    # CREATE ROLES
    # -----------------------------------------------------

    role_tasks = []

    for item in config.get(
        "roles",
        []
    ):

        amount = min(
            int(
                item.get(
                    "amount",
                    1
                )
            ),
            MAX_ROLES
        )

        for _ in range(amount):

            role_tasks.append(
                create_role(
                        guild,
                        item["name"]
                    )
            )

    if role_tasks:

        await asyncio.gather(
            *role_tasks,
            return_exceptions=True
        )

    # -----------------------------------------------------
    # CREATE CHANNELS + MESSAGE IMMEDIATELY
    # -----------------------------------------------------

    created_channels = []

    channel_tasks = []
    used_channel_emojis = set()

    for item in config.get(
        "channels",
        []
    ):

        amount = min(
            int(
                item.get(
                    "amount",
                    1
                )
            ),
            MAX_CHANNELS
        )

        for _ in range(amount):

            assigned_emoji = None
            if item.get("emoji_mode", False):
                assigned_emoji = get_channel_emoji(
                    item["name"],
                    used_channel_emojis
                )

            channel_tasks.append(
                create_channel_and_message(
                    guild,
                    item,
                    config.get(
                        "messages",
                        []
                    ),
                    created_channels,
                    assigned_emoji
                )
            )

    if channel_tasks:

        await asyncio.gather(
            *channel_tasks,
            return_exceptions=True
        )

    total_messages = 0

    # Count configured message work,
    # without creating unbounded automation.
    for message_config in config.get(
        "messages",
        []
    ):

        amount = min(
            int(
                message_config.get(
                    "amount",
                    1
                )
            ),
            MAX_CUSTOM_MESSAGES
        )

        target = message_config[
            "target"
        ]

        if target.upper() == "ALL":

            total_messages += (
                amount
                * len(created_channels)
            )

        else:

            total_messages += amount * sum(
                1
                for channel
                in created_channels
                if (
                    channel.name.lower()
                    == target.lower()
                    or target.lower()
                    == channel.name.lower()
                )
            )

    set_server_config(
        guild.id,
        config
    )

    return (
        len(created_channels),
        min(
            total_messages,
            MAX_TOTAL_MESSAGES_PER_START
        )
    )


# =========================================================
# CONFIG VIEW
# =========================================================

class ConfigView(
    discord.ui.View
):

    def __init__(
        self,
        guild_id
    ):

        super().__init__(
            timeout=900
        )

        self.guild_id = guild_id

    def get_guild(self):

        return bot.get_guild(
            self.guild_id
        )

    async def check_admin(
        self,
        interaction
    ):

        guild = self.get_guild()

        if guild is None:

            await interaction.response.send_message(
                "❌ Server not found."
            )

            return None

        member = guild.get_member(
            interaction.user.id
        )

        if not is_admin(member):

            await interaction.response.send_message(
                "❌ You need Administrator permissions."
            )

            return None

        return guild

    # =====================================================
    # CHANNELS
    # =====================================================

    @discord.ui.button(
        label="Create Channels",
        style=discord.ButtonStyle.primary,
        emoji="📁",
        row=0
    )
    async def create_channels(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_modal(
                CreateChannelModal(
                    self.guild_id
                )
            )

    @discord.ui.button(
        label="Delete Channels",
        style=discord.ButtonStyle.secondary,
        emoji="🗑️",
        row=0
    )
    async def delete_channels(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_modal(
                DeleteChannelModal(
                    self.guild_id
                )
            )

    @discord.ui.button(
        label="DELETE ALL CHANNELS",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        row=0
    )
    async def delete_all_channels(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_message(
                "⚠️ This will mark every channel for deletion.",
                view=ConfirmView(
                    self.guild_id,
                    "all_channels"
                )
            )

    # =====================================================
    # ROLES
    # =====================================================

    @discord.ui.button(
        label="Create Roles",
        style=discord.ButtonStyle.primary,
        emoji="🎭",
        row=1
    )
    async def create_roles(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_modal(
                CreateRoleModal(
                    self.guild_id
                )
            )

    @discord.ui.button(
        label="Delete Roles",
        style=discord.ButtonStyle.secondary,
        emoji="🗑️",
        row=1
    )
    async def delete_roles(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_modal(
                DeleteRoleModal(
                    self.guild_id
                )
            )

    @discord.ui.button(
        label="DELETE ALL ROLES",
        style=discord.ButtonStyle.danger,
        emoji="⚠️",
        row=1
    )
    async def delete_all_roles(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_message(
                "⚠️ This marks removable roles for deletion.\n"
                "The @everyone role, managed roles, and roles above "
                "the bot are protected.",
                view=ConfirmView(
                    self.guild_id,
                    "all_roles"
                )
            )

    # =====================================================
    # MESSAGES
    # =====================================================

    @discord.ui.button(
        label="Messages",
        style=discord.ButtonStyle.primary,
        emoji="💬",
        row=2
    )
    async def messages(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_modal(
                MessageModal(
                    self.guild_id
                )
            )

    # =====================================================
    # SETTINGS
    # =====================================================

    @discord.ui.button(
        label="Server Settings",
        style=discord.ButtonStyle.primary,
        emoji="⚙️",
        row=2
    )
    async def server_settings(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_modal(
                ServerSettingsModal(
                    self.guild_id
                )
            )

    # =====================================================
    # PREVIEW
    # =====================================================

    @discord.ui.button(
        label="Preview",
        style=discord.ButtonStyle.secondary,
        emoji="👀",
        row=2
    )
    async def preview(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_message(
                embed=preview_embed(
                    guild
                )
            )

    # =====================================================
    # SAVE
    # =====================================================

    @discord.ui.button(
        label="Save Config",
        style=discord.ButtonStyle.success,
        emoji="💾",
        row=3
    )
    async def save_config(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_modal(
                SaveTemplateModal(
                    self.guild_id
                )
            )

    # =====================================================
    # USE SAVED CONFIG
    # =====================================================

    @discord.ui.button(
        label="Use Saved Config",
        style=discord.ButtonStyle.success,
        emoji="📂",
        row=3
    )
    async def use_saved_config(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild is None:
            return

        data = load_data()

        if not data["templates"]:

            await interaction.response.send_message(
                "📂 No saved configs yet.\n"
                "Use 💾 Save Config first."
            )

            return

        await interaction.response.send_message(
            "📂 Select a saved configuration:",
            view=SavedConfigView(
                self.guild_id
            )
        )

    # =====================================================
    # RESET
    # =====================================================

    @discord.ui.button(
        label="Reset",
        style=discord.ButtonStyle.secondary,
        emoji="♻️",
        row=3
    )
    async def reset(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            await interaction.response.send_message(
                "⚠️ Are you sure you want to reset?",
                view=ConfirmView(
                    self.guild_id,
                    "reset"
                )
            )

    # =====================================================
    # START
    # =====================================================

    @discord.ui.button(
        label="START",
        style=discord.ButtonStyle.success,
        emoji="🚀",
        row=4
    )
    async def start(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild is None:
            return

        await interaction.response.send_message(
            "🚀 Starting configuration..."
        )

        try:

            created, messages = await execute_config(
                guild
            )

            await interaction.followup.send(
                f"✅ **Finished!**\n\n"
                f"📁 Channels created: `{created}`\n"
                f"💬 Configured messages: `{messages}`"
            )

        except Exception as e:

            await interaction.followup.send(
                f"❌ Error:\n`{str(e)[:1500]}`"
            )

    # =====================================================
    # BACKUP
    # =====================================================

    @discord.ui.button(
        label="Backup",
        style=discord.ButtonStyle.secondary,
        emoji="🗄️",
        row=4
    )
    async def backup(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            backup_server(
                self.guild_id
            )

            await interaction.response.send_message(
                "🗄️ Backup saved."
            )

    # =====================================================
    # RESTORE
    # =====================================================

    @discord.ui.button(
        label="Restore",
        style=discord.ButtonStyle.secondary,
        emoji="♻️",
        row=4
    )
    async def restore(
        self,
        interaction,
        button
    ):

        guild = await self.check_admin(
            interaction
        )

        if guild:

            if restore_server(
                self.guild_id
            ):

                await interaction.response.send_message(
                    "♻️ Backup restored."
                )

            else:

                await interaction.response.send_message(
                    "❌ No backup exists for this server."
                )


# =========================================================
# !CONFIG
# =========================================================

@bot.command()
@commands.guild_only()
async def config(ctx):

    if not is_admin(
        ctx.author
    ):

        await ctx.reply(
            "❌ You need Administrator permissions.",
            delete_after=5
        )

        return

    try:

        await ctx.message.delete()

    except Exception:
        pass

    try:

        await ctx.author.send(
            embed=config_embed(
                ctx.guild
            ),
            view=ConfigView(
                ctx.guild.id
            )
        )

    except discord.Forbidden:

        await ctx.channel.send(
            "❌ I couldn't DM you. Enable DMs from server members."
        )

    except Exception as e:

        await ctx.channel.send(
            f"❌ Error: `{str(e)[:500]}`"
        )


# =========================================================
# !SAVE
# =========================================================

@bot.command()
@commands.guild_only()
async def save(ctx):

    if not is_admin(
        ctx.author
    ):
        return

    backup_server(
        ctx.guild.id
    )

    await ctx.reply(
        "💾 Current configuration backed up."
    )


# =========================================================
# !PREVIEW
# =========================================================

@bot.command()
@commands.guild_only()
async def preview(ctx):

    if not is_admin(
        ctx.author
    ):
        return

    await ctx.reply(
        embed=preview_embed(
            ctx.guild
        )
    )


# =========================================================
# !RESET
# =========================================================

@bot.command()
@commands.guild_only()
async def reset(ctx):

    if not is_admin(
        ctx.author
    ):
        return

    await ctx.reply(
        "⚠️ Confirm configuration reset:",
        view=ConfirmView(
            ctx.guild.id,
            "reset"
        )
    )


# =========================================================
# !START
# =========================================================

@bot.command()
@commands.guild_only()
async def start(ctx):

    if not is_admin(
        ctx.author
    ):
        return

    message = await ctx.reply(
        "🚀 Starting..."
    )

    try:

        created, messages = await execute_config(
            ctx.guild
        )

        await message.edit(
            content=(
                "✅ **Finished!**\n"
                f"📁 Channels created: `{created}`\n"
                f"💬 Configured messages: `{messages}`"
            )
        )

    except Exception as e:

        await message.edit(
            content=f"❌ Error: `{str(e)[:1500]}`"
        )


# =========================================================
# !HELP
# =========================================================

@bot.command(
    name="help"
)
async def help_command(ctx):

    text = (
        "🤖 **Server Builder**\n\n"
        "`!config` — Private configuration menu\n"
        "`!save` — Backup configuration\n"
        "`!preview` — Preview configuration\n"
        "`!reset` — Reset configuration\n"
        "`!start` — Apply configuration\n"
        "`!help` — Show commands\n\n"
        "📂 Saved configurations can be reused in other servers."
    )

    try:

        await ctx.author.send(
            text
        )

        if ctx.guild:

            try:
                await ctx.message.delete()
            except Exception:
                pass

    except discord.Forbidden:

        await ctx.reply(
            "❌ I couldn't DM you. Enable DMs."
        )


# =========================================================
# REMOVE OLD SLASH COMMANDS
# =========================================================

@bot.event
async def setup_hook():

    try:

        bot.tree.clear_commands(
            guild=None
        )

        await bot.tree.sync()

        print(
            "🧹 Old global slash commands cleared."
        )

    except Exception as e:

        print(
            f"Slash command cleanup error: {e}"
        )


# =========================================================
# READY
# =========================================================

@bot.event
async def on_ready():

    print(
        "==================================="
    )

    print(
        f"🤖 Logged in as {bot.user}"
    )

    print(
        f"🆔 Bot ID: {bot.user.id}"
    )

    print(
        f"🌐 Servers: {len(bot.guilds)}"
    )

    print(
        "===================================")


# =========================================================
# RUN
# =========================================================

bot.run(TOKEN)
