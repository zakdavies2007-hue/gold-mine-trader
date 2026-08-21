"""
gold_mine_trader.py – Gold Mine Detector

Detects high-probability trading opportunities using:
  1. Price / technical data (yfinance)
  2. News sentiment (NewsAPI + FinBERT)
  3. Catalyst keyword scoring

Degraded mode
-------------
When optional providers (NewsAPI, FinBERT) are unavailable the detector
continues to run but *degraded results are ineligible for execution*.
Degraded results carry ``eligible=False`` and a non-empty ``degraded_providers``
list so callers can distinguish them from genuine low-score results.
"""

from __future__ import annotations

import logging
import math
import os
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeout
from datetime import datetime, timezone
from typing import Any, NamedTuple

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (read once at import; tests can monkeypatch at module level)
# ---------------------------------------------------------------------------
try:
    import config_advanced as _ca  # type: ignore[import]
    _FINBERT_MODEL: str = getattr(_ca, "FINBERT_MODEL", "yiyanghkust/finbert-tone")
    _NEWS_ARTICLES: int = getattr(_ca, "NEWS_ARTICLES_TO_FETCH", 3)
    _CATALYST_KW: list[str] = list(getattr(_ca, "CATALYST_KEYWORDS", []))
    _W_SENTIMENT: float = getattr(_ca, "WEIGHT_SENTIMENT", 0.35)
    _W_CATALYST: float = getattr(_ca, "WEIGHT_CATALYST", 0.30)
    _W_TECHNICAL: float = getattr(_ca, "WEIGHT_TECHNICAL", 0.35)
    _MA_SHORT: int = getattr(_ca, "MA_SHORT", 20)
    _MA_LONG: int = getattr(_ca, "MA_LONG", 200)
    _RSI_PERIOD: int = getattr(_ca, "RSI_PERIOD", 14)
    _RSI_OB: float = getattr(_ca, "RSI_OVERBOUGHT", 70)
    _RSI_OS: float = getattr(_ca, "RSI_OVERSOLD", 30)
    _VOL_MULT: float = getattr(_ca, "VOLUME_SPIKE_MULTIPLIER", 1.5)
    _API_TIMEOUT: int = getattr(_ca, "API_TIMEOUT", 5)
    _CACHE_INTERVAL: int = getattr(_ca, "CACHE_INTERVAL", 60)
    _MAX_WORKERS: int = getattr(_ca, "MAX_WORKERS", 4)
except Exception:
    _FINBERT_MODEL = "yiyanghkust/finbert-tone"
    _NEWS_ARTICLES = 3
    _CATALYST_KW = [
        "launch", "beat", "earnings", "partnership", "deal",
        "upgrade", "acquisition", "fda", "approval", "profit",
        "revenue", "record", "breakthrough", "innovation", "patent",
    ]
    _W_SENTIMENT, _W_CATALYST, _W_TECHNICAL = 0.35, 0.30, 0.35
    _MA_SHORT, _MA_LONG = 20, 200
    _RSI_PERIOD, _RSI_OB, _RSI_OS = 14, 70, 30
    _VOL_MULT = 1.5
    _API_TIMEOUT = 5
    _CACHE_INTERVAL = 60
    _MAX_WORKERS = 4

_DEFAULT_CATALYST_KW = _CATALYST_KW or [
    "launch", "beat", "earnings", "partnership", "deal",
    "upgrade", "acquisition", "fda", "approval", "profit",
    "revenue", "record", "breakthrough", "innovation", "patent",
]


def _validate_weights(w_sent: float, w_cat: float, w_tech: float) -> None:
    for name, w in [("WEIGHT_SENTIMENT", w_sent), ("WEIGHT_CATALYST", w_cat),
                    ("WEIGHT_TECHNICAL", w_tech)]:
        if not (0 <= w <= 1):
            raise ValueError(f"{name}={w} must be in [0, 1]")
    total = w_sent + w_cat + w_tech
    if not math.isclose(total, 1.0, abs_tol=1e-6):
        raise ValueError(f"Weights must sum to 1.0; got {total}")


