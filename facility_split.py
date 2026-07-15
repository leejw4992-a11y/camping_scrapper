# -*- coding: utf-8 -*-
"""
facility_split.py — 캠핑장 '시설'을 대분류/소분류로 쪼개 CSV로 저장
------------------------------------------------------------------
고캠핑 API의 시설 항목은 "전기,화장실,샤워실"처럼 콤마로 붙은 한 덩어리다.
이걸 콤마 기준으로 잘라, 시설 하나를 한 줄씩 풀어준다.

  (원본 1줄)
    금호강오토캠핑장 | 주요시설 = "전기,화장실,온수"
  (쪼갠 결과 3줄)
    금호강오토캠핑장 | 대분류=주요시설 | 소분류=전기
    금호강오토캠핑장 | 대분류=주요시설 | 소분류=화장실
    금호강오토캠핑장 | 대분류=주요시설 | 소분류=온수

이렇게 '긴 형식(tidy data)'으로 만들면 엑셀/판다스에서
시설별로 세기·거르기·집계하기가 아주 쉬워진다.

실행 방법
  python facility_split.py
  -> 같은 폴더에 campsite_facilities.csv 생성
"""

import csv
from camping_scrapper import get_campsites   # 데이터는 기존 scraper.py에서 가져온다


# 대분류 이름 : 그 시설이 담긴 항목(콤마로 붙은 문자열)
# 왼쪽이 대분류로 쓸 이름, 오른쪽이 캠핑장 딕셔너리에서 꺼낼 열 이름.
CATEGORIES = {
    "주요시설":       "주요시설",
    "글램핑 내부시설": "글램핑_내부시설",
    "카라반 내부시설": "카라반_내부시설",
}

# 저장할 열 순서
FIELDS = ["캠핑장명", "주소", "시도", "시군구", "대분류", "소분류"]


def explode_facilities(camps):
    """캠핑장 목록을 받아, 시설을 한 줄씩 쪼갠 목록으로 돌려준다."""
    result = []

    # 캠핑장 하나(camp)씩 처리
    for camp in camps:
        # 대분류(주요시설/글램핑/카라반)마다 반복
        for daebunryu, col in CATEGORIES.items():
            text = camp.get(col, "")          # 예) "전기,화장실,온수"

            # 콤마로 잘라 시설 하나(item)씩 꺼낸다
            for item in text.split(","):
                item = item.strip()           # 앞뒤 공백 제거
                if not item:                  # 빈 칸이면 건너뜀
                    continue

                # 시설 하나 = 결과 한 줄
                result.append({
                    "캠핑장명": camp["캠핑장명"],
                    "주소":    camp["주소"],
                    "시도":    camp["시도"],
                    "시군구":  camp["시군구"],
                    "대분류":  daebunryu,
                    "소분류":  item,
                })

    return result


def save_csv(rows, filename):
    """쪼갠 목록을 CSV로 저장한다."""
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    print("캠핑장 데이터를 받아옵니다...")
    # 전체를 쪼개려면 아래처럼. 특정 지역만 하려면 get_campsites(sido="대구광역시")
    camps = get_campsites()

    print("시설을 대분류/소분류로 쪼갭니다...")
    exploded = explode_facilities(camps)

    save_csv(exploded, "campsite_facilities.csv")
    print(f"완료! 총 {len(exploded)}줄 저장 -> campsite_facilities.csv")
