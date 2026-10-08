"""경쟁사 Radar 계산: 실제 낙찰업체 기준 순위·상세·병원별 점유율.

원칙
- 업체는 사업자번호가 같으면 한 업체, 없으면 정리한 이름이 같으면 한 업체 (표기 차이 '(주)', 띄어쓰기 흡수)
- 건수는 '공고 단위' (같은 공고의 투찰업체별 중복 행은 한 건)
- 점유율에는 기준(건수/금액)·기간·낙찰 건수를 항상 함께 돌려주고, 표본이 적으면 'sufficient=False' 로 알린다
"""
from __future__ import annotations

from datetime import date

import pandas as pd

from ..utils import normalize_name

MIN_SHARE_N = 5            # 점유율을 '충분한 표본'으로 보는 최소 낙찰 건수


def _vendor_key(row) -> str:
    biz = str(row.get("winner_biz_no") or "").replace("-", "").strip()
    return f"biz:{biz}" if biz else f"name:{normalize_name(row.get('winner_name'))}"


def prepare(awards: pd.DataFrame) -> pd.DataFrame:
    """낙찰 표에 업체 묶음 키(vendor_key)와 대표 표기(vendor)를 붙이고 공고 단위로 정리한다."""
    if awards is None or awards.empty or "winner_name" not in awards:
        return pd.DataFrame()
    df = awards[awards["winner_name"].notna()].copy()
    if df.empty:
        return df
    df["vendor_key"] = df.apply(_vendor_key, axis=1)
    # 대표 표기: 그 업체의 가장 흔한 원본 이름
    names = df.groupby("vendor_key")["winner_name"].agg(lambda s: s.value_counts().idxmax())
    df["vendor"] = df["vendor_key"].map(names)
    keys = [c for c in ("bid_ntce_no", "bid_ntce_ord", "vendor_key") if c in df]
    return df.drop_duplicates(keys)


def _window(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    if df.empty:
        return df
    d = pd.to_datetime(df["award_date"], errors="coerce")
    return df[(d >= pd.Timestamp(start)) & (d < pd.Timestamp(end) + pd.Timedelta(days=1))]


def coverage(df: pd.DataFrame) -> tuple[date | None, date | None]:
    """보유한 낙찰 데이터의 기간 (분석 기간보다 짧으면 화면에서 알려야 한다)."""
    if df is None or df.empty or "award_date" not in df:
        return None, None
    d = pd.to_datetime(df["award_date"], errors="coerce").dropna()
    return (d.min().date(), d.max().date()) if not d.empty else (None, None)


def vendor_ranking(df: pd.DataFrame, start: date, end: date, own_aliases=()) -> pd.DataFrame:
    """업체별 낙찰 건수·금액·병원 수·직전 같은 길이 기간 대비 건수 변화."""
    cols = ["업체", "낙찰 건수", "낙찰 금액", "낙찰 병원 수", "직전 기간 건수", "변화", "최근 낙찰일", "자사", "vendor_key"]
    if df is None or df.empty:
        return pd.DataFrame(columns=cols)
    from ..collectors.competitors import matches_any_alias

    span = (pd.Timestamp(end) - pd.Timestamp(start)).days + 1
    prev_start, prev_end = (pd.Timestamp(start) - pd.Timedelta(days=span)).date(), (pd.Timestamp(start) - pd.Timedelta(days=1)).date()
    cur, prev = _window(df, start, end), _window(df, prev_start, prev_end)
    if cur.empty:
        return pd.DataFrame(columns=cols)
    g = cur.groupby("vendor_key").agg(업체=("vendor", "first"), **{"낙찰 건수": ("vendor_key", "size"), "낙찰 금액": ("award_amount", "sum"),
                                                             "낙찰 병원 수": ("hospital_id", "nunique"), "최근 낙찰일": ("award_date", "max")}).reset_index()
    pc = prev.groupby("vendor_key").size()
    g["직전 기간 건수"] = g["vendor_key"].map(pc).fillna(0).astype(int)
    g["변화"] = g["낙찰 건수"] - g["직전 기간 건수"]
    g["자사"] = g["업체"].map(lambda n: matches_any_alias(n, own_aliases))
    return g.sort_values(["낙찰 건수", "낙찰 금액"], ascending=False)[cols].reset_index(drop=True)


def vendor_detail(df: pd.DataFrame, vendor_key: str, start: date, end: date) -> dict:
    """한 업체의 병원별·월별·분류별 낙찰과 이력."""
    d = _window(df[df["vendor_key"] == vendor_key], start, end) if df is not None and not df.empty else pd.DataFrame()
    if d.empty:
        return {"empty": True}
    month = pd.to_datetime(d["award_date"]).dt.to_period("M").dt.to_timestamp()
    by_hosp = d.groupby("hospital").agg(건수=("vendor_key", "size"), 금액=("award_amount", "sum"), 최근=("award_date", "max")).reset_index() \
        .sort_values(["건수", "금액"], ascending=False)
    tags = [t for ts in d["product_tags"] if isinstance(ts, (list, tuple)) for t in ts] if "product_tags" in d else []
    return {"empty": False, "total": len(d), "amount": float(d["award_amount"].fillna(0).sum()),
            "by_hospital": by_hosp, "monthly": d.assign(월=month).groupby("월").agg(건수=("vendor_key", "size"), 금액=("award_amount", "sum")).reset_index(),
            "tags": pd.Series(tags, dtype=object).value_counts().rename_axis("분류").reset_index(name="건수") if tags else pd.DataFrame(columns=["분류", "건수"]),
            "history": d.sort_values("award_date", ascending=False)}


def hospital_share(df: pd.DataFrame, hospital_id, start: date, end: date, by: str = "count", top: int = 6) -> dict:
    """병원 한 곳의 낙찰업체 점유율. by: count(낙찰 건수) | amount(낙찰 금액). 표본이 적으면 sufficient=False."""
    d = _window(df[df["hospital_id"] == hospital_id], start, end) if df is not None and not df.empty else pd.DataFrame()
    basis = "낙찰 건수" if by == "count" else "낙찰 금액"
    out = {"basis": basis, "start": start, "end": end, "n": len(d), "sufficient": len(d) >= MIN_SHARE_N, "table": pd.DataFrame(columns=["업체", "비중(%)", "건수"])}
    if d.empty:
        return out
    g = d.groupby("vendor_key").agg(업체=("vendor", "first"), 건수=("vendor_key", "size"), 금액=("award_amount", "sum")).reset_index()
    value = "건수" if by == "count" else "금액"
    total = g[value].sum()
    if not total:
        return out
    g["비중(%)"] = (g[value] / total * 100).round(1)
    g = g.sort_values(value, ascending=False)
    head, rest = g.head(top), g.iloc[top:]
    rows = head[["업체", "비중(%)", "건수"]].to_dict("records")
    if not rest.empty:
        rows.append({"업체": f"기타 {len(rest)}곳", "비중(%)": round(float(rest["비중(%)"].sum()), 1), "건수": int(rest["건수"].sum())})
    out["table"] = pd.DataFrame(rows)
    return out
