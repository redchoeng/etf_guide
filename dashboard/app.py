import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import streamlit as st
import yaml


def load_config():
    config_path = project_root / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_presets():
    preset_path = project_root / "config" / "etf_presets.yaml"
    with open(preset_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    st.set_page_config(
        page_title="우당탕탕 딩쵱 하우스 마련 대작전",
        page_icon="🏠",
        layout="wide",
        initial_sidebar_state="expanded",
    )

    if "config" not in st.session_state:
        st.session_state.config = load_config()
    if "presets" not in st.session_state:
        st.session_state.presets = load_presets()

    st.sidebar.title("🏠 딩쵱 하우스 대작전")
    st.sidebar.markdown("---")

    pages = {
        "개요": "overview",
        "그리드 설정": "grid_setup",
        "분석": "analysis",
        "백테스트": "backtest",
        "포트폴리오": "portfolio",
    }

    icons = {
        "개요": "🏠",
        "그리드 설정": "⚙️",
        "분석": "📈",
        "백테스트": "🧪",
        "포트폴리오": "💼",
    }

    selected = st.sidebar.radio(
        "메뉴",
        list(pages.keys()),
        format_func=lambda x: f"{icons[x]} {x}",
    )

    st.sidebar.markdown("---")
    st.sidebar.caption("우당탕탕 딩쵱 하우스 마련 대작전 v3.0")

    if selected == "개요":
        from dashboard.pages.overview import render
    elif selected == "그리드 설정":
        from dashboard.pages.grid_setup import render
    elif selected == "분석":
        from dashboard.pages.analysis import render
    elif selected == "백테스트":
        from dashboard.pages.backtest import render
    elif selected == "포트폴리오":
        from dashboard.pages.portfolio import render

    render()


if __name__ == "__main__":
    main()
