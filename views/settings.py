import pandas as pd
import streamlit as st

from hbr.auth import accounts
from hbr.analytics.alerts import generate_alerts
from hbr.analytics.scoring import ensure_scores
from hbr.company import products_frame, sync_products
from hbr.admin_stats import overview
from hbr.config import get_settings
from hbr.plans import PLANS, plan_of
from hbr.team import TEAM_ROLES, TeamError, set_member
from hbr.analytics.alert_rules import rule_from_row, rule_to_row, Rule
from hbr.constants import ALERT_TYPES, DEADLINE_DAYS, RULE_TYPES, ROLES
from hbr.reports.daily import build_for_user, render_html

from views import _ui
from views._common import company_id, current_user, opportunities, repo, snapshot

_ui.page_header("설정", "관심병원·사용자·수집 이력 관리", "SETTINGS")
user, r = current_user(), repo()
_names = (["내 설정", "관심병원", "회사·관심제품", "알림 설정"] + (["팀"] if user.can("team") and user.company_id else [])
          + (["운영 현황", "사용자 관리", "운영 / 파이프라인", "메일"] if user.can("admin") else []))
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

        _ui.section("요금제")
        _pl = plan_of(company)
        _u1, _u2, _u3 = st.columns(3)
        _u1.metric("현재 요금제", PLANS[_pl]["label"], help="결제 연동 전이라 요금제 변경은 관리자에게 요청하세요." + (f" (기한 {company['plan_until']})" if company.get("plan_until") else ""))
        _u2.metric("관심 제품", f"{len(r.list_products(cid))} / {PLANS[_pl]['products']}")
        _u3.metric("팀원", f"{r.seats_used(cid)} / {PLANS[_pl]['seats']}")

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

with T["알림 설정"]:
    if not user.id:
        st.info("로그인한 사용자만 알림 조건을 저장할 수 있습니다.")
    else:
        saved = r.get_alert_rule(user.id)
        rule = rule_from_row(saved)
        if not saved:
            st.info("아직 조건을 저장하지 않았습니다. 지금은 예전 방식(구독한 병원의 신규 입찰·계약 종료·낙찰)으로 알려 드려요. 아래에서 저장하면 새 조건으로 바뀝니다.")
        has_products = bool(r.list_products(company_id()))
        n_watched = len(r.watched_hospital_ids(user.id))
        with st.form("alert_rule_form"):
            _ui.section("받고 싶은 알림")
            types = st.multiselect("알림 종류", RULE_TYPES, default=list(rule.types), format_func=lambda t: ALERT_TYPES[t])
            days = st.multiselect("마감 임박은 며칠 전에 알릴까요?", list(DEADLINE_DAYS), default=list(rule.deadline_days), format_func=lambda d: f"D-{d}",
                                  help="'마감 임박'을 선택했을 때만 적용됩니다.")
            _ui.section("받을 범위")
            scope = st.radio("범위", ["all", "mine"], index=0 if rule.scope == "all" else 1, horizontal=True,
                             format_func=lambda x: "전체 (모든 병원·제품)" if x == "all" else "내 관심만 (관심 제품 매칭 또는 관심 병원)")
            min_match = st.selectbox("관심 제품 최소 매칭 신뢰도", ["HIGH", "MEDIUM", "LOW"], index=["HIGH", "MEDIUM", "LOW"].index(rule.min_match),
                                     help="'내 관심만'일 때 적용됩니다. HIGH=확실, MEDIUM=꽤 비슷, LOW=검토 필요한 정도까지")
            exclude_own = st.toggle("우리 회사가 낙찰받은 건은 제외", value=rule.exclude_own, help="회사 설정의 '자사 표기명'과 낙찰업체를 비교합니다.")
            _ui.section("받는 방법")
            st.caption("앱 안의 '알림' 화면에서는 항상 볼 수 있습니다.")
            email = st.toggle("이메일로도 받기", value=rule.email_enabled)
            if st.form_submit_button("알림 조건 저장", type="primary", use_container_width=True, key="alert_save"):
                r.save_alert_rule(user.id, rule_to_row(Rule(types=tuple(types), deadline_days=tuple(sorted(days, reverse=True)), scope=scope,
                                                            min_match=min_match, exclude_own=exclude_own, email_enabled=email)))
                st.cache_data.clear()
                st.success("저장했습니다. 이후 알림부터 새 조건이 적용됩니다.")
        if scope == "mine" or rule.scope == "mine":
            notes = []
            if not has_products:
                notes.append("관심 제품이 없어 제품 매칭 알림은 오지 않습니다 → '회사·관심제품' 탭에서 등록하세요.")
            if not n_watched:
                notes.append("관심 병원이 없어 병원 기준 알림은 오지 않습니다 → '관심병원' 탭에서 등록하세요.")
            for n in notes:
                st.warning(n)
        if "DEADLINE" in types and not days:
            st.warning("'마감 임박'을 선택했지만 D-day를 하나도 고르지 않아 이 알림은 오지 않습니다.")

