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


def main():
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

        # 1) 카카오 채널들
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

        # 2) 네이버 블로그(4개 식당)
        try:
            entries = naver.scrape_blog(page, req)
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
    # 모든 소스가 실패하면 비정상 종료(Actions에서 눈에 띄게)
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
