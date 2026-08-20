import os
from dotenv import load_dotenv

load_dotenv()

# ============================================
# CORE TRADING SETTINGS
# ============================================

STOCKS = ['AAPL', 'MSFT', 'NVDA', 'TSLA']
PRIMARY_STOCK = 'AAPL'
GOLD_MINE_THRESHOLD = 0.75
SCAN_INTERVAL = 30  # seconds
STARTING_CAPITAL = 500

# ============================================
# POSITION MANAGEMENT
# ============================================

RISK_PER_TRADE = 0.10  # 10% of capital per trade
STOP_LOSS_PERCENT = 0.05  # -5%
TAKE_PROFIT_PERCENT = 0.15  # +15%
MAX_POSITION_SIZE = 0.20  # Max 20% of capital in one trade
MAX_ACTIVE_POSITIONS = 5  # Max 5 open trades at once
POSITION_HOLD_TIME = 86400  # 24 hours (in seconds)

# ============================================
# TECHNICAL ANALYSIS
# ============================================

MA_SHORT = 20
MA_MEDIUM = 50
MA_LONG = 200
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30
VOLUME_SPIKE_MULTIPLIER = 1.5

# ============================================
# SENTIMENT ANALYSIS
# ============================================

FINBERT_MODEL = 'yiyanghkust/finbert-tone'
SENTIMENT_BULLISH_THRESHOLD = 0.65
SENTIMENT_BEARISH_THRESHOLD = 0.35

# ============================================
# NEWS & CATALYSTS
# ============================================

NEWS_API_KEY = os.getenv('NEWS_API_KEY', 'demo')
NEWS_ARTICLES_TO_FETCH = 5
NEWS_SORT_BY = 'publishedAt'

CATALYST_KEYWORDS = [
    'launch', 'beat', 'earnings', 'partnership', 'deal',
    'upgrade', 'acquisition', 'fda', 'approval', 'profit',
    'revenue', 'record', 'breakthrough', 'innovation', 'patent'
]

# ============================================
# SCORING WEIGHTS
# ============================================

WEIGHT_SENTIMENT = 0.35
WEIGHT_CATALYST = 0.30
WEIGHT_TECHNICAL = 0.35

# ============================================
# ALPACA BROKER (LIVE TRADING)
# ============================================

ALPACA_API_KEY = os.getenv('ALPACA_API_KEY', '')
ALPACA_SECRET_KEY = os.getenv('ALPACA_SECRET_KEY', '')
ALPACA_BASE_URL = os.getenv('ALPACA_BASE_URL', 'https://paper-api.alpaca.markets')

# Paper trading (fake money) vs Live (real money)
PAPER_TRADING = True  # Set to False for real money
LIVE_TRADING = False  # Set to True for real money

# Order execution
ORDER_TYPE = 'market'
TIME_IN_FORCE = 'day'
EXECUTION_DELAY = 0  # seconds to delay execution (for safety testing)

# ============================================
# ALERTS & NOTIFICATIONS
# ============================================

# Email
EMAIL_ALERTS = True
EMAIL_ADDRESS = os.getenv('EMAIL_ADDRESS', '')
EMAIL_PASSWORD = os.getenv('EMAIL_PASSWORD', '')
SMTP_SERVER = 'smtp.gmail.com'
SMTP_PORT = 587

# Discord Webhook
DISCORD_WEBHOOK = os.getenv('DISCORD_WEBHOOK', '')
DISCORD_ALERTS = True

# Telegram Bot
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID', '')
TELEGRAM_ALERTS = True

# SMS (Twilio)
TWILIO_ACCOUNT_SID = os.getenv('TWILIO_ACCOUNT_SID', '')
TWILIO_AUTH_TOKEN = os.getenv('TWILIO_AUTH_TOKEN', '')
TWILIO_PHONE = os.getenv('TWILIO_PHONE', '')
SMS_ALERTS = False

# ============================================
# DASHBOARD & REPORTING
# ============================================

DASHBOARD_PORT = 5000
DASHBOARD_HOST = '0.0.0.0'
DASHBOARD_UPDATE_INTERVAL = 5  # seconds

# Performance tracking
SAVE_TRADES = True
TRADES_FILE = 'trades.csv'
PERFORMANCE_LOG = 'performance.csv'
DATABASE_URL = os.getenv('DATABASE_URL', 'sqlite:///trading.db')

# ============================================
# MARKET ANALYSIS
# ============================================

# Price volatility analysis
VOLATILITY_WINDOW = 20  # days
VOLATILITY_THRESHOLD = 0.02  # 2% daily

# Trend analysis
TREND_WINDOW = 50  # days
TREND_STRENGTH_THRESHOLD = 0.05  # 5%

# Support/Resistance
SR_LOOKBACK = 100  # days

# ============================================
# MONITORING & LOGGING
# ============================================

VERBOSE = True
LOG_LEVEL = 'INFO'  # INFO, DEBUG, WARNING, ERROR
LOG_FILE = 'trader.log'

# Performance targets
TARGET_MONTHLY_RETURN = 0.08  # 8%
MAX_MONTHLY_LOSS = -0.10  # -10%
TARGET_WIN_RATE = 0.65  # 65%

# ============================================
# DATA SETTINGS
# ============================================

START_DATE = '2024-01-01'
CACHE_INTERVAL = 60  # seconds
API_TIMEOUT = 5  # seconds

# ============================================
# SYSTEM SETTINGS
# ============================================

USE_GPU = True
MAX_WORKERS = 4

# Market hours (EST)
MARKET_OPEN = 9.5  # 9:30 AM
MARKET_CLOSE = 16.0  # 4:00 PM
TRADING_DAYS = [0, 1, 2, 3, 4]  # Monday-Friday (0-4)

# Restart settings
AUTO_RESTART_ON_ERROR = True
RESTART_DELAY = 60  # seconds

# ============================================
# SAFETY SETTINGS
# ============================================

# Disable trading during testing
DRY_RUN = False  # Set to True to test without real trades

# Maximum daily loss before stopping
MAX_DAILY_LOSS_PERCENT = -0.20  # -20%

# Circuit breaker
CIRCUIT_BREAKER_LOSSES = 3  # Stop after 3 consecutive losses
CIRCUIT_BREAKER_ENABLED = True

# ============================================
# ADVANCED SETTINGS
# ============================================

# Multi-timeframe analysis
USE_MULTI_TIMEFRAME = True
TIMEFRAMES = ['1min', '5min', '15min', '1h', '1d']

# Machine learning model updates
ML_RETRAIN_INTERVAL = 604800  # 1 week (in seconds)
ML_VALIDATION_SPLIT = 0.2

# Portfolio rebalancing
REBALANCE_INTERVAL = 86400  # 1 day (in seconds)
TARGET_ALLOCATION = {
    'AAPL': 0.25,
    'MSFT': 0.25,
    'NVDA': 0.25,
    'TSLA': 0.25
}
