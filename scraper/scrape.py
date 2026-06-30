# -*- coding: utf-8 -*-
"""
오케스트레이터: 모든 소스를 스크래핑해 public/data/menus.json 갱신.

설계 원칙
- 소스 하나가 실패해도 전체 run은 죽지 않는다(try/except).
- 실패한 소스는 기존(이전 run) 데이터를 그대로 유지한다.
- 결과는 menus.json + 다운로드된 이미지(public/data/images).
"""
import sys
import traceback

from playwright.sync_api import sync_playwright

import config
import common
import kakao
import naver

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _stored_naver_logno(manifest):
    """기존 매니페스트의 네이버 항목 sourceUrl에서 logNo를 추출."""
    import re
    for r in manifest.get("restaurants", []):
        if r.get("source") == "naver":
            m = re.search(r"/(\d{6,})(?:\D|$)", r.get("sourceUrl", ""))
            if m:
                return m.group(1)
    return None


def main():
    # 인자: kakao | naver | all(기본). 스케줄에 따라 소스를 분리 실행한다.
    target = (sys.argv[1] if len(sys.argv) > 1 else "all").lower()
    do_kakao = target in ("all", "kakao")
    do_naver = target in ("all", "naver")
    print(f"수집 대상: {target} (kakao={do_kakao}, naver={do_naver})")

    manifest = common.load_manifest()
    manifest.setdefault("errors", {})
    ok, fail = 0, 0

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
        ctx = browser.new_context(
            user_agent=UA,
            locale="ko-KR",
            viewport={"width": 1280, "height": 2000},
            extra_http_headers={"Accept-Language": "ko-KR,ko;q=0.9"},
        )
        page = ctx.new_page()
        req = ctx.request  # 이미지 다운로드용(쿠키/헤더 공유)

        # 1) 카카오 채널들(매일 갱신)
        if do_kakao:
            for src in config.KAKAO_SOURCES:
                try:
                    entry = kakao.scrape_channel(page, req, src)
                    common.merge_restaurant(manifest, entry)
                    manifest["errors"][src["id"]] = None
                    ok += 1
                except Exception as e:
                    fail += 1
                    manifest["errors"][src["id"]] = str(e)
                    print(f"  [FAIL] kakao {src['id']}: {e}")
                    traceback.print_exc()

        # 2) 네이버 블로그(주간 갱신, 새 게시물 있을 때만)
        if do_naver:
            try:
                stored = _stored_naver_logno(manifest)
                entries = naver.scrape_blog(page, req, stored_logno=stored)
                if entries is None:
                    # 이번주 새 게시물 없음 → 기존 데이터 유지(정상)
                    print("  [naver] 새 게시물 없음 — 기존 데이터 유지")
                else:
                    # 옛 네이버 항목 제거 후 새로 채운다.
                    manifest["restaurants"] = [
                        r for r in manifest.get("restaurants", [])
                        if r.get("source") != "naver"
                    ]
                    for entry in entries:
                        common.merge_restaurant(manifest, entry)
                        manifest["errors"][entry["id"]] = entry.get("note") or None
                ok += 1
            except Exception as e:
                fail += 1
                manifest["errors"]["naver"] = str(e)
                print(f"  [FAIL] naver: {e}")
                traceback.print_exc()

        browser.close()

    common.save_manifest(manifest)
    print(f"\n완료: 성공 {ok} / 실패 {fail}")
    print(f"매니페스트: {config.MANIFEST}")
    # 실행한 소스가 전부 실패하면 비정상 종료(Actions에서 눈에 띄게)
    if (do_kakao or do_naver) and ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
