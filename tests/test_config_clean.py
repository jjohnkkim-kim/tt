import pytest

from hbr.config import clean_secret, clean_supabase_url


@pytest.mark.parametrize("raw,want", [
    ("https://abc.supabase.co", "https://abc.supabase.co"),
    ("  https://abc.supabase.co\n", "https://abc.supabase.co"),
    ('"https://abc.supabase.co"', "https://abc.supabase.co"),
    ("'https://abc.supabase.co/'", "https://abc.supabase.co"),
    ("abc.supabase.co", "https://abc.supabase.co"),
    ("https://abc.supabase.co/rest/v1/", "https://abc.supabase.co"),
    ("", ""), (None, ""), ("   ", ""),
])
def test_clean_supabase_url(raw, want):
    assert clean_supabase_url(raw) == want


def test_clean_secret():
    assert clean_secret(' "sb_secret_x"\n') == "sb_secret_x" and clean_secret(None) == ""


def test_pipeline_script_imports():
    """scripts/run_pipeline.py 문법 오류가 테스트에서 잡히도록 import 한다."""
    import importlib

    assert hasattr(importlib.import_module("scripts.run_pipeline"), "main")
