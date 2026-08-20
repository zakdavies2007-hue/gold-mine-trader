# ============================================
# GOLD MINE TRADER CONFIGURATION
# ============================================

# STOCKS TO MONITOR
STOCKS = ['AAPL', 'MSFT', 'NVDA', 'TSLA']

# PRIMARY STOCK FOR SINGLE SCANS
PRIMARY_STOCK = 'AAPL'

# GOLD MINE DETECTION THRESHOLD (0-1.0)
# Higher = more selective, fewer false signals
GOLD_MINE_THRESHOLD = 0.75

# SCANNING INTERVAL (seconds)
SCAN_INTERVAL = 30

# STARTING CAPITAL (USD)
CAPITAL = 500

# RISK PER TRADE (percentage of capital)
RISK_PER_TRADE = 0.10  # 10%

# ============================================
# TECHNICAL ANALYSIS SETTINGS
# ============================================

# Moving average periods
MA_SHORT = 20
MA_MEDIUM = 50
MA_LONG = 200

# RSI settings
RSI_PERIOD = 14
RSI_OVERBOUGHT = 70
RSI_OVERSOLD = 30

# Volume spike multiplier
VOLUME_SPIKE_MULTIPLIER = 1.5

# ============================================
# SENTIMENT ANALYSIS SETTINGS
# ============================================

# FinBERT model
FINBERT_MODEL = 'yiyanghkust/finbert-tone'

# Sentiment thresholds
SENTIMENT_BULLISH_THRESHOLD = 0.65
SENTIMENT_BEARISH_THRESHOLD = 0.35

# ============================================
# NEWS SETTINGS
# ============================================

# News API
NEWS_API_KEY = "demo"  # Get free key from newsapi.org
NEWS_ARTICLES_TO_FETCH = 3
NEWS_SORT_BY = "publishedAt"

# Catalyst keywords
CATALYST_KEYWORDS = [
    'launch', 'beat', 'earnings', 'partnership', 'deal',
    'upgrade', 'acquisition', 'fda', 'approval', 'profit',
    'revenue', 'record', 'breach', 'ceo', 'patent'
]

# ============================================
# SCORING WEIGHTS
# ============================================

# How much each component affects gold mine score
WEIGHT_SENTIMENT = 0.35
WEIGHT_CATALYST = 0.30
WEIGHT_TECHNICAL = 0.35

# ============================================
# ALPACA TRADING SETTINGS
# ============================================

# Set to True to use real money trading
LIVE_TRADING = False  # START WITH FALSE (paper trading)

# Paper trading (fake money) or live
PAPER_TRADING = True

# Alpaca API credentials (add your own)
ALPACA_API_KEY = ""
ALPACA_SECRET_KEY = ""
ALPACA_BASE_URL = "https://paper-api.alpaca.markets"  # Paper trading

# Order type
ORDER_TYPE = "market"  # Fast execution
TIME_IN_FORCE = "day"

# ============================================
# MONITORING & ALERTS
# ============================================

# Print detailed logs
VERBOSE = True

# Save trades to file
SAVE_TRADES = True
TRADES_FILE = "trades.csv"

# Email alerts (optional)
EMAIL_ALERTS = False
EMAIL_ADDRESS = ""

# ============================================
# PERFORMANCE TARGETS
# ============================================

# Expected monthly return
TARGET_MONTHLY_RETURN = 0.05  # 5%

# Maximum monthly loss
MAX_MONTHLY_LOSS = -0.10  # -10%

# Win rate target
TARGET_WIN_RATE = 0.65  # 65%

# ============================================
# DATA SETTINGS
# ============================================

# Date range for historical data
START_DATE = "2024-01-01"

# Cache interval (seconds)
CACHE_INTERVAL = 60

# Timeout for API calls
API_TIMEOUT = 5

# ============================================
# SYSTEM SETTINGS
# ============================================

# Use GPU if available
USE_GPU = True

# Number of parallel workers
MAX_WORKERS = 4

# Logging level
LOG_LEVEL = "INFO"  # INFO, DEBUG, WARNING, ERROR
