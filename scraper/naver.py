# -*- coding: utf-8 -*-
"""
네이버 블로그(hongkongbus) '센텀시티 구내식당' 카테고리 스크래퍼.

게시글 구조(모바일 본문):
  [식당명 제목]  예) "동서대 구내식당 (지하) - 파티박스 (7,000원)"
  [그 식당의 식단표 사진]
  [다음 식당명 제목]
  [식단표 사진] ...
  [맨 끝에 위치 지도(메뉴 아님)]

→ 본문을 '순서대로' 훑으며, 식당명 제목이 나오면 현재 식당을 바꾸고,
  그 식당의 '첫 식단표 사진' 1장만 가져온다. 지도/스티커 등은 제외.
한 번의 호출로 4개 식당 항목(list[dict])을 반환한다.
"""
import re
import time

import config
import common

# 본문 업로드 이미지(식단표) 후보 도메인/경로
MENU_HOST_HINTS = ("mblogthumb", "postfiles", "blogfiles")
# 지도/스티커 등 메뉴와 무관한 이미지 제외 키워드
NON_MENU_HINTS = ("staticmap", "static.map", "simg.pstatic", "/map", "sticker",
                  "ssl.pstatic.net/static", "dthumb")


def _find_category_no(page):
    """모바일 카테고리 목록에서 이름이 일치하는 카테고리 번호를 찾는다."""
    api = f"https://m.blog.naver.com/rego/CategoryList.naver?blogId={config.NAVER_BLOG_ID}"
    try:
        page.goto(api, wait_until="domcontentloaded", timeout=30000)
        txt = page.inner_text("body")
        txt = txt[txt.find("{"):]
        import json
        data = json.loads(txt)
        cats = data.get("result", {}).get("mylogCategoryList", []) or data.get("categoryList", [])
        for c in cats:
            nm = c.get("categoryName", "")
            if config.NAVER_CATEGORY_NAME in nm:
                print(f"  [naver] 카테고리 '{nm}' -> no={c.get('categoryNo')}")
                return str(c.get("categoryNo"))
    except Exception as e:
        print(f"  [naver] 카테고리 API 실패: {e}")
    return None


def _latest_logno(page, category_no):
    """카테고리의 '가장 최신' 게시글 logNo를 구한다(최근 글일수록 logNo가 큼)."""
    candidates = []
    if category_no:
        list_url = (f"https://m.blog.naver.com/api/blogs/{config.NAVER_BLOG_ID}"
                    f"/post-list?categoryNo={category_no}&itemCount=10&page=1")
        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=30000)
            txt = page.inner_text("body")
            txt = txt[txt.find("{"):]
            import json
            data = json.loads(txt)
            items = data.get("result", {}).get("items", []) or data.get("items", [])
            for it in items[:10]:
                ln = str(it.get("logNo") or "")
                if ln.isdigit():
                    candidates.append(ln)
            if items:
                titles = [(str(it.get("logNo")), it.get("titleWithInspectMessage")
                           or it.get("title") or "") for it in items[:5]]
                print(f"  [naver] 최근 글 후보: {titles}")
        except Exception as e:
            print(f"  [naver] post-list API 실패: {e}")

    if not candidates:
        # 폴백: 카테고리 페이지에서 글 링크 추출
        cat_url = f"https://m.blog.naver.com/PostList.naver?blogId={config.NAVER_BLOG_ID}"
        if category_no:
            cat_url += f"&categoryNo={category_no}"
        page.goto(cat_url, wait_until="networkidle", timeout=40000)
        time.sleep(2)
        hrefs = page.eval_on_selector_all(
            "a[href*='logNo'], a[href*='/hongkongbus/']",
            "els => els.map(a => a.href)")
        for h in hrefs:
            m = re.search(r"(?:logNo=|/)(\d{6,})", h)
            if m:
                candidates.append(m.group(1))

    if not candidates:
        return None
    # 가장 큰 logNo = 가장 최신 글
    latest = max(candidates, key=lambda x: int(x))
    return latest


