"""사이드바 '메일 구독' 박스: 이메일 → 인증코드 → 등록/취소."""
import time

import streamlit as st

from hbr import subscribe as sub
from hbr.config import get_settings
from hbr.reports.mailer import MailError

MAX_SENDS, MAX_TRIES, COOLDOWN = 3, 5, 60       # 세션당 발송/검증 시도 제한, 재발송 대기(초)


def _flow(repo, s, purpose: str, key: str) -> None:
    st_ = st.session_state
    email = st.text_input("이메일 주소", key=f"{key}_email", placeholder="name@example.com")
    if st.button("인증코드 받기", key=f"{key}_send", width="stretch"):
        if st_.get(f"{key}_sends", 0) >= MAX_SENDS:
            st.error("요청 횟수를 초과했습니다. 잠시 후 다시 시도하세요.")
        elif time.time() - st_.get(f"{key}_last", 0) < COOLDOWN:
            st.warning(f"{COOLDOWN}초 후에 다시 요청할 수 있습니다.")
        else:
            try:
                addr = sub.normalize_email(email)
                if purpose == "subscribe":
                    sub.check_domain(addr)
                st_[f"{key}_last"], st_[f"{key}_sends"] = time.time(), st_.get(f"{key}_sends", 0) + 1
                # 가입 여부와 관계없이 같은 안내를 보여 주소 존재 여부를 노출하지 않는다
                if purpose == "subscribe" or repo.get_user(addr):
                    result = sub.send_code(s, addr, purpose)
                    if result == "dry_run":
                        st.info("테스트 모드: 메일은 outbox 폴더에 저장되었습니다.")
                st_[f"{key}_sent_to"], st_[f"{key}_tries"] = addr, 0
                st.success("인증코드를 보냈습니다. 메일함을 확인해 주세요.")
            except (sub.SubscribeError, MailError) as e:
                st.error(str(e))
    sent_to = st_.get(f"{key}_sent_to")       # 버튼 처리 후에 읽어야 같은 실행에서 입력칸이 보인다
    if sent_to:
        code = st.text_input("인증코드 (6자리)", key=f"{key}_code", max_chars=6)
        if st.button("확인", key=f"{key}_ok", type="primary", width="stretch"):
            if st_.get(f"{key}_tries", 0) >= MAX_TRIES:
                st.error("시도 횟수를 초과했습니다. 코드를 다시 받아 주세요.")
            elif not sub.verify_code(sub.secret_for(s), sent_to, purpose, code):
                st_[f"{key}_tries"] = st_.get(f"{key}_tries", 0) + 1
                st.error("인증코드가 올바르지 않거나 만료되었습니다.")
            else:
                try:
                    if purpose == "subscribe":
                        r = sub.subscribe(repo, sent_to)
                        st.success("이미 구독 중입니다." if r == "already" else f"구독되었습니다. 매일 아침 {sent_to} 로 리포트를 보내드립니다.")
                    else:
                        st.success("구독을 취소했습니다." if sub.unsubscribe(repo, sent_to) else "구독 중이 아닌 주소입니다.")
                    st_.pop(f"{key}_sent_to", None)
                except sub.SubscribeError as e:
                    st.error(str(e))


def render(repo) -> None:
    s = get_settings()
    with st.sidebar.expander("메일 구독", icon=":material/mail:"):
        if not sub.secret_for(s):
            st.caption("구독 기능이 설정되지 않았습니다.")
            return
        t1, t2 = st.tabs(["구독", "취소"])
        with t1:
            st.caption("이메일을 입력하면 매일 아침 신규 의약품 공고·마감 임박 리포트를 받습니다.")
            _flow(repo, s, "subscribe", "sub")
        with t2:
            _flow(repo, s, "unsubscribe", "unsub")
