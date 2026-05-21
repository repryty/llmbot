import traceback
import discord
from discord.ext import commands
from discord import app_commands


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if interaction.response.is_done():
            send = interaction.followup.send
        else:
            send = interaction.response.send_message

        if isinstance(error, app_commands.CheckFailure):
            await send("이 명령어를 사용할 권한이 없습니다.", ephemeral=True)
        elif isinstance(error, app_commands.CommandInvokeError):
            original = error.original
            await send(f"명령어 실행 중 오류가 발생했습니다: {original}", ephemeral=True)
            traceback.print_exception(type(original), original, original.__traceback__)
        else:
            await send(f"오류가 발생했습니다: {error}", ephemeral=True)
            traceback.print_exception(type(error), error, error.__traceback__)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
