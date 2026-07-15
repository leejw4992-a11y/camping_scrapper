import io
import csv
from flask import Flask,request, render_template, Response

from camping_scrapper import get_campsites, get_sido_list, get_sigungu_list,FIELD_MAP

app = Flask(__name__)

PER_PAGE = 20

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
        mode=mode,               # 현재 검색 방식(화면 select/링크 유지용)
        sido=sido,               # 현재 선택된 시도
        sido_list=sido_list,     # 시도 드롭다운 목록
        sigungu=sigungu,         # 현재 선택된 시군구
        sigungu_list=sigungu_list,  # 시군구 드롭다운 목록
        rows=rows,               # 이번 페이지 캠핑장들만
        page=page,               # 현재 페이지 번호
        total_pages=total_pages, # 전체 페이지 수
        total=total,             # 검색된 전체 개수
        page_numbers=page_numbers,
    )

@app.route("/download")
def download():
    region = request.args.get("region", "").strip()
    mode = request.args.get("mode", "and")
    sido = request.args.get("sido", "").strip()
    sigungu = request.args.get("sigungu", "").strip()
    rows = get_campsites(region,mode,sido,sigungu)

    buffer = io.StringIO()
    writer = csv.DictWriter(buffer,fieldnames=list(FIELD_MAP.values()))
    writer.writeheader()
    writer.writerows(rows)

    csv_data = "﻿" + buffer.getvalue()

    filename = f"campsite_{region or 'all'}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition":f"attachment; filename={filename}"},
    )

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)