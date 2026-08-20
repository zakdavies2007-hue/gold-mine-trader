import unittest

from market_research import MarketResearch


class MarketResearchTests(unittest.TestCase):
    def test_analyze_returns_expected_keys(self):
        data = {
            'Close': [100 + value for value in range(60)],
            'Volume': [1000 + (value * 10) for value in range(60)],
            'Low': [99 + value for value in range(60)],
            'High': [101 + value for value in range(60)],
        }
        snapshot = MarketResearch().analyze(data)
        self.assertEqual(
            set(snapshot.keys()),
            {'volatility', 'momentum', 'trend', 'avg_volume', 'volume_ratio', 'support', 'resistance'},
        )
        self.assertGreater(snapshot['resistance'], snapshot['support'])


if __name__ == '__main__':
    unittest.main()
