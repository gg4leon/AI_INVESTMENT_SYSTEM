"""Manual connectivity probe for Kraken public real-time WebSocket.

Run locally with Internet: python -m nory.kraken_probe --seconds 20
No keys, no account and no simulated or real financial transactions.
"""
import argparse
import json
import time

from nory.kraken_public import KrakenPublicClient


def main():
    parser=argparse.ArgumentParser(description="Kraken real public bid/ask connectivity check")
    parser.add_argument("--seconds",type=int,default=20)
    parser.add_argument("--symbols",nargs="+",default=["BTC-USD","ETH-USD"])
    args=parser.parse_args()
    if not 5<=args.seconds<=90:
        parser.error("seconds must be between 5 and 90")
    try:
        feed=KrakenPublicClient(symbols=args.symbols)
    except ValueError as exc:
        parser.error(str(exc))
    print("Connecting to PUBLIC real-time Kraken. Quotes real; NO ORDERS.")
    feed.start()
    deadline=time.monotonic()+args.seconds
    seen=set()
    try:
        while time.monotonic()<deadline:
            snap=feed.store.snapshot(symbols=args.symbols,max_age_seconds=10)
            for symbol,quote in snap.items():
                if symbol not in seen:
                    print(json.dumps(quote.as_dict(),ensure_ascii=False,allow_nan=False))
                    seen.add(symbol)
            if len(seen)==len(set(args.symbols)):
                print("PASS: fresh bid/ask updates received for all selected instruments.")
                return 0
            time.sleep(.5)
        print("NO FRESH QUOTES: "+json.dumps(feed.status(),ensure_ascii=False))
        return 2
    finally:
        feed.stop()


if __name__=="__main__":
    raise SystemExit(main())
