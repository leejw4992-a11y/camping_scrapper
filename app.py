import io
import csv
import requests
from flask import Flask,request, render_template, Response, jsonify

from camping_scrapper import get_campsites, get_sido_list, get_sigungu_list,FIELD_MAP

app = Flask(__name__)

PER_PAGE = 20

# ============================================================
# 소요시간 계산용 네이버 클라우드 Maps 키 (Directions 5)
# 네이버 클라우드 콘솔 > Maps > Application > 인증 정보
# ============================================================
NAVER_KEY_ID = "dvm06v1qnm"
NAVER_KEY    = "SWo3XbOhDFxDzBCFIxkeMeIgcK3GxrD1K5gSsUZB"

# 네이버가 도메인을 두 가지로 운영 중이라, 되는 쪽을 자동으로 찾는다
# (새 Maps = maps..., 구형 = naveropenapi...)
DIRECTION_URLS = [
    "https://maps.apigw.ntruss.com/map-direction/v1/driving",
    "https://naveropenapi.apigw.ntruss.com/map-direction/v1/driving",
]


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
    app.run(host="127.0.0.1", port=5000, debug=True)
