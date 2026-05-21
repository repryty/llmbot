# OpenAI Compatible API vs NovelAI API 규격 정리

## 개요

| 항목 | OpenAI Compatible | NovelAI Text | NovelAI Image |
|------|------------------|--------------|---------------|
| 베이스 URL | 공급자마다 다름 (`/v1`) | `https://api.novelai.net` | `https://api.novelai.net` |
| 인증 방식 | `Bearer {api_key}` | `Bearer {pst-...}` | `Bearer {pst-...}` |
| 입력 형식 | messages 배열 (chat) | 원시 문자열 (completion) | 프롬프트 문자열 + 파라미터 |
| 출력 형식 | JSON (choices 배열) | SSE 스트리밍 / JSON | ZIP (PNG 바이너리) |

---

# 1. OpenAI Compatible API

## 1-1. 개요

OpenAI가 표준화한 REST API 규격. Ollama Cloud, Together AI, DeepSeek, Groq, LM Studio 등 대부분의 서드파티 LLM 서비스가 이 규격을 그대로 채택하거나 호환 레이어를 제공한다. `base_url`만 바꾸면 동일한 SDK/코드를 재사용할 수 있다.

## 1-2. 엔드포인트 목록

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/v1/chat/completions` | 채팅 완성 (핵심 엔드포인트) |
| POST | `/v1/completions` | 레거시 텍스트 완성 (구형, 비권장) |
| GET | `/v1/models` | 사용 가능한 모델 목록 조회 |
| POST | `/v1/embeddings` | 텍스트 임베딩 벡터 생성 |

## 1-3. 인증

```http
Authorization: Bearer {API_KEY}
Content-Type: application/json
```

API 키 검증을 하지 않는 구현체도 많으며, 이 경우 `api_key="EMPTY"` 같은 더미 값을 넣어도 작동한다.

## 1-4. POST /v1/chat/completions

### 요청 바디

```json
{
  "model": "모델 ID (필수)",
  "messages": [
    { "role": "system",    "content": "시스템 지시문" },
    { "role": "user",      "content": "사용자 입력" },
    { "role": "assistant", "content": "AI 응답 (다중턴 시)" }
  ],

  "temperature":        0.7,
  "top_p":              1.0,
  "max_tokens":         1024,
  "stream":             false,
  "stop":               ["</s>", "###"],
  "seed":               42,
  "presence_penalty":   0.0,
  "frequency_penalty":  0.0,
  "logit_bias":         {},
  "n":                  1,
  "response_format":    { "type": "json_object" },

  "tools": [
    {
      "type": "function",
      "function": {
        "name": "함수명",
        "description": "설명",
        "parameters": { "type": "object", "properties": {} }
      }
    }
  ]
}
```

#### 주요 파라미터 설명

| 파라미터 | 타입 | 설명 |
|---------|------|------|
| `model` | string | 필수. 모델 식별자 |
| `messages` | array | 필수. 역할(role)과 내용(content) 쌍의 배열 |
| `temperature` | float | 0~2, 높을수록 창의적. 기본값 1.0 |
| `top_p` | float | 누적 확률 샘플링. temperature와 동시 사용 비권장 |
| `max_tokens` | int | 최대 생성 토큰 수 |
| `stream` | bool | true면 SSE 형식으로 청크 단위 스트리밍 |
| `stop` | string/array | 생성 중단 시퀀스 (최대 4개) |
| `seed` | int | 동일 seed로 재현성 확보 (보장은 아님) |
| `presence_penalty` | float | -2~2, 이미 등장한 토큰 재사용 억제 |
| `frequency_penalty` | float | -2~2, 빈도 기반 토큰 억제 |
| `n` | int | 동시에 생성할 응답 수 |
| `response_format` | object | `{"type": "json_object"}` 또는 `{"type": "text"}` |
| `tools` | array | 함수 호출(Function Calling) 도구 목록 |

### 응답 바디

```json
{
  "id":      "chatcmpl-xxxx",
  "object":  "chat.completion",
  "created": 1741569952,
  "model":   "gpt-4.1-2025-04-14",
  "choices": [
    {
      "index":         0,
      "message": {
        "role":    "assistant",
        "content": "생성된 텍스트"
      },
      "finish_reason": "stop"
    }
  ],
  "usage": {
    "prompt_tokens":     19,
    "completion_tokens": 42,
    "total_tokens":      61
  }
}
```

### 스트리밍 응답 (stream: true)

`data:` 접두사가 붙은 SSE 형식으로 전송되며, 마지막에 `data: [DONE]`으로 종료된다.

```
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"안"},...}]}
data: {"id":"chatcmpl-xxx","choices":[{"delta":{"content":"녕"},...}]}
data: [DONE]
```

## 1-5. 서드파티 연결 패턴

```python
from openai import OpenAI

