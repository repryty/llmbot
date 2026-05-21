#!/usr/bin/env python3
"""
llm-bot 주요 기능 테스트
실행: python test_bot.py  (프로젝트 루트에서)
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PASS = "[OK]"
FAIL = "[NG]"
WARN = "[!!]"


def ok(msg):   print(f"  {PASS} {msg}")
def fail(msg): print(f"  {FAIL} {msg}")
def warn(msg): print(f"  {WARN} {msg}")


# ── 1. Config ─────────────────────────────────────────────────────
def test_config():
    print("\n[1] Config 로딩")
    try:
        from bot.core.config import settings

        ok(f"DISCORD_TOKEN  : {'설정됨' if settings.DISCORD_TOKEN else '없음'}")
        ok(f"OLLAMA_BASE_URL: {settings.OLLAMA_BASE_URL}")
        ok(f"OLLAMA_MODEL   : {settings.OLLAMA_MODEL}")
        ok(f"NOVELAI_BASE_URL: {settings.NOVELAI_BASE_URL}")
        ok(f"whitelist_ids  : {settings.novelai_whitelist_ids}")

        # NovelAI BASE_URL 에 경로가 포함되어 있으면 URL이 중복됨
        for bad_path in ("/ai/generate-image", "/ai/generate-stream", "/ai/"):
            if bad_path in settings.NOVELAI_BASE_URL:
                warn(
                    f"NOVELAI_BASE_URL에 경로가 포함되어 있습니다.\n"
                    f"       현재: {settings.NOVELAI_BASE_URL}\n"
                    f"       실제 요청: {settings.NOVELAI_BASE_URL.rstrip('/')}/ai/generate-image  ← 경로 중복!\n"
                    f"       수정: .env에서 경로 부분을 제거하세요."
                )
                break

        return True
    except Exception as e:
        fail(f"Config 로딩 실패: {e}")
        return False


# ── 2. Session Manager 단위 테스트 ───────────────────────────────
def test_session_manager():
    print("\n[2] Session Manager 단위 테스트")
    try:
        from bot.core.session_manager import SessionManager

        mgr = SessionManager()
        uid = "test_user_999"

        # 초기 상태
        assert mgr.get_messages(uid) == []
        ok("초기 세션 생성")

        # 메시지 추가
        mgr.add_message(uid, "user", "안녕하세요")
        mgr.add_message(uid, "assistant", "안녕하세요!")
        assert len(mgr.get_messages(uid)) == 2
        ok("메시지 추가 (user + assistant)")

        # 시스템 프롬프트 — 항상 첫 번째로 prepend
        mgr.set_system_prompt(uid, "당신은 친절한 AI입니다.")
        msgs = mgr.get_messages(uid)
        assert msgs[0]["role"] == "system" and len(msgs) == 3
        ok("시스템 프롬프트 prepend 확인")

        # 파라미터
        mgr.update_params(uid, temperature=0.5, max_tokens=512)
        params = mgr.get_params(uid)
        assert params["temperature"] == 0.5 and params["max_tokens"] == 512
        ok("파라미터 업데이트")

        mgr.remove_param(uid, "max_tokens")
        assert "max_tokens" not in mgr.get_params(uid)
        ok("파라미터 제거 (remove_param)")

        # 메시지 삭제 (1-based index)
        mgr.delete_message(uid, 1)          # system 다음 첫 user 메시지 삭제
        assert len(mgr.get_messages(uid)) == 2  # system + assistant
        ok("메시지 삭제 (1-based index)")

        # 범위 밖 삭제는 False 반환
        result = mgr.delete_message(uid, 99)
        assert result is False
        ok("범위 밖 삭제 → False 반환")

        # clear_params
        mgr.update_params(uid, temperature=0.8, top_p=0.95)
        mgr.clear_params(uid)
        assert mgr.get_params(uid) == {}
        ok("clear_params")

        # 리셋
        mgr.reset(uid)
        assert mgr.get_messages(uid) == [] and mgr.get_params(uid) == {}
        ok("세션 리셋")

        return True
    except AssertionError as e:
        fail(f"검증 실패: {e}")
        return False
    except Exception as e:
        fail(f"예외: {e}")
        return False


# ── 3. Ollama API ─────────────────────────────────────────────────
async def test_ollama():
    print("\n[3] Ollama API 연결 테스트")
    try:
        from bot.core.ollama_client import OllamaClient

        client = OllamaClient()

        # 모델 목록
        models = await client.list_models()
        if models:
            ids = ", ".join(m["id"] for m in models[:3])
            ok(f"모델 목록: {len(models)}개 ({ids}{'...' if len(models) > 3 else ''})")
        else:
            warn("모델 목록 비어있음 (API 키 문제이거나 엔드포인트가 /models 미지원)")

        # 간단한 채팅 (thinking 모델은 max_tokens가 작으면 content가 비어있을 수 있음)
        messages = [{"role": "user", "content": "Reply with only the word OK."}]
        response = await client.chat(messages, max_tokens=512)
        if response:
            ok(f"채팅 응답: '{response.strip()[:100]}'")
        else:
            fail("채팅 응답 비어있음")
            return False

        return True
    except Exception as e:
        fail(f"Ollama API 오류: {type(e).__name__}: {e}")
        return False


# ── 4. NovelAI 텍스트 ─────────────────────────────────────────────
async def test_novelai_text():
    print("\n[4] NovelAI 텍스트 API 테스트")
    try:
        from bot.core.config import settings
        from bot.core.novelai_client import NovelAIClient

        url = f"{settings.NOVELAI_BASE_URL.rstrip('/')}/ai/generate-stream"
        print(f"     요청 URL: {url}")

        client = NovelAIClient()
        result = await client.generate_text(
            input_text="Once upon a time",
            model="kayra-v1",
            params={"max_length": 20, "min_length": 1},
        )
        if result:
            ok(f"텍스트 생성 성공: '{result[:100]}'")
        else:
            warn("응답은 왔으나 output 비어있음")
        return True
    except Exception as e:
        fail(f"NovelAI 텍스트 오류: {type(e).__name__}: {e}")
        return False


# ── 5. NovelAI 이미지 ─────────────────────────────────────────────
async def test_novelai_image():
    print("\n[5] NovelAI 이미지 API 테스트")
    try:
        from bot.core.config import settings
        from bot.core.novelai_client import NovelAIClient

        url = f"{settings.NOVELAI_BASE_URL.rstrip('/')}/ai/generate-image"
        print(f"     요청 URL: {url}")

        client = NovelAIClient()
        images = await client.generate_image(
            input_text="1girl, simple background",
            model="nai-diffusion-4-5",
            action="generate",
            params={"width": 512, "height": 512, "steps": 1, "n_samples": 1},
        )
        if images:
            ok(f"이미지 생성 성공: {len(images)}장, 첫 이미지 {len(images[0])} bytes")
        else:
            fail("이미지 데이터 없음")
            return False
        return True
    except Exception as e:
        fail(f"NovelAI 이미지 오류: {type(e).__name__}: {e}")
        return False


# ── 메인 ──────────────────────────────────────────────────────────
async def main():
    print("=" * 52)
    print("  llm-bot 기능 테스트")
    print("=" * 52)

    results = {
        "config":    test_config(),
        "session":   test_session_manager(),
        "ollama":    await test_ollama(),
        "nai_text":  await test_novelai_text(),
        "nai_image": await test_novelai_image(),
    }

    labels = {
        "config":    "Config 로딩",
        "session":   "Session Manager",
        "ollama":    "Ollama API",
        "nai_text":  "NovelAI 텍스트",
        "nai_image": "NovelAI 이미지",
    }

    print("\n" + "=" * 52)
    print("  결과 요약")
    print("=" * 52)
    for k, v in results.items():
        print(f"  {'[OK]' if v else '[NG]'} {labels[k]}")
    passed = sum(1 for v in results.values() if v)
    print(f"\n  {passed}/{len(results)} 통과\n")


if __name__ == "__main__":
    asyncio.run(main())
