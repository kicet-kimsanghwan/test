---
name: centum-menu-dashboard
description: 부산 센텀시티 구내식당 식단표 대시보드(이 저장소)를 다룰 때 사용. 카카오/네이버 스크래퍼 수정·디버깅, 식당(소스) 추가·변경, 실패한 GitHub Actions 실행 원인 분석, 메뉴 사진(식단표) 선별 튜닝, 자동 수집 스케줄/지연 문제 해결, 대시보드 UI 변경 등. "메뉴가 안 나온다/이상하다", "식당 추가", "자동 업데이트가 안 된다", "스크래퍼 고쳐줘" 같은 요청에 트리거.
---

# 센텀시티 구내식당 식단표 대시보드 — 유지보수 가이드

부산 센텀시티 일대 6개 구내식당의 식단표를 한 화면에 모으는 대시보드.
**서버 없이** GitHub Actions(수집) + Git(저장) + GitHub Pages(호스팅)로 동작한다.

라이브: `https://kicet-kimsanghwan.github.io/test/`

## 아키텍처 한눈에

```
GitHub Actions (정해진 시각에 잠깐 실행)
   └─ Playwright로 스크래핑 → public/data/menus.json + public/data/images/*.jpg|png 커밋
        └─ GitHub Pages 가 public/ 을 정적 서빙 → 브라우저
```

- 전용 서버·DB 없음. `public/data/menus.json` 이 사실상 DB.
- 프론트(`public/app.js`)가 `menus.json` 을 fetch 해서 카드로 렌더.

## 파일 지도

```
scraper/
  config.py    소스·식당·키워드·임계값 등 모든 설정 (튜닝은 대부분 여기)
  common.py    매니페스트 IO, 이미지 다운로드/측정(Pillow), 파일명 헬퍼
  kakao.py     카카오 채널(정담·슈마우스) 스크래퍼
  naver.py     네이버 블로그(동서대·다와푸드·벽산·영상) 스크래퍼
  scrape.py    오케스트레이터. 인자 kakao|naver|all 로 소스 분리 실행
  requirements.txt  playwright, Pillow
public/
  index.html / style.css / app.js   대시보드
  data/menus.json                   수집 결과(매니페스트)
  data/images/                      다운로드된 식단표 이미지
.github/workflows/deploy.yml        수집 + Pages 배포 워크플로
```

## 수집 대상 (config.py)

| id | 이름 | 소스 | 주기 |
|----|------|------|------|
| jeongdam | 정담식당 | 카카오 채널 `_vKxgdn` | 매일 |
| schmaus | 슈마우스 센텀 | 카카오 채널 `_CiVis` | 매일 |
| dongseo/dawa/byucksan/video | 동서대·다와푸드 에이스하이테크21·벽산e센텀클래스원·부산영상산업센터 | 네이버 블로그 `hongkongbus` 카테고리 9 | 매주(월요일 새 글) |

## 스크래퍼 동작 원리 & 튜닝 포인트

### 카카오 (kakao.py)
- 게시물 페이지는 SPA. 페이지가 부르는 **JSON 응답을 가로채** 게시물/이미지/날짜 추출(`_walk_collect_posts`, 미디어 필드 기준으로 **게시물 단위** 수집). 실패 시 DOM 폴백.
- **정담은 같은 날 게시물이 2개**(대표메뉴 사진첩 + 식단표)다. 그래서 **당일(top_dt.date()) 모든 게시물** 이미지를 후보로 모으되, `KAKAO_PER_POST`로 게시물별 상한을 둬 한 게시물이 후보를 독점(=식단표 누락)하지 않게 한다.
- 후보 중 **식단표 선별 = 흰 배경 비율(`common.image_stats`)이 가장 높은(세로형 가산점) 1장.** 음식 사진은 흰 배경이 적어 자연히 걸러진다. (`KAKAO_CANDIDATES`, `MIN_IMAGE_WIDTH`)
- 카카오는 **같은 이미지를 여러 해상도**로 준다. 흰 배경 점수가 같으면 area 큰 걸 고른다.
- 튜닝: 엉뚱한 사진(대표메뉴)이 잡히면 → white 임계/세로형 가중치(`kakao.py`의 `score` 식) 조정. 로그의 `[kakao] 후보 WxH white=.. ratio=.. score=..` 를 근거로.

### 네이버 (naver.py)
- **모바일**(m.blog.naver.com)이 프레임 없어 다루기 쉬움. 카테고리 번호는 `config.NAVER_CATEGORY_NO="9"` 고정(이름 검색은 폴백).
- 최신 글 = **logNo 최댓값**(`_latest_logno`). 최신 글 logNo가 기존 저장분과 같으면 `scrape_blog`이 **None 반환 → 갱신 생략**(이번주 새 게시물이 있을 때만 업데이트). stored logNo는 `scrape.py:_stored_naver_logno`가 기존 sourceUrl에서 뽑아 전달.
- 본문 구조: `[식당명 제목] → [그 식당 식단표 사진] → [다음 제목] → … → [맨 끝 지도]`.
  본문을 **문서 순서대로** 텍스트/이미지로 평탄화(`page.evaluate`) 후, 텍스트에 식당 키워드가 나오면 current 식당 전환, 그 식당의 **첫 식단표 사진 1장**만 채택.
