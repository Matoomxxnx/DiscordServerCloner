"""
Bunmee Store Discord Bot
Features: Verify, Welcome, Ticket, Giveaway, Shop, Credit
"""

import discord
from aiohttp import web
from discord import app_commands
from discord.ext import commands, tasks
import json, os, sys, asyncio, random, re
from datetime import datetime, timedelta, timezone

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "verify_config.json")


# ─── Config ───────────────────────────────────────────────────────────────────

def load_config() -> dict:
    config = {}
    env_cfg = os.getenv("VERIFY_CONFIG")
    if env_cfg:
        try:
            config.update(json.loads(env_cfg))
        except Exception:
            pass
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, encoding="utf-8") as f:
            config.update(json.load(f))
    return config


def save_config(config: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


def guild_cfg(guild_id) -> dict:
    return load_config().get(str(guild_id), {})


def update_guild(guild_id, **kwargs):
    cfg = load_config()
    cfg.setdefault(str(guild_id), {}).update(kwargs)
    save_config(cfg)


REVIEW_COUNTER_PATTERN = re.compile(r"^(?P<prefix>.*?)(?P<count>\d+)$")


def parse_review_counter_channel_name(name: str):
    if "รีวิว" not in name:
        return None, None
    match = REVIEW_COUNTER_PATTERN.match(name)
    if not match:
        return None, None
    return match.group("prefix"), int(match.group("count"))


# ─── Verify View ──────────────────────────────────────────────────────────────

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ยืนยันตัวตน", emoji="✅", style=discord.ButtonStyle.success, custom_id="persistent:verify")
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        gcfg = guild_cfg(interaction.guild_id)
        role_id = gcfg.get("verify_role_id") or gcfg.get("role_id")
        role = interaction.guild.get_role(int(role_id)) if role_id else None
        if not role:
            await interaction.followup.send("❌ ยังไม่ได้ตั้งค่าระบบยืนยัน กรุณาติดต่อ Admin", ephemeral=True)
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await interaction.guild.fetch_member(interaction.user.id)
        if role in member.roles:
            await interaction.followup.send(f"✅ คุณได้รับการยืนยันแล้ว! (Role: **{role.name}**)", ephemeral=True)
            return
        try:
            await member.add_roles(role, reason="Verify Bot")
            await interaction.followup.send(f"✅ ยืนยันตัวตนสำเร็จ! ได้รับ Role: **{role.name}**", ephemeral=True)
            print(f"[VERIFY] {member} → {role.name}")
        except discord.Forbidden:
            await interaction.followup.send("❌ Bot ไม่มีสิทธิ์กำหนด Role กรุณาตรวจสอบสิทธิ์ของ Bot", ephemeral=True)


# ─── Ticket Views ─────────────────────────────────────────────────────────────

class TicketOpenView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เปิด Ticket", emoji="🎫", style=discord.ButtonStyle.primary, custom_id="persistent:ticket_open")
    async def open_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        gcfg = guild_cfg(guild.id)

        existing = discord.utils.get(guild.text_channels, name=f"ticket-{interaction.user.name.lower()}")
        if existing:
            await interaction.followup.send(f"❌ คุณมี Ticket อยู่แล้วที่ {existing.mention}", ephemeral=True)
            return

        category_id = gcfg.get("ticket_category_id")
        category = guild.get_channel(int(category_id)) if category_id else None

        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
            guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, read_message_history=True, attach_files=True, embed_links=True),
        }
        staff_role_id = gcfg.get("ticket_staff_role_id")
        if staff_role_id:
            staff_role = guild.get_role(int(staff_role_id))
            if staff_role:
                overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)

        try:
            channel = await guild.create_text_channel(
                f"ticket-{interaction.user.name}",
                category=category,
                overwrites=overwrites,
                reason=f"Ticket by {interaction.user}"
            )
        except Exception as e:
            await interaction.followup.send(f"❌ สร้าง Ticket ไม่สำเร็จ: {e}", ephemeral=True)
            return

        embed = discord.Embed(
            title="🎫 Ticket เปิดแล้ว",
            description=f"สวัสดี {interaction.user.mention}!\nทีมงานจะตอบกลับโดยเร็ว\nกรุณาอธิบายปัญหาหรือรายการที่ต้องการ",
            color=0xDC2626
        )
        ticket_image = gcfg.get("ticket_image_url")
        if ticket_image:
            embed.set_image(url=ticket_image)
        embed.set_footer(text=f"{guild.name} • Ticket System")
        await channel.send(content=interaction.user.mention, embed=embed, view=TicketCloseView())
        await interaction.followup.send(f"✅ Ticket ถูกสร้างที่ {channel.mention}", ephemeral=True)
        print(f"[TICKET] {interaction.user} เปิด {channel.name}")


