import pandas as pd
import streamlit as st

from hbr.analytics.alert_rules import rule_from_row, visible_alerts
from hbr.constants import ALERT_TYPES, DEADLINE_DAYS

from views import _ui
from views._common import current_user, empty_notice, repo

_ui.page_header("알림", "내 조건에 맞는 입찰·낙찰·유찰·재공고 소식", "ALERTS")
user, r = current_user(), repo()
row = r.get_user(user.email)
if not row:
    st.info("로그인한 사용자만 알림을 볼 수 있습니다.")
    st.stop()

saved = r.get_alert_rule(row["id"])
rule = rule_from_row(saved)
scope_txt = "전체 (모든 병원·제품)" if rule.scope == "all" else f"내 관심만 (관심 제품 {rule.min_match} 이상 매칭 또는 관심 병원)"
types_txt = ", ".join(ALERT_TYPES[t] + (f" D-{'/D-'.join(str(d) for d in rule.deadline_days)}" if t == "DEADLINE" and rule.deadline_days else "")
                      for t in rule.types) or "없음"
c1, c2 = st.columns([4, 1])
c1.caption(("내 알림 조건 · " if saved else "기본 조건(저장 전) · ") + f"종류: {types_txt} · 범위: {scope_txt} · 이메일 {'켬' if rule.email_enabled else '끔'}")
try:
    c2.page_link("views/settings.py", label="조건 바꾸기", icon=":material/tune:")
except Exception:   # noqa: BLE001 — 이 화면만 단독 실행(테스트)될 때는 페이지 목록이 없다
    pass

f1, f2 = st.columns([1, 2])
days = f1.selectbox("기간", [7, 30, 90], index=1, format_func=lambda d: f"최근 {d}일")
kinds = f2.multiselect("종류", [t for t in ALERT_TYPES if t != "COMPETITOR_AWARD"], format_func=lambda t: ALERT_TYPES[t], placeholder="전체 종류")

alerts = visible_alerts(r, row, days=days)
if kinds:
    alerts = [a for a in alerts if a["alert_type"] in kinds]
if not alerts:
    st.markdown('<div class="hbr-empty">조건에 맞는 알림이 아직 없습니다.<br><span style="font-size:.82rem">새 공고·낙찰·유찰은 매일 아침 수집 후 이 곳에 쌓여요.</span></div>', unsafe_allow_html=True)
    st.stop()

st.caption(f"{len(alerts):,}건")
LIMIT = 100


def kst(v) -> str:
    t = pd.to_datetime(v, errors="coerce", utc=True)
    return "" if pd.isna(t) else t.tz_convert("Asia/Seoul").strftime("%m/%d %H:%M")


st.markdown('<div class="hbr-list">' + "".join(_ui.alert_item(a, kst(a.get("created_at"))) for a in alerts[:LIMIT]) + "</div>", unsafe_allow_html=True)
if len(alerts) > LIMIT:
    st.caption(f"최근 {LIMIT}건만 표시합니다. 기간·종류 필터로 줄여 보세요.")
