import os
import csv
import time
import requests

from dotenv import load_dotenv
load_dotenv()

# 환경변수(SERVICE_KEY)가 있으면 그걸 쓰고, 없으면 아래 기본값을 쓴다.
SERVICE_KEY = os.environ.get(
    "SERVICE_KEY",
    "",
)
BASE_URL = "https://apis.data.go.kr/B551011/GoCamping/basedList"
NUM_OF_ROWS = 1000

FIELD_MAP = {
    "facltNm" : "캠핑장명",
    "facltDivNm" : "운영기관",   # ← 추가: 사업주체(공공/민간)
    "mangeDivNm" : "관리기관",   # ← 추가: 관리형태(직영/위탁)
    "induty" : "업종",
    "addr1" : "주소",
    "sbrsCl" : "주요시설",
    "toiletCo" : "화장실(개)",
    "swrmCo" : "샤워실(개)",
    "animalCmgCl" : "반려동물_동반여부",
    "tel" : "전화번호",
    "resveUrl" : "예약페이지",
    "firstImageUrl" : "대표사진",   # ← 추가: 카드에 보여줄 대표 사진 주소
    "siteMg1Co" : "데크사이트",
    "siteMg2Co" : "파쇄석사이트",
    "siteMg3Co" : "카라반사이트",
    "doNm" : "시도",
    "sigunguNm" : "시군구",
    "mapX" : "경도",   # ← 추가: 소요시간 계산에 쓸 좌표(경도)
    "mapY" : "위도",   # ← 추가: 소요시간 계산에 쓸 좌표(위도)
}


def _get_with_retry(params, tries=3): # 실패해도 몇번 더 시도하기
    """공공데이터 서버가 가끔 느리거나 잠깐 끊길 때를 대비해 몇 번 다시 시도한다.
    (Render 무료 플랜은 한동안 안 쓰면 잠들었다가 깨어나며 데이터를 다시 받아오는데,
     그때 한 번 실패해도 곧바로 죽지 않도록 하기 위함)"""
    last_error = None
    for i in range(tries):
        try:
            res = requests.get(BASE_URL, params=params, timeout=30)
            res.raise_for_status()
            return res
        except Exception as e:
            last_error = e
            time.sleep(1.5 * (i + 1))   # 1.5초, 3초 … 점점 길게 쉬었다 재시도
    raise RuntimeError(f"공공데이터 API 연결에 계속 실패했습니다: {last_error}")


def fetch_all_items(): #전국데이터 전부 받기
    all_items = []
    page_no = 1

    while True:
        params = {
            "serviceKey" : SERVICE_KEY,
            "numOfRows" : NUM_OF_ROWS,
            "pageNo" : page_no,
            "MobileOS" : "ETC",
            "MobileApp" : "CampSearch",
            "_type" : "json"
        }

        res = _get_with_retry(params)

        try:
            body = res.json()["response"]["body"]
        except ValueError:
            raise RuntimeError(
                "JSON이 아닌 응답이 왔습니다. 인증키 승인 여부를 확인하세요.\n"
                +res.text[:300]
            )
        items = body.get("items")
        if not items:
            break

        item = items["item"]
        if isinstance(item, dict):
            item = [item]
        all_items.extend(item)  #

        if len(all_items) >= int(body["totalCount"]):
            break
        page_no += 1  # 종료조건인데 전체개수만큼 모였으면 멈추어라는것.

    return all_items

_items_cache = None

def all_items():
    global _items_cache
    if _items_cache is None:
        _items_cache = fetch_all_items()
    return _items_cache


def get_campsites(region = "", mode='and',sido="", sigungu=""):
    raw_list = all_items()
    result = []

    for one in raw_list:
        row = {}
        for eng_name, kor_name in FIELD_MAP.items():
            value = one.get(eng_name,"")
            if value is None:
                value = ''
            row[kor_name] = value

        if sido and row["시도"] != sido:
            continue

        if sigungu and row["시군구"] != sigungu:
            continue

        if region:
            haystack= " ".join([
                row["시도"], row["시군구"], row["주소"], row["캠핑장명"],
                row["업종"],                     # ← 추가: 글램핑·카라반·오토캠핑 등 업종으로도 검색됨
                row["주요시설"], row["화장실(개)"],
                row["샤워실(개)"], row["반려동물_동반여부"],
                row["데크사이트"],row["파쇄석사이트"],row["카라반사이트"],
            ])
            # 공백을 무시하고 비교한다.
            # (예: 데이터에는 "금호강 오토캠핑장"인데 검색어는 "금호강오토캠핑장"처럼
            #  붙여 쓴 경우에도 찾을 수 있도록, 양쪽에서 띄어쓰기를 지운 뒤 비교)
            haystack_c = haystack.replace(" ", "")
            keywords = region.split()

            if mode == "or":
                matched = False
                for kw in keywords:
                    if kw.replace(" ", "") in haystack_c:
                        matched = True
                        break
            else:
                matched = True
                for kw in keywords:
                    if kw.replace(" ", "") not in haystack_c:
                        matched = False
                        break
            if not matched:
                continue


        result.append(row)
    result.sort(key=lambda one: one["캠핑장명"])
    return result

def save_to_csv(rows, filename):
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(FIELD_MAP.values()))
        writer.writeheader()
        writer.writerows(rows)

_sido_cache = None

def get_sido_list():
    global _sido_cache
    if _sido_cache is None:
        names = set()
        for one in all_items():
            value = one.get("doNm") or ""
            if value:
                names.add(value)
        _sido_cache = sorted(names)
    return _sido_cache

def get_sigungu_list(sido):
    names = set()
    if sido:
        for one in all_items():
            if (one.get("doNm") or "") == sido:
                value = one.get("sigunguNm") or ""
                if value:
                    names.add(value)
    return sorted(names)

if __name__ == "__main__":
    print("전국 캠핑장 데이터 찾아옵니다.")
    campsites = get_campsites()
    save_to_csv(campsites, "campsite_list.csv")
    print(f"완료! 총 {len(campsites)}개 -> campsites_list.csv 저장")
