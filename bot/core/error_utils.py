import traceback


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
