"""데모 데이터 생성기. 실제 API 키 없이 화면/알림/리포트를 시연하기 위한 *가상* 데이터.

⚠ 모든 금액·일자·업체 낙찰 이력은 난수로 만든 가짜 값이며 실제 나라장터 정보가 아니다.
"""
from __future__ import annotations

import random
from datetime import date, datetime, timedelta

from ..collectors.hospital_filter import classify
from ..utils import add_months, normalize_name, today_kst

HOSPITALS = [
    "서울대학교병원", "삼성서울병원", "서울아산병원", "분당서울대학교병원", "세브란스병원",
    "서울성모병원", "고려대학교안암병원", "아주대학교병원", "경북대학교병원", "부산대학교병원",
    "전남대학교병원", "충남대학교병원", "인천성모병원", "국립암센터", "국립중앙의료원",
    "중앙보훈병원", "부산보훈병원", "서울적십자병원", "경기도의료원 수원병원", "강원대학교병원",
]
ITEMS = [("알부민 20% 100mL 구매", "알부민"), ("면역글로불린(IVIG) 구매", "면역글로불린"),
         ("혈액제제 구매", "혈액제제"), ("의약품 연간단가계약", "의약품"), ("수액제 구매", "수액")]
NOISE = ["본관동 냉난방기 교체 공사", "환자식 위탁급식 용역", "의료폐기물 처리 용역", "PACS 유지보수 용역"]
VENDORS = ["GC녹십자", "한국씨에스엘베링(주)", "JW중외제약", "SK플라즈마(주)", "(주)다케다제약",
           "옥타파마코리아", "지오영", "(주)백제약품", "동원약품(주)"]


def load_demo(repo, seed: int = 20261008, today: date | None = None) -> None:
    if repo.rows("hospitals", limit=1):
        return
    rng = random.Random(seed)
    today = today or today_kst()
    comps = repo.competitor_index()
    from ..collectors.competitors import match_competitor

    hmap = repo.upsert_hospitals([classify(h) for h in HOSPITALS])
    bids, awards, contracts = [], [], []
    n = 0
    for i, h in enumerate(HOSPITALS):
        hid = hmap[normalize_name(h)]
        pool = rng.sample(VENDORS, rng.randint(1, 4))   # 병원별 주요 공급사
        size = 1.0 + (6 - i * 0.25 if i < 20 else 0) * rng.uniform(0.6, 1.4)
        # 과거 계약 (의약품) — 종료일을 오늘 기준 -40 ~ +420 일로 분산
        end = today + timedelta(days=rng.choice([-40, 5, 18, 26, 44, 58, 75, 80, 95, 130, 200, 320, 420]) + rng.randint(-3, 3))
        for k, (item, tag) in enumerate(rng.sample(ITEMS, 2)):
            vendor = rng.choice(pool)
            c_end = end + timedelta(days=rng.randint(-20, 40)) if k else end
            start = add_months(c_end, -12)
            amount = round(size * rng.uniform(0.8, 3.2) * 1e8, -5)
            n += 1
            comp = match_competitor(vendor, comps)
            contracts.append({
                "contract_key": f"DEMO-C{n}-00", "contract_no": f"DEMO-C{n}", "title": f"{h} {item}",
                "inst_name": h, "hospital_id": hid, "vendor_name": vendor,
                "competitor_id": comp["id"] if comp else None, "contract_amount": amount,
                "contract_date": start.isoformat(), "start_date": start.isoformat(),
                "end_date": c_end.isoformat(), "end_date_estimated": False, "is_pharma": True,
                "product_tags": [tag], "raw": {"demo": True}})
        n += 1
        contracts.append({   # 비의약품 노이즈 (점수에서 제외되어야 함)
            "contract_key": f"DEMO-C{n}-00", "contract_no": f"DEMO-C{n}", "title": f"{h} {rng.choice(NOISE)}",
            "inst_name": h, "hospital_id": hid, "vendor_name": "가나다종합서비스", "competitor_id": None,
            "contract_amount": 2e8, "contract_date": (today - timedelta(days=100)).isoformat(),
            "start_date": (today - timedelta(days=100)).isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(), "end_date_estimated": False,
            "is_pharma": False, "product_tags": [], "raw": {"demo": True}})
        # 과거 낙찰 3~6건 (최근 3년)
        for j in range(rng.randint(3, 6)):
            vendor = rng.choice(pool)
            d = today - timedelta(days=rng.randint(3, 1000) if j else rng.randint(1, 25))
            item, tag = rng.choice(ITEMS)
            n += 1
            comp = match_competitor(vendor, comps)
            awards.append({
                "award_key": f"DEMO-A{n}-00-x", "bid_ntce_no": f"DEMO-A{n}", "bid_ntce_ord": "00",
                "title": f"{h} {item}", "inst_name": h, "hospital_id": hid, "winner_name": vendor,
                "winner_biz_no": None, "competitor_id": comp["id"] if comp else None,
                "award_amount": round(size * rng.uniform(0.5, 2.5) * 1e8, -5),
                "award_rate": round(rng.uniform(85, 99.5), 3), "award_date": d.isoformat(),
                "is_pharma": True, "product_tags": [tag], "raw": {"demo": True}})
        # 입찰공고: 과거 이력 + 진행중
        for j in range(rng.randint(2, 7)):
            nd = today - timedelta(days=rng.randint(0, 600) if j > 1 else rng.randint(0, 6))
            dl = datetime.combine(nd + timedelta(days=rng.randint(8, 20)), datetime.min.time()).replace(hour=10)
            item, tag = rng.choice(ITEMS)
            n += 1
            bids.append({
                "bid_key": f"DEMO-B{n}-00", "bid_ntce_no": f"DEMO-B{n}", "bid_ntce_ord": "00",
                "title": f"{h} {item}", "inst_name": h, "hospital_id": hid,
                "bid_date": nd.isoformat(), "deadline": dl.isoformat() + "+09:00",
                "budget": round(size * rng.uniform(0.3, 1.5) * 1e8, -5),
                "bid_method": rng.choice(["전자입찰", "제한경쟁", "일반경쟁"]),
                "contract_method": "제한경쟁", "is_pharma": True, "product_tags": [tag], "raw": {"demo": True}})
        n += 1
        bids.append({
            "bid_key": f"DEMO-B{n}-00", "bid_ntce_no": f"DEMO-B{n}", "bid_ntce_ord": "00",
            "title": f"{h} {rng.choice(NOISE)}", "inst_name": h, "hospital_id": hid,
            "bid_date": today.isoformat(), "deadline": (datetime.combine(today + timedelta(days=9), datetime.min.time())).isoformat() + "+09:00",
            "budget": 3e8, "bid_method": "일반경쟁", "contract_method": "일반경쟁",
            "is_pharma": False, "product_tags": [], "raw": {"demo": True}})
    repo.upsert("bids", bids)
    repo.upsert("awards", awards)
    repo.upsert("contracts", contracts)
