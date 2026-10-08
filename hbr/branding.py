"""브랜드 요소: 로고 마크(SVG)와 이름. 화면(사이드바)·로그인 화면·파비콘이 같은 마크를 쓴다."""
from __future__ import annotations

NAME = "Hospital Bid Radar"
TAGLINE = "PHARMA · BID INTELLIGENCE"


def mark_svg(size: int = 52, uid: str = "m") -> str:
    """병원 + 레이더: 그라데이션 라운드 사각형, 레이더 원·스윕, 의료 십자 표식."""
    return f"""<svg width="{size}" height="{size}" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg" aria-label="{NAME}">
  <defs>
    <linearGradient id="bg{uid}" x1="6" y1="4" x2="58" y2="62" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#3b82f6"/><stop offset=".55" stop-color="#1d4ed8"/><stop offset="1" stop-color="#0f9d8f"/>
    </linearGradient>
    <linearGradient id="sw{uid}" x1="32" y1="32" x2="50" y2="14" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#fff" stop-opacity=".62"/>
    </linearGradient>
    <radialGradient id="gl{uid}" cx="22" cy="12" r="40" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#fff" stop-opacity=".30"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
    </radialGradient>
  </defs>
  <rect x="2" y="2" width="60" height="60" rx="18" fill="url(#bg{uid})"/>
  <rect x="2" y="2" width="60" height="60" rx="18" fill="url(#gl{uid})"/>
  <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="17.3" stroke="#fff" stroke-opacity=".22" stroke-width="1.5"/>
  <circle cx="32" cy="34" r="20" stroke="#fff" stroke-opacity=".38" stroke-width="1.8"/>
  <circle cx="32" cy="34" r="12.5" stroke="#fff" stroke-opacity=".55" stroke-width="1.8"/>
  <path d="M32 34 L50.6 15.6 A26 26 0 0 0 32 8 Z" fill="url(#sw{uid})" opacity=".0"/>
  <path d="M32 34 L46.1 19.9 A20 20 0 0 0 32 14 Z" fill="url(#sw{uid})"/>
  <path d="M32 34 L46.1 19.9" stroke="#fff" stroke-width="2.4" stroke-linecap="round"/>
  <circle cx="32" cy="34" r="3.1" fill="#fff"/>
  <g transform="translate(43.5 39.5)">
    <rect x="-2.1" y="-6.2" width="4.2" height="12.4" rx="1.4" fill="#fff"/>
    <rect x="-6.2" y="-2.1" width="12.4" height="4.2" rx="1.4" fill="#fff"/>
  </g>
</svg>"""