if "팀" in T:
    with T["팀"]:
        co = r.get_company(user.company_id)
        pl = plan_of(co)
        st.caption(f"{co['name'] if co else ''} · 요금제 {PLANS[pl]['label']} · 팀원 {r.seats_used(user.company_id)} / {PLANS[pl]['seats']}명. "
                   "새 팀원은 가입 후 관리자가 회사에 배정합니다 (매니저는 역할과 사용 여부만 바꿀 수 있어요).")
        members = r.company_members(user.company_id)
        if not members:
            st.info("팀원이 없습니다.")
        for m in members:
            c = st.columns([3, 2, 1, 1])
            c[0].write(f"**{m.get('name') or '-'}** · {m['email']}" + (" · (나)" if m["id"] == user.id else ""))
            locked = m["id"] == user.id or (m.get("role") == "admin" and user.role != "admin")
            roles = TEAM_ROLES if m.get("role") in TEAM_ROLES else [m.get("role")]
            new_role = c[1].selectbox("역할", roles, index=roles.index(m["role"]) if m.get("role") in roles else 0,
                                      key=f"team_role_{m['id']}", label_visibility="collapsed", disabled=locked)
            active = m.get("is_active", True)
            if c[2].button("저장", key=f"team_save_{m['id']}", disabled=locked or new_role == m.get("role")):
                try:
                    set_member(r, user, m["id"], role=new_role)
                    st.rerun()
                except TeamError as e:
                    st.error(str(e))
            if c[3].button("사용 중지" if active else "다시 사용", key=f"team_act_{m['id']}", disabled=locked):
                try:
                    set_member(r, user, m["id"], is_active=not active)
                    st.rerun()
                except TeamError as e:
                    st.error(str(e))

if user.can("admin"):
    with T["운영 현황"]:
        ov = overview(r)
        k = st.columns(4)
        k[0].metric("회사", ov["companies"]); k[1].metric("활성 사용자", ov["active"]); k[2].metric("승인 대기", ov["pending"])
        k[3].metric("회사 미배정 사용자", ov["no_company_users"], help="가입했지만 회사에 배정되지 않은 사용자 — 사용자 관리 탭에서 배정하세요.")
        k = st.columns(3)
        k[0].metric("마지막 수집 성공", ov["last_success"].tz_convert("Asia/Seoul").strftime("%m-%d %H:%M") if ov["last_success"] is not None and not pd.isna(ov["last_success"]) else "기록 없음")
        k[1].metric("최근 수집 실패(10회 중)", ov["recent_failures"])
        k[2].metric("메일 7일: 발송 / 실패", f"{ov['mail_7d']['sent']} / {ov['mail_7d']['failed']}")
        _ui.section("회사별 현황과 요금제")
        st.dataframe(ov["table"].drop(columns="company_id"), hide_index=True, width="stretch")
        if not ov["table"].empty:
            p1, p2, p3, p4 = st.columns([3, 2, 2, 1])
            names = list(ov["table"]["회사"])
            who = p1.selectbox("회사", names, key="plan_company")
            cid_p = int(ov["table"].loc[ov["table"]["회사"] == who, "company_id"].iloc[0])
            plan_new = p2.selectbox("요금제", list(PLANS), format_func=lambda k: PLANS[k]["label"], key="plan_new")
            until = p3.date_input("기한 (선택)", value=None, key="plan_until")
            if p4.button("변경", key="plan_btn"):
                try:
                    r.set_plan(cid_p, plan_new, until)
                    st.cache_data.clear()
                    st.success("요금제를 바꿨습니다.")
                    st.rerun()
                except Exception as e:      # noqa: BLE001  (마이그레이션 006 전에는 컬럼이 없다)
                    st.error(f"변경하지 못했습니다: {e}")
            st.caption("결제 연동 전이라 요금제는 여기서 직접 바꿉니다. 기한이 지나면 자동으로 Free 한도가 적용됩니다.")

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
                try:
                    r.assign_company(target["id"], sel)
                    st.cache_data.clear()
                    st.success("배정했습니다.")
                except ValueError as e:
                    st.error(str(e))
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
