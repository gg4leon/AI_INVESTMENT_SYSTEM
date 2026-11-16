"""Public Coinbase Exchange WebSocket connectivity probe; no account/orders.

python -m nory.coinbase_probe --seconds 25 --symbols BTC-USD ETH-USD SOL-USD
"""
import argparse
import json
import time

from nory.coinbase_public import CoinbasePublicClient,PAIRS


def main():
    p=argparse.ArgumentParser(description="Coinbase PUBLIC live market data validation")
    p.add_argument("--seconds",type=int,default=25)
    p.add_argument("--symbols",nargs="+",default=["BTC-USD","ETH-USD","SOL-USD"])
    a=p.parse_args()
    if not 5<=a.seconds<=120:
        p.error("seconds must be 5..120")
    if any(s not in PAIRS for s in a.symbols):
        p.error("unsupported Coinbase Exchange USD product")
    c=CoinbasePublicClient(symbols=a.symbols)
    print("Coinbase public WebSocket — real quote verification, NO BROKER, NO REAL ORDERS")
    c.start()
    seen=set()
    deadline=time.monotonic()+a.seconds
    try:
        while time.monotonic()<deadline:
            snap=c.store.snapshot(a.symbols,max_age_seconds=10)
            for symbol,q in snap.items():
                if symbol not in seen:
                    print(json.dumps(q.as_dict(),ensure_ascii=False,allow_nan=False))
                    seen.add(symbol)
            if len(seen)==len(set(a.symbols)):
                print("PASS: fresh Coinbase bid/ask for all selected USD products")
                return 0
            time.sleep(.5)
        print("NO FRESH QUOTES: "+json.dumps(c.status(),ensure_ascii=False))
        return 2
    finally:
        c.stop()


if __name__=="__main__":
    raise SystemExit(main())