_validate_weights(_W_SENTIMENT, _W_CATALYST, _W_TECHNICAL)


# ---------------------------------------------------------------------------
# Lightweight cache
# ---------------------------------------------------------------------------

class _Cache:
    def __init__(self, ttl: int = 60) -> None:
        self._store: dict[str, tuple[float, Any]] = {}
        self._ttl = ttl

    def get(self, key: str) -> Any | None:
        import time
        entry = self._store.get(key)
        if entry is None:
            return None
        ts, value = entry
        if time.time() - ts > self._ttl:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any) -> None:
        import time
        self._store[key] = (time.time(), value)


_price_cache = _Cache(ttl=_CACHE_INTERVAL)

# ---------------------------------------------------------------------------
# Result types
# ---------------------------------------------------------------------------


class DetectorResult(NamedTuple):
    symbol: str
    score: float
    eligible: bool          # False means degraded → never execute
    degraded_providers: list[str]
    sentiment_score: float
    catalyst_score: float
    technical_score: float
    catalyst_count: int
    latest_price: float
    timestamp: str
    metadata: dict


class GoldMineResult(NamedTuple):
    """Returned by scan_for_gold_mine / scan_multiple_stocks."""
    symbol: str
    is_gold_mine: bool
    score: float
    eligible: bool
    degraded_providers: list[str]
    sentiment_score: float
    catalyst_score: float
    technical_score: float
    catalyst_count: int
    latest_price: float
    timestamp: str
    metadata: dict


# ---------------------------------------------------------------------------
# Price-data retrieval
# ---------------------------------------------------------------------------

def get_price_data(
    symbol: str,
    period: str = "1y",
    interval: str = "1d",
    timeout: int | None = None,
) -> pd.DataFrame | None:
    """Download OHLCV data via yfinance.  Returns None on failure.

    Results are cached for CACHE_INTERVAL seconds.
    """
    cache_key = f"{symbol}:{period}:{interval}"
    cached = _price_cache.get(cache_key)
    if cached is not None:
        return cached

    try:
        import yfinance as yf
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            df = yf.download(
                symbol,
                period=period,
                interval=interval,
                progress=False,
                auto_adjust=True,
            )
        if df is None or df.empty:
            log.warning("No price data returned for %s", symbol)
            return None
        # Flatten MultiIndex columns if present (yfinance ≥ 0.2.28)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        df = df.rename(columns=str.lower)
        _price_cache.set(cache_key, df)
        return df
    except Exception as exc:
        log.error("Price data error for %s: %s", symbol, exc)
        return None


# ---------------------------------------------------------------------------
# News retrieval
# ---------------------------------------------------------------------------

def get_news(
    symbol: str,
    api_key: str,
    n_articles: int | None = None,
    timeout: int | None = None,
) -> list[dict]:
    """Fetch recent news from NewsAPI.  Returns [] on any failure."""
    if not api_key or api_key.lower() == "demo":
        log.debug("NEWS_API_KEY not set; skipping news fetch for %s", symbol)
        return []
    n = n_articles or _NEWS_ARTICLES
    t = timeout or _API_TIMEOUT
    try:
        import requests
        # Use POST-like params to avoid API key in log-visible URL path
        url = "https://newsapi.org/v2/everything"
        params = {
            "q": symbol,
            "apiKey": api_key,
            "sortBy": "publishedAt",
            "pageSize": n,
            "language": "en",
        }
        resp = requests.get(url, params=params, timeout=t)
        resp.raise_for_status()
        data = resp.json()
        return data.get("articles", [])[:n]
    except Exception as exc:
        log.warning("News fetch failed for %s: %s", symbol, exc)
        return []


# ---------------------------------------------------------------------------
# Sentiment analysis
# ---------------------------------------------------------------------------

_finbert_pipeline = None
_finbert_failed = False