- **지도/스티커 제외**: `NON_MENU_HINTS`(staticmap, simg.pstatic, sticker 등). 메뉴 이미지 힌트: `MENU_HOST_HINTS`(mblogthumb/postfiles/blogfiles).
- **404 주의**: 네이버 썸네일 URL의 `?type=w800` 파라미터를 **떼면 404**난다 → src를 그대로(파라미터 유지) 사용. `data-lazy-src` 우선.
- 튜닝: 특정 식당이 비면 → 로그의 `[naver] 제목 감지 -> id` 와 `식단표 사진 채택` 라인 확인. 키워드는 `config.NAVER_RESTAURANTS[].keywords`.

## 개발/배포 워크플로 (중요)

1. **항상 최신 main에서 브랜치를 뜬다**: `git fetch origin main && git checkout -B <branch> origin/main`.
2. `scraper/` 수정 → `python3 -m py_compile scraper/*.py` 로 문법 검증.
3. 커밋·푸시 후 **브랜치에서 워크플로를 수동 실행**해 테스트:
   `mcp__github__actions_run_trigger(run_workflow, workflow_id=deploy.yml, ref=<branch>)`.
   - ⚠️ **브랜치 실행은 build는 성공해도 deploy(Pages)가 항상 실패한다** — Pages 환경이 main에서만 배포되도록 보호돼 있어서다. **정상**이다. build 잡만 성공하면 됨.
4. build 잡 로그(`get_job_logs`, `list_workflow_jobs(filter:latest)`로 build job_id)와 `menus.json`(브랜치 ref)으로 결과 검증.
5. 좋으면 **main으로 PR 생성** → 사용자가 머지 → main push가 실행되어 **build+deploy 모두 성공, 라이브 반영**.
6. 커밋 author는 `Claude <noreply@anthropic.com>`.

### 실행 결과 확인 팁
- `mcp__github__actions_list` 응답이 매우 커서 토큰 한도를 넘으면 파일로 저장된다 → `python3 -c "import json; d=open('<file>').read(); o=json.loads(d[d.find('{'):]); r=o['workflow_runs'][0]; print(r['id'],r['status'],r['conclusion'])"` 로 슬라이스.
- `menus.json`의 `errors` 가 전부 null이고 6개 식당이 각 1장이면 정상.

## 과거에 겪은 버그(재발 방지)

- `page.off(...)` → Playwright 파이썬엔 없음. **`page.remove_listener(...)`** 사용.
- 러너 `ubuntu-latest`(24.04)에서 playwright 1.44의 `--with-deps`가 `libasound2` 못 찾음 → 워크플로 build 잡을 **`ubuntu-22.04`** 로 고정.
- 변수명 바꾼 뒤 return에 옛 이름 남아 `NameError`(예: chosen_dt) → 리팩터 후 py_compile 필수.
- 옛 이미지들이 `public/data/images/`에 계속 쌓인다(orphan). 필요 시 정리 가능(현재는 방치).

## 자동 수집 스케줄 & "왜 제때 안 되나" (자주 나오는 질문)

- 워크플로 cron(KST): 카카오 매일 11시대, 네이버 월요일 오전/오후. `github.event.schedule`로 소스 분기(`scrape.py` 인자).
- **핵심 한계**: GitHub 무료 **schedule 은 정시에 안 돈다.** 실측상 11:00 예정이 **~15시에 실행(수 시간 지연)**, 가끔 스킵. 저활동 공개 repo·정각(:00)일수록 심함. → "11시 자동"을 GitHub 자체 cron으로는 **보장 불가**.
- **즉시 수동 실행**은 지연 없음: Actions → Run workflow, 또는 `actions_run_trigger(run_workflow, ref=main)`.
- **정시 보장 해결책 = 외부에서 dispatch 찔러주기**(dispatch는 즉시 실행됨):
  - cron-job.org(무료)에서 매일 11:15 KST에 아래를 POST.
    - URL: `https://api.github.com/repos/kicet-kimsanghwan/test/actions/workflows/deploy.yml/dispatches`
    - Headers: `Authorization: Bearer <fine-grained PAT, repo test, Actions: R/W>`, `Accept: application/vnd.github+json`, `Content-Type: application/json`
    - Body: `{"ref":"main"}`
  - 토큰 발급·외부 서비스 가입은 **사용자 계정으로만** 가능(대신 못 해줌). 워크플로는 이미 dispatch 수신 준비 완료.

## 흔한 요청별 대응 요약

- "메뉴가 안 바뀐다" → 먼저 최신 main `menus.json`의 `scrapedAt`/`date` 확인. 오래됐으면 **수동 실행**으로 갱신. 근본은 위 스케줄 지연 문제.
- "정담이 음식사진으로 나온다" → kakao 흰배경 선별 튜닝(위 카카오 항목).
- "특정 네이버 식당이 비었다/틀렸다" → 로그의 제목감지·채택 라인 + `NAVER_RESTAURANTS` 키워드.
- "식당 추가" → `config.py`의 `KAKAO_SOURCES` 또는 `NAVER_RESTAURANTS`에 항목 추가. 네이버면 이미지 힌트/키워드 확인.
- "실행이 빨갛다(실패)" → 브랜치 실행이면 deploy 실패는 정상. build 잡 로그로 실제 원인 확인.
