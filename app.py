import io
import os
import csv
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


def _weekend_indices(dates):
    """예보 날짜 목록에서 '다가오는 금요일'을 찾아 금·토·일 3일의 인덱스를 돌려준다."""
    parsed = [datetime.date.fromisoformat(x) for x in dates]
    fri = None
    for i, dt in enumerate(parsed):
        if dt.weekday() == 4:   # 금요일
            fri = i
            break
    if fri is None:
        return list(range(min(3, len(dates))))
    return [i for i in (fri, fri + 1, fri + 2) if i < len(dates)]


@app.route("/api/weather", methods=["POST"])
def api_weather():
    """여러 캠핑장 좌표를 한 번에 받아, 다가오는 주말(금·토·일) 예보를 돌려준다.
    무료 서비스 Open-Meteo 사용 (API 키 불필요).
    요청 본문 예: {"points": [[37.5,127.9],[37.8,127.5], ...]}"""
    body = request.get_json(silent=True) or {}
    points = body.get("points") or []
    if not points:
        return jsonify({"ok": False, "error": "좌표가 없어요."})

    # 유효한 숫자 좌표만 추려서 보낸다.
    # (좌표 하나가 빈 값·0·한국 범위 밖이면 그 요청 전체가 실패할 수 있어서 미리 걸러냄)
    valid = []   # (원래 순번, 위도, 경도)
    for idx, p in enumerate(points):
        try:
            lat = float(p[0])
            lng = float(p[1])
        except (TypeError, ValueError, IndexError):
            continue
        if not (33.0 <= lat <= 39.0 and 124.0 <= lng <= 132.0):
            continue   # 한국(남한) 범위 밖이면 제외
        valid.append((idx, lat, lng))

    print(f"[날씨] 받은 좌표 {len(points)}개 중 유효 {len(valid)}개")

    results = [{"ok": False} for _ in points]
    if not valid:
        # 보낼 만한 좌표가 하나도 없으면 그냥 빈 결과
        print("[날씨] 유효한 좌표가 없어 요청 안 함")
        return jsonify({"ok": True, "list": results})

    params = {
        "latitude": ",".join(str(v[1]) for v in valid),
        "longitude": ",".join(str(v[2]) for v in valid),
        "daily": "weather_code,temperature_2m_max,temperature_2m_min",
        "timezone": "Asia/Seoul",
        "forecast_days": 10,   # 다음 주말까지 확실히 포함되도록 넉넉히
    }
    try:
        res = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=15)
        data = res.json()
    except Exception as e:
        print("[날씨] 연결 실패:", e)
        return jsonify({"ok": False, "error": f"날씨 서버 연결 실패: {e}"})

    # Open-Meteo가 오류를 돌려주면 그 이유를 그대로 보여준다(원인 파악용)
    if isinstance(data, dict) and data.get("error"):
        print("[날씨] Open-Meteo 오류:", data.get("reason"))
        return jsonify({"ok": False, "error": f"Open-Meteo: {data.get('reason')}"})

    # 좌표가 하나면 dict, 여러 개면 list로 온다
    locs = data if isinstance(data, list) else [data]
    try:
        weekend = _weekend_indices(locs[0]["daily"]["time"])
    except Exception as ex:
        print("[날씨] 파싱 실패:", ex, "| 응답 일부:", str(data)[:300])
        return jsonify({"ok": False, "error": "예보를 읽지 못했어요."})

    # 걸러낸 좌표 순서대로 결과를 원래 순번 자리에 채워 넣는다
    for (orig_idx, _, _), loc in zip(valid, locs):
        try:
            d = loc["daily"]
            days = []
            for i in weekend:
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
            results[orig_idx] = {"ok": True, "days": days}
        except Exception:
            results[orig_idx] = {"ok": False}

    return jsonify({"ok": True, "list": results})


@app.route("/api/duration")
def api_duration():
    """현재 위치(slat,slng) -> 캠핑장(glat,glng) 자동차 소요시간을 계산해서 돌려준다."""
    slat = request.args.get("slat", "").strip()   # 내 위치 위도
    slng = request.args.get("slng", "").strip()   # 내 위치 경도
    glat = request.args.get("glat", "").strip()   # 캠핑장 위도
    glng = request.args.get("glng", "").strip()   # 캠핑장 경도

    if not (slat and slng and glat and glng):
        return jsonify({"ok": False, "error": "좌표가 없어요."})

    # Directions API는 'start', 'goal' 모두 '경도,위도' 순서로 넣는다
    params = {
        "start": f"{slng},{slat}",
        "goal": f"{glng},{glat}",
        "option": "traoptimal",
    }
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
