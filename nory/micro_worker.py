"""Nory MicroLab: ~1 wall-clock second per SYNTHETIC price step.

No live data, broker connections, secret credentials or financial orders.
Seconds are virtual and do NOT represent tradable quotations.
"""
import argparse
import json
import time

from nory.micro_feed import SCENARIOS
from nory.micro_lab import (
    DEFAULT_DB, DEFAULT_SYMBOLS, is_paused, process_second,
)


def run_steps(symbols=DEFAULT_SYMBOLS, scenario="mixed", steps=1,
              interval_seconds=0., db_path=DEFAULT_DB, sleeper=time.sleep,
              clock=time.monotonic):
    if not 1<=steps<=100_000:
        raise ValueError("steps must be 1..100000")
    if not 0<=interval_seconds<=60:
        raise ValueError("interval_seconds must be in [0,60]")
    result=None
    for _ in range(steps):
        start=clock()
        result=process_second(
            symbols=tuple(symbols), scenario=scenario, db_path=db_path,
        )
        if result["status"]!="PROCESSED":
            break
        if interval_seconds:
            sleeper(max(0., interval_seconds-(clock()-start)))
    return result


def main():
    p=argparse.ArgumentParser(
        description="Nory seconds laboratory: ONLY SYNTHETIC PAPER SIMULATION"
    )
    p.add_argument("--demo", action="store_true", required=True,
                   help="Mandatory: explicitly accept fabricated data")
    mode=p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--steps", type=int,
                      help="Run a fixed number of virtual steps")
    mode.add_argument("--loop",action="store_true",
                      help="Run until stopped by user or paused")
    p.add_argument("--interval-seconds", type=float, default=1.,
                   help="Wall-clock seconds between simulated steps (default 1)")
    p.add_argument("--scenario", choices=SCENARIOS, default="mixed")
    p.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS))
    args=p.parse_args()
    if not 0.1<=args.interval_seconds<=60:
        p.error("Interval must be 0.1..60 seconds")
    print("NORY MICRO LAB v0.8 | 100% FABRICATED PRICE STREAM")
    print("This is NOT a live exchange feed, real quote, or brokerage trading.")
    try:
        if args.loop:
            while True:
                result=run_steps(
                    args.symbols,args.scenario,1,args.interval_seconds
                )
                print(json.dumps(result,ensure_ascii=False,allow_nan=False))
                if result["status"]!="PROCESSED":
                    print("Stopped: simulator paused or risk circuit triggered.")
                    break
        else:
            for _ in range(args.steps):
                result=run_steps(
                    args.symbols,args.scenario,1,args.interval_seconds
                )
                if result["status"]!="PROCESSED":
                    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
                    break
                if result["tick"]%10==0 or result["trades"]:
                    print(json.dumps(result,ensure_ascii=False,allow_nan=False))
    except KeyboardInterrupt:
        print("Simulator stopped safely by keyboard.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
