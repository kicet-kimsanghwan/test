# -*- coding: utf-8 -*-
"""
카카오 채널(pf.kakao.com) 게시물 스크래퍼.

채널 게시물 페이지는 SPA라서 내부 JSON API를 호출한다.
1순위: 페이지가 부르는 JSON 응답을 가로채(파싱) 게시물/이미지/날짜를 얻는다.
2순위: 렌더된 DOM에서 이미지/날짜를 긁는다.
둘 중 되는 쪽으로 "메뉴 사진"(최근 N일 내 이미지 포함 최신 게시물)을 선별한다.
"""
import re
import time
from datetime import timedelta

import config
import common

CDN_PAT = re.compile(r"https?://[^\"'\\ ]+(kakaocdn\.net|daumcdn\.net)[^\"'\\ ]*", re.IGNORECASE)


def _walk_collect_posts(node, posts):
    """JSON 트리를 순회하며 (createdAt 류 날짜) + (이미지 url 배열)을 가진 객체를 모은다."""
    if isinstance(node, dict):
        date_val = None
        for k in ("createdAt", "created_at", "updatedAt", "regDateTime", "createTime"):
            if k in node and node[k]:
                date_val = node[k]
                break
        imgs = _collect_image_urls(node)
        if date_val and imgs:
            posts.append({"date": date_val, "images": imgs, "raw": node})
        for v in node.values():
            _walk_collect_posts(v, posts)
    elif isinstance(node, list):
        for v in node:
            _walk_collect_posts(v, posts)


def _collect_image_urls(node, acc=None, depth=0):
    """객체(한 게시물) 안의 모든 카카오 CDN 이미지 url 수집. 너무 깊이 들어가진 않음."""
    if acc is None:
        acc = []
    if depth > 6:
        return acc
    if isinstance(node, str):
        for m in CDN_PAT.finditer(node):
            acc.append(m.group(0))
    elif isinstance(node, dict):
        for v in node.values():
            _collect_image_urls(v, acc, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _collect_image_urls(v, acc, depth + 1)
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for u in acc:
        u = u.replace("\\/", "/")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _parse_date(val):
    """다양한 카카오 날짜 표현 -> KST datetime (실패 시 None)."""
    from datetime import datetime
    if isinstance(val, (int, float)):
        ts = val / 1000 if val > 1e12 else val
        try:
            return datetime.fromtimestamp(ts, common.KST)
        except Exception:
            return None
    if isinstance(val, str):
        s = val.strip()
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y.%m.%d", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(s[:len(fmt) + 2].split("+")[0].split(".")[0], fmt)
                return dt.replace(tzinfo=common.KST)
            except Exception:
                continue
    return None


def scrape_channel(page, request_context, src):
    """한 카카오 채널을 스크래핑해 식당 항목(dict) 반환. 실패 시 예외."""
    rid, name, channel = src["id"], src["name"], src["channel"]
    url = f"https://pf.kakao.com/{channel}/posts"
    print(f"  [kakao] {name} -> {url}")

    captured = []

    def on_response(resp):
        try:
            ct = resp.headers.get("content-type", "")
            if "json" in ct and ("post" in resp.url or "rocket" in resp.url):
                captured.append(resp.json())
        except Exception:
            pass

    page.on("response", on_response)
    page.goto(url, wait_until="networkidle", timeout=45000)
    time.sleep(3)  # 지연 로딩 대기
    page.off("response", on_response)

    # 1순위: 가로챈 JSON에서 게시물 추출
    posts = []
    for blob in captured:
        _walk_collect_posts(blob, posts)

    # 2순위: DOM 폴백
    if not posts:
        print("  [kakao] JSON 캡처 실패 -> DOM 폴백")
        urls = page.eval_on_selector_all(
            "img, *[style*='background-image']",
            """els => els.map(el => {
                if (el.tagName === 'IMG') return el.src;
                const m = (el.getAttribute('style')||'').match(/url\\([\"']?([^\"')]+)/);
                return m ? m[1] : null;
            }).filter(Boolean)"""
        )
        cdn = [u for u in urls if "kakaocdn" in u or "daumcdn" in u]
        if cdn:
            posts.append({"date": common.now_kst().isoformat(), "images": cdn, "raw": None})

    if not posts:
        raise RuntimeError("게시물/이미지를 찾지 못함")

    # 날짜 파싱 + 최신순 정렬, 최근 N일 이내 우선
    for p in posts:
        p["dt"] = _parse_date(p["date"])
    cutoff = common.now_kst() - timedelta(days=config.KAKAO_RECENT_DAYS)
    dated = [p for p in posts if p["dt"]]
    dated.sort(key=lambda p: p["dt"], reverse=True)
    recent = [p for p in dated if p["dt"] >= cutoff] or dated or posts

    chosen = recent[0]
    chosen_dt = chosen.get("dt")
    print(f"  [kakao] 선택 게시물 날짜={chosen_dt}, 이미지 {len(chosen['images'])}장")

    # 이미지 다운로드
    saved = []
    for i, img_url in enumerate(chosen["images"]):
        fn = common.image_filename(rid, i, img_url)
        dest = f"{config.IMAGE_DIR}/{fn}"
        if common.download_image(request_context, img_url, dest, referer=url):
            saved.append(f"data/images/{fn}")
    if not saved:
        raise RuntimeError("이미지 다운로드 전부 실패")

    return {
        "id": rid,
        "name": name,
        "source": "kakao",
        "sourceUrl": url,
        "type": "daily",
        "date": chosen_dt.strftime("%Y-%m-%d") if chosen_dt else common.today_kst_str(),
        "images": saved,
        "scrapedAt": common.now_kst().isoformat(),
    }