client = OpenAI(
    base_url="https://api.ollama.ai/v1",   # 공급자 URL로 교체
    api_key="your-key"
)
response = client.chat.completions.create(
    model="deepseek-r1",
    messages=[{"role": "user", "content": "안녕"}]
)
```

---

# 2. NovelAI API — 텍스트 생성

## 2-1. 개요

NovelAI의 텍스트 생성 API는 OpenAI 방식과 근본적으로 다르다. **채팅 모델이 아니라 텍스트 완성(completion) 모델**이기 때문에, 입력이 messages 배열이 아닌 **원시 텍스트 문자열**이다. AI는 해당 텍스트를 이어서 완성한다.

## 2-2. 인증 및 토큰

영구 API 토큰(Persistent API Token)을 사용하며, NovelAI 사이트의 계정 설정에서 발급한다. 토큰은 `pst-`로 시작한다.

```http
Authorization: Bearer pst-xxxxxxxxxxxxxxxx
Content-Type: application/json
```

구독 정보 조회: `GET /user/subscription`  
컨텍스트 제한이 모델·구독 티어별로 다르므로, 연동 시 반드시 먼저 확인해야 한다.

## 2-3. 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/ai/generate` | 동기 텍스트 생성 |
| POST | `/ai/generate-stream` | SSE 스트리밍 텍스트 생성 (권장) |
| GET | `/user/subscription` | 구독 티어 및 컨텍스트 한도 조회 |

## 2-4. POST /ai/generate-stream

### 요청 바디

```json
{
  "input":  "원시 텍스트 프롬프트 (필수)",
  "model":  "kayra-v1",
  "parameters": {
    "temperature":               1.35,
    "max_length":                150,
    "min_length":                1,
    "top_p":                     0.95,
    "top_k":                     0,
    "top_a":                     1.0,
    "tail_free_sampling":        0.99,
    "repetition_penalty":        1.1,
    "repetition_penalty_range":  2048,
    "repetition_penalty_slope":  0.09,
    "stop_sequences":            [[2]],
    "bad_words_ids":             [],
    "use_cache":                 false,
    "return_full_text":          false,
    "logprobs":                  0
  }
}
```

#### 주요 파라미터 설명

| 파라미터 | 설명 |
|---------|------|
| `input` | 필수. 이어쓸 원시 텍스트. messages 배열 아님 |
| `model` | 모델 ID. 아래 모델 목록 참조 |
| `max_length` | 최대 생성 토큰. NAI 응답 한도는 약 150토큰 |
| `temperature` | 창의성 조절. NAI 권장값은 1.0~1.5 |
| `top_a` | Entropy-based 필터링 (NAI 고유 파라미터) |
| `tail_free_sampling` | 꼬리 분포 제거 (NAI 고유 파라미터) |
| `repetition_penalty` | 반복 억제 강도 |
| `repetition_penalty_range` | 반복 억제 적용 토큰 범위 |
| `stop_sequences` | 토큰 ID 배열로 지정하는 중단 시퀀스 |

### 모델 목록 (2025 기준)

| 모델 ID | 설명 | 최소 티어 |
|---------|------|---------|
| `clio-v1` | 이전 세대, 대형 컨텍스트 | Tablet |
| `kayra-v1` | 현재 주력 모델 | Tablet |
| `erato-v1` | Llama 3 기반 최신 모델 | Opus |

### 응답 (스트리밍)

```
data: {"token": "안", "ptr": 0, "output": "안"}
data: {"token": "녕", "ptr": 1, "output": "안녕"}
...
```

OpenAI와 달리 `output` 필드에 누적 텍스트가 들어온다.

## 2-5. OpenAI API와의 핵심 차이점

| 항목 | OpenAI Chat | NovelAI Text |
|------|------------|--------------|
| 입력 형식 | `messages` 배열 | 원시 문자열 `input` |
| 모델 특성 | 명령 수행 (instruction-tuned) | 텍스트 이어쓰기 (completion) |
| 응답 필드 | `choices[0].message.content` | `output` |
| 스트림 종료 | `data: [DONE]` | 스트림 종료 |
| 샘플러 파라미터 | temperature, top_p 중심 | top_a, TFS 등 고유 파라미터 포함 |

---

# 3. NovelAI API — 이미지 생성

## 3-1. 개요

NAI Diffusion 모델 기반의 이미지 생성 API. 응답이 JSON이 아닌 **ZIP 파일 (PNG 바이너리)**이다.

## 3-2. 엔드포인트

| 메서드 | 경로 | 설명 |
|--------|------|------|
| POST | `/ai/generate-image` | 이미지 생성 (T2I / I2I / Inpaint) |
| POST | `/ai/upscale` | 이미지 업스케일 |
| POST | `/ai/augment-image` | 이미지 보정 (배경 제거, 라인아트 등) |
| POST | `/ai/generate-image/suggest-tags` | 태그 추천 |

## 3-3. POST /ai/generate-image

### 요청 바디

```json
{
  "input":  "1girl, solo, masterpiece, best quality",
  "model":  "nai-diffusion-4-5",
  "action": "generate",
  "parameters": {
    "width":               832,
    "height":              1216,
    "scale":               6.0,
    "sampler":             "k_euler_ancestral",
    "steps":               28,
    "seed":                0,
    "n_samples":           1,
    "negative_prompt":     "blurry, lowres, bad quality",
    "ucPreset":            0,
    "qualityToggle":       true,
    "noise_schedule":      "karras",
    "sm":                  false,
    "sm_dyn":              false,
    "dynamic_thresholding": false,

    "image":    "base64_encoded_image (img2img 시)",
    "strength": 0.7,
    "noise":    0.0,
    "mask":     "base64_encoded_mask (inpaint 시)"
  }
}
```

