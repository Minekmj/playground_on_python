# playground_on_python 사용 가이드

Google AI Studio Playground를 Selenium으로 제어해 API처럼 호출할 수 있는 파이썬 모듈입니다.  
최초 1회 구글 로그인만 완료하면 이후에는 **브라우저 창 없이(`headless=True`)** 텍스트 생성, 이미지·문서·오디오·비디오 업로드, 이미지 생성, 다중 클라이언트 병렬 처리를 사용할 수 있습니다.

---

## 1. 설치

```powershell
pip install -U selenium cryptography
```

---

## 2. 빠른 시작 (로그인 & 기본 질의)

`connect(backup=True)`는 자동으로 로그인 상태를 확인합니다.  
**저장된 세션이 없거나 만료되었으면 자동으로 로그인용 Chrome 창을 열어주고**, 로그인 완료 후 백업까지 저장한 뒤 연결됩니다.

```python
from playground_on_python import PlayGround

with PlayGround() as pg:
    # 1. 자동 확인 후 연결 (창 숨김 기본값: headless=True)
    pg.connect(backup=True)

    # 2. 질문 전송 -> 응답 텍스트 반환
    reply = pg.send(
        text="파이썬의 장점을 3줄로 설명해줘.",
        system_input="핵심만 간결하게 답하는 한국어 어시스턴트입니다.",
        model="gemini-4-hydrogen",
        thinnk="Low",
    )
    print(reply)
```

### 로그인만 먼저 따로 해두고 싶을 때
```python
from playground_on_python import PlayGround

pg = PlayGround()
# first="auto": 세션이 살아있으면 창 없이 통과, 없으면 로그인 창 표시
pg.setting(first="auto", backup=True)
```
- 화면에 뜬 Chrome 창에서 구글 로그인 후 AI Studio 플레이그라운드(`aistudio.google.com/prompts/...`) 화면으로 넘어가면 자동으로 감지해 세션을 저장하고 창을 닫습니다.
- 디버깅용으로 실행 과정을 눈으로 보고 싶을 때는 `pg.connect(backup=True, headless=False)`를 사용하면 됩니다.

---

## 3. 로그 끄기 / 조절하기

```python
from playground_on_python import PlayGround, PlayGroundPool

# 로그 완전히 끄기
pg = PlayGround(verbose=False)
pool = PlayGroundPool(count=3, verbose=False)

# 상세 디버그 로그까지 전부 보기 (문제 추적용)
pg_debug = PlayGround(verbose="debug")

# 실행 중에 동적으로 끄기/켜기
pg.logger.level = 0   # 0: 끄기, 1: 기본, 2: 상세 디버그
```

GUI나 파일로 로그를 받고 싶으면 `log_cb`를 넘깁니다.
```python
pg = PlayGround(verbose=True, log_cb=lambda msg: my_log_list.append(msg))
```

---

## 4. 모델 목록 조회 & 필터링 (`paid`, `kind`)

현재 계정에서 사용 가능한 모델 목록을 가져오고, **유료(`Paid`) 모델 제외** 및 **종류별 필터링**을 할 수 있습니다.

```python
with PlayGround(verbose=False) as pg:
    pg.connect(backup=True)

    # 무료(Paid 제외) 모델 전체
    free_all = pg.list_models(paid=False)

    # 무료 텍스트 모델만
    free_text = pg.list_models(kind="text", paid=False)

    # 무료 이미지 생성 모델만
    free_image = pg.list_models(kind="image", paid=False)

    # 비디오 / 오디오 모델만
    video_models = pg.list_models(kind="video")
    audio_models = pg.list_models(kind="audio")

    # 유료(Paid) 모델만
    paid_models = pg.list_models(paid=True)

    for m in free_image:
        print(m["name"], "|", m["id"], "| paid:", m["is_paid"], "| badges:", m["badges"])
```

> **유료 모델 오사용 방지:**  
> `send(..., allow_paid=False)` 또는 `PlayGroundConfig(allow_paid=False)`를 설정하면 유료 모델 선택 시 즉시 `PermissionError`를 발생시켜 차단합니다.

---

## 5. 미디어 입력 (이미지 · PDF · 오디오 · 비디오)

