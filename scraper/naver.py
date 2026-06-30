# -*- coding: utf-8 -*-
"""
네이버 블로그(hongkongbus) '센텀시티 구내식당' 카테고리 스크래퍼.

- 모바일 사이트(m.blog.naver.com)가 프레임이 없어 다루기 쉬움.
- 카테고리 -> 최신 게시글 -> 본문 이미지들을 순서대로 추출.
- 각 이미지 직전 텍스트에서 식당 키워드를 찾아 식당별로 분류(휴리스틱).
한 번의 호출로 4개 식당 항목(list[dict])을 반환한다.
"""
import re
import time

import config
import common

PSTATIC_PAT = re.compile(r"(post(files)?|blogfiles|mblogthumb)[^\"']*pstatic\.net", re.IGNORECASE)


def _find_category_no(page):
    """모바일 카테고리 목록에서 이름이 일치하는 카테고리 번호를 찾는다."""
    api = f"https://m.blog.naver.com/rego/CategoryList.naver?blogId={config.NAVER_BLOG_ID}"
    try:
        page.goto(api, wait_until="domcontentloaded", timeout=30000)
        txt = page.inner_text("body")
        txt = txt[txt.find("{"):]  # 앞쪽 안전 prefix 제거
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
    """카테고리의 최신 게시글 logNo를 구한다."""
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
            if items:
                return str(items[0].get("logNo"))
        except Exception as e:
            print(f"  [naver] post-list API 실패: {e}")

    # 폴백: 카테고리 페이지에서 첫 글 링크 추출
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
            return m.group(1)
    return None


def _classify(label_text):
    """텍스트에서 식당 키워드를 찾아 식당 id 반환(없으면 None)."""
    for r in config.NAVER_RESTAURANTS:
        for kw in r["keywords"]:
            if kw in label_text:
                return r["id"]
    return None


def scrape_blog(page, request_context):
    """네이버 블로그를 스크래핑해 식당 항목 리스트 반환."""
    print("  [naver] 시작")
    category_no = _find_category_no(page)
    log_no = _latest_logno(page, category_no)
    if not log_no:
        raise RuntimeError("최신 게시글 logNo를 찾지 못함")

    post_url = f"https://m.blog.naver.com/{config.NAVER_BLOG_ID}/{log_no}"
    print(f"  [naver] 게시글 -> {post_url}")
    page.goto(post_url, wait_until="networkidle", timeout=45000)
    time.sleep(2)

    # 본문 컨테이너(SmartEditor ONE 우선)에서 이미지 + 직전 텍스트를 순서대로 추출
    blocks = page.evaluate(
        """() => {
            const root = document.querySelector('.se-main-container')
                       || document.querySelector('#viewTypeSelector')
                       || document.body;
            const out = [];
            let lastText = '';
            const walk = (el) => {
                for (const node of el.childNodes) {
                    if (node.nodeType === 3) {
                        const t = node.textContent.trim();
                        if (t) lastText = (lastText + ' ' + t).slice(-200);
                    } else if (node.nodeType === 1) {
                        if (node.tagName === 'IMG') {
                            const src = node.getAttribute('data-lazy-src')
                                     || node.getAttribute('data-src')
                                     || node.src;
                            if (src) out.push({src, label: lastText,
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

    # pstatic 이미지(네이버 업로드)만, 너무 작은 건 제외
    imgs = []
    for b in blocks:
        src = (b.get("src") or "").split("?")[0]
        if not src:
            continue
        if "pstatic.net" not in src and "blogfiles" not in src and "postfiles" not in src:
            continue
        if config.MIN_IMAGE_WIDTH and b.get("w") and b["w"] < config.MIN_IMAGE_WIDTH:
            continue
        # 원본 화질 요청 (썸네일 파라미터 제거됨; ?type 원본은 그대로 둠)
        imgs.append({"src": src, "label": b.get("label", "")})
    print(f"  [naver] 본문 이미지 {len(imgs)}장")

    # [디버그] 각 이미지의 직전 텍스트(라벨)를 로그로 남겨 본문 구조를 파악한다.
    for i, im in enumerate(imgs):
        lbl = (im.get("label") or "").strip().replace("\n", " ")
        print(f"  [naver][img {i}] label='{lbl[-120:]}'")

    if not imgs:
        raise RuntimeError("본문에서 이미지를 찾지 못함")

    # 이 블로그 게시글은 4개 식당 메뉴판이 '한 게시글에 사진으로 줄줄이' 올라오고,
    # 사진별로 어느 식당인지 텍스트 표시가 없다(소개 문단에 4곳을 한꺼번에 나열).
    # 따라서 텍스트만으로 식당별 자동 분리는 불가 → 메뉴판 전체를 한 섹션으로 모아 보여준다.
    # (식당/요일별 정확한 분리는 사진 OCR이 필요하며, 추후 옵션으로 추가 가능.)
    geo_words = ("NAVER Corp", "OpenStreetMap", "지도 데이터", "지도 컨트롤러")
    saved = []
    for i, im in enumerate(imgs):
        # 본문 끝의 지도 캡처 등 메뉴와 무관한 이미지는 제외
        if any(w in (im.get("label") or "") for w in geo_words):
            continue
        src = im["src"]
        fn = common.image_filename("naver", i, src)
        dest = f"{config.IMAGE_DIR}/{fn}"
        if common.download_image(request_context, src, dest, referer=post_url):
            saved.append(f"data/images/{fn}")
    print(f"  [naver] 주간 메뉴판 {len(saved)}장 저장")

    if not saved:
        raise RuntimeError("메뉴 이미지 다운로드 전부 실패")

    rest_names = " · ".join(r["name"].replace(" 구내식당", "") for r in config.NAVER_RESTAURANTS)
    return [{
        "id": "naver_weekly",
        "name": "센텀 구내식당 주간 메뉴",
        "subtitle": rest_names,
        "source": "naver",
        "sourceUrl": post_url,
        "type": "weekly",
        "weekOf": common.today_kst_str(),
        "images": saved,
        "scrapedAt": common.now_kst().isoformat(),
        "note": "",
    }]
