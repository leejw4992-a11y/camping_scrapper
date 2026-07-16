import csv
import requests

SERVICE_KEY = "1f7e167f547aa29e1a582a5ff739306d50e293a9e06b92d24e559287785468b8"
BASE_URL = "https://apis.data.go.kr/B551011/GoCamping/basedList"
NUM_OF_ROWS = 1000

FIELD_MAP = {
    "facltNm" : "캠핑장명",
    "induty" : "업종",
    "addr1" : "주소",
    "sbrsCl" : "주요시설",
    "toiletCo" : "화장실(개)",
    "swrmCo" : "샤워실(개)",
    "animalCmgCl" : "반려동물_동반여부",
    "tel" : "전화번호",
    "resveUrl" : "예약페이지",
    "siteMg1Co" : "데크사이트",
    "siteMg2Co" : "파쇄석사이트",
    "siteMg3Co" : "카라반사이트",
    "doNm" : "시도",
    "sigunguNm" : "시군구",
    "mapX" : "경도",   # ← 추가: 소요시간 계산에 쓸 좌표(경도)
    "mapY" : "위도",   # ← 추가: 소요시간 계산에 쓸 좌표(위도)
}


def fetch_all_items():
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

        res = requests.get(BASE_URL, params=params, timeout=20)
        res.raise_for_status()

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
        all_items.extend(item)

        if len(all_items) >= int(body["totalCount"]):
            break
        page_no += 1

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
                row["주요시설"], row["화장실(개)"],
                row["샤워실(개)"], row["반려동물_동반여부"],
                row["데크사이트"],row["파쇄석사이트"],row["카라반사이트"],
            ])
            keywords = region.split()

            if mode == "or":
                matched = False
                for kw in keywords:
                    if kw in haystack:
                        matched = True
                        break
            else:
                matched = True
                for kw in keywords:
                    if kw not in haystack:
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
