# -*- coding: utf-8 -*-
"""
센텀시티 구내식당 대시보드 - 스크래퍼 설정.

소스(카카오 채널 ID, 네이버 블로그/카테고리, 식당 키워드)가 바뀌면
여기만 고치면 됩니다. 셀렉터 튜닝 포인트도 주석으로 표시해 두었습니다.
"""

# 결과 산출물 경로 (public 아래에 두어 GitHub Pages가 그대로 서빙)
OUTPUT_DIR = "public/data"
IMAGE_DIR = "public/data/images"
MANIFEST = "public/data/menus.json"

# 카카오 채널(플러스친구) 소스: 매일 11시 전후 메뉴 사진 업로드.
# id = pf.kakao.com/{id}/posts 의 그 id 값.
KAKAO_SOURCES = [
    {
        "id": "jeongdam",
        "name": "정담식당",
        "channel": "_vKxgdn",
    },
    {
        "id": "schmaus",
        "name": "슈마우스 센텀",
        "channel": "_CiVis",
    },
]

# 네이버 블로그 소스: 매주 1회 한 게시글에 4개 식당의 주간(월~토) 메뉴가 사진으로 올라옴.
NAVER_BLOG_ID = "hongkongbus"
# 카테고리 이름(부분 일치). 카테고리 번호가 바뀌어도 이름으로 찾도록 함.
NAVER_CATEGORY_NAME = "센텀시티 구내식당"

# 네이버 게시글 안에서 각 식당을 라벨링하기 위한 키워드.
# 이미지 주변 텍스트(캡션/문단)에 아래 키워드가 보이면 해당 식당으로 분류.
NAVER_RESTAURANTS = [
    {"id": "dongseo",  "name": "동서대 구내식당",            "keywords": ["동서대"]},
    {"id": "dawa",     "name": "다와푸드 에이스하이테크21",  "keywords": ["다와", "에이스하이테크", "에이스 하이테크", "하이테크21"]},
    {"id": "byucksan", "name": "벽산e센텀클래스원 구내식당", "keywords": ["벽산", "센텀클래스", "클래스원"]},
    {"id": "video",    "name": "부산 영상산업센터 구내식당", "keywords": ["영상산업", "영상센터", "영상 산업"]},
]

# 휴리스틱: 메뉴 사진으로 볼 게시물/이미지 판단 기준.
# - 카카오: 최근 N일 이내의, 이미지가 포함된 가장 최신 게시물을 메뉴로 간주.
KAKAO_RECENT_DAYS = 2
# 한 게시물에서 가져올 이미지 최대 개수(메뉴는 보통 1~몇 장 → 과다 수집 방지).
KAKAO_MAX_IMAGES = 4
# 너무 작은(아이콘/이모지) 이미지는 메뉴표가 아니므로 제외 (픽셀 기준, 0이면 미적용).
MIN_IMAGE_WIDTH = 200

# 타임존
TZ = "Asia/Seoul"
