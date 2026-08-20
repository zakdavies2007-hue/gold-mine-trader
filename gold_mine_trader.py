from __future__ import annotations

import importlib
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, List, Optional

import numpy as np
import requests
import yfinance as yf

from market_research import MarketResearch

LOGGER = logging.getLogger(__name__)


def _load_config_module():
    for name in ('config_advanced', 'config'):
        try:
            return importlib.import_module(name)
        except ModuleNotFoundError:
            continue
    raise ModuleNotFoundError('Expected config.py or config_advanced.py to be available')


_CFG = _load_config_module()
STOCKS = list(getattr(_CFG, 'STOCKS', ['AAPL', 'MSFT', 'NVDA', 'TSLA']))
PRIMARY_STOCK = getattr(_CFG, 'PRIMARY_STOCK', 'AAPL')
GOLD_MINE_THRESHOLD = float(getattr(_CFG, 'GOLD_MINE_THRESHOLD', 0.75))
MA_SHORT = int(getattr(_CFG, 'MA_SHORT', 20))
MA_MEDIUM = int(getattr(_CFG, 'MA_MEDIUM', 50))
MA_LONG = int(getattr(_CFG, 'MA_LONG', 200))
RSI_PERIOD = int(getattr(_CFG, 'RSI_PERIOD', 14))
VOLUME_SPIKE_MULTIPLIER = float(getattr(_CFG, 'VOLUME_SPIKE_MULTIPLIER', 1.5))
WEIGHT_SENTIMENT = float(getattr(_CFG, 'WEIGHT_SENTIMENT', 0.35))
WEIGHT_CATALYST = float(getattr(_CFG, 'WEIGHT_CATALYST', 0.30))
WEIGHT_TECHNICAL = float(getattr(_CFG, 'WEIGHT_TECHNICAL', 0.35))
CATALYST_KEYWORDS = list(getattr(_CFG, 'CATALYST_KEYWORDS', []))
NEWS_API_KEY = getattr(_CFG, 'NEWS_API_KEY', 'demo')
NEWS_ARTICLES_TO_FETCH = int(getattr(_CFG, 'NEWS_ARTICLES_TO_FETCH', 3))
NEWS_SORT_BY = getattr(_CFG, 'NEWS_SORT_BY', 'publishedAt')
START_DATE = getattr(_CFG, 'START_DATE', '2024-01-01')
API_TIMEOUT = int(getattr(_CFG, 'API_TIMEOUT', 5))
CACHE_INTERVAL = int(getattr(_CFG, 'CACHE_INTERVAL', 60))
FINBERT_MODEL = getattr(_CFG, 'FINBERT_MODEL', 'yiyanghkust/finbert-tone')


