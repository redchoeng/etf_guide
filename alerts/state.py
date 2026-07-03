import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

STATE_FILE = Path(__file__).parent / "state.json"
KST = timezone(timedelta(hours=9))


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _should_alert(key: str, state: dict) -> bool:
    """같은 알림은 하루(KST 날짜 기준) 1번만.

    타임스탬프 비교가 아니라 날짜 문자열 비교라서
    크론 지연·수동 실행 시간과 무관하게 매일 리셋된다.
    """
    today = datetime.now(KST).strftime("%Y-%m-%d")
    cache_key = f"_alert_{key}"
    if state.get(cache_key) == today:
        return False
    state[cache_key] = today
    return True