def _classify(text):
    """텍스트에 식당 키워드가 있으면 그 식당 id 반환(여러 개면 마지막 위치 우선)."""
    best_id, best_pos = None, -1
    for r in config.NAVER_RESTAURANTS:
        for kw in r["keywords"]:
            pos = text.rfind(kw)
            if pos > best_pos:
                best_pos, best_id = pos, r["id"]
    return best_id


def _is_menu_image(src):
    low = src.lower()
    if any(b in low for b in NON_MENU_HINTS):
        return False
    if "pstatic.net" not in low and "naver.net" not in low:
        return False
    return any(h in low for h in MENU_HOST_HINTS)


def scrape_blog(page, request_context, stored_logno=None):
    """네이버 블로그를 스크래핑해 식당별(4개) 항목 리스트 반환.

    stored_logno가 주어지고 최신 글이 그것과 같으면(=이번주 새 게시물 없음)
    None을 반환해 기존 데이터를 그대로 유지하게 한다.
    """
    print("  [naver] 시작")
    category_no = config.NAVER_CATEGORY_NO or _find_category_no(page)
    log_no = _latest_logno(page, category_no)
    if not log_no:
        raise RuntimeError("최신 게시글 logNo를 찾지 못함")

    if stored_logno and str(log_no) == str(stored_logno):
        print(f"  [naver] 최신 글(logNo={log_no})이 기존과 동일 — 새 게시물 없음")
        return None

    post_url = f"https://m.blog.naver.com/{config.NAVER_BLOG_ID}/{log_no}"
    print(f"  [naver] 게시글 -> {post_url}")
    page.goto(post_url, wait_until="networkidle", timeout=45000)
    time.sleep(2)

    # 본문을 '문서 순서대로' 텍스트/이미지 이벤트로 평탄화해서 추출
    events = page.evaluate(
        """() => {
            const root = document.querySelector('.se-main-container')
                       || document.querySelector('#viewTypeSelector')
                       || document.querySelector('#postViewArea')
                       || document.body;
            const out = [];
            const walk = (el) => {
                for (const node of el.childNodes) {
                    if (node.nodeType === 3) {
                        const t = node.textContent.replace(/\\s+/g, ' ').trim();
                        if (t) out.push({t: 'text', v: t});
                    } else if (node.nodeType === 1) {
                        if (node.tagName === 'IMG') {
                            const src = node.getAttribute('data-lazy-src')
                                     || node.getAttribute('data-src')
                                     || node.src || '';
                            out.push({t: 'img', v: src,
                                      w: node.naturalWidth || node.width || 0});
                        } else {
                            walk(node);
                        }
                    }
                }
            };
            walk(root);
            return out;
        }"""
    )

    # 순서대로 훑으며 식당명 제목→현재 식당 전환, 그 식당의 첫 식단표 사진 1장 채택
    picked = {}     # restaurant id -> image src
    current = None
    for ev in events:
        if ev["t"] == "text":
            hit = _classify(ev["v"])
            if hit:
                current = hit
                print(f"  [naver] 제목 감지 -> {current}: '{ev['v'][:40]}'")
        else:
            src = (ev.get("v") or "").strip()
            if not src or not _is_menu_image(src):
                continue
            if current and current not in picked:
                picked[current] = src
                print(f"  [naver] {current} 식단표 사진 채택: ...{src[-50:]}")

    week = common.today_kst_str()
    results = []
    any_ok = False
    for r in config.NAVER_RESTAURANTS:
        src = picked.get(r["id"])
        saved = []
        if src:
            fn = common.image_filename(r["id"], 0, src)
            dest = f"{config.IMAGE_DIR}/{fn}"
            if common.download_image(request_context, src, dest, referer=post_url):
                saved.append(f"data/images/{fn}")
        if saved:
            any_ok = True
        results.append({
            "id": r["id"],
            "name": r["name"],
            "source": "naver",
            "sourceUrl": post_url,
            "type": "weekly",
            "weekOf": week,
            "images": saved,
            "scrapedAt": common.now_kst().isoformat(),
            "note": "" if saved else "식단표 사진을 찾지 못함 — 원문 링크 확인",
        })
        print(f"  [naver] {r['name']}: {len(saved)}장")

    if not any_ok:
        raise RuntimeError("어느 식당의 식단표도 가져오지 못함")
    return results
