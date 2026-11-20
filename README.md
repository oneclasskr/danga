# 자재 단가 조회 앱

조달청 시설공통자재 가격을 매주 자동으로 받아와서 검색, 견적서 작성, 가격 변동 알림에 쓰는 웹앱입니다.

- **데이터:** 공공데이터포털 `조달청_나라장터 가격정보현황서비스`의 시설공통자재(종합) 가격정보
- **자동 실행:** GitHub Actions가 매주 월요일 오전 6시 17분에 새로 게시된 가격을 받아옵니다
- **알림:** 직전 가격보다 5% 이상 바뀐 품목이 있으면 GitHub 이슈로 등록되고, 그 내용이 메일로 옵니다
- **앱:** GitHub Pages에 올라가서 PC와 휴대폰 브라우저에서 같은 주소로 엽니다
- **비용:** 모두 무료입니다 (공공데이터포털, GitHub 무료 계정)

## 폴더 구성

| 경로 | 내용 |
|---|---|
| `collect.py` | 수집기. 가격을 받아 `data/`에 저장합니다 |
| `site/index.html` | 웹앱 화면 |
| `.github/workflows/collect.yml` | 매주 자동 실행 설정 |
| `tests/test_collect.py` | 가짜 응답으로 수집기를 확인하는 테스트 |
| `data/` | 첫 실행 후 생깁니다. 가격 이력(`postings.csv`), 앱용 단가(`prices.json`) |

## 설치 순서 (처음 한 번, 약 20분)

### 1. 인증키 재발급

대화 중에 인증키가 화면에 노출되었으니, [공공데이터포털](https://www.data.go.kr) 마이페이지 → 데이터활용 → Open API → 인증키 발급현황에서 **재발급**을 받으세요. 아래 4단계에서 새 키를 씁니다.

### 2. GitHub 가입과 저장소 만들기

1. [github.com](https://github.com)에서 회사 메일로 무료 가입합니다.
2. 오른쪽 위 **+** → **New repository**를 누릅니다.
3. 이름은 `danga`처럼 정하고 **Public**을 고릅니다.
   - 무료 계정에서 GitHub Pages로 앱을 열려면 공개 저장소여야 합니다.
   - 저장소에 들어가는 것은 조달청 공개 가격과 프로그램뿐입니다. 견적서에 넣는 공사명이나 수량은 각자 브라우저에만 저장되고 저장소에 올라가지 않습니다.
4. **Create repository**를 누릅니다.

### 3. 파일 올리기

1. 저장소 화면에서 **uploading an existing file**(또는 **Add file → Upload files**)을 누릅니다.
2. 압축을 푼 폴더에서 `collect.py`, `README.md`, `site` 폴더, `tests` 폴더를 끌어다 놓고 **Commit changes**를 누릅니다.
3. `.github` 폴더는 숨김 폴더라 끌어다 놓기로 안 올라갈 수 있습니다. 그럴 때는 **Add file → Create new file**을 누르고,
   - 파일 이름 칸에 `.github/workflows/collect.yml`을 그대로 입력합니다.
   - 내용 칸에 압축 파일 안 `collect.yml`의 내용을 전부 붙여 넣고 **Commit changes**를 누릅니다.

### 4. 인증키 등록

1. 저장소의 **Settings → Secrets and variables → Actions**로 갑니다.
2. **New repository secret**을 누릅니다.
3. Name에 `DATA_GO_KR_KEY`, Secret에 재발급받은 **일반 인증키**를 넣고 저장합니다.

인증키는 이 비밀 저장소에만 두고, 파일이나 메일, 채팅에 적지 마세요.

### 5. 앱 공개 설정

**Settings → Pages**에서 Source를 **GitHub Actions**로 바꿉니다.

### 6. 첫 실행

1. **Actions** 탭 → 왼쪽 **단가 수집** → **Run workflow**를 누릅니다.
2. 첫 실행은 2025년 1월 1일부터 지금까지 게시된 가격을 모두 받아서 시간이 걸립니다.
3. 끝나면 **Settings → Pages**에 앱 주소가 나옵니다. 보통 `https://계정이름.github.io/danga/` 형태입니다. 이 주소를 휴대폰과 PC에 즐겨찾기 해 두세요.

첫 실행에서는 과거 자료를 쌓기만 하고 알림은 보내지 않습니다. 알림은 두 번째 실행부터 갑니다.

### 7. 알림 메일 받기

저장소 위쪽 **Watch → Custom → Issues**를 체크합니다. 가격 변동 이슈가 등록되면 가입한 메일로 알림이 옵니다. 팀원도 받게 하려면 GitHub 계정을 만들어 같은 방식으로 Watch 하면 됩니다.

## 문제가 생기면

수집이 실패하면 GitHub가 메일로 알려줍니다. Actions 탭에서 실패한 실행을 열면 원인이 나옵니다.

| 메시지 | 원인과 조치 |
|---|---|
| `DATA_GO_KR_KEY 환경변수에…` | 4단계의 Secret 이름이 정확한지 확인하세요 |
| `JSON이 아닌 응답` (내용에 `SERVICE_KEY_IS_NOT_REGISTERED`) | 인증키가 틀렸거나 아직 활성화 전입니다. 새로 받은 키는 활성화에 1~2시간 걸릴 수 있습니다 |
| `API 오류 22` 또는 `호출 한도` | 하루 호출 한도(1,000회)를 넘었습니다. 받은 데까지는 저장되고, 다음 실행에서 이어 받습니다. 첫 수집 중이면 다음 날 **Run workflow**를 한 번 더 누르세요 |
| 연결 시간 초과 | 공공데이터포털 서버 문제일 수 있습니다. 잠시 뒤 다시 실행하세요 |

## 설정 바꾸기

`.github/workflows/collect.yml`에서 바꿉니다.

- `ALERT_THRESHOLD: "5"` 알림 기준 변동률(%)
- `BACKFILL_FROM: "20250101"` 첫 실행 때 받을 시작일
- `cron: "17 21 * * 0"` 실행 시각 (세계 표준시 기준, 한국 시간보다 9시간 늦음)

## 내 컴퓨터에서 확인하기

```
python tests/test_collect.py          # 가짜 응답으로 수집기 테스트
DATA_GO_KR_KEY=인증키 python collect.py  # 실제로 수집
```