def _load_finbert(model_name: str) -> Any | None:
    global _finbert_pipeline, _finbert_failed
    if _finbert_failed:
        return None
    if _finbert_pipeline is not None:
        return _finbert_pipeline
    try:
        from transformers import pipeline as hf_pipeline
        import torch
        device = 0 if torch.cuda.is_available() else -1
        _finbert_pipeline = hf_pipeline(
            "text-classification",
            model=model_name,
            device=device,
            truncation=True,
            max_length=512,
        )
        log.info("FinBERT loaded (device=%s)", "cuda" if device == 0 else "cpu")
        return _finbert_pipeline
    except Exception as exc:
        log.warning("FinBERT unavailable: %s", exc)
        _finbert_failed = True
        return None


def analyze_sentiment(
    texts: list[str],
    model_name: str | None = None,
    disable_finbert: bool = False,
) -> tuple[float, bool]:
    """Return (sentiment_score, degraded).

    sentiment_score: 0..1 where >0.5 is bullish.
    degraded: True when FinBERT was unavailable (score is 0.5 neutral fallback).
    """
    if not texts:
        return 0.5, False  # neutral, not degraded (no news is not an error)

    if disable_finbert or os.environ.get("DISABLE_FINBERT", "").lower() in ("1", "true", "yes"):
        return 0.5, True

    pipe = _load_finbert(model_name or _FINBERT_MODEL)
    if pipe is None:
        return 0.5, True

    scores = []
    for text in texts:
        if not text or not text.strip():
            continue
        try:
            result = pipe(text[:512])
            label = result[0]["label"].lower()
            conf = float(result[0]["score"])
            if label == "positive":
                scores.append(conf)
            elif label == "negative":
                scores.append(1.0 - conf)
            else:
                scores.append(0.5)
        except Exception as exc:
            log.debug("FinBERT inference error: %s", exc)
    if not scores:
        return 0.5, False
    return float(np.mean(scores)), False


# ---------------------------------------------------------------------------
# Catalyst detection
# ---------------------------------------------------------------------------

def detect_catalysts(
    articles: list[dict],
    keywords: list[str] | None = None,
) -> tuple[float, int]:
    """Return (catalyst_score 0..1, catalyst_count).

    Scores based on whole-word keyword matches in title+description.
    """
    kw = [k.lower() for k in (keywords or _DEFAULT_CATALYST_KW)]
    count = 0
    for article in articles:
        text = " ".join([
            str(article.get("title") or ""),
            str(article.get("description") or ""),
        ]).lower()
        for keyword in kw:
            # Whole-word match using word boundaries
            import re
            if re.search(r"\b" + re.escape(keyword) + r"\b", text):
                count += 1
                break  # count once per article
    if not articles:
        return 0.0, 0
    score = min(count / max(len(articles), 1), 1.0)
    return score, count


# ---------------------------------------------------------------------------
# Technical scoring
# ---------------------------------------------------------------------------

