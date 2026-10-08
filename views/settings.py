import pandas as pd
import streamlit as st

from hbr.analytics.alerts import generate_alerts
from hbr.analytics.scoring import ensure_scores
from hbr.auth import accounts
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

    if get_settings().auth_mode == "password" and not get_settings().auth_disabled and user.id:
        with st.expander("🔑 비밀번호 변경"):
            with st.form("change_pw"):
                old_pw = st.text_input("현재 비밀번호", type="password", key="cp_old")
                new_pw = st.text_input("새 비밀번호", type="password", key="cp_new")
                new_pw2 = st.text_input("새 비밀번호 확인", type="password", key="cp_new2")
                if st.form_submit_button("변경", key="cp_submit"):
                    if new_pw != new_pw2:
                        st.error("새 비밀번호 확인이 일치하지 않습니다.")
                    else:
                        try:
                            accounts.change_password(r, user.id, old_pw, new_pw)
                            st.success("비밀번호를 변경했습니다.")
                        except accounts.AccountError as e:
                            st.error(str(e))

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
        rows = r.rows("users")
        pending = [u for u in rows if accounts.status_of(u) == "pending"]
        st.subheader(f"승인 대기 {len(pending)}명")
        if not pending:
            st.caption("대기 중인 가입 신청이 없습니다.")
        for u in pending:
            c = st.columns([3, 2, 1, 1])
            c[0].write(f"**{u.get('name') or '-'}** · {u['email']}")
            role = c[1].selectbox("부여할 역할", ROLES, key=f"role_{u['id']}", label_visibility="collapsed")
            if c[2].button("승인", key=f"ok_{u['id']}", type="primary"):
                accounts.approve(r, u["id"], role, user.id)
                st.rerun()
            if c[3].button("거절", key=f"no_{u['id']}"):
                try:
                    accounts.reject(r, u["id"])
                    st.rerun()
                except accounts.AccountError as e:
                    st.error(str(e))

        st.subheader("전체 사용자")
        members = [u for u in rows if accounts.status_of(u) != "pending"]
        if members:
            df = pd.DataFrame(members)
            df["status"] = df.apply(lambda x: accounts.status_of(x), axis=1)
            edited = st.data_editor(df[["id", "email", "name", "role", "status", "is_active", "report_enabled"]],
                                    disabled=["id", "email", "status"], hide_index=True, width="stretch",
                                    column_config={"role": st.column_config.SelectboxColumn("role", options=ROLES)})
            if st.button("사용자 변경 저장"):
                errors = []
                for rec in edited.to_dict("records"):
                    try:
                        accounts.update_user(r, rec["id"], role=rec["role"], is_active=bool(rec["is_active"]),
                                             report_enabled=bool(rec["report_enabled"]), name=rec["name"])
                    except accounts.AccountError as e:
                        errors.append(f"{rec['email']}: {e}")
                st.error("\n\n".join(errors)) if errors else st.success("저장했습니다.")

            st.markdown("##### 비밀번호 초기화 / 가입 상태")
            target = st.selectbox("대상 사용자", [f"{u['email']}" for u in members], key="reset_target")
            c1, c2 = st.columns(2)
            tgt = next(u for u in members if u["email"] == target)
            if c1.button("임시 비밀번호 발급", key="reset_btn"):
                temp = accounts.reset_password(r, tgt["id"])
                st.warning("아래 임시 비밀번호는 **지금 한 번만** 표시됩니다. 사용자에게 안전하게 전달하세요 (다음 로그인 때 변경이 강제됩니다).")
                st.code(temp)
            if tgt.get("status") in ("rejected", "disabled") and c2.button("다시 승인", key="reapprove_btn"):
                accounts.approve(r, tgt["id"], tgt.get("role") or "viewer", user.id)
                st.rerun()
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
