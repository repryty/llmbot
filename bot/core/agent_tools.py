import asyncio
import json
import sys
from pathlib import Path

MEMOS_PATH = Path("data/memos")


async def python_exec(code: str) -> str:
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-c", code,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=10.0)
        except asyncio.TimeoutError:
            proc.kill()
            return "오류: 실행 시간 초과 (10초)"
        out = stdout.decode("utf-8", errors="replace").strip()
        err = stderr.decode("utf-8", errors="replace").strip()
        if err:
            out = (out + f"\n[stderr]\n{err}").strip()
        return out or "(출력 없음)"
    except Exception as e:
        return f"오류: {e}"


async def read_history(channel, limit: int = 20) -> str:
    limit = min(max(1, limit), 50)
    lines = []
    async for msg in channel.history(limit=limit):
        content = msg.content[:300] if msg.content else "(내용 없음)"
        lines.append(f"{msg.author.display_name}: {content}")
    lines.reverse()
    return "\n".join(lines) if lines else "(메시지 없음)"


async def get_member_info(guild, name_or_id: str) -> str:
    member = None
    try:
        member = guild.get_member(int(name_or_id))
    except (ValueError, Exception):
        pass
    if member is None:
        name_lower = name_or_id.lower()
        for m in guild.members:
            if m.display_name.lower() == name_lower or m.name.lower() == name_lower:
                member = m
                break
    if member is None:
        return f"'{name_or_id}' 멤버를 찾을 수 없습니다."
    roles = [r.name for r in member.roles if r.name != "@everyone"]
    joined = member.joined_at.strftime("%Y-%m-%d") if member.joined_at else "알 수 없음"
    return (
        f"닉네임: {member.display_name}\n"
        f"이름: {member.name}\n"
        f"역할: {', '.join(roles) or '없음'}\n"
        f"가입일: {joined}\n"
        f"ID: {member.id}"
    )


async def list_channels(guild) -> str:
    lines = []
    for ch in guild.text_channels:
        topic = f" — {ch.topic[:60]}" if ch.topic else ""
        lines.append(f"#{ch.name} (ID: {ch.id}){topic}")
    return "\n".join(lines) if lines else "(채널 없음)"


def save_memo(user_id: str, key: str, content: str) -> str:
    MEMOS_PATH.mkdir(parents=True, exist_ok=True)
    memo_file = MEMOS_PATH / f"{user_id}.json"
    try:
        memos = json.loads(memo_file.read_text(encoding="utf-8")) if memo_file.exists() else {}
        memos[key] = content
        memo_file.write_text(json.dumps(memos, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"메모 '{key}' 저장 완료."
    except Exception as e:
        return f"저장 오류: {e}"


def read_memo(user_id: str, key: str) -> str:
    memo_file = MEMOS_PATH / f"{user_id}.json"
    if not memo_file.exists():
        return "저장된 메모가 없습니다."
    try:
        memos = json.loads(memo_file.read_text(encoding="utf-8"))
        if key == "*":
            if not memos:
                return "저장된 메모가 없습니다."
            return "\n".join(f"[{k}] {v}" for k, v in memos.items())
        if key not in memos:
            keys = ", ".join(memos.keys()) or "없음"
            return f"'{key}' 메모 없음. 저장된 키: {keys}"
        return memos[key]
    except Exception as e:
        return f"읽기 오류: {e}"
