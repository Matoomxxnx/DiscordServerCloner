"""
Discord Verification Role Bot
ตั้งค่าด้วย /setup_verify แล้วสมาชิกกดปุ่มยืนยันตัวตนเพื่อรับ Role
"""

import discord
from discord import app_commands
from discord.ext import commands
import json
import os
import sys

CONFIG_FILE = os.path.join(os.path.dirname(__file__), "verify_config.json")


# ─────────────────────────────────────────────
# Config helpers
# ─────────────────────────────────────────────

def load_config() -> dict:
    # GitHub Actions: อ่านจาก env var VERIFY_CONFIG (JSON string)
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


# ─────────────────────────────────────────────
# Persistent verify button view
# ─────────────────────────────────────────────

class VerifyView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)  # ทำงานตลอดแม้ bot restart

    @discord.ui.button(
        label="ยืนยันตัวตน",
        emoji="✅",
        style=discord.ButtonStyle.success,
        custom_id="persistent:verify"
    )
    async def verify_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        config = load_config()

        if guild_id not in config:
            await interaction.followup.send(
                "❌ ยังไม่ได้ตั้งค่าระบบยืนยัน กรุณาติดต่อ Admin",
                ephemeral=True
            )
            return

        role_id = config[guild_id].get("role_id")
        role = interaction.guild.get_role(int(role_id)) if role_id else None

        if not role:
            await interaction.followup.send(
                "❌ ไม่พบ Role ที่กำหนดไว้ กรุณาติดต่อ Admin",
                ephemeral=True
            )
            return

        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await interaction.guild.fetch_member(interaction.user.id)

        if role in member.roles:
            await interaction.followup.send(
                f"✅ คุณได้รับการยืนยันแล้ว! (Role: **{role.name}**)",
                ephemeral=True
            )
            return

        try:
            await member.add_roles(role, reason="Verify Bot")
            await interaction.followup.send(
                f"✅ ยืนยันตัวตนสำเร็จ!\nคุณได้รับ Role: **{role.name}**",
                ephemeral=True
            )
            print(f"[VERIFY] {member} ({member.id}) ได้รับ Role '{role.name}' ใน {interaction.guild.name}")
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ Bot ไม่มีสิทธิ์กำหนด Role กรุณาตรวจสอบสิทธิ์ของ Bot",
                ephemeral=True
            )
        except Exception as e:
            await interaction.followup.send(f"❌ เกิดข้อผิดพลาด: {e}", ephemeral=True)


# ─────────────────────────────────────────────
# Bot class
# ─────────────────────────────────────────────

class VerifyBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.none()
        intents.guilds = True
        super().__init__(command_prefix="!", intents=intents)

    async def setup_hook(self):
        self.add_view(VerifyView())
        try:
            await self.tree.sync()
            print("[BOT] Slash commands synced.")
        except Exception as e:
            print(f"[BOT] Warning: failed to sync commands: {e}")

    async def on_ready(self):
        activity = discord.Activity(
            type=discord.ActivityType.watching,
            name="การยืนยันตัวตน"
        )
        await self.change_presence(activity=activity)
        print(f"[BOT] ✅ Online as {self.user}  (ID: {self.user.id})")
        print(f"[BOT] Servers: {len(self.guilds)}")


bot = VerifyBot()


# ─────────────────────────────────────────────
# Global app command error handler
# ─────────────────────────────────────────────

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


# ─────────────────────────────────────────────
# Slash commands
# ─────────────────────────────────────────────

