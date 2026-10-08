import pandas as pd
import streamlit as st

from hbr.auth import accounts
from hbr.analytics.alerts import generate_alerts
from hbr.analytics.scoring import ensure_scores
from hbr.company import products_frame, sync_products
from hbr.config import get_settings
from hbr.constants import ROLES
from hbr.reports.daily import build_for_user, render_html

from views import _ui
from views._common import company_id, current_user, opportunities, repo, snapshot

_ui.page_header("설정", "관심병원·사용자·수집 이력 관리", "SETTINGS")
user, r = current_user(), repo()
_names = ["내 설정", "관심병원", "회사·관심제품"] + (["사용자 관리", "운영 / 파이프라인", "메일"] if user.can("admin") else [])
T = dict(zip(_names, st.tabs(_names)))

with T["내 설정"]:
    row = r.get_user(user.email) or {}
    st.write(f"**{user.name}** ({user.email}) · 역할 `{user.role}`")
    personal = st.text_input("개인 이메일 (Daily Report 추가 수신)", row.get("personal_email") or "")
    enabled = st.toggle("매일 08:00 Daily Report 수신", value=bool(row.get("report_enabled", True)))
    if st.button("저장", key="save_me") and user.id:
        r.update("users", {"personal_email": personal.strip() or None, "report_enabled": enabled}, [("id", "eq", user.id)])
        st.success("저장했습니다.")
    cfg = get_settings()
    if cfg.auth_mode == "password" and not cfg.auth_disabled and user.id:
        with st.expander("비밀번호 변경", icon=":material/key:"):
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

with T["관심병원"]:
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


with T["회사·관심제품"]:
    cid = company_id()
    company = r.get_company(cid)
    COMPANY_TYPES = ["제약사", "바이오기업", "CSO", "의약품 도매", "의료기기", "진단", "기타"]
    if not company:
        st.info("아직 소속 회사가 없습니다. 회사를 만들거나 관리자에게 배정을 요청하세요.")
        if user.can("company_edit") and user.id:
            with st.form("new_company"):
                nm = st.text_input("회사명")
                tp = st.selectbox("회사 유형", COMPANY_TYPES)
                al = st.text_area("자사 표기명 (낙찰·계약업체 이름과 비교, 쉼표 또는 줄바꿈으로 구분)",
                                  placeholder="예: 가나제약, 가나 제약(주)", help="비워 두면 회사명만 사용합니다.")
                if st.form_submit_button("회사 만들기", type="primary", use_container_width=True):
                    try:
                        c = r.create_company(nm, tp, [a for a in al.replace("\n", ",").split(",")])
                        r.assign_company(user.id, c["id"])
                        st.cache_data.clear()
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
        else:
            st.caption("회사 만들기는 관리자 또는 매니저 권한이 필요합니다.")
    else:
        can_company, can_products = user.can("company_edit"), user.can("product_edit")
        _ui.section("회사 정보")
        with st.form("company_form"):
            nm = st.text_input("회사명", company["name"], disabled=not can_company)
            tp = st.selectbox("회사 유형", COMPANY_TYPES, index=COMPANY_TYPES.index(company["company_type"]) if company["company_type"] in COMPANY_TYPES else 0,
                              disabled=not can_company)
            al = st.text_area("자사 표기명", ", ".join(company.get("own_aliases") or []), disabled=not can_company,
                              help="낙찰·계약업체 이름이 이 중 하나와 맞으면 '자사'로 봅니다. 경쟁사 분석과 알림에서 자사를 구분하는 데 쓰입니다.")
            if st.form_submit_button("회사 정보 저장", disabled=not can_company):
                try:
                    r.update_company(company["id"], nm, tp, al.replace("\n", ",").split(","))
                    st.cache_data.clear()
                    st.success("저장했습니다.")
                except ValueError as e:
                    st.error(str(e))
        if not can_company:
            st.caption("회사 정보 수정은 매니저 이상 권한이 필요합니다.")

        _ui.section("관심 제품")
        st.caption("등록한 제품은 입찰 품목과 자동으로 매칭하는 데 쓰입니다. 제품명·성분명·동의어(다른 표기)를 넣을수록 정확해집니다. "
                   "다른 회사의 제품은 보이지 않습니다.")
        prods = r.list_products(cid)
        base = products_frame(prods)
        edited = st.data_editor(base, num_rows="dynamic" if can_products else "fixed", disabled=(not can_products) or ["id"], hide_index=True,
                                width="stretch", key="products_editor", column_config={"id": None})
        if can_products and st.button("관심 제품 저장", type="primary"):
            saved, errors = sync_products(r, cid, edited.to_dict("records"))
            if errors:
                st.error("\n\n".join(errors) + "\n\n오류가 있어 삭제는 반영하지 않았습니다.")
            else:
                st.cache_data.clear()
                st.success(f"저장했습니다 ({saved}개).")
        if not can_products:
            st.caption("관심 제품 수정은 영업(sales) 이상 권한이 필요합니다.")

if user.can("admin"):
    with T["사용자 관리"]:
        rows = r.rows("users")
        pending = [u for u in rows if accounts.status_of(u) == "pending"]
        _ui.section(f"승인 대기 {len(pending)}명")
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

        _ui.section("전체 사용자")
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

        _ui.section("회사 배정")
        companies = r.list_companies()
        cname = {c["id"]: c["name"] for c in companies}
        if not rows:
            st.caption("사용자가 없습니다.")
        else:
            a1, a2, a3 = st.columns([3, 3, 1])
            who = a1.selectbox("사용자", [u["email"] for u in rows], key="assign_user")
            target = next(u for u in rows if u["email"] == who)
            opts = [None] + [c["id"] for c in companies]
            sel = a2.selectbox("소속 회사", opts, index=opts.index(target.get("company_id")) if target.get("company_id") in opts else 0,
                               format_func=lambda x: "(없음)" if x is None else cname[x], key="assign_company")
            if a3.button("배정", key="assign_btn"):
                r.assign_company(target["id"], sel)
                st.cache_data.clear()
                st.success("배정했습니다.")
        with st.expander("새 회사 만들기"):
            with st.form("admin_new_company"):
                n2 = st.text_input("회사명")
                t2 = st.selectbox("회사 유형", ["제약사", "바이오기업", "CSO", "의약품 도매", "의료기기", "진단", "기타"], key="t2")
                a2s = st.text_area("자사 표기명 (쉼표 구분, 비우면 회사명)", key="a2s")
                if st.form_submit_button("만들기"):
                    try:
                        r.create_company(n2, t2, a2s.replace("\n", ",").split(","))
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))

    with T["운영 / 파이프라인"]:
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
    with T["메일"]:
        s = get_settings()
        st.write(f"발송 모드: {'**Dry-run (outbox/ 저장)**' if s.mail_dry_run or not s.smtp_user else 'SMTP ' + s.smtp_host}")
        if st.button("내 계정으로 리포트 미리보기"):
            data = build_for_user(r, r.get_user(user.email), briefing=False)
            st.components.v1.html(render_html(data, s.app_base_url), height=900, scrolling=True)
        logs = pd.DataFrame(r.rows("email_reports", order="-id", limit=50))
        if not logs.empty:
            st.dataframe(logs[["report_date", "recipient", "status", "error", "sent_at"]], hide_index=True, width="stretch")