#### action 값

| 값 | 설명 |
|----|------|
| `generate` | 텍스트 → 이미지 (T2I) |
| `img2img` | 이미지 + 프롬프트 → 이미지 (I2I) |
| `infill` | 인페인팅 (마스크 영역 재생성) |

#### 주요 파라미터 설명

| 파라미터 | 설명 |
|---------|------|
| `input` | 포지티브 프롬프트 (태그 나열) |
| `model` | 사용할 Diffusion 모델 ID |
| `width` / `height` | 이미지 크기 (px). 64의 배수 권장 |
| `scale` | CFG Scale. 프롬프트 준수 강도. 보통 5~7 |
| `sampler` | 샘플러 종류 (하단 목록 참조) |
| `steps` | 디노이징 스텝 수. 보통 20~28 |
| `seed` | 0이면 랜덤. 동일 seed로 재현 가능 |
| `n_samples` | 한 번에 생성할 이미지 수 |
| `negative_prompt` | 네거티브 프롬프트 |
| `ucPreset` | 기본 네거티브 추가 여부. 0=Heavy, 1=Light, 2=None |
| `qualityToggle` | true면 퀄리티 태그 자동 추가 |
| `noise_schedule` | 노이즈 스케줄. `karras` 권장 |
| `sm` / `sm_dyn` | SMEA / SMEA DYN 활성화 |
| `strength` | I2I 강도. 0=원본, 1=완전 재생성 |

#### 샘플러 목록

| 값 | 설명 |
|----|------|
| `k_euler_ancestral` | 권장. 다양하고 안정적 |
| `k_euler` | 결정론적, 일관성 높음 |
| `k_dpm_2` | DPM2 |
| `k_dpm_2_ancestral` | DPM2 Ancestral |
| `k_dpmpp_2s_ancestral` | DPM++ 2S Ancestral |
| `k_dpmpp_2m` | DPM++ 2M. 고퀄리티 권장 |
| `k_dpmpp_sde` | DPM++ SDE |
| `ddim_v3` | DDIM (v3 이상용) |

#### 모델 목록 (2025 기준)

| 모델 ID | 설명 |
|---------|------|
| `nai-diffusion-4` | NAI Diffusion V4 |
| `nai-diffusion-4-curated-preview` | V4 큐레이티드 |
| `nai-diffusion-4-5` | NAI Diffusion V4.5 (최신) |
| `nai-diffusion-4-5-curated` | V4.5 큐레이티드 (최신) |
| `nai-diffusion-3` | V3 (구버전) |
| `nai-diffusion-3-inpainting` | V3 인페인팅 전용 |

### 응답

응답 Content-Type은 `application/zip`이며, 압축 해제 시 PNG 파일이 나온다. `n_samples` 값만큼 PNG가 포함된다.

```python
import zipfile, io

# response.content = ZIP 바이너리
z = zipfile.ZipFile(io.BytesIO(response.content))
for name in z.namelist():
    with open(name, "wb") as f:
        f.write(z.read(name))
```

### V4+ 다중 캐릭터 프롬프트 (characterPrompts)

V4 이상에서는 캐릭터별 프롬프트를 별도로 지정할 수 있다.

```json
"parameters": {
  "characterPrompts": [
    {
      "prompt": "1girl, black hair, grey eyes",
      "uc": "blonde hair",
      "center": { "x": 0.3, "y": 0.5 }
    },
    {
      "prompt": "1girl, white hair, fox ears",
      "uc": "black hair",
      "center": { "x": 0.7, "y": 0.5 }
    }
  ]
}
```

---

# 4. 요약 비교표

| 항목 | OpenAI Compatible | NovelAI Text | NovelAI Image |
|------|------------------|--------------|---------------|
| 목적 | 범용 LLM 채팅/완성 | 소설 이어쓰기 | AI 이미지 생성 |
| Base URL | 공급자별 상이 | `api.novelai.net` | `api.novelai.net` |
| 핵심 엔드포인트 | `/v1/chat/completions` | `/ai/generate-stream` | `/ai/generate-image` |
| 입력 | messages 배열 | 원시 문자열 | 프롬프트 + params |
| 출력 | JSON (choices) | SSE (output 필드) | ZIP (PNG) |
| 스트리밍 | SSE, `data: [DONE]` 종료 | SSE, 자체 종료 | 해당 없음 |
| 샘플러 파라미터 | temperature, top_p 위주 | top_a, TFS 포함 | CFG scale, sampler, steps |
| 모델 지정 | model 필드 | model 필드 | model 필드 |
| 인증 | Bearer (공급자별 키) | Bearer (pst-xxx 토큰) | Bearer (pst-xxx 토큰) |
| SDK 호환성 | OpenAI SDK 그대로 사용 | 전용 라이브러리 필요 | 전용 라이브러리 필요 |
