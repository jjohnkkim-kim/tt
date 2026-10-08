import streamlit as st

from hbr.ai.copilot import Copilot
from hbr.ai.llm import provider

from views import _ui
from views._common import company_id, repo

_ui.page_header("AI Copilot", "데이터에 대해 자유롭게 질문하세요", "ASSISTANT")
mode = provider()
st.caption(f"모드: {'Claude' if mode == 'anthropic' else 'OpenAI' if mode == 'openai' else '기본 분석(규칙 기반 — API 키 없음)'}"
           " · 모든 수치는 DB 조회 결과이며 읽기 전용입니다.")

EXAMPLES = ["최근 90일 이내 계약종료 예정 병원은?", "이번 달 가장 중요한 입찰은?", "GC가 가장 많이 수주한 병원은?",
            "이번 주 새로 발생한 대학병원 입찰은?", "방문 우선순위를 추천해줘", "Opportunity Score 상위 병원을 보여줘"]
if "chat" not in st.session_state:
    st.session_state.chat = []

cols = st.columns(3)
clicked = None
for i, ex in enumerate(EXAMPLES):
    if cols[i % 3].button(ex, width="stretch"):
        clicked = ex

for m in st.session_state.chat:
    with st.chat_message(m["role"]):
        st.markdown(m["content"])

question = st.chat_input("질문을 입력하세요") or clicked
if question:
    with st.chat_message("user"):
        st.markdown(question)
    with st.chat_message("assistant"):
        with st.spinner("분석 중…"):
            ans = Copilot(repo(), own_aliases=repo().own_aliases(company_id())).ask(question, st.session_state.chat)
        st.markdown(ans.text)
        if ans.tools_used:
            st.caption("조회 도구: " + ", ".join(dict.fromkeys(ans.tools_used)))
    st.session_state.chat += [{"role": "user", "content": question}, {"role": "assistant", "content": ans.text}]
