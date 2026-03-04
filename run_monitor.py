#!/usr/bin/env python
"""
가격 모니터링 + Telegram 알림 스케줄러.

사용법:
  python run_monitor.py              # 기본: 5분 간격
  python run_monitor.py --interval 3 # 3분 간격
  python run_monitor.py --once       # 1회만 실행

장 운영시간(미국 동부 09:30~16:00)에만 동작합니다.
장외 시간에는 자동으로 대기합니다.
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

# Add project root to path
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

# 미국 동부 시간 (ET) = UTC-5 (EST) / UTC-4 (EDT)
ET_OFFSET = timedelta(hours=-5)


def is_market_hours() -> bool:
    """미국 장 운영시간인지 확인 (월~금 09:30~16:00 ET)."""
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc + ET_OFFSET  # 대략적 EST (DST 무시)

    # 주말 제외
    if now_et.weekday() >= 5:
        return False

    # 09:30 ~ 16:00
    market_open = now_et.replace(hour=9, minute=30, second=0, microsecond=0)
    market_close = now_et.replace(hour=16, minute=0, second=0, microsecond=0)

    return market_open <= now_et <= market_close


def is_extended_hours() -> bool:
    """프리마켓/애프터마켓 포함 (08:00~20:00 ET)."""
    now_utc = datetime.now(timezone.utc)
    now_et = now_utc + ET_OFFSET

    if now_et.weekday() >= 5:
        return False

    return 8 <= now_et.hour < 20


def load_config():
    config_path = Path(__file__).parent / "config" / "settings.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def run_check():
    """1회 가격 체크 및 알림."""
    if not is_extended_hours():
        logger.info("⏸️  장외 시간 - 스킵")
        return

    market_status = "🟢 정규장" if is_market_hours() else "🟡 시간외"
    logger.info(f"{market_status} 가격 체크 시작...")

    try:
        config = load_config()
        check_and_notify(config)
        logger.info("✅ 체크 완료")
    except Exception as e:
        logger.error(f"❌ 체크 실패: {e}")


def main():
    parser = argparse.ArgumentParser(description="ETF 가격 모니터링 + 알림")
    parser.add_argument("--interval", type=int, default=5, help="체크 간격 (분, 기본: 5)")
    parser.add_argument("--once", action="store_true", help="1회만 실행")
    parser.add_argument("--force", action="store_true", help="장외 시간에도 실행")
    args = parser.parse_args()

    # Telegram 설정 확인
    notifier = TelegramNotifier()
    if not notifier.is_configured:
        logger.error(
            "❌ Telegram 설정이 필요합니다.\n"
            "   .env 파일에 다음을 추가하세요:\n"
            "   TELEGRAM_BOT_TOKEN=your_token\n"
            "   TELEGRAM_CHAT_ID=your_chat_id"
        )
        sys.exit(1)

    logger.info(f"📊 ETF 가격 모니터 시작 (간격: {args.interval}분)")
    logger.info(f"   Telegram: ✅ 설정됨 (chat_id: {notifier.chat_id})")

    # 1회 실행 모드
    if args.once:
        if args.force or is_extended_hours():
            config = load_config()
            check_and_notify(config)
        else:
            logger.info("장외 시간입니다. --force로 강제 실행할 수 있습니다.")
        return

    # 시작 메시지
    notifier.send_message("📊 <b>ETF 모니터 시작</b>\n\n체크 간격: {args.interval}분")

    # 스케줄 설정
    schedule.every(args.interval).minutes.do(run_check)

    # 첫 실행
    run_check()

    # 루프
    logger.info(f"⏰ {args.interval}분 간격으로 모니터링 중... (Ctrl+C로 종료)")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("🛑 모니터 종료")
        notifier.send_message("🛑 ETF 모니터가 종료되었습니다.")


if __name__ == "__main__":
    main()
