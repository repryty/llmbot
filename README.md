# llmbot

Discord LLM 챗봇. OpenAI 호환 API, Gemini, NovelAI를 지원하며 다중 사용자 세션과 스트리밍 응답을 제공한다.

## 기술 스택

- **Python 3.14+**, UV 패키지 매니저
- **discord.py** — Discord 봇 프레임워크
- **openai SDK** — OpenAI 호환 엔드포인트 및 Gemini 연결
- **httpx** — NovelAI 비동기 HTTP 요청
- **pydantic-settings** — `.env` 기반 설정 관리

## 프로젝트 구조

```
llmbot/
├── main.py                   # 엔트리포인트 — Discord 봇 초기화, cog 로드
├── bot/
│   ├── cogs/                 # Discord 슬래시 커맨드 플러그인
│   │   ├── chat_cog.py       # 채팅, 세션 관리 커맨드
│   │   ├── novelai_cog.py    # NovelAI 이미지 생성 커맨드
│   │   ├── admin_cog.py      # 전역 에러 핸들러, 화이트리스트 체크
│   │   └── logging_cog.py    # 로그 조회, 디버그 모드 토글
│   ├── core/
│   │   ├── config.py         # Pydantic Settings — .env 파싱
│   │   ├── llm_client.py     # LLM 클라이언트 (OpenAI 호환 + Gemini 자동 감지)
│   │   ├── novelai_client.py # NovelAI 텍스트/이미지 생성
│   │   ├── session_manager.py# 사용자별 세션 영속성 관리
│   │   ├── bot_logger.py     # 로테이팅 파일 로거 (5MB, 2백업)
│   │   ├── error_utils.py    # 에러 포맷팅, 긴 메시지 청킹
│   │   ├── appearance_gen.py # 이미지 프롬프트용 의상 태그 생성
│   │   └── ollama_client.py  # Ollama 클라이언트 (레거시)
│   └── models/
│       └── session.py        # Session 데이터클래스 (messages, params, system_prompt)
├── data/                     # 런타임 생성 데이터 (gitignore)
│   ├── chat_sessions.json    # 사용자별 메시지 히스토리 및 파라미터
│   └── image_params.json     # 이미지 생성 설정
├── prompts/
│   ├── system_prompt.txt     # 기본 시스템 프롬프트 (시작 시 로드)
│   └── system_prompt.example.txt
├── pyproject.toml            # UV 프로젝트 설정
├── requirements.txt          # pip 의존성
├── Dockerfile
├── docker-compose.yml
└── api_doc.md                # OpenAI/NovelAI API 스펙 참고 문서 (한국어)
```

## 환경 설정

### 의존성 설치

```sh
uv sync
uv pip install -r requirements.txt
```

### .env 파일

```env
DISCORD_TOKEN=<봇_토큰>

# OpenAI 호환 엔드포인트 (Ollama, Together AI, DeepSeek 등)
OPENAI_BASE_URL=http://localhost/v1
OPENAI_MODEL=gpt-4o
OPENAI_API_KEY=

# Gemini (모델명에 "gemini" 포함 시 자동 감지)
GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash

# NovelAI
NOVELAI_BASE_URL=https://api.novelai.net
NOVELAI_API_KEY=

# 접근 제어
WHITELIST=<Discord_사용자_ID,콤마_구분>

# 기본 LLM 파라미터
DEFAULT_TEMPERATURE=0.7
DEFAULT_TOP_P=0.9
DEFAULT_MAX_TOKENS=2048

# 로그
LOG_DEBUG=false
```

## 실행

```sh
# 직접 실행
uv run python main.py

# Docker
docker compose up -d
```

## 주요 커맨드

| 커맨드 | 설명 |
|--------|------|
| `/chat <prompt>` | 스트리밍 LLM 응답 (thinking 표시 포함) |
| `/agent <on\|off>` | 에이전트 모드 토글 |
| `/reset` | 대화 히스토리 초기화 |
| `/system <prompt>` | 시스템 프롬프트 설정 |
| `/set [key] [value]` | 파라미터 조회/변경 (temperature, model 등) |
| `/history` | 현재 세션 메시지 목록 |
| `/add <role> <content>` | 히스토리에 메시지 삽입 |
| `/delete <index>` | 히스토리에서 메시지 삭제 |
| `/models [backend]` | 사용 가능한 모델 목록 |
| `/image <prompt>` | NovelAI 이미지 생성 |
| `/logs [lines]` | 최근 로그 조회 |
| `/log_debug [on\|off]` | 디버그 로그 토글 |

봇 멘션(@봇)으로도 채팅 가능. `.txt` 첨부 파일 자동 읽기. 답장(@멘션)으로 인용 메시지 자동 참조.

## 에이전트 모드

`/agent on`으로 활성화. Gemini Function Calling 기반 툴 루프를 사용한다.

| 툴 | 설명 |
|----|------|
| `python_exec` | Python 코드 실행 (timeout 10초) |
| `read_history` | 현재 채널 최근 메시지 읽기 (최대 50개) |
| `get_member_info` | 서버 멤버 닉네임·역할·가입일 조회 |
| `list_channels` | 서버 텍스트 채널 목록 조회 |
| `save_memo` | 영구 메모 저장 (`data/memos/{user_id}.json`) |
| `read_memo` | 저장된 메모 읽기 (`*`로 전체 조회) |

- 툴 실행 중에는 `-# 🔧 tool_name 실행 중...` 으로 진행 상태 표시
- 최대 8회 반복 후 종료
- 툴 호출 이력은 세션에 저장되어 이후 대화에서도 참조 가능

## 아키텍처 메모

- **LLM 백엔드 자동 감지**: 모델명에 `gemini` 포함 시 Gemini API, 아니면 OpenAI 호환으로 처리
- **스트리밍**: `<think>` 태그와 `reasoning_content` 필드를 파싱해 Discord 스포일러로 표시
- **세션 영속성**: `data/chat_sessions.json`에 사용자별 저장, 봇 재시작 후에도 유지
- **화이트리스트**: `WHITELIST` env에 Discord 사용자 ID 목록으로 접근 제어
- **로그**: 기본은 API 요청만 기록, `/log_debug on`으로 전체 로그 활성화
