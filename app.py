import io
import os
import csv
import time
import datetime
import requests
from flask import Flask,request, render_template, Response, jsonify

from camping_scrapper import get_campsites, get_sido_list, get_sigungu_list,FIELD_MAP

app = Flask(__name__)

PER_PAGE = 20

# ============================================================
# 소요시간 계산용 네이버 클라우드 Maps 키 (Directions 5)
# 네이버 클라우드 콘솔 > Maps > Application > 인증 정보
# ============================================================
# 보안을 위해 Render 대시보드의 Environment(환경변수)에 넣는 걸 권장.
# 환경변수가 없으면 아래 기본값을 그대로 쓰므로, 안 넣어도 일단 동작은 한다.
NAVER_KEY_ID = os.environ.get("NAVER_KEY_ID", "dvm06v1qnm")
NAVER_KEY    = os.environ.get("NAVER_KEY", "SWo3XbOhDFxDzBCFIxkeMeIgcK3GxrD1K5gSsUZB")

# 네이버가 도메인을 두 가지로 운영 중이라, 되는 쪽을 자동으로 찾는다
# (새 Maps = maps..., 구형 = naveropenapi...)
DIRECTION_URLS = [
    "https://maps.apigw.ntruss.com/map-direction/v1/driving",
    "https://naveropenapi.apigw.ntruss.com/map-direction/v1/driving",
]


@app.route("/healthz")
def healthz():
    """Render가 서버 살아있는지 확인할 때 쓰는 가벼운 주소. 데이터는 안 건드린다."""
    return "ok", 200


@app.route("/")
def index():
    region = request.args.get("region","").strip()
    mode = request.args.get("mode","and")
    sido = request.args.get("sido", "").strip()
    sigungu = request.args.get("sigungu", "").strip()
    page = request.args.get("page",1, type=int)

    sido_list = get_sido_list()
    sigungu_list = get_sigungu_list(sido)

    all_rows = (
        get_campsites(region, mode, sido, sigungu)
        if(region or sido or sigungu) else [])
    total = len(all_rows)

    total_pages = (total + PER_PAGE -1) // PER_PAGE
    if total_pages <1:
        total_pages = 1

    if page < 1:
        page = 1
    if page > total_pages:
        page = total_pages

    start = (page-1) * PER_PAGE
    end = start + PER_PAGE
    rows = all_rows[start:end]

    first = max(1,page-2)
    last = min(total_pages, page + 2)
    page_numbers = list(range(first, last+1))

    return render_template(
        "index.html",
        region=region,
        mode=mode,
        sido=sido,
        sido_list=sido_list,
        sigungu=sigungu,
        sigungu_list=sigungu_list,
        rows=rows,
        page=page,
        total_pages=total_pages,
        total=total,
        page_numbers=page_numbers,
    )


@app.route("/api/sigungu")
def api_sigungu():
    """시도를 고르면, 그 시도에 속한 시군구 목록을 JSON으로 돌려준다.
    (검색 버튼을 누르지 않아도 시군구를 바로 고를 수 있게 하기 위함)"""
    sido = request.args.get("sido", "").strip()
    return jsonify(get_sigungu_list(sido))


# WMO 날씨 코드 → (이모지, 한글 설명)
WEATHER_CODES = {
    0: ("☀️", "맑음"),
    1: ("🌤️", "대체로 맑음"), 2: ("⛅", "구름 조금"), 3: ("☁️", "흐림"),
    45: ("🌫️", "안개"), 48: ("🌫️", "안개"),
    51: ("🌦️", "약한 이슬비"), 53: ("🌦️", "이슬비"), 55: ("🌦️", "짙은 이슬비"),
    56: ("🌧️", "어는 이슬비"), 57: ("🌧️", "어는 이슬비"),
    61: ("🌧️", "약한 비"), 63: ("🌧️", "비"), 65: ("🌧️", "강한 비"),
    66: ("🌧️", "어는 비"), 67: ("🌧️", "어는 비"),
    71: ("🌨️", "약한 눈"), 73: ("🌨️", "눈"), 75: ("🌨️", "강한 눈"), 77: ("🌨️", "싸락눈"),
    80: ("🌦️", "소나기"), 81: ("🌦️", "소나기"), 82: ("🌦️", "강한 소나기"),
    85: ("🌨️", "소나기눈"), 86: ("🌨️", "소나기눈"),
    95: ("⛈️", "뇌우"), 96: ("⛈️", "우박 뇌우"), 99: ("⛈️", "우박 뇌우"),
}


WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]

# 날씨 캐시: 좌표(소수1자리 반올림)별로 주말 예보를 잠시 저장해 Open-Meteo 호출을 줄인다
_weather_cache = {}          # key "la,ln" -> {"days": [...], "ts": epoch}
_WEATHER_TTL = 3 * 60 * 60   # 3시간 동안 캐시 재사용


