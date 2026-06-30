# 센텀시티 구내식당 메뉴 대시보드

부산 센텀시티 일대 구내식당 메뉴를 한 화면에서 보는 대시보드입니다.
GitHub Actions가 매일 메뉴 사진을 자동 수집하고, GitHub Pages로 배포합니다.

## 수집 대상

| 식당 | 소스 | 주기 |
|------|------|------|
| 정담식당 | 카카오 채널 `_vKxgdn` | 매일 (오전 11시 전후) |
| 슈마우스 센텀 | 카카오 채널 `_CiVis` | 매일 (오전 11시 전후) |
| 동서대 / 다와푸드 에이스하이테크21 / 벽산e센텀클래스원 / 영상산업센터 | 네이버 블로그 `hongkongbus` → '센텀시티 구내식당' 카테고리 | 매주 (월요일경) |

## 구조

```
scraper/        Playwright 스크래퍼 (Python)
  config.py     소스/식당/키워드 설정 (튜닝은 여기서)
  kakao.py      카카오 채널 스크래퍼
  naver.py      네이버 블로그 스크래퍼
  scrape.py     오케스트레이터 → public/data/menus.json 생성
public/         정적 대시보드 (GitHub Pages 루트)
  index.html / style.css / app.js
  data/menus.json          수집 결과(매니페스트)
  data/images/             다운로드된 메뉴 사진
.github/workflows/deploy.yml   소스별 스케줄 수집 + Pages 배포
```

## 설정 (최초 1회)

1. **GitHub Pages 활성화**: 저장소 → Settings → Pages → *Source*를 **GitHub Actions**로 설정.
2. **Actions 권한**: Settings → Actions → General → Workflow permissions를 *Read and write* 로.
3. 자동 실행 스케줄(KST):
   - **카카오(정담·슈마우스)** — 매일 **11:00**
   - **네이버(동서대·다와푸드·벽산·영상산업센터)** — 매주 **월요일 10:30 / 11:10**, 그리고 그 주 게시물이 아직 없으면 **17:00** 보강. 새 주간 게시물이 있을 때만 갱신.
   - Actions 탭에서 **Run workflow**로 전체 수동 실행도 가능합니다.

## 로컬 실행/테스트

```bash
pip install -r scraper/requirements.txt
python -m playwright install chromium
python scraper/scrape.py          # public/data/menus.json 갱신
# 대시보드 미리보기
cd public && python -m http.server 8000   # http://localhost:8000
```

## 동작 원리 / 튜닝 메모

- **메뉴 사진 선별(휴리스틱)**
  - 카카오: 최근 `KAKAO_RECENT_DAYS`일 이내, 이미지가 포함된 가장 최신 게시물의 사진을 메뉴로 간주.
  - 네이버: 게시글 본문 이미지를 순서대로 읽으며, 직전 텍스트에서 식당 키워드(`config.NAVER_RESTAURANTS`)를 만나면 그 식당으로 분류.
- **견고성**: 소스 하나가 실패해도 run은 죽지 않고, 실패한 소스는 직전 수집 데이터를 유지합니다.
- **카카오/네이버 구조 변경 시**: 셀렉터/키워드는 `scraper/config.py`와 각 스크래퍼 상단에서 조정하세요.

> ⚠️ 카카오·네이버는 비공식 스크래핑을 막을 수 있습니다(봇 차단·DOM 변경). 첫 실행 로그를 보고
> 셀렉터를 다듬어야 할 수 있습니다. 수집 실패 시 각 카드의 "원문 보기" 링크로 직접 확인 가능합니다.
