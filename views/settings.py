import pandas as pd
import streamlit as st

from hbr.analytics.alerts import generate_alerts
from hbr.analytics.scoring import ensure_scores
from hbr.config import get_settings
from hbr.constants import ROLES
from hbr.reports.daily import build_for_user, render_html

from views._common import current_user, opportunities, repo, snapshot

st.title("⚙️ 설정")
user, r = current_user(), repo()
tabs = st.tabs(["내 설정", "관심병원"] + (["사용자 관리", "운영 / 파이프라인", "메일"] if user.can("admin") else []))

with tabs[0]:
    row = r.get_user(user.email) or {}
    st.write(f"**{user.name}** ({user.email}) · 역할 `{user.role}`")
    personal = st.text_input("개인 이메일 (Daily Report 추가 수신)", row.get("personal_email") or "")
    enabled = st.toggle("매일 08:00 Daily Report 수신", value=bool(row.get("report_enabled", True)))
    from hbr.notify.kakao import normalize_phone

    st.markdown("##### 카카오톡 알림톡 (선택)")
    phone = st.text_input("휴대폰번호", row.get("phone") or "", placeholder="010-1234-5678")
    opt_in = st.checkbox("알림톡 수신에 동의합니다 (입력한 휴대폰번호를 알림 발송에만 사용하며, 언제든 해제할 수 있습니다)",
                         value=bool(row.get("kakao_opt_in")))
    if st.button("저장", key="save_me") and user.id:
        norm = normalize_phone(phone) if phone.strip() else None
        if phone.strip() and not norm:
            st.error("휴대폰번호 형식이 올바르지 않습니다.")
        elif opt_in and not norm:
            st.error("알림톡을 받으려면 휴대폰번호가 필요합니다.")
        else:
            vals = {"personal_email": personal.strip() or None, "report_enabled": enabled,
                    "phone": norm, "kakao_opt_in": bool(opt_in and norm)}
            if vals["kakao_opt_in"] and not row.get("kakao_opt_in"):
                vals["kakao_opt_in_at"] = __import__("hbr.utils", fromlist=["now_kst"]).now_kst().isoformat()
            r.update("users", vals, [("id", "eq", user.id)])
            st.success("저장했습니다.")

with tabs[1]:
    snap = snapshot()
    if not user.id or not user.can("watchlist"):
        st.info("관심병원 등록은 영업(sales) 이상 권한에서 가능합니다.")
    else:
        watched = r.watched_hospital_ids(user.id)
        names = dict(zip(snap.hospitals["id"], snap.hospitals["name"])) if not snap.hospitals.empty else {}
        chosen = st.multiselect("관심병원 (신규 입찰·계약만료·경쟁사 수주 즉시 알림)", sorted(names.values()),
                                default=sorted(names[h] for h in watched if h in names))
        if st.button("저장", key="save_watch"):
            by_name = {v: k for k, v in names.items()}
            want = {int(by_name[n]) for n in chosen}
            for h in want - watched: r.add_watch(user.id, h)
            for h in watched - want: r.remove_watch(user.id, h)
            st.success("관심병원을 저장했습니다.")

if user.can("admin"):
    with tabs[2]:
        users = pd.DataFrame(r.rows("users"))
        edited = st.data_editor(users[["id", "email", "name", "role", "is_active", "report_enabled"]] if not users.empty else users,
                                disabled=["id", "email"], hide_index=True, width="stretch",
                                column_config={"role": st.column_config.SelectboxColumn("role", options=ROLES)})
        if st.button("사용자 변경 저장") and not users.empty:
            for rec in edited.to_dict("records"):
                r.update("users", {k: rec[k] for k in ("name", "role", "is_active", "report_enabled")}, [("id", "eq", rec["id"])])
            st.success("저장했습니다.")
    with tabs[3]:
        runs = pd.DataFrame(r.rows("pipeline_runs", order="-id", limit=30))
        st.dataframe(runs.drop(columns=["raw"], errors="ignore"), hide_index=True, width="stretch") if not runs.empty else st.info("실행 이력이 없습니다.")
        c1, c2 = st.columns(2)
        if c1.button("점수 재계산"):
            st.success(f"{len(ensure_scores(r))}개 병원 점수를 저장했습니다.")
            st.cache_data.clear()
        if c2.button("알림 생성"):
            st.success(f"신규 알림 {len(generate_alerts(r))}건")
        st.caption("수집은 `python scripts/run_pipeline.py --job all` 또는 GitHub Actions/Azure Job 으로 실행합니다.")
        alerts = pd.DataFrame(r.rows("alerts", order="-id", limit=50))
        if not alerts.empty:
            st.dataframe(alerts[["created_at", "alert_type", "title", "message", "severity"]], hide_index=True, width="stretch")
    with tabs[4]:
        s = get_settings()
        st.write(f"발송 모드: {'**Dry-run (outbox/ 저장)**' if s.mail_dry_run or not s.smtp_user else 'SMTP ' + s.smtp_host}")
        if st.button("내 계정으로 리포트 미리보기"):
            data = build_for_user(r, r.get_user(user.email), briefing=False)
            st.components.v1.html(render_html(data, s.app_base_url), height=900, scrolling=True)
        from hbr.notify.channels import CHANNELS

        for ch in CHANNELS.values():
            url = ch.url(s)
            st.write(f"{ch.label} 웹훅: {'설정됨' if url else '미설정'}")
            if st.button(f"{ch.label} 테스트 전송", disabled=not url, key=f"test_{ch.name}"):
                try:
                    ch.send(url, ch.report_card(build_for_user(r, None, briefing=False), s.app_base_url))
                    st.success(f"{ch.label} 채널에 테스트 카드를 보냈습니다.")
                except ch.error as e:
                    st.error(str(e))
        st.write(f"카카오 알림톡: {'설정됨' if s.kakao_enabled and s.kakao_tpl_alert else '미설정 (SOLAPI_*, KAKAO_*)'}")
        me = r.get_user(user.email) or {}
        if st.button("알림톡 테스트 (내 번호)", disabled=not (s.kakao_enabled and s.kakao_tpl_report and me.get("kakao_opt_in") and me.get("phone"))):
            from hbr.notify.kakao import KakaoError, get_provider, report_variables

            try:
                get_provider(s).send(me["phone"], s.kakao_tpl_report, report_variables(build_for_user(r, None, briefing=False)))
                st.success("내 휴대폰으로 알림톡을 보냈습니다.")
            except KakaoError as e:
                st.error(str(e))
        logs = pd.DataFrame(r.rows("email_reports", order="-id", limit=50))
        if not logs.empty:
            st.dataframe(logs[["report_date", "recipient", "status", "error", "sent_at"]], hide_index=True, width="stretch")