class TicketCloseView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="ปิด Ticket", emoji="🔒", style=discord.ButtonStyle.danger, custom_id="persistent:ticket_close")
    async def close_ticket(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        channel = interaction.channel
        guild = interaction.guild

        # หา owner จากชื่อช่อง ticket-username หรือ order-username
        owner = None
        for prefix in ("ticket-", "order-"):
            if channel.name.startswith(prefix):
                uname = channel.name[len(prefix):]
                owner = discord.utils.find(lambda m: m.name.lower() == uname.lower(), guild.members)
                break

        # ส่ง DM แจ้งปิด Ticket
        if owner and owner != guild.me:
            try:
                dm_embed = discord.Embed(
                    title="🔒 Ticket ถูกปิดแล้ว",
                    description=f"Ticket ของคุณใน **{guild.name}** ถูกปิดโดย {interaction.user.mention}\nหากมีคำถามเพิ่มเติมสามารถเปิด Ticket ใหม่ได้เลย",
                    color=0xDC2626
                )
                dm_embed.set_footer(text=f"{guild.name} • Ticket System")
                await owner.send(embed=dm_embed)
                print(f"[TICKET] ส่ง DM ถึง {owner}")
            except Exception:
                pass

        embed = discord.Embed(
            title="🔒 Ticket กำลังปิด",
            description=f"ปิดโดย {interaction.user.mention} — ลบช่องใน 5 วินาที",
            color=0x808080
        )
        await channel.send(embed=embed)
        await asyncio.sleep(5)
        try:
            await channel.delete(reason=f"Ticket closed by {interaction.user}")
        except Exception as e:
            await channel.send(f"❌ ลบช่องไม่สำเร็จ: {e}")


# ─── Giveaway View ────────────────────────────────────────────────────────────

class GiveawayView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="เข้าร่วม 🎉", style=discord.ButtonStyle.success, custom_id="persistent:giveaway_join")
    async def join(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cfg = load_config()
        gid = str(interaction.guild_id)
        msg_id = str(interaction.message.id)
        giveaways = cfg.get(gid, {}).get("giveaways", {})

        if msg_id not in giveaways:
            await interaction.followup.send("❌ Giveaway นี้ไม่พบในระบบ", ephemeral=True)
            return

        uid = str(interaction.user.id)
        participants = giveaways[msg_id].setdefault("participants", [])

        if uid in participants:
            participants.remove(uid)
            msg_text = "❌ ออกจาก Giveaway แล้ว"
        else:
            participants.append(uid)
            msg_text = "✅ เข้าร่วม Giveaway สำเร็จ!"

        save_config(cfg)
        await interaction.followup.send(msg_text, ephemeral=True)

        # อัพเดตจำนวนผู้เข้าร่วม
        try:
            count = len(participants)
            embed = interaction.message.embeds[0]
            new_embed = discord.Embed(title=embed.title, description=embed.description, color=embed.color)
            new_embed.set_footer(text=embed.footer.text if embed.footer else "")
            for field in embed.fields:
                if field.name == "ผู้เข้าร่วม":
                    new_embed.add_field(name="ผู้เข้าร่วม", value=f"🎟️ {count} คน", inline=True)
                else:
                    new_embed.add_field(name=field.name, value=field.value, inline=field.inline)
            await interaction.message.edit(embed=new_embed)
        except Exception:
            pass


# ─── Shop View ────────────────────────────────────────────────────────────────

async def open_order_channel(interaction: discord.Interaction, order_note: str = ""):
    await interaction.response.defer(ephemeral=True)
    guild = interaction.guild
    gcfg = guild_cfg(guild.id)

    existing = discord.utils.get(guild.text_channels, name=f"order-{interaction.user.name.lower()}")
    if existing:
        await interaction.followup.send(f"❌ คุณมี Order อยู่แล้วที่ {existing.mention}", ephemeral=True)
        return

    category_id = gcfg.get("ticket_category_id")
    category = guild.get_channel(int(category_id)) if category_id else None

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        interaction.user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True, attach_files=True, embed_links=True),
    }
    staff_role_id = gcfg.get("ticket_staff_role_id")
    if staff_role_id:
        staff_role = guild.get_role(int(staff_role_id))
        if staff_role:
            overwrites[staff_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, attach_files=True, embed_links=True)

    try:
        channel = await guild.create_text_channel(
            f"order-{interaction.user.name}",
            category=category,
            overwrites=overwrites,
        )
    except Exception as e:
        await interaction.followup.send(f"❌ สร้าง Order ไม่สำเร็จ: {e}", ephemeral=True)
        return

    note_text = f"\n\n**รายการที่เลือก:** {order_note}" if order_note else ""
    embed = discord.Embed(
        title="🛒 Order เปิดแล้ว",
        description=(
            f"สวัสดี {interaction.user.mention}!\n"
            "กรุณาระบุ:\n"
            "- รายการที่ต้องการสั่งซื้อ\n"
            "- ช่องทางชำระเงิน\n"
            "- ข้อมูลติดต่อ"
            f"{note_text}"
        ),
        color=0x00AA00
    )
    await channel.send(content=interaction.user.mention, embed=embed, view=TicketCloseView())
    await interaction.followup.send(f"✅ ช่อง Order ถูกสร้างที่ {channel.mention}", ephemeral=True)


class NitroProductSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label="Nitro Basic", description="เลือกแพ็กเกจ Nitro Basic", emoji="✨", value="Nitro Basic"),
            discord.SelectOption(label="Nitro", description="เลือกแพ็กเกจ Nitro ตัวเต็ม", emoji="💎", value="Nitro"),
            discord.SelectOption(label="Server Boost", description="เลือกแพ็กเกจบูสต์เซิร์ฟเวอร์", emoji="🚀", value="Server Boost"),
        ]
        super().__init__(
            placeholder="📦 เลือกประเภทหมวดหมู่สินค้า",
            min_values=1,
            max_values=1,
            options=options,
            custom_id="persistent:nitro_product_select",
            row=0
        )

    async def callback(self, interaction: discord.Interaction):
        selected = self.values[0]
        await interaction.response.send_message(
            f"✅ เลือก **{selected}** แล้ว กดปุ่ม **สั่งซื้อ** เพื่อเปิดช่อง Order ได้เลย",
            ephemeral=True
        )


class NitroShopPanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)
        self.add_item(NitroProductSelect())

    @discord.ui.button(label="เติมเงิน", emoji="💵", style=discord.ButtonStyle.success, custom_id="persistent:shop_topup", row=1)
    async def topup(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_order_channel(interaction, "เติมเงิน")

    @discord.ui.button(label="เช็คยอดเงิน", emoji="👛", style=discord.ButtonStyle.primary, custom_id="persistent:shop_balance", row=1)
    async def balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("💰 ระบบเช็คยอดเงินยังไม่ได้เชื่อมฐานข้อมูล กรุณาติดต่อแอดมิน", ephemeral=True)

    @discord.ui.button(label="ประวัติซื้อสินค้า", emoji="📦", style=discord.ButtonStyle.secondary, custom_id="persistent:shop_history", row=1)
    async def history(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("📋 ระบบประวัติการซื้อยังไม่ได้เชื่อมฐานข้อมูล กรุณาติดต่อแอดมิน", ephemeral=True)

    @discord.ui.button(label="สั่งซื้อ", emoji="🛒", style=discord.ButtonStyle.success, custom_id="persistent:shop_order", row=1)
    async def order(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_order_channel(interaction, "Discord Nitro")


class ShopBuyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="🛒 สั่งซื้อ", style=discord.ButtonStyle.success, custom_id="persistent:shop_buy")
    async def buy(self, interaction: discord.Interaction, button: discord.ui.Button):
        await open_order_channel(interaction)


# ─── Bot ──────────────────────────────────────────────────────────────────────

class VerifyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        intents.members = True  # ต้องเปิด Server Members Intent ใน Developer Portal ด้วย
        intents.messages = True
        intents.voice_states = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        for view in [VerifyView(), TicketOpenView(), TicketCloseView(), GiveawayView(), ShopBuyView(), NitroShopPanelView()]:
            self.add_view(view)
        self.check_giveaways.start()
        self.keep_voice_connected.start()

    async def on_ready(self):
        await self.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="Bunmee Store 🚀"))
        print(f"[BOT] ✅ Online: {self.user} | Servers: {len(self.guilds)}")
        print("[BOT] ✅ Loaded SHOP UI v2 (Nitro dropdown + buttons)")
        # copy global commands → guild แล้ว sync ทันที (ไม่ต้องรอ 1 ชั่วโมง)
        for guild in self.guilds:
            try:
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                print(f"[BOT] Synced to {guild.name}")
            except Exception as e:
                print(f"[BOT] Sync failed {guild.name}: {e}")

    async def on_member_join(self, member: discord.Member):
        gcfg = guild_cfg(member.guild.id)
        ch_id = gcfg.get("welcome_channel_id")
        if not ch_id:
            return
        channel = member.guild.get_channel(int(ch_id))
        if not channel:
            return
        embed = discord.Embed(
            title=f"🎉 ยินดีต้อนรับสู่ {member.guild.name}!",
            description=f"สวัสดี {member.mention}!\nยินดีต้อนรับเข้าสู่เซิร์ฟเวอร์\nกรุณายืนยันตัวตนเพื่อเข้าใช้งาน",
            color=0xDC2626
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.set_footer(
            text=f"{member.guild.name} • สมาชิกคนที่ {member.guild.member_count}",
            icon_url=member.guild.icon.url if member.guild.icon else None
        )
        try:
            await channel.send(embed=embed)
        except Exception:
            pass

    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        await self.update_review_counter(message)
        await self.process_commands(message)

    async def update_review_counter(self, message: discord.Message):
        channel = message.channel
        if not isinstance(channel, discord.TextChannel):
            return

        cfg = load_config()
        gid = str(message.guild.id)
        guild_data = cfg.setdefault(gid, {})
        counters = guild_data.setdefault("review_counters", {})
        channel_id = str(channel.id)
        counter = counters.get(channel_id)

        if not counter:
            prefix, current_count = parse_review_counter_channel_name(channel.name)
            if prefix is None:
                return
            counter = {
                "base_count": current_count,
                "prefix": prefix,
                "users": []
            }
            counters[channel_id] = counter

        user_id = str(message.author.id)
        users = counter.setdefault("users", [])
        if user_id in users:
            return

        users.append(user_id)
        base_count = int(counter.get("base_count", 0))
        new_count = base_count + len(users)
        prefix = counter.get("prefix")

        if not prefix:
            prefix, current_count = parse_review_counter_channel_name(channel.name)
            if prefix is None:
                return
            counter["prefix"] = prefix
            if not counter.get("base_count"):
                counter["base_count"] = current_count
                base_count = current_count
                new_count = base_count + len(users)

        save_config(cfg)

        new_name = f"{prefix}{new_count}"
        if channel.name == new_name:
            return
        try:
            await channel.edit(name=new_name, reason="Review counter updated")
        except discord.Forbidden:
            print(f"[REVIEW] Missing permission to rename {channel.name}")
        except Exception as e:
            print(f"[REVIEW] Failed to rename {channel.name}: {e}")

    @tasks.loop(minutes=1)
    async def check_giveaways(self):
        cfg = load_config()
        changed = False
        for gid, gcfg in list(cfg.items()):
            giveaways = gcfg.get("giveaways", {})
            ended = []
            for msg_id, gdata in giveaways.items():
                end_iso = gdata.get("end_time")
                if not end_iso or datetime.now(timezone.utc) < datetime.fromisoformat(end_iso):
                    continue
                guild = self.get_guild(int(gid))
                if not guild:
                    ended.append(msg_id)
                    continue
                channel = guild.get_channel(int(gdata.get("channel_id", 0)))
                participants = gdata.get("participants", [])
                prize = gdata.get("prize", "รางวัล")
                n = int(gdata.get("winners", 1))
                if participants:
                    winners = random.sample(participants, min(n, len(participants)))
                    winner_text = " ".join(f"<@{w}>" for w in winners)
                else:
                    winner_text = "ไม่มีผู้เข้าร่วม"
                if channel:
                    try:
                        msg = await channel.fetch_message(int(msg_id))
                        result_embed = discord.Embed(
                            title="🏆 Giveaway สิ้นสุดแล้ว!",
                            description=f"**รางวัล:** {prize}\n**ผู้ชนะ:** {winner_text}",
                            color=0xFFD700
                        )
                        await msg.edit(embed=result_embed, view=None)
                        await channel.send(f"🎊 ขอแสดงความยินดีกับ {winner_text}! ได้รับ **{prize}**!")
                    except Exception:
                        pass
                ended.append(msg_id)
                changed = True
            for mid in ended:
                del cfg[gid]["giveaways"][mid]
        if changed:
            save_config(cfg)

    @check_giveaways.before_loop
    async def before_giveaways(self):
        await self.wait_until_ready()

    @tasks.loop(seconds=30)
    async def keep_voice_connected(self):
        for guild in self.guilds:
            gcfg = guild_cfg(guild.id)
            channel_id = gcfg.get("stay_voice_channel_id")
            if not channel_id:
                continue

            channel = guild.get_channel(int(channel_id))
            if not isinstance(channel, discord.VoiceChannel):
                continue

            voice_client = guild.voice_client
            try:
                if voice_client and voice_client.is_connected():
                    if voice_client.channel.id != channel.id:
                        await voice_client.move_to(channel)
                    continue
                await channel.connect(self_mute=True, self_deaf=False, reconnect=True)
                print(f"[VOICE] Joined {guild.name} / {channel.name}")
            except discord.ClientException:
                pass
            except Exception as e:
                print(f"[VOICE] Failed to join {guild.name} / {channel.name}: {e}")

    @keep_voice_connected.before_loop
    async def before_keep_voice_connected(self):
        await self.wait_until_ready()


bot = VerifyBot()


async def health_check(request):
    return web.Response(text="Bunmee Store bot is online")


async def start_health_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)

    runner = web.AppRunner(app)
    await runner.setup()

    port = int(os.getenv("PORT", "8080"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[WEB] Health server running on port {port}")


async def run_bot_with_health(token: str):
    await start_health_server()
    async with bot:
        await bot.start(token)


# ─── Global error handler ─────────────────────────────────────────────────────

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    msg = f"❌ เกิดข้อผิดพลาด: {error}"
    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass
    print(f"[ERROR] {interaction.command.name if interaction.command else '?'}: {error}")


# ─── Verify ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="setup_verify", description="ตั้งค่าระบบยืนยันตัวตน — รันในช่องที่ต้องการวางปุ่ม (Admin)")
@app_commands.describe(role="Role ที่จะมอบ", title="หัวข้อ embed", message="ข้อความใน embed", image_url="URL รูปภาพ", color="สี hex เช่น ff0000")
@app_commands.default_permissions(administrator=True)
async def setup_verify(interaction: discord.Interaction, role: discord.Role, title: str = None,
                       message: str = "กรุณายืนยันตัวตนเพื่อเข้าใช้งานเซิร์ฟเวอร์",
                       image_url: str = None, color: str = "DC2626"):
    await interaction.response.defer(ephemeral=True)
    try:
        embed_color = int(color.lstrip("#"), 16)
    except ValueError:
        embed_color = 0xDC2626
    channel_id = interaction.channel_id
    update_guild(interaction.guild_id, verify_role_id=str(role.id), verify_channel_id=str(channel_id))
    final_image = image_url or (interaction.guild.icon.url if interaction.guild.icon else None)
    embed = discord.Embed(title=title or interaction.guild.name, description=f"🛡️  **{message}**", color=embed_color)
    embed.set_footer(text=f"{interaction.guild.name} • Powered by Verify Bot",
                     icon_url=interaction.guild.icon.url if interaction.guild.icon else None)
    if final_image:
        embed.set_image(url=final_image)
    try:
        channel = interaction.channel or await interaction.guild.fetch_channel(channel_id)
        await channel.send(embed=embed, view=VerifyView())
    except discord.Forbidden:
        await interaction.followup.send("❌ Bot ไม่มีสิทธิ์ส่งข้อความในช่องนี้", ephemeral=True)
        return
    except Exception as e:
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)
        return
    await interaction.followup.send(f"✅ ตั้งค่าสำเร็จ!\n📌 ช่อง: <#{channel_id}>\n🎖️ Role: **{role.name}**", ephemeral=True)


@bot.tree.command(name="verify_info", description="ดูการตั้งค่าระบบยืนยัน (Admin)")
@app_commands.default_permissions(administrator=True)
async def verify_info(interaction: discord.Interaction):
    gcfg = guild_cfg(interaction.guild_id)
    if "verify_role_id" not in gcfg:
        await interaction.response.send_message("❌ ยังไม่ได้ตั้งค่า", ephemeral=True)
        return
    role = interaction.guild.get_role(int(gcfg["verify_role_id"]))
    embed = discord.Embed(title="⚙️ การตั้งค่าระบบยืนยัน", color=0xDC2626)
    embed.add_field(name="Role", value=role.mention if role else "❌ ไม่พบ", inline=True)
    embed.add_field(name="ช่อง", value=f"<#{gcfg['verify_channel_id']}>", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


# ─── Welcome ──────────────────────────────────────────────────────────────────

@bot.tree.command(name="setup_welcome", description="ตั้งค่าห้อง Welcome — รันในช่องที่ต้องการ (Admin)")
@app_commands.default_permissions(administrator=True)
async def setup_welcome(interaction: discord.Interaction):
    update_guild(interaction.guild_id, welcome_channel_id=str(interaction.channel_id))
    await interaction.response.send_message(
        f"✅ ตั้งค่า Welcome ที่ <#{interaction.channel_id}> แล้ว", ephemeral=True)


# ─── Stay Voice ───────────────────────────────────────────────────────────────

@bot.tree.command(name="setup_stay_voice", description="ตั้งห้องเสียงที่ให้บอทเข้าไปอยู่ตลอดเวลา (Admin)")
@app_commands.describe(channel="ห้องเสียงที่ต้องการให้บอทค้างอยู่")
@app_commands.default_permissions(administrator=True)
async def setup_stay_voice(interaction: discord.Interaction, channel: discord.VoiceChannel = None):
    await interaction.response.defer(ephemeral=True)
    target_channel = channel

    if target_channel is None and isinstance(interaction.user, discord.Member) and interaction.user.voice:
        target_channel = interaction.user.voice.channel

    if target_channel is None:
        await interaction.followup.send("❌ เลือกห้องเสียง หรือเข้าห้องเสียงก่อนแล้วใช้คำสั่งนี้อีกครั้ง", ephemeral=True)
        return

    update_guild(interaction.guild_id, stay_voice_channel_id=str(target_channel.id))

    voice_client = interaction.guild.voice_client
    try:
        if voice_client and voice_client.is_connected():
            if voice_client.channel.id != target_channel.id:
                await voice_client.move_to(target_channel)
        else:
            await target_channel.connect(self_mute=True, self_deaf=False, reconnect=True)
    except Exception as e:
        await interaction.followup.send(
            f"⚠️ บันทึกห้องแล้ว แต่บอทยังเข้าห้องเสียงไม่ได้: {e}\n"
            "เช็ค Permission: View Channel / Connect",
            ephemeral=True
        )
        return

    await interaction.followup.send(f"✅ ตั้งให้บอทอยู่ห้องเสียง **{target_channel.name}** ตลอดเวลาแล้ว", ephemeral=True)


@bot.tree.command(name="stop_stay_voice", description="ปิดระบบให้บอทค้างอยู่ห้องเสียง (Admin)")
@app_commands.default_permissions(administrator=True)
async def stop_stay_voice(interaction: discord.Interaction):
    cfg = load_config()
    gid = str(interaction.guild_id)
    if gid in cfg:
        cfg[gid].pop("stay_voice_channel_id", None)
        save_config(cfg)

    voice_client = interaction.guild.voice_client
    if voice_client and voice_client.is_connected():
        await voice_client.disconnect(force=True)

    await interaction.response.send_message("✅ ปิดระบบค้างห้องเสียงแล้ว", ephemeral=True)


# ─── Ticket ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="setup_ticket", description="ตั้งค่าระบบ Ticket — รันในช่องที่ต้องการวางปุ่ม (Admin)")
@app_commands.describe(staff_role="Role ที่จะเห็น Ticket ทั้งหมด", category="Category ที่จะสร้างช่อง Ticket")
@app_commands.describe(image_url="URL รูป/GIF banner ใน embed Ticket")
@app_commands.default_permissions(administrator=True)
async def setup_ticket(interaction: discord.Interaction, staff_role: discord.Role = None, category: discord.CategoryChannel = None, image_url: str = None):
    await interaction.response.defer(ephemeral=True)
    gcfg = guild_cfg(interaction.guild_id)
    updates = {}
    if staff_role:
        updates["ticket_staff_role_id"] = str(staff_role.id)
    if category:
        updates["ticket_category_id"] = str(category.id)
    if image_url:
        updates["ticket_image_url"] = image_url
    update_guild(interaction.guild_id, **updates)

    embed = discord.Embed(
        title="🎫 ระบบ Support Ticket",
        description="กดปุ่มด้านล่างเพื่อเปิด Ticket\nทีมงานจะตอบกลับโดยเร็วที่สุด",
        color=0xDC2626
    )
    final_image = image_url or gcfg.get("ticket_image_url")
    if final_image:
        embed.set_image(url=final_image)
    embed.set_footer(text=f"{interaction.guild.name} • Ticket System")
    try:
        channel = interaction.channel or await interaction.guild.fetch_channel(interaction.channel_id)
        await channel.send(embed=embed, view=TicketOpenView())
    except discord.Forbidden:
        await interaction.followup.send("❌ Bot ไม่มีสิทธิ์ส่งข้อความในช่องนี้", ephemeral=True)
        return
    await interaction.followup.send(
        f"✅ ตั้งค่า Ticket สำเร็จ!\n"
        f"📌 ช่อง: <#{interaction.channel_id}>\n"
        f"👥 Staff: {staff_role.mention if staff_role else 'ไม่ได้ตั้ง'}\n"
        f"📁 Category: {category.name if category else 'ไม่ได้ตั้ง'}\n"
        f"GIF/Banner: {final_image if final_image else 'ไม่ได้ตั้ง'}",
        ephemeral=True
    )


@bot.tree.command(name="setup_review_counter", description="ตั้งช่องนี้ให้นับรีวิวจากคนที่มาพิมพ์แบบไม่ซ้ำ (Admin)")
@app_commands.describe(start_number="เลขเริ่มต้นท้ายชื่อช่อง เช่น 10684 (ไม่ใส่จะอ่านจากชื่อช่องปัจจุบัน)")
@app_commands.default_permissions(administrator=True)
async def setup_review_counter(interaction: discord.Interaction, start_number: int = None):
    channel = interaction.channel or await interaction.guild.fetch_channel(interaction.channel_id)
    if not isinstance(channel, discord.TextChannel):
        await interaction.response.send_message("❌ คำสั่งนี้ใช้ได้เฉพาะช่องข้อความ", ephemeral=True)
        return

    prefix, current_count = parse_review_counter_channel_name(channel.name)
    if prefix is None:
        await interaction.response.send_message("❌ ชื่อช่องต้องมีคำว่า รีวิว และลงท้ายด้วยตัวเลข เช่น 📝・รีวิวบริการ・10684", ephemeral=True)
        return

    base_count = start_number if start_number is not None else current_count
    cfg = load_config()
    cfg.setdefault(str(interaction.guild_id), {}).setdefault("review_counters", {})[str(channel.id)] = {
        "base_count": base_count,
        "prefix": prefix,
        "users": []
    }
    save_config(cfg)

    new_name = f"{prefix}{base_count}"
    if channel.name != new_name:
        try:
            await channel.edit(name=new_name, reason="Review counter setup")
        except discord.Forbidden:
            await interaction.response.send_message("❌ Bot ไม่มีสิทธิ์แก้ชื่อช่อง", ephemeral=True)
            return

    await interaction.response.send_message(
        f"✅ ตั้งช่องรีวิวแล้ว\n"
        f"ช่อง: {channel.mention}\n"
        f"เลขเริ่มต้น: {base_count}\n"
        f"จากนี้จะนับเฉพาะคนที่มาพิมพ์ในช่องนี้ และไม่นับคนเดิมซ้ำ",
        ephemeral=True
    )


# ─── Giveaway ─────────────────────────────────────────────────────────────────

@bot.tree.command(name="giveaway", description="เริ่ม Giveaway ในช่องนี้ (Admin)")
@app_commands.describe(prize="รางวัล", duration="ระยะเวลา เช่น 10m 1h 1d", winners="จำนวนผู้ชนะ")
@app_commands.default_permissions(administrator=True)
async def giveaway_cmd(interaction: discord.Interaction, prize: str, duration: str, winners: int = 1):
    await interaction.response.defer(ephemeral=True)
    unit = duration[-1].lower()
    try:
        amount = int(duration[:-1])
    except ValueError:
        await interaction.followup.send("❌ รูปแบบเวลาไม่ถูกต้อง ใช้ 10m, 1h, 1d", ephemeral=True)
        return
    multipliers = {"m": 60, "h": 3600, "d": 86400}
    if unit not in multipliers:
        await interaction.followup.send("❌ ใช้ m (นาที), h (ชั่วโมง), d (วัน)", ephemeral=True)
        return
    end_time = datetime.now(timezone.utc) + timedelta(seconds=amount * multipliers[unit])

    embed = discord.Embed(title="🎉 GIVEAWAY!", description=f"**รางวัล:** {prize}\n\nกดปุ่มด้านล่างเพื่อเข้าร่วม!", color=0xFFD700)
    embed.add_field(name="สิ้นสุด", value=f"<t:{int(end_time.timestamp())}:R>", inline=True)
    embed.add_field(name="ผู้ชนะ", value=f"🏆 {winners} คน", inline=True)
    embed.add_field(name="ผู้เข้าร่วม", value="🎟️ 0 คน", inline=True)
    embed.set_footer(text=f"โดย {interaction.user.name}")

    try:
        channel = interaction.channel or await interaction.guild.fetch_channel(interaction.channel_id)
        msg = await channel.send(embed=embed, view=GiveawayView())
    except Exception as e:
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)
        return

    cfg = load_config()
    cfg.setdefault(str(interaction.guild_id), {}).setdefault("giveaways", {})[str(msg.id)] = {
        "prize": prize, "winners": winners,
        "channel_id": str(interaction.channel_id),
        "end_time": end_time.isoformat(),
        "participants": []
    }
    save_config(cfg)
    await interaction.followup.send(f"✅ Giveaway เริ่มแล้ว! สิ้นสุดใน {duration}", ephemeral=True)


# ─── Shop ─────────────────────────────────────────────────────────────────────

@bot.tree.command(name="setup_shop", description="ส่ง embed ร้านค้าในช่องนี้ (Admin)")
@app_commands.describe(shop_type="ประเภทร้านค้า", image_url="URL รูปใหญ่/banner ใน embed (ไม่ใส่ก็ใช้ค่าที่เคยตั้งไว้)")
@app_commands.choices(shop_type=[
    app_commands.Choice(name="App Premium (Netflix, YouTube ฯลฯ)", value="apps"),
    app_commands.Choice(name="Discord Nitro", value="nitro"),
])
@app_commands.default_permissions(administrator=True)
async def setup_shop(interaction: discord.Interaction, shop_type: str, image_url: str = None):
    await interaction.response.defer(ephemeral=True)
    gcfg = guild_cfg(interaction.guild_id)
    guild = interaction.guild
    if image_url:
        update_guild(interaction.guild_id, **{f"shop_{shop_type}_image_url": image_url})

    if shop_type == "apps":
        products = gcfg.get("shop_apps", [
            {"name": "Netflix Premium", "price": "xxx บาท/เดือน", "desc": "4K | 4 อุปกรณ์ | ไม่มีโฆษณา"},
            {"name": "YouTube Premium", "price": "xxx บาท/เดือน", "desc": "ไม่มีโฆษณา | Download | Background"},
            {"name": "Spotify Premium", "price": "xxx บาท/เดือน", "desc": "ฟังเพลงไม่จำกัด | Download | ไม่มีโฆษณา"},
        ])
        embed = discord.Embed(title="📱 APP PREMIUM SHOP", description="แอปพรีเมี่ยมราคาถูก คุณภาพเต็ม ๆ\nกด **สั่งซื้อ** เพื่อเปิดช่อง Order", color=0xE50914)
        view = ShopBuyView()
    else:
        products = gcfg.get("shop_nitro", [
            {"name": "Nitro Basic", "price": "xxx บาท/เดือน", "desc": "Custom emoji | Animated avatar | 50MB upload"},
            {"name": "Nitro", "price": "xxx บาท/เดือน", "desc": "Server Boost | 500MB upload | ทุกอย่างใน Basic"},
        ])
        product_lines = "\n".join(
            f"> ✨ **{p['name']}**\n> 💰 {p['price']}\n> 📋 {p['desc']}"
            for p in products
        )
        embed = discord.Embed(
            title="🌸 ซื้อไนโตรอัตโนมัติ 🌸",
            description=(
                "```"
                "\n• · ˚ ༘─────────────────────༘˚ · •\n\n"
                "✦ จำหน่ายไนโตรเบสิก - ไนโตรเต็ม\n"
                "✦ สำหรับแอคเคาท์ที่ไม่เคยเติมไนโตร\n"
                "✦ ในโปรโมชั่น 1 เดือน และ 3 เดือน\n"
                "✦ ในรูปแบบ Gift 1 เดือน\n\n"
                "• · ˚ ༘─────────────────────༘˚ · •"
                "```\n"
                "```diff\n! โปรดอ่านเงื่อนไขก่อนชำระสินค้า !\n```\n"
                f"{product_lines}"
            ),
            color=0xFF0033
        )
        view = NitroShopPanelView()

    if shop_type == "apps":
        for p in products:
            embed.add_field(name=f"✨ {p['name']}", value=f"💰 {p['price']}\n📋 {p['desc']}", inline=True)
    final_image = image_url or gcfg.get(f"shop_{shop_type}_image_url")
    if final_image:
        embed.set_image(url=final_image)
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)
    embed.set_footer(text=f"{guild.name} • Shop")

    try:
        channel = interaction.channel or await interaction.guild.fetch_channel(interaction.channel_id)
        await channel.send(embed=embed, view=view)
    except Exception as e:
        await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)
        return
    await interaction.followup.send("✅ ส่ง Shop embed สำเร็จ! (SHOP UI v2)", ephemeral=True)


