import json
import time
from pathlib import Path

STATE_FILE = Path(__file__).parent / "state.json"
ALERT_COOLDOWN = 86400  # 24시간 — 같은 알림 하루에 1번만


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
    """쿨다운 내 중복 알림 방지 (state.json에 영속 저장)."""
    now = time.time()
    cache_key = f"_alert_{key}"
    last = state.get(cache_key, 0)
    if now - last < ALERT_COOLDOWN:
        return False
    state[cache_key] = now
    return True
