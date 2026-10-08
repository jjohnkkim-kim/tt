"""조달청 나라장터 공공데이터개방표준서비스 클라이언트.

오퍼레이션/파라미터/필드명은 이 파일 한 곳에 모아 두었다. API 명세가 바뀌거나
실제 응답 필드가 다르면 OPERATIONS / FIELD_CANDIDATES 만 수정하면 된다.
"""
from __future__ import annotations

import logging
import re
import time
import xml.etree.ElementTree as ET
from datetime import date
from typing import Iterator
from urllib.parse import unquote

import requests

from ..utils import date_windows

log = logging.getLogger(__name__)

# dataset → (operation, 조회기간 파라미터(시작, 종료), 날짜 포맷)
OPERATIONS = {
    "bids": ("getDataSetOpnStdBidPblancInfo", ("bidNtceBgnDt", "bidNtceEndDt"), "%Y%m%d%H%M"),
    "awards": ("getDataSetOpnStdScsbidInfo", ("opengBgnDt", "opengEndDt"), "%Y%m%d%H%M"),
    "contracts": ("getDataSetOpnStdCntrctInfo", ("cntrctCnclsBgnDate", "cntrctCnclsEndDate"), "%Y%m%d"),
}
WINDOW_DAYS = {"bids": 7, "awards": 1, "contracts": 7}   # 낙찰 API 는 조회기간 1일 초과 시 '입력범위값 초과'(07)
# 데이터셋별 필수 추가 파라미터 조합. 낙찰은 업무구분코드(bsnsDivCd)가 필수: 1 물품, 3 공사, 5 용역
EXTRA_PARAMS = {"awards": [{"bsnsDivCd": c} for c in ("1", "3", "5")]}


class G2BError(RuntimeError):
    pass


class G2BClient:
    def __init__(self, service_key: str, base_url: str, timeout: int = 30,
                 max_retries: int = 3, rows_per_page: int = 999, session: requests.Session | None = None):
        if not service_key or service_key == "YOUR_SERVICE_KEY":
            raise G2BError("SERVICE_KEY 가 설정되지 않았습니다 (.env 확인)")
        # 포털의 'Encoding' 키(%2B 등 포함)를 넣어도 이중 인코딩되지 않도록 디코딩
        self.service_key = unquote(service_key)
        self.base_url = base_url.rstrip("/")
        self.timeout, self.max_retries, self.rows = timeout, max_retries, rows_per_page
        self.http = session or requests.Session()

    # ── low level ───────────────────────────────────────────
    def _request(self, operation: str, params: dict) -> dict:
        q = {"serviceKey": self.service_key, "type": "json", "numOfRows": self.rows, **params}
        url = f"{self.base_url}/{operation}"
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                r = self.http.get(url, params=q, timeout=self.timeout)
                if r.status_code >= 500:
                    raise G2BError(f"HTTP {r.status_code}")
                return self.parse_response(r.text, r.status_code)
            except (requests.RequestException, G2BError) as e:
                last = e
                if isinstance(e, G2BError) and "HTTP" not in str(e):
                    raise                      # 키 오류 등은 재시도해도 소용없음
                time.sleep(min(2 ** attempt, 8))
        raise G2BError(f"{operation} 호출 실패: {last}")

    @staticmethod
    def parse_response(text: str, status: int = 200) -> dict:
        """JSON/XML 응답을 {'items': [...], 'total': n} 로 표준화. 오류코드는 예외."""
        text = text.strip()
        if text.startswith("<"):                 # 키 오류 등은 type=json 이어도 XML 로 온다
            return G2BClient._parse_xml(text)
        try:
            import json

            body = json.loads(text)
        except ValueError:
            raise G2BError(f"응답 파싱 실패 (HTTP {status}): {text[:200]}")
        gateway = body.get("OpenAPI_ServiceResponse")   # 게이트웨이 오류(키 미등록 등)는 JSON 이어도 이 형태
        if gateway:
            h = gateway.get("cmmMsgHeader", {})
            raise G2BError(f"API 오류 {h.get('returnReasonCode', '')}: "
                           f"{h.get('returnAuthMsg') or h.get('errMsg')}")
        err = body.get("nkoneps.com.response.ResponseError")   # 파라미터 오류(필수값 누락·기간 초과 등)
        if err:
            h = err.get("header", {})
            raise G2BError(f"API 오류 {h.get('resultCode', '')}: {h.get('resultMsg')}")
        resp = body.get("response", body)
        header = resp.get("header", {})
        code = str(header.get("resultCode", "00"))
        if code not in {"00", "0", "000"}:
            raise G2BError(f"API 오류 {code}: {header.get('resultMsg')}")
        data = resp.get("body", {})
        items = data.get("items", [])
        if isinstance(items, dict):
            items = items.get("item", [])
        if isinstance(items, dict):
            items = [items]
        return {"items": items or [], "total": int(data.get("totalCount", len(items or [])) or 0)}

    @staticmethod
    def _parse_xml(text: str) -> dict:
        root = ET.fromstring(text)
        code = (root.findtext(".//resultCode") or root.findtext(".//returnReasonCode") or "").strip()
        msg = (root.findtext(".//resultMsg") or root.findtext(".//returnAuthMsg") or "").strip()
        if code not in {"", "00", "0", "000"} or root.tag == "OpenAPI_ServiceResponse":
            raise G2BError(f"API 오류 {code}: {msg}")
        items = [{c.tag: (c.text or "").strip() for c in it} for it in root.iter("item")]
        total = int(root.findtext(".//totalCount") or len(items))
        return {"items": items, "total": total}

    # ── high level ──────────────────────────────────────────
    def fetch(self, dataset: str, start: date, end: date) -> Iterator[dict]:
        """기간 내 전체 레코드를 (기간 분할 + 페이지네이션) 로 순회."""
        operation, (p_from, p_to), fmt = OPERATIONS[dataset]
        for ws, we in date_windows(start, end, WINDOW_DAYS[dataset]):
            lo = ws.strftime(fmt) if fmt == "%Y%m%d" else ws.strftime("%Y%m%d") + "0000"
            hi = we.strftime(fmt) if fmt == "%Y%m%d" else we.strftime("%Y%m%d") + "2359"
            for extra in EXTRA_PARAMS.get(dataset, [{}]):
                page = 1
                while True:
                    res = self._request(operation, {p_from: lo, p_to: hi, "pageNo": page, **extra})
                    yield from res["items"]
                    if page * self.rows >= res["total"] or not res["items"]:
                        break
                    page += 1


def pick(row: dict, *names: str, default=None):
    """여러 후보 필드명 중 값이 있는 첫 항목."""
    for n in names:
        v = row.get(n)
        if v not in (None, "", "null"):
            return v
    return default


_NO_RE = re.compile(r"[^0-9A-Za-z\-]")


def clean_no(value) -> str:
    return _NO_RE.sub("", str(value or "")).strip()