`media` 인자에 파일 경로, 리스트, `PIL.Image.Image`, `(bytes, 파일명)` 튜플을 그대로 넣을 수 있습니다.

```python
from PIL import Image
from playground_on_python import PlayGround

with PlayGround(verbose=False) as pg:
    pg.connect(backup=True)

    # 1) 이미지 파일 1장
    res1 = pg.send("이 이미지에 적힌 일본어를 그대로 추출해줘.", media="page_01.png", new_chat=True)

    # 2) 여러 파일 동시에 첨부 (이미지 + PDF + 텍스트 등)
    res2 = pg.send("두 자료를 비교 요약해줘.", media=["a.png", "doc.pdf"], new_chat=True)

    # 3) PIL Image 객체 바로 전달 (디스크 저장 불필요)
    pil_img = Image.open("scan.png").crop((0, 0, 800, 1200))
    res3 = pg.send("본문만 추출해줘.", media=pil_img, new_chat=True)

    # 4) 메모리 바이트 직접 전달
    raw_bytes = open("photo.jpg", "rb").read()
    res4 = pg.send("이 사진 설명해줘.", media=(raw_bytes, "photo.jpg"), new_chat=True)
```

---

## 6. 이미지 생성 모델 사용 (`generate_image`)

Imagen 계열이나 이미지 출력 지원 Gemini 모델로 이미지를 생성하고 파일/바이트로 받아옵니다.

```python
from playground_on_python import PlayGround

with PlayGround(verbose=False) as pg:
    pg.connect(backup=True)

    # 무료 이미지 모델 자동 선택
    img_models = pg.list_models(kind="image", paid=False)
    target_model = img_models[0]["id"]

    result = pg.generate_image(
        prompt="비 내리는 밤의 고요한 일본 신사, 시네마틱 조명",
        model=target_model,
        aspect_ratio="16:9",       # "1:1", "16:9", "9:16", "4:3", "3:4" 등
        image_size="1K",           # "0.5K", "1K", "2K", "4K" (지원 모델 한정)
        save_to="./generated",     # 지정 폴더에 자동 저장
        allow_paid=False,
    )

    print("저장된 파일:", result["paths"])
    print("함께 나온 텍스트:", result["text"])
    # 바이트 직접 접근: result["images"][0]["bytes"]
```

---

## 7. 모든 설정 사용하기 (`PlayGroundConfig`)

자주 쓰는 설정은 `PlayGroundConfig`로 묶어서 기본값으로 등록하거나 호출마다 넘길 수 있습니다.  
**이전 호출과 동일한 설정은 자동으로 건너뛰어** 불필요한 UI 조작 시간 없이 빠르게 실행됩니다.

```python
from playground_on_python import PlayGround, PlayGroundConfig

cfg = PlayGroundConfig(
    # 기본 모델/프롬프트/사고 설정
    model="gemini-4-hydrogen",
    system_input="당신은 일본어 원서 OCR 전문가입니다. 원문만 출력하세요.",
    temp=0.0,
    thinnk="Low",                  # "Minimal", "Low", "Medium", "High", True/False
    # thinking_budget=1024,

    # Tools 설정
    google_search=False,           # Google Search 끄기
    url_context=False,
    code_execution=False,
    # structured_output={"type": "OBJECT", "properties": {"title": {"type": "STRING"}}},
    # function_calling=False,

    # 고급 설정 (Advanced settings)
    media_resolution="High",       # "Default", "Low", "Medium", "High"
    max_output_tokens=8192,
    stop_sequences=["<END>"],
    safety_settings="off",         # 안전 필터 최소로 내리기
    # top_p=0.95,
    # seed=42,

    # 제어 옵션
    allow_paid=False,
    include_thoughts=False,        # True면 Thoughts 내용도 함께 반환
    new_chat=True,                 # 매 호출마다 새 대화로 시작
)

with PlayGround(verbose=False, default_config=cfg) as pg:
    pg.connect(backup=True)

    # 기본 설정(cfg) 그대로 실행
    out1 = pg.send("페이지 1 텍스트 추출", media="p1.png")

    # 특정 호출만 일부 옵션 덮어쓰기
    out2 = pg.send("이 페이지는 정밀하게 읽어줘", media="p2.png", thinnk="High")
```

