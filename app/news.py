"""RSS público para investigación. Los titulares NO producen órdenes automáticas.

Un titular agregado no equivale a verificación. No infiere hechos sobre personas.
"""
from dataclasses import asdict, dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urlencode
import re
import xml.etree.ElementTree as ET

import requests

BASE_URL = "https://news.google.com/rss/search"
DEFAULT_HEADERS = {"User-Agent": "AIS-Research/0.6.1 (educational RSS reader)"}
SENSITIVE_WORDS = ("rumor", "rumour", "gossip", "alleged", "unconfirmed",
                   "supuesto", "rumores", "chisme", "presunto", "se dice")


@dataclass(frozen=True)
class Headline:
    title: str
    publisher: str
    url: str
    published: str
    category: str
    unverified: bool

    def as_dict(self):
        return asdict(self)


def fetch_headlines(
    query: str, category: str = "Mercados", limit: int = 12, timeout: int = 7,
) -> list[dict]:
    """Solicita RSS de Google News sin hacer scraping de artículos completos."""
    if not query.strip() or len(query) > 120:
        raise ValueError("Consulta vacía o excesiva")
    if not 1 <= limit <= 30:
        raise ValueError("limit debe estar entre 1 y 30")
    url = BASE_URL + "?" + urlencode({
        "q": query, "hl": "es-419", "gl": "MX", "ceid": "MX:es-419",
    })
    response = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    response.raise_for_status()
    if len(response.content) > 2_000_000:
        raise ValueError("Feed RSS demasiado grande")
    root = ET.fromstring(response.content)
    out = []
    for item in root.findall(".//channel/item")[:limit]:
        title = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        source = item.find("source")
        publisher = (source.text if source is not None and source.text else "Agregador").strip()
        stamp = (item.findtext("pubDate") or "").strip()
        if not title or not link.startswith("https://"):
            continue
        try:
            published = parsedate_to_datetime(stamp).isoformat()
        except (TypeError, ValueError):
            published = stamp
        unverified = any(w in title.lower() for w in SENSITIVE_WORDS)
        out.append(Headline(
            title=title[:240], publisher=publisher[:100], url=link,
            published=published, category=category, unverified=unverified,
        ).as_dict())
    return out


def market_news(symbol: str, market_name: str, limit: int = 10) -> list[dict]:
    return fetch_headlines(
        f"{market_name} {symbol} bolsa resultados empresa", "Mercados", limit
    )


def media_news(limit: int = 8) -> list[dict]:
    """Observatorio mediático: no verificado ni apto para disparar operaciones."""
    return fetch_headlines(
        "celebrity brand endorsement business stock market", "Cultura y marcas", limit
    )