def calculate_technical_score(df: pd.DataFrame) -> tuple[float, bool]:
    """Compute a composite technical score (0..1).

    Returns (score, degraded).  degraded=True when insufficient data.
    """
    if df is None or df.empty or len(df) < 2:
        return 0.5, True  # neutral fallback, degraded

    try:
        closes = df["close"].astype(float)
        volumes = df["volume"].astype(float)

        # Replace non-finite values
        closes = closes.replace([np.inf, -np.inf], np.nan).dropna()
        volumes = volumes.replace([np.inf, -np.inf], np.nan).fillna(0)

        if closes.empty or not math.isfinite(float(closes.iloc[-1])):
            return 0.5, True

        latest = float(closes.iloc[-1])
        score_parts: list[float] = []

        # --- Moving-average trend ---
        if len(closes) >= _MA_SHORT:
            ma_short = float(closes.tail(_MA_SHORT).mean())
            if math.isfinite(ma_short) and ma_short > 0:
                score_parts.append(1.0 if latest > ma_short else 0.0)

        if len(closes) >= _MA_LONG:
            ma_long = float(closes.tail(_MA_LONG).mean())
            if math.isfinite(ma_long) and ma_long > 0:
                score_parts.append(1.0 if latest > ma_long else 0.0)

        # --- RSI ---
        if len(closes) >= _RSI_PERIOD + 1:
            deltas = closes.diff().dropna().tail(_RSI_PERIOD)
            gains = deltas.clip(lower=0)
            losses = (-deltas).clip(lower=0)
            avg_gain = float(gains.mean())
            avg_loss = float(losses.mean())
            if avg_loss == 0:
                rsi = 100.0
            else:
                rs = avg_gain / avg_loss
                rsi = 100 - (100 / (1 + rs))
            if math.isfinite(rsi):
                # Score: oversold (30) → 1.0, overbought (70) → 0.0
                if rsi <= _RSI_OS:
                    score_parts.append(1.0)
                elif rsi >= _RSI_OB:
                    score_parts.append(0.0)
                else:
                    score_parts.append((_RSI_OB - rsi) / (_RSI_OB - _RSI_OS))

        # --- Volume spike ---
        if len(volumes) >= 2:
            current_vol = float(volumes.iloc[-1])
            avg_vol = float(volumes.iloc[:-1].tail(20).mean())
            if avg_vol > 0 and math.isfinite(current_vol / avg_vol):
                ratio = current_vol / avg_vol
                score_parts.append(min(ratio / (_VOL_MULT * 2), 1.0))

        if not score_parts:
            return 0.5, True

        return float(np.mean(score_parts)), False

    except Exception as exc:
        log.warning("Technical score error: %s", exc)
        return 0.5, True


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------