---

## 8. 다중 클라이언트 병렬 처리 (`PlayGroundPool`)

여러 Chrome 워커를 동시에 띄워 대량 작업을 병렬로 처리합니다.

### 방법 A: 로그인된 1개 계정을 복제해 워커 N개 동시 실행
```python
from playground_on_python import PlayGroundPool, PlayGroundConfig

cfg = PlayGroundConfig(
    model="gemini-4-hydrogen",
    thinnk="Low",
    google_search=False,
    new_chat=True,
)

# default 프로필 백업을 worker_1, worker_2, worker_3로 복제해 3개 동시 실행
with PlayGroundPool(count=3, base_profile="default", verbose=False, default_config=cfg) as pool:
    tasks = [
        {"text": "OCR 추출", "media": "page_01.png"},
        {"text": "OCR 추출", "media": "page_02.png"},
        {"text": "OCR 추출", "media": "page_03.png"},
        {"text": "OCR 추출", "media": "page_04.png"},
        {"text": "OCR 추출", "media": "page_05.png"},
    ]

    # 입력 순서를 유지한 채 3개 브라우저가 동시에 처리
    results = pool.send_batch(tasks)
    for idx, text in enumerate(results, 1):
        print(f"[{idx}] {len(text)}자 완료")
```

### 방법 B: 서로 다른 구글 계정 여러 개를 묶어서 실행
```python
from playground_on_python import PlayGround, PlayGroundPool

# 계정별 최초 1회 로그인 (자동 확인)
# PlayGround(profile_name="acc1").setting(first="auto", backup=True)
# PlayGround(profile_name="acc2").setting(first="auto", backup=True)

with PlayGroundPool(profiles=["acc1", "acc2"], verbose=False) as pool:
    # 1건씩 유휴 워커에 자동 배정
    ans = pool.send("간단히 인사해줘")

    # 또는 워커를 직접 대여해 연속 작업 수행
    with pool.acquire() as pg:
        a = pg.send("첫 번째 질문")
        b = pg.send("방금 답변 요약해줘")  # 같은 워커 대화 이어가기
```

---

## 9. 프로필 데이터 암호화 (`key.bmp`)

기본 설정(`encrypt=True`)에서는 저장되는 민감 데이터만 **AES-256-GCM**으로 암호화하고, 암호화 키는 24비트 BMP 이미지(`key.bmp`) 내부에 은닉 저장합니다.

```text
.pg_data/
├── key.bmp                       <- 암호화 키가 은닉된 BMP 이미지
└── default/
    ├── state.enc                 <- 암호화된 계정/URL 상태
    ├── cookies.enc               <- 암호화된 인증 쿠키
    ├── profile/                  <- Chrome 실행용 작업 폴더
    └── backup/
        ├── state.enc
        ├── cookies.enc
        ├── history_backup.enc    <- 암호화된 요청/응답 기록
        └── profile_data.enc      <- 암호화된 필수 인증 프로필 백업
```

- **키 파일 위치 직접 지정**:
  ```python
  pg = PlayGround(encrypt=True, key_path="./secret_key.bmp")
  ```
- **종료 시 런타임 `profile/` 폴더까지 완전 삭제**하고 싶을 때 (다음 `connect()` 시 `profile_data.enc`에서 자동 복원):
  ```python
  pg = PlayGround(encrypt=True, wipe_runtime_profile=True)
  ```
- **암호화 끄기**:
  ```python
  pg = PlayGround(encrypt=False)
  ```

---

## 10. 기존 대화 이어가기 vs 매번 새 대화

- **대화 이어가기 (기본 `new_chat=False`)**:  
  `connect(backup=True)`는 마지막에 작업하던 플레이그라운드 URL로 들어가며, `send()`를 여러 번 호출하면 같은 채팅창에서 문맥을 이어서 질문합니다.
- **매번 독립된 새 대화로 보내기 (`new_chat=True`)**:  
  OCR/번역/분류처럼 이전 대화 문맥이 섞이면 안 되는 작업에서는 `send(..., new_chat=True)` 또는 `PlayGroundConfig(new_chat=True)`를 사용하거나 중간에 `pg.new_chat()`을 호출하세요.