def _weekend_dates():
    """다가오는 금·토·일 날짜 3개를 돌려준다.
    (오늘이 토/일이면 이번 주말은 지났으니 다음 주 금요일 기준)"""
    today = datetime.date.today()
    days_to_fri = (4 - today.weekday()) % 7   # 금요일(=4)까지 남은 일수
    fri = today + datetime.timedelta(days=days_to_fri)
    return [fri, fri + datetime.timedelta(days=1), fri + datetime.timedelta(days=2)]


@app.route("/api/weather", methods=["POST"])
def api_weather():
    """여러 캠핑장 좌표를 받아 다가오는 주말(금·토·일) 예보를 돌려준다.
    무료 서비스 Open-Meteo 사용 (API 키 불필요).
    호출을 아끼려고 (1) 좌표를 소수1자리로 반올림해 가까운 곳끼리 묶고
    (2) 결과를 잠시 캐시하며 (3) 딱 주말 3일치만 요청한다."""
    body = request.get_json(silent=True) or {}
    points = body.get("points") or []
    if not points:
        return jsonify({"ok": False, "error": "좌표가 없어요."})

    # 유효 좌표만 추리고, 날씨는 정밀도가 필요 없어 소수 1자리로 반올림한다
    valid = []   # (원래순번, "la,ln")
    for idx, p in enumerate(points):
        try:
            lat = round(float(p[0]), 1)
            lng = round(float(p[1]), 1)
        except (TypeError, ValueError, IndexError):
            continue
        if not (33.0 <= lat <= 39.0 and 124.0 <= lng <= 132.0):
            continue   # 한국(남한) 범위 밖이면 제외
        valid.append((idx, f"{lat},{lng}"))

    results = [{"ok": False} for _ in points]
    if not valid:
        return jsonify({"ok": True, "list": results})

    now = time.time()
    # 캐시에 없거나 오래된 좌표만 모아서 한 번에 요청
    need = []
    for _, key in valid:
        c = _weather_cache.get(key)
        if key not in need and (not c or now - c["ts"] > _WEATHER_TTL):
            need.append(key)

    print(f"[날씨] 좌표 {len(points)}개 · 유효 {len(valid)} · 새로 조회 {len(need)}")

    if need:
        wd = _weekend_dates()
        params = {
            "latitude": ",".join(k.split(",")[0] for k in need),
            "longitude": ",".join(k.split(",")[1] for k in need),
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "timezone": "Asia/Seoul",
            "start_date": wd[0].isoformat(),
            "end_date": wd[2].isoformat(),
        }
        try:
            res = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=15)
            data = res.json()
        except Exception as e:
            print("[날씨] 연결 실패:", e)
            return jsonify({"ok": False, "error": f"날씨 서버 연결 실패: {e}"})

        if isinstance(data, dict) and data.get("error"):
            print("[날씨] Open-Meteo 오류:", data.get("reason"))
            return jsonify({"ok": False, "error": f"Open-Meteo: {data.get('reason')}"})

        locs = data if isinstance(data, list) else [data]
        for key, loc in zip(need, locs):
            try:
                d = loc["daily"]
                days = []
                for i in range(len(d["time"])):
                    code = int(d["weather_code"][i])
                    icon, desc = WEATHER_CODES.get(code, ("🌡️", "날씨"))
                    dt = datetime.date.fromisoformat(d["time"][i])
                    days.append({
                        "label": WEEKDAYS[dt.weekday()],
                        "date": dt.strftime("%m/%d"),
                        "icon": icon,
                        "desc": desc,
                        "tmax": round(d["temperature_2m_max"][i]),
                        "tmin": round(d["temperature_2m_min"][i]),
                    })
                _weather_cache[key] = {"days": days, "ts": now}
            except Exception as ex:
                print("[날씨] 파싱 실패:", ex, "| 응답 일부:", str(loc)[:200])

    # 캐시에서 각 좌표 결과를 원래 자리에 채운다
    for orig_idx, key in valid:
        c = _weather_cache.get(key)
        if c:
            results[orig_idx] = {"ok": True, "days": c["days"]}

    return jsonify({"ok": True, "list": results})


