"""하위 호환 re-export. 직접 import는 각 서브모듈을 사용하세요.

  from alerts.telegram import TelegramNotifier
  from alerts.checker import check_and_notify
  from alerts.state import _load_state, _save_state, _should_alert
  from engine.scorer import DD_ZONES, dd_multiplier
  from engine.formatters import fmt_price, buy_phrase
"""

from alerts.state import (  # noqa: F401
    STATE_FILE, ALERT_COOLDOWN,
    _load_state, _save_state, _should_alert,
)
from alerts.telegram import (  # noqa: F401
    TelegramNotifier, REPORT_URL, report_kb,
)
from alerts.checker import check_and_notify  # noqa: F401
from engine.scorer import DD_ZONES, dd_multiplier  # noqa: F401
from engine.formatters import fmt_price, buy_phrase  # noqa: F401
