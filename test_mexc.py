#!/usr/bin/env python3
# test_mexc.py — Tests publics MEXC (sans API key)
# Lance depuis /root/mexc-bot/

import os, sys
os.environ.setdefault('MEXC_API_KEY', '')
os.environ.setdefault('MEXC_SECRET_KEY', '')
os.environ.setdefault('DRY_RUN', 'true')

sys.path.insert(0, '/root/mexc-bot')

from mexc_client import MEXCRestClient
from config import COINS, to_mexc_symbol, to_mexc_interval

PASS = "PASS"
FAIL = "FAIL"
results = []

def log(label, status, detail=""):
    tag = f"[{status}]"
    msg = f"{tag:8} {label}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append((label, status, detail))

client = MEXCRestClient()

# ── Test 1: Ping ──────────────────────────────────────
try:
    ping = client.ping()
    log("REST ping", PASS, str(ping))
except Exception as e:
    log("REST ping", FAIL, str(e))

# ── Test 2: Klines 1h ────────────────────────────────
for coin in COINS:
    try:
        sym = to_mexc_symbol(coin)
        candles = client.get_klines_full(sym, to_mexc_interval('1h'), limit=10)
        last = candles[-1] if candles else {}
        log(
            f"REST klines 1h {coin}",
            PASS if len(candles) > 0 else FAIL,
            f"count={len(candles)}  C={last.get('c', '?')}",
        )
    except Exception as e:
        log(f"REST klines 1h {coin}", FAIL, str(e))

# ── Test 3: Klines 3m ────────────────────────────────
for coin in COINS:
    try:
        sym = to_mexc_symbol(coin)
        candles = client.get_klines_full(sym, to_mexc_interval('3m'), limit=10)
        log(
            f"REST klines 3m {coin}",
            PASS if len(candles) > 0 else FAIL,
            f"count={len(candles)}",
        )
    except Exception as e:
        log(f"REST klines 3m {coin}", FAIL, str(e))

# ── Test 4: Ticker ───────────────────────────────────
for coin in COINS:
    try:
        sym = to_mexc_symbol(coin)
        ticker = client.get_ticker(sym)
        price = ticker.get('lastPrice', ticker.get('last', '?'))
        log(f"REST ticker {coin}", PASS, f"lastPrice={price}")
    except Exception as e:
        log(f"REST ticker {coin}", FAIL, str(e))

# ── Test 5: Donchian signal (logique bot) ────────────
try:
    from bot import donchian_signal, chandelier_exit, ema_filter
    candles_1h = client.get_klines_full('SOL_USDT', 'Min60', limit=50)
    signal = donchian_signal(candles_1h, period=5)
    log("Donchian signal SOL 1h", PASS, f"signal={signal}")
except Exception as e:
    log("Donchian signal", FAIL, str(e))

# ── Sommaire ─────────────────────────────────────────
passed = [r for r in results if r[1] == PASS]
failed = [r for r in results if r[1] == FAIL]
print("\n" + "=" * 55)
print(f"MEXC BOT — TEST RESULT: {len(passed)} PASS / {len(failed)} FAIL")
print("=" * 55)
if failed:
    print("ECHECS:")
    for label, _, detail in failed:
        print(f"  - {label}: {detail}")
print(f"\nISOLATION: champion-v4-bot NON TOUCHE")
print(f"DRY_RUN={os.environ.get('DRY_RUN')} — aucun ordre reel place")
