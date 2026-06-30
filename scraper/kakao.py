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

DATE_KEYS = ("createdAt", "created_at", "updatedAt", "regDateTime", "createTime", "publishedAt")
# 한 게시물(post item)의 첨부 이미지가 담기는 필드명 후보
MEDIA_KEYS = ("media", "images", "image", "attachments", "photos", "imageList",
              "files", "thumbnail", "contents", "content")


def _dedup(urls):
    seen, out = set(), []
    for u in urls:
        u = u.replace("\\/", "/")
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def _urls_in(node, acc=None, depth=0):
    """주어진 서브트리에서 카카오 CDN 이미지 url을 모은다."""
    if acc is None:
        acc = []
    if depth > 6:
        return acc
    if isinstance(node, str):
        for m in CDN_PAT.finditer(node):
            acc.append(m.group(0))
    elif isinstance(node, dict):
        for v in node.values():
            _urls_in(v, acc, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _urls_in(v, acc, depth + 1)
    return acc


def _media_images(node):
    """dict(한 게시물)에서 '미디어 필드'에 담긴 이미지만 수집(형제 게시물 침범 방지)."""
    urls = []
    for k, v in node.items():
        if any(mk in k.lower() for mk in MEDIA_KEYS):
            urls += _urls_in(v)
    return _dedup(urls)


def _find_date(node):
    for k in DATE_KEYS:
        if k in node and node[k]:
            return node[k]
    return None


def _walk_collect_posts(node, posts):
    """개별 게시물 단위로 수집. 날짜+미디어이미지를 가진 dict을 게시물로 보고,
    그 안으로는 더 내려가지 않아 상위 컨테이너가 전체 이미지를 싹쓸이하는 것을 막는다."""
    if isinstance(node, dict):
        date_val = _find_date(node)
        imgs = _media_images(node)
        if date_val and imgs:
            posts.append({"date": date_val, "images": imgs, "raw": node})
            return  # 이 게시물 하위로는 재귀하지 않음
        for v in node.values():
            _walk_collect_posts(v, posts)
    elif isinstance(node, list):
        for v in node:
            _walk_collect_posts(v, posts)


def _walk_collect_posts_generic(node, posts, depth=0):
    """폴백: 미디어 필드명을 못 찾는 구조용. 날짜를 가진 dict의 모든 CDN 이미지를 수집."""
    if isinstance(node, dict):
        date_val = _find_date(node)
        if date_val:
            imgs = _dedup(_urls_in(node))
            if imgs:
                posts.append({"date": date_val, "images": imgs, "raw": node})
        for v in node.values():
            _walk_collect_posts_generic(v, posts, depth + 1)
    elif isinstance(node, list):
        for v in node:
            _walk_collect_posts_generic(v, posts, depth + 1)


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
    page.remove_listener("response", on_response)

    # 1순위: 가로챈 JSON에서 게시물 추출(개별 게시물 단위)
    posts = []
    for blob in captured:
        _walk_collect_posts(blob, posts)
    if not posts:
        # 미디어 필드명을 못 찾은 경우 제네릭 폴백
        for blob in captured:
            _walk_collect_posts_generic(blob, posts)
    print(f"  [kakao] JSON에서 게시물 후보 {len(posts)}개 발견")

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

    # 후보 게시물들의 날짜·이미지수 로그(구조 진단용)
    for p in recent[:6]:
        print(f"  [kakao] 후보: 날짜={p.get('dt')} 이미지={len(p['images'])}장")

    chosen = recent[0]
    chosen_dt = chosen.get("dt")
    # 메뉴 게시물은 보통 사진 1~몇 장. 과다 수집 방지로 상한 적용.
    chosen_images = chosen["images"][:config.KAKAO_MAX_IMAGES]
    print(f"  [kakao] 선택 게시물 날짜={chosen_dt}, 이미지 {len(chosen['images'])}장 "
          f"-> {len(chosen_images)}장 사용")

    # 이미지 다운로드
    saved = []
    for i, img_url in enumerate(chosen_images):
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
