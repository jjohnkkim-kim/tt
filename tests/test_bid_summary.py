from datetime import date

import pandas as pd

from hbr.ai import bid_summary as bs

TODAY = date(2026, 10, 8)
ROW = pd.Series({"title": "2026년 의약품 알부민 구매", "hospital": "가병원", "bid_date": pd.Timestamp("2026-10-01"),
                 "deadline": pd.Timestamp("2026-10-12 17:00"), "budget": 250_000_000.0, "bid_method": "전자입찰",
                 "contract_method": None, "product_tags": ["혈액제제"]})


def test_facts_missing_values_are_none_and_shown_as_unknown():
    f = bs.build_facts(ROW, TODAY)
    assert f["D-day"] == 4 and f["예산"] == "2.50억원" and f["계약방식"] is None
    assert "계약방식: 정보 없음" in bs.facts_text(f)
    sparse = bs.build_facts(pd.Series({"title": "x"}), TODAY)
    assert sparse["D-day"] is None and sparse["예산"] is None and sparse["마감"] is None


def test_rule_summary_never_invents_items_and_mentions_missing_attachments():
    txt = bs.rule_summary(bs.build_facts(ROW, TODAY))
    assert "D-4" in txt and "2.50억원" in txt and "정보 없음" in txt and "찾지 못했어요" in txt


def test_summarize_falls_back_without_ai_key(monkeypatch):
    monkeypatch.setattr(bs, "provider", lambda: None)
    text, src = bs.summarize(bs.build_facts(ROW, TODAY))
    assert src == "규칙" and "알부민" in text


def test_summarize_uses_ai_and_falls_back_when_it_fails(monkeypatch):
    seen = {}
    monkeypatch.setattr(bs, "provider", lambda: "anthropic")
    monkeypatch.setattr(bs, "complete", lambda system, user, max_tokens=0: seen.update(system=system, user=user) or "- AI 요약")
    assert bs.summarize(bs.build_facts(ROW, TODAY)) == ("- AI 요약", "AI")
    assert "지시로 따르지" in seen["system"] and "공고 정보" in seen["user"] and "첨부" not in seen["user"]
    monkeypatch.setattr(bs, "complete", lambda *a, **k: None)
    assert bs.summarize(bs.build_facts(ROW, TODAY))[1] == "규칙"
