from __future__ import annotations

import streamlit as st


GLOBAL_CSS = """
<style>
  .block-container {padding-top: 1.35rem; max-width: 1600px}
  [data-testid="stSidebar"] {border-right: 1px solid #203349}
  .ve-eyebrow {color:#43D6B5;letter-spacing:.13em;font-size:.72rem;font-weight:750;text-transform:uppercase}
  .ve-hero {font-size:clamp(1.75rem,3vw,2.45rem);line-height:1.06;font-weight:730;margin:.22rem 0 .32rem}
  .ve-subtle {color:#8FA4B8;margin-bottom:1.15rem;max-width:1000px}
  .ve-note {border:1px solid #825f28;background:#2a2115;padding:.7rem .9rem;border-radius:.55rem;color:#e7c981}
  .ve-source {display:inline-block;padding:.16rem .45rem;border:1px solid #2b5362;border-radius:1rem;color:#79e2c8;font-size:.72rem}
  .ve-metric-grid {display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:.65rem;margin:.35rem 0 1rem}
  .ve-metric {background:#101D2E;border:1px solid #203349;padding:.72rem .82rem;border-radius:10px;min-width:0;overflow-x:auto}
  .ve-metric-label {color:#8FA4B8;font-size:.76rem;white-space:nowrap}
  .ve-metric-value {font-variant-numeric:tabular-nums;font-size:clamp(1.05rem,1.6vw,1.42rem);font-weight:680;white-space:nowrap;min-width:max-content}
  .ve-metric-note {font-size:.69rem;color:#6f879c;white-space:nowrap}
  .stButton > button {border-radius:8px}
  [data-testid="stDataFrame"] {font-variant-numeric:tabular-nums}
</style>
"""


def apply_layout() -> None:
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def page_header(kicker: str, title: str, subtitle: str) -> None:
    st.markdown(
        f'<div class="ve-eyebrow">{kicker}</div><div class="ve-hero">{title}</div>'
        f'<div class="ve-subtle">{subtitle}</div>', unsafe_allow_html=True,
    )


def assumption_note(text: str) -> None:
    st.markdown(f'<div class="ve-note">{text}</div>', unsafe_allow_html=True)

