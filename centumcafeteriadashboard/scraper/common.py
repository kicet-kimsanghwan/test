# -*- coding: utf-8 -*-
"""공용 유틸: 매니페스트 입출력, 이미지 다운로드, 날짜 헬퍼."""
import json
import os
import re
import hashlib
from datetime import datetime, timezone, timedelta

import config

KST = timezone(timedelta(hours=9))


def now_kst():
    return datetime.now(KST)


def today_kst_str():
    return now_kst().strftime("%Y-%m-%d")


def load_manifest():
    """기존 매니페스트를 읽어온다. 없으면 빈 골격을 반환.

    스크래핑이 실패한 소스는 이전 데이터를 그대로 유지하기 위해 사용한다.
    """
    if os.path.exists(config.MANIFEST):
        try:
            with open(config.MANIFEST, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"updatedAt": None, "restaurants": [], "errors": {}}


def save_manifest(data):
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    data["updatedAt"] = now_kst().isoformat()
    with open(config.MANIFEST, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def merge_restaurant(manifest, entry):
    """식당 항목을 id 기준으로 매니페스트에 삽입/갱신."""
    rs = manifest.setdefault("restaurants", [])
    for i, r in enumerate(rs):
        if r.get("id") == entry.get("id"):
            rs[i] = entry
            return
    rs.append(entry)


def get_existing(manifest, rid):
    for r in manifest.get("restaurants", []):
        if r.get("id") == rid:
            return r
    return None


def slugify(text):
    text = re.sub(r"[^0-9a-zA-Z가-힣]+", "-", text).strip("-")
    return text or "img"


def download_image(request_context, url, dest_path, referer=None):
    """Playwright APIRequestContext로 이미지를 내려받는다.

    브라우저 컨텍스트의 헤더/쿠키를 그대로 써서 referer 검사를 통과한다.
    성공하면 True.
    """
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    headers = {}
    if referer:
        headers["referer"] = referer
    try:
        resp = request_context.get(url, headers=headers, timeout=30000)
        if not resp.ok:
            print(f"    [download] HTTP {resp.status} for {url}")
            return False
        body = resp.body()
        if not body or len(body) < 1024:  # 1KB 미만이면 깨진/플레이스홀더 이미지로 간주
            print(f"    [download] too small ({len(body) if body else 0}B) {url}")
            return False
        with open(dest_path, "wb") as f:
            f.write(body)
        return True
    except Exception as e:
        print(f"    [download] error {e} for {url}")
        return False


def ext_from_url(url, default=".jpg"):
    m = re.search(r"\.(jpg|jpeg|png|gif|webp)(\?|$)", url, re.IGNORECASE)
    if m:
        return "." + m.group(1).lower()
    return default


def image_filename(rid, index, url):
    h = hashlib.md5(url.encode("utf-8")).hexdigest()[:8]
    return f"{rid}-{today_kst_str()}-{index}-{h}{ext_from_url(url)}"
