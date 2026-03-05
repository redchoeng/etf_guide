# 🏠 우당탕탕 딩쵱 하우스 마련 대작전

TQQQ 무한매수법에서 영감을 받은 **레버리지 ETF 무한매수 전략** 프로그램입니다.

가격이 하락할수록 더 많이 매수하는 피라미딩 방식으로 최적 매수 가격과 수량을 추천하고, 과거 데이터 기반 백테스트와 실시간 매수 시그널을 제공합니다.

**핵심 철학**: 매수만 하고 익절하지 않는다. 하락할수록 더 많이 사서 평단가를 낮추고, 장기 보유로 복리 효과를 극대화한다.

## 주요 기능

### ⚙️ 그리드 설정
- **4가지 가중치 방식**: 균등, 선형(추천), 지수, 피보나치
- 역사적 최대 낙폭 기반 **자동 간격 계산**
- 레벨별 매수 목표가, 수량, 배정 금액 자동 계산

### 📈 분석
- **낙폭 분석**: 역사적 낙폭 이벤트 탐지 (COVID, 2022 베어마켓 등)
- **회복 기간**: 낙폭 깊이별 평균/최장 회복 소요일
- **변동성**: 연환산 변동성, 샤프 비율, VaR
- **레버리지 디케이**: 기초 지수 대비 실제 수익률 차이

### 🧪 백테스트
- 무한매수법 그리드 전략 시뮬레이션
- **전략 비교**: 그리드 vs 일시 매수 vs 월 적립식(DCA)
- **크래시 시나리오**: COVID, 2022 베어마켓 시뮬레이션

### 📊 매수 시그널
- RSI + SMA + 낙폭 + 그리드 근접도 **복합 점수**
- 매크로 환경(VIX/금리) 연동
- 적극 매수 / 매수 / 관망 / 대기 판정

### 💼 포트폴리오
- 실제 매수 기록 관리 및 평균 단가 추적
- 그리드 진행률 시각화

### 🔔 알림
- Telegram 봇을 통한 매수 시그널 알림
- 그리드 레벨 도달, 급락 알림
- 일일 종합 요약 발송

## 지원 ETF (프리셋)

| 종목 | 이름 | 기초 지수 | 배율 |
|------|------|----------|------|
| QLD | ProShares Ultra QQQ | QQQ | 2x |
| TQQQ | ProShares UltraPro QQQ | QQQ | 3x |
| SSO | ProShares Ultra S&P 500 | SPY | 2x |
| UPRO | ProShares UltraPro S&P 500 | SPY | 3x |
| SOXL | Direxion Semiconductor Bull 3X | SOXX | 3x |
| TECL | Direxion Technology Bull 3X | XLK | 3x |
| FAS | Direxion Financial Bull 3X | XLF | 3x |

사용자가 원하는 ETF 티커를 직접 추가할 수도 있습니다.

## 설치 및 실행

```bash
# 저장소 클론
git clone https://github.com/redchoeng/etf_guide.git
cd etf_guide

# 의존성 설치
pip install -r requirements.txt

# 대시보드 실행
streamlit run dashboard/app.py
```

## Telegram 알림 설정

1. [@BotFather](https://t.me/BotFather)에서 봇을 생성하고 토큰을 받습니다
2. 봇에게 메시지를 보내고, `https://api.telegram.org/bot{TOKEN}/getUpdates`에서 chat_id를 확인합니다
3. `.env` 파일에 설정:

```
TELEGRAM_BOT_TOKEN=your_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
```

## 전략: 무한매수법 v3

| 시장 환경 | 투자비율 | 전략 |
|----------|---------|------|
| 🚀 강한 상승장 | 75% | 시드매수 30% → 풀백 시 그리드 추가매수 → 장기 보유 |
| 📈 상승장 | 70% | 시드매수 30% → 눌림목 그리드 매수 → 장기 보유 |
| ➡️ 횡보장 | 55% | 그리드 레벨 도달 시 매수 + 유휴 현금 DCA |
| 📉 하락장 | 45% | 예비금 55% 유지 + 하위 레벨 위주 매수 |
| 🔥 위기 | 40% | 예비금 60% 유지, 극단적 저점 소량 매수 |

## 라이선스

MIT License