@bot.tree.command(name="setup_verify", description="ตั้งค่าระบบยืนยันตัวตน (Admin เท่านั้น)")
@app_commands.describe(
    channel="ช่องที่จะส่งข้อความยืนยัน",
    role="Role ที่จะมอบให้เมื่อยืนยันสำเร็จ",
    title="หัวข้อ embed (default: ชื่อ server)",
    message="ข้อความใน embed",
    image_url="URL รูปภาพใน embed (ไม่จำเป็น)",
    color="สี hex ของ embed เช่น ff0000 (default: แดง)",
)
@app_commands.default_permissions(administrator=True)
async def setup_verify(
    interaction: discord.Interaction,
    channel: discord.abc.GuildChannel,
    role: discord.Role,
    title: str = None,
    message: str = "! กรุณายืนยันตัวตนเพื่อเข้าใช้งานเซิร์ฟเวอร์",
    image_url: str = None,
    color: str = "DC2626",
):
    await interaction.response.defer(ephemeral=True)

    if not isinstance(channel, discord.abc.Messageable):
        await interaction.followup.send(
            "❌ กรุณาเลือกช่องข้อความ (Text Channel) เท่านั้น ไม่สามารถใช้ Forum หรือ Category ได้",
            ephemeral=True
        )
        return

    # ตรวจสอบ hex color
    try:
        embed_color = int(color.lstrip("#"), 16)
    except ValueError:
        embed_color = 0xDC2626

    # บันทึก config
    cfg = load_config()
    cfg[str(interaction.guild_id)] = {
        "role_id": str(role.id),
        "channel_id": str(channel.id),
    }
    save_config(cfg)

    # ถ้าไม่ได้ใส่รูป → ใช้โลโก้ server อัตโนมัติ
    final_image = image_url or (interaction.guild.icon.url if interaction.guild.icon else None)

    # สร้าง embed
    embed = discord.Embed(
        title=title or interaction.guild.name,
        description=f"🛡️  **{message}**",
        color=embed_color
    )
    embed.set_footer(
        text=f"{interaction.guild.name} • Powered by Verify Bot",
        icon_url=interaction.guild.icon.url if interaction.guild.icon else None
    )
    if final_image:
        embed.set_image(url=final_image)

    view = VerifyView()
    try:
        await channel.send(embed=embed, view=view)
    except discord.Forbidden:
        await interaction.followup.send(
            "❌ Bot ไม่มีสิทธิ์ส่งข้อความในช่องนี้ กรุณาเพิ่มสิทธิ์ Send Messages และ Embed Links ให้ Bot",
            ephemeral=True
        )
        return
    except Exception as e:
        await interaction.followup.send(f"❌ ส่งข้อความยืนยันไม่สำเร็จ: {e}", ephemeral=True)
        return

    await interaction.followup.send(
        f"✅ ตั้งค่าสำเร็จ!\n"
        f"📌 ช่อง: {channel.mention}\n"
        f"🎖️ Role: **{role.name}**",
        ephemeral=True
    )


@bot.tree.command(name="verify_info", description="ดูการตั้งค่าระบบยืนยันตัวตนปัจจุบัน")
@app_commands.default_permissions(administrator=True)
async def verify_info(interaction: discord.Interaction):
    cfg = load_config()
    guild_id = str(interaction.guild_id)

    if guild_id not in cfg:
        await interaction.response.send_message("❌ ยังไม่ได้ตั้งค่าระบบยืนยัน", ephemeral=True)
        return

    data = cfg[guild_id]
    role = interaction.guild.get_role(int(data["role_id"]))
    channel = interaction.guild.get_channel(int(data["channel_id"]))

    embed = discord.Embed(title="⚙️ การตั้งค่าระบบยืนยันตัวตน", color=0xDC2626)
    embed.add_field(name="Role", value=role.mention if role else "❌ ไม่พบ", inline=True)
    embed.add_field(name="ช่อง", value=channel.mention if channel else "❌ ไม่พบ", inline=True)
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="verify_reset", description="ลบการตั้งค่าระบบยืนยันของ server นี้")
@app_commands.default_permissions(administrator=True)
async def verify_reset(interaction: discord.Interaction):
    cfg = load_config()
    guild_id = str(interaction.guild_id)
    if guild_id in cfg:
        del cfg[guild_id]
        save_config(cfg)
    await interaction.response.send_message("✅ ลบการตั้งค่าสำเร็จ", ephemeral=True)


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────

if __name__ == "__main__":
    token = os.getenv("VERIFY_BOT_TOKEN")
    if not token:
        print("=" * 50)
        print("  Discord Verification Role Bot")
        print("=" * 50)
        token = input("กรอก Bot Token: ").strip()
        if not token:
            print("❌ ต้องการ Token เพื่อรัน Bot")
            sys.exit(1)

    import time
    while True:
        try:
            bot.run(token, log_handler=None)
            break  # ออกปกติ (KeyboardInterrupt จะถูก handle โดย discord.py แล้ว break)
        except discord.LoginFailure:
            print("❌ Token ไม่ถูกต้อง กรุณาตรวจสอบ Bot Token")
            sys.exit(1)
        except KeyboardInterrupt:
            print("\n[BOT] ปิด Bot แล้ว")
            break
        except Exception as e:
            print(f"[BOT] Crash: {e} — restarting in 30s...")
            time.sleep(30)
            bot = VerifyBot()