@bot.tree.command(name="shop_product", description="เพิ่ม/ลบสินค้าในร้าน (Admin)")
@app_commands.describe(action="เพิ่มหรือลบ", shop_type="ประเภทร้านค้า", name="ชื่อสินค้า", price="ราคา", description="รายละเอียด")
@app_commands.choices(
    action=[app_commands.Choice(name="เพิ่ม", value="add"), app_commands.Choice(name="ลบ", value="remove")],
    shop_type=[app_commands.Choice(name="App Premium", value="apps"), app_commands.Choice(name="Nitro", value="nitro")]
)
@app_commands.default_permissions(administrator=True)
async def shop_product(interaction: discord.Interaction, action: str, shop_type: str, name: str, price: str = "", description: str = ""):
    cfg = load_config()
    gid = str(interaction.guild_id)
    key = f"shop_{shop_type}"
    products = cfg.setdefault(gid, {}).setdefault(key, [])
    if action == "add":
        products.append({"name": name, "price": price, "desc": description})
        save_config(cfg)
        await interaction.response.send_message(f"✅ เพิ่มสินค้า **{name}** สำเร็จ\nใช้ `/setup_shop` ใหม่เพื่ออัพเดต embed", ephemeral=True)
    else:
        before = len(products)
        products[:] = [p for p in products if p["name"].lower() != name.lower()]
        save_config(cfg)
        if len(products) < before:
            await interaction.response.send_message(f"✅ ลบสินค้า **{name}** สำเร็จ", ephemeral=True)
        else:
            await interaction.response.send_message(f"❌ ไม่พบสินค้า **{name}**", ephemeral=True)


