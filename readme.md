# playground_on_python

Google AI Studio Playground 웹 인터페이스를 Selenium과 JavaScript 제어로 자동화하여, **API 키 없이 파이썬 코드에서 Gemini 텍스트·멀티모달·이미지 생성 모델을 호출**할 수 있게 해주는 백엔드 모듈입니다.

---

## 주요 특징

- **자동 로그인 및 백그라운드 실행 (`Headless`)**
  - 최초 로그인 시 일반 Chrome을 직접 실행해 Google 보안 차단(`안전하지 않은 브라우저`)을 우회하고, 이후에는 창을 숨긴 상태(`headless=True`)로 동작합니다.
  - `connect(backup=True)`만 호출해도 기존 세션 유효성을 자동 확인하며, 세션이 없거나 만료된 경우에만 로그인 창을 자동으로 띄웁니다.
- **프로필 데이터 암호화 (`AES-256-GCM` + `key.bmp`)**
  - `cryptography` 라이브러리의 AES-256-GCM으로 계정 상태, 쿠키, 백업 프로필, 대화 기록(`.enc`)만 선별 암호화합니다.
  - 암호화 키는 24비트 BMP 이미지(`key.bmp`)의 픽셀 LSB(최하위 비트)에 은닉 저장됩니다.
- **멀티모달 입력 & 이미지 생성 지원**
  - 파일 경로(`str`, `Path`), 다중 파일 리스트, `PIL.Image.Image`, `(bytes, filename)` 형태로 이미지·PDF·오디오·비디오를 바로 첨부할 수 있습니다.
  - Imagen 및 이미지 생성 지원 Gemini 모델 호출(`generate_image`)과 생성 이미지 자동 저장을 지원합니다.
- **모델 목록 조회 및 유료(`Paid`) 필터**
  - `list_models(kind=..., paid=False)`로 텍스트/이미지/비디오/오디오 종류별 필터링 및 유료(`Paid`) 모델 제외가 가능합니다.
  - `allow_paid=False` 옵션으로 유료 모델 오사용을 사전에 차단할 수 있습니다.
- **다중 클라이언트 병렬 처리 (`PlayGroundPool`)**
  - 1개의 로그인된 프로필 백업을 복제해 워커 N개를 동시에 실행하거나, 서로 다른 여러 구글 계정 프로필을 묶어 `send_batch()`로 병렬 처리할 수 있습니다.
- **자가 복구 (Self-Healing)**
  - 이전 실행에서 남은 좀비 Chrome 프로세스 점유나 잠금 파일(`lockfile`, `SingletonLock`), 프로필 손상 시 자동 정리 후 백업/쿠키로 복구합니다.

---

## 동작 원리

### 1. 로그인 및 세션 백업
1. `setting(first="auto")` 또는 `connect(auto_login=True)`가 저장된 세션 존재 여부를 확인합니다.
2. 유효한 세션이 없으면 로컬 Chrome을 `--remote-debugging-port`로 실행해 사용자가 직접 로그인하도록 합니다.
3. AI Studio 플레이그라운드 진입과 계정 로그인(`ms-account-switcher`)이 확인되면 쿠키·URL·필수 인증 프로필만 추출해 `.enc` 파일로 암호화 저장합니다.

### 2. 프롬프트 전송 및 완료 판정
1. `PlayGroundConfig`에 지정된 모델·시스템 프롬프트·도구·고급 옵션을 JS로 반영하며, 직전 호출과 같은 옵션은 건너뜁니다.
2. 프롬프트 전송 후 실제 턴 증가 또는 생성 시작 여부를 즉시 검증합니다.
3. 모델의 생각 과정(`<ms-thought-chunk>`), 로딩 스피너(`loading-indicator`), 코드 블록 스트리밍(`.container.generating`), 실행 버튼(`.stoppable`)이 모두 종료되고 본문 또는 이미지가 완성될 때까지 대기한 뒤, 아이콘 문자열(`content_copy` 등)과 생각 블록을 제외한 순수 결과만 반환합니다.

---

## 설치

```powershell
git clone https://github.com/Minekmj/playground_on_python.git
pip install -r requirements.txt
```

- Google Chrome 브라우저가 설치되어 있어야 합니다.

---

## 빠른 시작

### 기본 사용
```python
from playground_on_python import PlayGround

with PlayGround(verbose=False) as pg:  # verbose=False 로 로그 끄기
    pg.connect(backup=True)

    reply = pg.send(
        text="안녕하세요. 한 줄로 자기소개 해주세요.",
        system_input="간결하게 답하는 한국어 어시스턴트입니다.",
        model="gemini-4-hydrogen",
        thinnk="Low",
    )
    print(reply)
```

### 무료 이미지 모델 조회 및 이미지 생성
```python
from playground_on_python import PlayGround

with PlayGround(verbose=False) as pg:
    pg.connect(backup=True)

    free_img_models = pg.list_models(kind="image", paid=False)
    print("무료 이미지 모델:", [m["id"] for m in free_img_models])

    if free_img_models:
        res = pg.generate_image(
            "별이 빛나는 밤의 작은 등대, 일러스트",
            model=free_img_models[0]["id"],
            aspect_ratio="16:9",
            save_to="./outputs",
            allow_paid=False,
        )
        print("저장 완료:", res["paths"])
```

### 다중 클라이언트 병렬 처리
```python
from playground_on_python import PlayGroundPool, PlayGroundConfig

cfg = PlayGroundConfig(
    model="gemini-4-hydrogen",
    thinnk="Low",
    google_search=False,
    new_chat=True,
)

# default 프로필 백업을 3개 워커로 복제해 동시 실행
with PlayGroundPool(count=3, base_profile="default", verbose=False, default_config=cfg) as pool:
    results = pool.send_batch([
        {"text": "텍스트 추출", "media": "page_01.png"},
        {"text": "텍스트 추출", "media": "page_02.png"},
        {"text": "텍스트 추출", "media": "page_03.png"},
    ])
    for r in results:
        print(r)
```