"""RSS con respuesta falsa: sin Internet y sin decisiones de inversión."""
import unittest
from unittest.mock import Mock, patch

from app.news import fetch_headlines, market_news, media_news


RSS = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"><channel>
<item><title>Resultados de una empresa</title>
<link>https://news.google.com/articles/abc</link>
<pubDate>Mon, 16 Nov 2026 12:00:00 GMT</pubDate>
<source>Agencia</source></item>
<item><title>Rumor no confirmado de un famoso</title>
<link>https://news.google.com/articles/xyz</link>
<source>Portal</source></item>
</channel></rss>"""


class NewsTests(unittest.TestCase):
    def test_read_and_label_rumor(self):
        with patch("app.news.requests.get") as req:
            response = Mock(content=RSS)
            response.raise_for_status.return_value = None
            req.return_value = response
            out = fetch_headlines("acciones", limit=10)
        self.assertEqual(len(out), 2)
        self.assertFalse(out[0]["unverified"])
        self.assertTrue(out[1]["unverified"])
        self.assertEqual(out[0]["publisher"], "Agencia")
        self.assertTrue(req.call_args.kwargs["timeout"] <= 10)

    def test_invalid_query_and_limit(self):
        with self.assertRaises(ValueError):
            fetch_headlines(" ")
        with self.assertRaises(ValueError):
            fetch_headlines("mercado", limit=0)


if __name__ == "__main__":
    unittest.main()