class GoldMineTrader:
    """High-level detector.  All public methods return structured results."""

    def __init__(
        self,
        news_api_key: str = "",
        model_name: str | None = None,
        disable_finbert: bool = False,
        threshold: float = 0.75,
        w_sentiment: float = _W_SENTIMENT,
        w_catalyst: float = _W_CATALYST,
        w_technical: float = _W_TECHNICAL,
        catalyst_keywords: list[str] | None = None,
        max_workers: int | None = None,
    ) -> None:
        _validate_weights(w_sentiment, w_catalyst, w_technical)
        self.news_api_key = news_api_key
        self.model_name = model_name or _FINBERT_MODEL
        self.disable_finbert = disable_finbert
        self.threshold = threshold
        self.w_sentiment = w_sentiment
        self.w_catalyst = w_catalyst
        self.w_technical = w_technical
        self.catalyst_keywords = catalyst_keywords or _DEFAULT_CATALYST_KW
        self.max_workers = max_workers or _MAX_WORKERS

    # ------------------------------------------------------------------
    # Public API (notebook-compatible names preserved)
    # ------------------------------------------------------------------

    def get_price_data(self, symbol: str, period: str = "1y") -> pd.DataFrame | None:
        return get_price_data(symbol, period=period)

    def get_news(self, symbol: str, n_articles: int | None = None) -> list[dict]:
        return get_news(symbol, self.news_api_key, n_articles)

    def analyze_sentiment(self, texts: list[str]) -> tuple[float, bool]:
        return analyze_sentiment(texts, self.model_name, self.disable_finbert)

    def detect_catalysts(self, articles: list[dict]) -> tuple[float, int]:
        return detect_catalysts(articles, self.catalyst_keywords)

    def calculate_technical_score(self, df: pd.DataFrame) -> tuple[float, bool]:
        return calculate_technical_score(df)

    def get_research_metrics(self, symbol: str) -> dict:
        """Return MarketResearch metrics for *symbol*."""
        from market_research import MarketResearch
        df = get_price_data(symbol)
        if df is None or df.empty:
            return {}
        try:
            return MarketResearch().analyse(df)
        except Exception as exc:
            log.warning("MarketResearch error for %s: %s", symbol, exc)
            return {}

    def scan_for_gold_mine(self, symbol: str) -> GoldMineResult:
        """Scan a single symbol and return a structured result."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        degraded: list[str] = []
        metadata: dict = {}

        # --- Price data ---
        df = get_price_data(symbol)
        if df is None or df.empty:
            degraded.append("price_data")
            return GoldMineResult(
                symbol=symbol,
                is_gold_mine=False,
                score=0.0,
                eligible=False,
                degraded_providers=degraded,
                sentiment_score=0.5,
                catalyst_score=0.0,
                technical_score=0.0,
                catalyst_count=0,
                latest_price=0.0,
                timestamp=ts,
                metadata={"error": "price_data_unavailable"},
            )

        closes = df["close"].replace([np.inf, -np.inf], np.nan).dropna()
        latest_price = float(closes.iloc[-1]) if not closes.empty else 0.0
        if not math.isfinite(latest_price) or latest_price <= 0:
            degraded.append("price_data")
            latest_price = 0.0

        # --- Technical score ---
        tech_score, tech_degraded = calculate_technical_score(df)
        if tech_degraded:
            degraded.append("technical")

        # --- News & sentiment ---
        articles = get_news(symbol, self.news_api_key)
        texts = [
            " ".join(filter(None, [a.get("title"), a.get("description")]))
            for a in articles
        ]
        sent_score, sent_degraded = analyze_sentiment(texts, self.model_name, self.disable_finbert)
        if sent_degraded:
            degraded.append("sentiment")

        # --- Catalysts ---
        cat_score, cat_count = detect_catalysts(articles, self.catalyst_keywords)

        # --- Composite score ---
        score = (
            self.w_sentiment * sent_score
            + self.w_catalyst * cat_score
            + self.w_technical * tech_score
        )
        if not math.isfinite(score):
            score = 0.0

        # Eligible only when no providers are degraded AND price is valid
        eligible = (
            len(degraded) == 0
            and latest_price > 0
        )

        is_gold_mine = eligible and score >= self.threshold

        metadata["articles_fetched"] = len(articles)
        metadata["technical_degraded"] = tech_degraded

        return GoldMineResult(
            symbol=symbol,
            is_gold_mine=is_gold_mine,
            score=score,
            eligible=eligible,
            degraded_providers=list(degraded),
            sentiment_score=sent_score,
            catalyst_score=cat_score,
            technical_score=tech_score,
            catalyst_count=cat_count,
            latest_price=latest_price,
            timestamp=ts,
            metadata=metadata,
        )

    def scan_multiple_stocks(
        self,
        symbols: list[str],
        max_workers: int | None = None,
    ) -> list[GoldMineResult]:
        """Scan multiple symbols in parallel; preserve input order."""
        workers = min(max_workers or self.max_workers, len(symbols))
        results: dict[str, GoldMineResult] = {}

        with ThreadPoolExecutor(max_workers=max(workers, 1)) as executor:
            futures = {
                executor.submit(self.scan_for_gold_mine, sym): sym
                for sym in symbols
            }
            for fut in as_completed(futures):
                sym = futures[fut]
                try:
                    results[sym] = fut.result(timeout=60)
                except FuturesTimeout:
                    log.warning("Scan timed out for %s", sym)
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    results[sym] = GoldMineResult(
                        symbol=sym, is_gold_mine=False, score=0.0, eligible=False,
                        degraded_providers=["timeout"], sentiment_score=0.5,
                        catalyst_score=0.0, technical_score=0.0, catalyst_count=0,
                        latest_price=0.0, timestamp=ts,
                        metadata={"error": "scan_timeout"},
                    )
                except Exception as exc:
                    log.error("Scan failed for %s: %s", sym, exc)
                    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    results[sym] = GoldMineResult(
                        symbol=sym, is_gold_mine=False, score=0.0, eligible=False,
                        degraded_providers=["error"], sentiment_score=0.5,
                        catalyst_score=0.0, technical_score=0.0, catalyst_count=0,
                        latest_price=0.0, timestamp=ts,
                        metadata={"error": str(exc)},
                    )
        # Return in input order
        return [results[s] for s in symbols if s in results]
