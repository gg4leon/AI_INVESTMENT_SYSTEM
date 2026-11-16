"""Catálogo educativo ampliado. Símbolos sujetos a disponibilidad de Yahoo."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Market:
    symbol: str
    name: str
    category: str
    currency: str
    paper_eligible: bool = True


CATALOG = (
    # ETFs
    Market("SPY", "SPDR S&P 500 ETF", "ETFs", "USD"),
    Market("QQQ", "Invesco Nasdaq 100 ETF", "ETFs", "USD"),
    Market("VTI", "Vanguard Total Stock Market", "ETFs", "USD"),
    Market("DIA", "SPDR Dow Jones ETF", "ETFs", "USD"),
    Market("IWM", "iShares Russell 2000 ETF", "ETFs", "USD"),
    Market("GLD", "SPDR Gold Shares", "ETFs", "USD"),
    Market("TLT", "iShares 20+ Year Treasury", "ETFs", "USD"),
    Market("EEM", "iShares Emerging Markets", "ETFs", "USD"),
    # Acciones EEUU
    Market("AAPL", "Apple", "Acciones EE. UU.", "USD"),
    Market("MSFT", "Microsoft", "Acciones EE. UU.", "USD"),
    Market("NVDA", "NVIDIA", "Acciones EE. UU.", "USD"),
    Market("AMZN", "Amazon", "Acciones EE. UU.", "USD"),
    Market("GOOGL", "Alphabet", "Acciones EE. UU.", "USD"),
    Market("META", "Meta Platforms", "Acciones EE. UU.", "USD"),
    Market("TSLA", "Tesla", "Acciones EE. UU.", "USD"),
    Market("NFLX", "Netflix", "Acciones EE. UU.", "USD"),
    Market("JPM", "JPMorgan Chase", "Acciones EE. UU.", "USD"),
    Market("V", "Visa", "Acciones EE. UU.", "USD"),
    Market("KO", "Coca-Cola", "Acciones EE. UU.", "USD"),
    Market("WMT", "Walmart", "Acciones EE. UU.", "USD"),
    Market("DIS", "Disney", "Acciones EE. UU.", "USD"),
    Market("BRK-B", "Berkshire Hathaway B", "Acciones EE. UU.", "USD"),
    Market("AMD", "AMD", "Acciones EE. UU.", "USD"),
    Market("PLTR", "Palantir", "Acciones EE. UU.", "USD"),
    # México (la disponibilidad puede variar)
    Market("WALMEX.MX", "Walmart de México", "Acciones México", "MXN"),
    Market("AMXL.MX", "América Móvil", "Acciones México", "MXN"),
    Market("CEMEXCPO.MX", "Cemex", "Acciones México", "MXN"),
    Market("BIMBOA.MX", "Grupo Bimbo", "Acciones México", "MXN"),
    Market("GFNORTEO.MX", "Grupo Financiero Banorte", "Acciones México", "MXN"),
    Market("FEMSAUBD.MX", "FEMSA", "Acciones México", "MXN"),
    # Internacionales (ADR/acciones)
    Market("TSM", "Taiwan Semiconductor", "Acciones internacionales", "USD"),
    Market("ASML", "ASML Holding (ADR)", "Acciones internacionales", "USD"),
    Market("TM", "Toyota (ADR)", "Acciones internacionales", "USD"),
    Market("BABA", "Alibaba (ADR)", "Acciones internacionales", "USD"),
    Market("NVO", "Novo Nordisk (ADR)", "Acciones internacionales", "USD"),
    # Cripto (cotizaciones, NO custodia)
    Market("BTC-USD", "Bitcoin / USD", "Criptomonedas", "USD"),
    Market("ETH-USD", "Ethereum / USD", "Criptomonedas", "USD"),
    Market("SOL-USD", "Solana / USD", "Criptomonedas", "USD"),
    Market("XRP-USD", "XRP / USD", "Criptomonedas", "USD"),
    Market("ADA-USD", "Cardano / USD", "Criptomonedas", "USD"),
    # Forex, futuros e índices: consulta analítica, NO activos de compra directa.
    Market("EURUSD=X", "EUR / USD", "Divisas", "USD", False),
    Market("GBPUSD=X", "GBP / USD", "Divisas", "USD", False),
    Market("MXN=X", "USD / MXN", "Divisas", "MXN", False),
    Market("JPY=X", "USD / JPY", "Divisas", "JPY", False),
    Market("GC=F", "Oro futuro", "Materias primas", "USD", False),
    Market("SI=F", "Plata futuro", "Materias primas", "USD", False),
    Market("CL=F", "Petróleo WTI futuro", "Materias primas", "USD", False),
    Market("^GSPC", "Índice S&P 500", "Índices", "puntos", False),
    Market("^IXIC", "Índice Nasdaq Composite", "Índices", "puntos", False),
    Market("^DJI", "Índice Dow Jones", "Índices", "puntos", False),
    Market("^MXX", "Índice S&P/BMV IPC", "Índices", "puntos", False),
)
MARKET_BY_SYMBOL = {m.symbol: m for m in CATALOG}
MARKETS = {m.symbol: m.name for m in CATALOG}
CATEGORIES = tuple(dict.fromkeys(m.category for m in CATALOG))
PAPER_SYMBOLS = tuple(m.symbol for m in CATALOG if m.paper_eligible)


def quote_currency(symbol: str) -> str:
    return MARKET_BY_SYMBOL[symbol].currency