# ─── Credit ───────────────────────────────────────────────────────────────────

@bot.tree.command(name="setup_credit", description="ตั้งค่าช่อง Credit Log — รันในช่องที่ต้องการ (Admin)")
@app_commands.default_permissions(administrator=True)
async def setup_credit(interaction: discord.Interaction):
    update_guild(interaction.guild_id, credit_channel_id=str(interaction.channel_id))
    await interaction.response.send_message(f"✅ ตั้งค่าช่อง Credit Log ที่ <#{interaction.channel_id}> แล้ว", ephemeral=True)


@bot.tree.command(name="credit", description="บันทึกการส่งของให้ลูกค้าเรียบร้อย (Admin)")
@app_commands.describe(user="ลูกค้า", item="รายการที่ส่ง", note="หมายเหตุ")
@app_commands.default_permissions(administrator=True)
async def credit(interaction: discord.Interaction, user: discord.Member, item: str, note: str = ""):
    await interaction.response.defer(ephemeral=True)
    gcfg = guild_cfg(interaction.guild_id)
    ch_id = gcfg.get("credit_channel_id")

    embed = discord.Embed(title="✅ ส่งของเรียบร้อย", color=0x00AA00, timestamp=datetime.now(timezone.utc))
    embed.add_field(name="ลูกค้า", value=user.mention, inline=True)
    embed.add_field(name="รายการ", value=item, inline=True)
    embed.add_field(name="ผู้ดำเนินการ", value=interaction.user.mention, inline=True)
    if note:
        embed.add_field(name="หมายเหตุ", value=note, inline=False)

    sent_log = False
    if ch_id:
        log_channel = interaction.guild.get_channel(int(ch_id))
        if log_channel:
            try:
                await log_channel.send(embed=embed)
                sent_log = True
            except Exception:
                pass

    # ส่ง DM ให้ลูกค้า
    try:
        dm_embed = discord.Embed(
            title="📦 รายการของคุณถูกส่งแล้ว!",
            description=f"**รายการ:** {item}" + (f"\n**หมายเหตุ:** {note}" if note else ""),
            color=0x00AA00
        )
        dm_embed.set_footer(text=interaction.guild.name)
        await user.send(embed=dm_embed)
    except Exception:
        pass

    await interaction.followup.send(
        f"✅ บันทึกสำเร็จ!\n👤 {user.mention} — **{item}**"
        + (f"\n📋 Log บันทึกไปที่ช่อง credit แล้ว" if sent_log else "\n⚠️ ยังไม่ได้ตั้งช่อง Credit Log (ใช้ /setup_credit)"),
        ephemeral=True
    )


# ─── Entry point ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    token = os.getenv("VERIFY_BOT_TOKEN")
    if not token:
        print("=" * 50)
        print("  Bunmee Store Discord Bot")
        print("=" * 50)
        token = input("กรอก Bot Token: ").strip()
        if not token:
            print("❌ ต้องการ Token เพื่อรัน Bot")
            sys.exit(1)

    import time
    while True:
        try:
            asyncio.run(run_bot_with_health(token))
            break
        except discord.LoginFailure:
            print("❌ Token ไม่ถูกต้อง")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n[BOT] ปิด Bot แล้ว")
            break
        except Exception as e:
            print(f"[BOT] Crash: {e} — restarting in 30s...")
            time.sleep(30)
            bot = VerifyBot()