class GoldMineTrader:
    """Production-friendly detector extracted from the notebook with the same public API."""

    def __init__(
        self,
        symbol: str = PRIMARY_STOCK,
        sentiment_analyzer: Optional[Callable[[List[str]], Iterable[Any]]] = None,
        session: Optional[requests.Session] = None,
        research: Optional[MarketResearch] = None,
    ):
        self.symbol = symbol
        self.data_cache: Dict[str, Any] = {}
        self.cache_timestamps: Dict[str, float] = {}
        self.session = session or requests.Session()
        self.research = research or MarketResearch()
        self._sentiment = sentiment_analyzer

    def _ensure_sentiment(self):
        if self._sentiment is not None:
            return self._sentiment
        if os.getenv('DISABLE_FINBERT', '').lower() in {'1', 'true', 'yes'}:
            self._sentiment = lambda texts: [[{'label': 'neutral', 'score': 0.5}] for _ in texts]
            return self._sentiment
        try:
            import torch
            from transformers import pipeline

            device = 0 if torch.cuda.is_available() else -1
            self._sentiment = pipeline('sentiment-analysis', model=FINBERT_MODEL, device=device)
        except Exception as exc:  # pragma: no cover - depends on optional model runtime
            LOGGER.warning('Falling back to neutral sentiment because FinBERT was unavailable: %s', exc)
            self._sentiment = lambda texts: [[{'label': 'neutral', 'score': 0.5}] for _ in texts]
        return self._sentiment

    def get_price_data(self, symbol: Optional[str] = None):
        symbol = symbol or self.symbol
        now = time.time()
        if symbol in self.data_cache and (now - self.cache_timestamps.get(symbol, 0)) < CACHE_INTERVAL:
            return self.data_cache[symbol]

        last_error = None
        for delay in (0, 1, 2):
            if delay:
                time.sleep(delay)
            try:
                data = yf.download(symbol, start=START_DATE, progress=False, auto_adjust=False)
                if data is not None and not data.empty:
                    self.data_cache[symbol] = data
                    self.cache_timestamps[symbol] = now
                return data
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = exc
        if last_error:
            LOGGER.warning('Unable to fetch price data for %s: %s', symbol, last_error)
        return None

    def get_news(self, symbol: Optional[str] = None):
        symbol = symbol or self.symbol
        if not NEWS_API_KEY or NEWS_API_KEY == 'demo':
            return []

        params = {
            'q': symbol,
            'sortBy': NEWS_SORT_BY,
            'language': 'en',
            'pageSize': NEWS_ARTICLES_TO_FETCH,
            'apiKey': NEWS_API_KEY,
        }
        last_error = None
        for delay in (0, 1, 2):
            if delay:
                time.sleep(delay)
            try:
                response = self.session.get('https://newsapi.org/v2/everything', params=params, timeout=API_TIMEOUT)
                response.raise_for_status()
                return response.json().get('articles', [])
            except Exception as exc:  # pragma: no cover - network dependent
                last_error = exc
        if last_error:
            LOGGER.warning('Unable to fetch news for %s: %s', symbol, last_error)
        return []

    def analyze_sentiment(self, news_items: List[Dict[str, Any]]) -> float:
        if not news_items:
            return 0.5
        texts = []
        for article in news_items:
            title = article.get('title') or ''
            description = article.get('description') or ''
            texts.append(f'{title}. {description}'[:512])
        try:
            results = self._ensure_sentiment()(texts)
            scores = []
            for result in results:
                payload = result[0] if isinstance(result, list) else result
                score = float(payload.get('score', 0.5))
                label = str(payload.get('label', 'neutral')).lower()
                if label == 'positive':
                    scores.append(score)
                elif label == 'negative':
                    scores.append(1 - score)
                else:
                    scores.append(0.5)
            return float(np.mean(scores)) if scores else 0.5
        except Exception as exc:
            LOGGER.warning('Unable to analyze sentiment, using neutral score: %s', exc)
            return 0.5

    def detect_catalysts(self, news_items: List[Dict[str, Any]]) -> int:
        if not news_items:
            return 0
        count = 0
        for article in news_items:
            text = f"{article.get('title', '')} {article.get('description', '')}".lower()
            if any(keyword in text for keyword in CATALYST_KEYWORDS):
                count += 1
        return count

    def calculate_technical_score(self, data) -> float:
        if data is None or len(data) < MA_LONG:
            return 0.5
        close = data['Close']
        score = 0.0
        ma_short = close.rolling(MA_SHORT).mean().iloc[-1]
        ma_medium = close.rolling(MA_MEDIUM).mean().iloc[-1]
        ma_long = close.rolling(MA_LONG).mean().iloc[-1]
        current_price = close.iloc[-1]

        if current_price > ma_short:
            score += 0.15
        if current_price > ma_medium:
            score += 0.15
        if current_price > ma_long:
            score += 0.10

        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(RSI_PERIOD).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(RSI_PERIOD).mean()
        rs = gain / loss.replace(0, np.nan)
        rsi = (100 - (100 / (1 + rs))).iloc[-1]
        if np.isfinite(rsi) and 30 < rsi < 70:
            score += 0.20

        volume = data['Volume'] if 'Volume' in data else None
        if volume is not None:
            vol_avg = volume.rolling(MA_SHORT).mean().iloc[-1]
            vol_ratio = (volume.iloc[-1] / vol_avg) if vol_avg else 1.0
            if vol_ratio > VOLUME_SPIKE_MULTIPLIER:
                score += 0.25

        if len(close) >= 5 and current_price > close.iloc[-5]:
            score += 0.15
        return min(score, 1.0)

    def scan_for_gold_mine(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        symbol = symbol or self.symbol
        with ThreadPoolExecutor(max_workers=2) as executor:
            price_future = executor.submit(self.get_price_data, symbol)
            news_future = executor.submit(self.get_news, symbol)
            price_data = price_future.result(timeout=API_TIMEOUT + 2)
            news_items = news_future.result(timeout=API_TIMEOUT + 2)

        with ThreadPoolExecutor(max_workers=3) as executor:
            sentiment_future = executor.submit(self.analyze_sentiment, news_items)
            catalysts_future = executor.submit(self.detect_catalysts, news_items)
            technical_future = executor.submit(self.calculate_technical_score, price_data)
            sentiment = sentiment_future.result()
            catalysts = catalysts_future.result()
            technical = technical_future.result()

        catalyst_component = min(catalysts * 0.33, 1.0)
        score = (
            sentiment * WEIGHT_SENTIMENT
            + catalyst_component * WEIGHT_CATALYST
            + technical * WEIGHT_TECHNICAL
        )
        research = self.research.analyze(price_data)
        last_price = float(price_data['Close'].iloc[-1]) if price_data is not None and not price_data.empty else 0.0
        return {
            'symbol': symbol,
            'gold_mine_score': score,
            'sentiment': sentiment,
            'catalysts': catalysts,
            'technical': technical,
            'is_gold_mine': score >= GOLD_MINE_THRESHOLD,
            'price': last_price,
            'research': research,
            'timestamp': datetime.utcnow().isoformat() + 'Z',
        }

    def scan_multiple_stocks(self, symbols: Optional[Iterable[str]] = None) -> Dict[str, Dict[str, Any]]:
        symbols = list(symbols or STOCKS)
        results: Dict[str, Dict[str, Any]] = {}
        with ThreadPoolExecutor(max_workers=max(1, len(symbols))) as executor:
            futures = {executor.submit(self.scan_for_gold_mine, symbol): symbol for symbol in symbols}
            for future in as_completed(futures):
                symbol = futures[future]
                try:
                    results[symbol] = future.result()
                except Exception as exc:
                    LOGGER.warning('Scan failed for %s: %s', symbol, exc)
        return results

    def print_result(self, result: Dict[str, Any]):
        score = result['gold_mine_score']
        print(f"\n{'=' * 60}")
        print('🚀 GOLD MINE DETECTED!' if result['is_gold_mine'] else '⏳ NOT A GOLD MINE')
        print(f"{'=' * 60}")
        print(f"Stock:           {result['symbol']}")
        print(f"Price:           ${result['price']:.2f}")
        print(f"Gold Mine Score: {score:.2f}/1.00")
        print('Research Metrics:')
        for key, value in result.get('research', {}).items():
            print(f'  {key:14} {value:.4f}')
        print(f"{'=' * 60}\n")
