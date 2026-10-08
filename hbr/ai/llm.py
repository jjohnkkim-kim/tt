"""LLM 공급자 추상화 (Claude 우선, OpenAI 폴백). 키가 없으면 None → 규칙 기반으로 동작."""
from __future__ import annotations

import logging

from ..config import Settings, get_settings

log = logging.getLogger(__name__)


def provider(settings: Settings | None = None) -> str | None:
    s = settings or get_settings()
    if s.llm_provider == "none":
        return None
    if s.llm_provider in {"anthropic", "openai"}:
        key = s.anthropic_api_key if s.llm_provider == "anthropic" else s.openai_api_key
        return s.llm_provider if key else None
    if s.anthropic_api_key:
        return "anthropic"
    if s.openai_api_key:
        return "openai"
    return None


def complete(system: str, user: str, max_tokens: int = 500, settings: Settings | None = None) -> str | None:
    """단발 텍스트 생성. 실패해도 예외를 던지지 않고 None (리포트 발송을 막지 않기 위함)."""
    s = settings or get_settings()
    p = provider(s)
    try:
        if p == "anthropic":
            import anthropic

            r = anthropic.Anthropic(api_key=s.anthropic_api_key).messages.create(
                model=s.claude_model, max_tokens=max_tokens, system=system,
                messages=[{"role": "user", "content": user}])
            return "".join(b.text for b in r.content if getattr(b, "type", "") == "text").strip() or None
        if p == "openai":
            from openai import OpenAI

            r = OpenAI(api_key=s.openai_api_key).chat.completions.create(
                model=s.openai_model, max_tokens=max_tokens,
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
            return (r.choices[0].message.content or "").strip() or None
    except Exception:       # noqa: BLE001
        log.exception("LLM 호출 실패")
    return None


def executive_briefing(top_opps, today) -> str | None:
    """Daily Report 상단 3~4문장 브리핑. 점수/수치는 입력 그대로만 사용하도록 지시."""
    if not top_opps or provider() is None:
        return None
    facts = "\n".join(f"- {o.hospital}: {o.score}점, " + ", ".join(o.reasons) for o in top_opps)
    return complete(
        "당신은 제약회사 영업관리자를 위한 입찰 인텔리전스 분석가입니다. 아래 사실만 근거로 "
        "한국어 3문장 이내로 오늘의 핵심을 요약하세요. 주어진 숫자 외의 수치나 사실을 만들지 마세요.",
        f"기준일 {today}\n{facts}", max_tokens=300)
