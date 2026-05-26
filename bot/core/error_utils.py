import traceback
import discord


async def send_long(
    interaction: discord.Interaction,
    text: str,
    ephemeral: bool = False,
    chunk_size: int = 1990,
) -> None:
    """긴 텍스트를 chunk_size 단위로 잘라 전송한다."""
    chunks = [text[i:i + chunk_size] for i in range(0, len(text), chunk_size)] if text else [""]
    if len(chunks) == 1:
        await interaction.response.send_message(chunks[0], ephemeral=ephemeral)
        return
    await interaction.response.defer(ephemeral=ephemeral)
    for chunk in chunks:
        await interaction.followup.send(chunk, ephemeral=ephemeral)


def format_error(e: Exception, **context) -> str:
    tb = traceback.format_exc()
    lines = [
        f"**오류 타입:** `{type(e).__name__}`",
        f"**오류 메시지:** {e}",
    ]
    for key, val in context.items():
        val_str = str(val)
        if len(val_str) > 300:
            val_str = val_str[:297] + "..."
        lines.append(f"**{key}:** {val_str}")
    tb_block = f"```\n{tb[-1500:]}\n```" if tb.strip() != "NoneType: None" else ""
    full = "\n".join(lines) + ("\n" + tb_block if tb_block else "")
    return full[:1990] if len(full) > 1990 else full