@app.route("/api/place")
def api_place():
    """장소/주소를 검색해 좌표(위도·경도)를 돌려준다. (경유지=장보기 지점 찾기용)
    네이버 지오코딩 API 사용 — 소요시간과 '같은 네이버 키'를 그대로 쓴다.
    ※ 주소·건물명 위주로 잘 찾는다. 'OO 이마트', '원주 하나로마트'처럼
      지역명을 붙이거나 도로명 주소로 검색하면 더 잘 나온다."""
    q = request.args.get("query", "").strip()
    if not q:
        return jsonify({"ok": False, "error": "검색어가 없어요."})

    headers = {
        "x-ncp-apigw-api-key-id": NAVER_KEY_ID,
        "x-ncp-apigw-api-key": NAVER_KEY,
    }
    geocode_urls = [
        "https://maps.apigw.ntruss.com/map-geocode/v2/geocode",
        "https://naveropenapi.apigw.ntruss.com/map-geocode/v2/geocode",
    ]
    for url in geocode_urls:
        try:
            res = requests.get(url, params={"query": q}, headers=headers, timeout=10)
            data = res.json()
        except Exception as e:
            print("[장소검색] 연결 실패:", e)
            continue

        addrs = data.get("addresses")
        if addrs is None:
            print("[장소검색] 예상 밖 응답:", str(data)[:200])
            continue

        items = []
        for a in addrs[:5]:
            try:
                items.append({
                    "name": a.get("roadAddress") or a.get("jibunAddress") or q,
                    "addr": a.get("jibunAddress") or a.get("roadAddress") or "",
                    "lat": float(a["y"]),   # 위도
                    "lng": float(a["x"]),   # 경도
                })
            except Exception:
                continue

        if items:
            return jsonify({"ok": True, "items": items})
        return jsonify({"ok": False, "error": "장소를 못 찾았어요. 주소나 '지역명+상호'로 검색해 보세요."})

    return jsonify({"ok": False, "error": "장소 검색 서버에 연결하지 못했어요."})


@app.route("/api/duration")
def api_duration():
    """현재 위치(slat,slng) -> 캠핑장(glat,glng) 자동차 소요시간을 계산해서 돌려준다."""
    slat = request.args.get("slat", "").strip()   # 내 위치 위도
    slng = request.args.get("slng", "").strip()   # 내 위치 경도
    glat = request.args.get("glat", "").strip()   # 캠핑장 위도
    glng = request.args.get("glng", "").strip()   # 캠핑장 경도
    wlat = request.args.get("wlat", "").strip()   # 경유지(장보기) 위도 - 선택
    wlng = request.args.get("wlng", "").strip()   # 경유지(장보기) 경도 - 선택

    if not (slat and slng and glat and glng):
        return jsonify({"ok": False, "error": "좌표가 없어요."})

    # Directions API는 'start', 'goal' 모두 '경도,위도' 순서로 넣는다
    params = {
        "start": f"{slng},{slat}",
        "goal": f"{glng},{glat}",
        "option": "traoptimal",
    }
    # 경유지(장보기)가 있으면 그곳을 들르는 경로로 계산 (waypoints = 경도,위도)
    if wlat and wlng:
        params["waypoints"] = f"{wlng},{wlat}"
    headers = {
        "x-ncp-apigw-api-key-id": NAVER_KEY_ID,
        "x-ncp-apigw-api-key": NAVER_KEY,
    }

    last_error = "알 수 없는 오류"
    # 두 도메인을 순서대로 시도해서 되는 걸 쓴다
    for url in DIRECTION_URLS:
        try:
            res = requests.get(url, params=params, headers=headers, timeout=10)
            data = res.json()
        except Exception as e:
            last_error = f"서버 연결 실패: {e}"
            print(f"[연결 실패] {url} -> {e}")
            continue

        # 성공
        if data.get("code") == 0:
            summary = data["route"]["traoptimal"][0]["summary"]
            total_min = round(summary["duration"] / 1000 / 60)   # 밀리초 -> 분
            hours, mins = divmod(total_min, 60)
            time_text = f"{hours}시간 {mins}분" if hours else f"{mins}분"
            print(f"[성공] {url}")
            return jsonify({
                "ok": True,
                "time_text": time_text,
                "distance_km": round(summary["distance"] / 1000, 1),
            })

        # 실패 -> 진짜 원인을 터미널에 찍고 다음 도메인 시도
        print(f"\n[실패] {url}")
        print("[요청]", params)
        print("[응답]", data, "\n")

        err = data.get("message")
        if not err and isinstance(data.get("error"), dict):
            err = data["error"].get("message") or data["error"].get("errorMessage")
        code = data.get("code")
        code_hint = {
            1: "출발지와 도착지가 같음",
            2: "출발지나 도착지가 도로에서 너무 멀리 떨어짐(산속 캠핑장)",
            3: "자동차 경로 제공 불가",
            5: "직선거리가 1500km 이상",
        }.get(code)
        last_error = err or code_hint or f"경로 실패 (code={code})"

    return jsonify({"ok": False, "error": last_error})


@app.route("/download")
def download():
    region = request.args.get("region", "").strip()
    mode = request.args.get("mode", "and")
    sido = request.args.get("sido", "").strip()
    sigungu = request.args.get("sigungu", "").strip()
    rows = get_campsites(region, mode, sido, sigungu)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=list(FIELD_MAP.values()))
    writer.writeheader()
    writer.writerows(rows)

    csv_data = "﻿" + buffer.getvalue()

    filename = f"campsite_{region or 'all'}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    # 내 컴퓨터에서 직접 python app.py 로 실행할 때만 쓰는 부분.
    # Render에서는 gunicorn이 app 객체를 직접 불러 쓰므로 이 블록은 실행되지 않는다.
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
