#!/usr/bin/env python
"""
가격 체크 + Telegram 알림 실행기.

사용법:
  python run_monitor.py --once            # 1회 실행 (긴급 알림만)
  python run_monitor.py --once --digest   # 1회 실행 (주간 매수 가이드 포함)
  python run_monitor.py                   # 5분 간격 반복 (로컬 테스트용)

실행 시점 관리는 GitHub Actions 크론(평일 KST 09:30)이 담당한다.
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import schedule
import yaml
from dotenv import load_dotenv

from alerts.notifier import check_and_notify, TelegramNotifier

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def load_config():
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser(description="ETF 가격 체크 + 알림")
    parser.add_argument("--interval", type=int, default=5, help="반복 간격 (분, 기본: 5)")
    parser.add_argument("--once", action="store_true", help="1회만 실행")
    parser.add_argument("--force", action="store_true", help="(하위 호환용, 무시됨)")
    parser.add_argument("--digest", action="store_true", help="주간 매수 가이드 발송 (미지정 시 긴급 알림만)")
    parser.add_argument("--inav", action="store_true", help="추정 iNAV 알림만 발송 (미국장 마감 후)")
    parser.add_argument("--premarket", action="store_true",
                        help="장전 브리핑 (08:30) — 구성종목 매매내역 + 추정 iNAV 예상가")
    args = parser.parse_args()

    if args.inav:
        from alerts.inav import send_inav_alert
        send_inav_alert(load_config())
        return

    if args.premarket:
        from alerts.holdings import check_holdings_changes
        from alerts.state import _load_state, _save_state
        from alerts.inav import send_inav_alert

        notifier = TelegramNotifier()
        if not notifier.is_configured:
            logger.error("Telegram 설정이 필요합니다.")
            sys.exit(1)
        preset_path = Path(__file__).parent / "config" / "etf_presets.yaml"
        with open(preset_path, "r", encoding="utf-8") as f:
            presets = yaml.safe_load(f).get("presets", {})
        state = _load_state()
        notifier._state = state
        n = check_holdings_changes(notifier, state, presets, krx_attempts=3)
        _save_state(state)
        logger.info(f"장전 구성종목 체크 완료: {n}건 알림")

        send_inav_alert(load_config())
        return

    mode = "digest" if args.digest else "urgent"

    notifier = TelegramNotifier()
    if not notifier.is_configured:
        logger.error(
            "❌ Telegram 설정이 필요합니다.\n"
            "   .env 파일에 다음을 추가하세요:\n"
            "   TELEGRAM_BOT_TOKEN=your_token\n"
            "   TELEGRAM_CHAT_ID=your_chat_id"
        )
        sys.exit(1)

    logger.info(f"📊 ETF 가격 체크 시작 (mode={mode})")
    logger.info(f"   Telegram: ✅ 설정됨 (chat_id: {notifier.chat_id})")

    if args.once:
        config = load_config()
        check_and_notify(config, mode=mode)
        return

    # 반복 모드 (로컬 테스트용)
    def run_check():
        try:
            check_and_notify(load_config(), mode=mode)
        except Exception as e:
            logger.error(f"❌ 체크 실패: {e}")

    schedule.every(args.interval).minutes.do(run_check)
    run_check()

    logger.info(f"⏰ {args.interval}분 간격으로 모니터링 중... (Ctrl+C로 종료)")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("🛑 모니터 종료")


if __name__ == "__main__":
    main()
