import sys
sys.path.insert(0, '/root/mexc-bot')
from dotenv import load_dotenv; load_dotenv('/root/mexc-bot/.env')
from mexc_client import MEXCRestClient
from config import CH_PERIOD, CH_MULTIPLIER, ATR_PERIOD

c = MEXCRestClient()

bars = c.get_klines_full('ETH_USDT', 'Min1', 600)
print('ETH bars loaded:', len(bars))

entry_unix = 1747001040  # 22:04 UTC May 11
bars_since = [b for b in bars if b['t'] >= entry_unix]
print('Bars since entry:', len(bars_since), '/ need', CH_PERIOD)

if len(bars_since) >= CH_PERIOD:
    period = min(ATR_PERIOD, len(bars_since)-1)
    trs = []
    for i in range(1, len(bars_since)):
        b = bars_since[i]
        prev_c = bars_since[i-1]['c']
        tr = max(b['h'] - b['l'], abs(b['h'] - prev_c), abs(b['l'] - prev_c))
        trs.append(tr)
    atr = sum(trs[-period:]) / period if period > 0 else 0
    last_n = bars_since[-CH_PERIOD:]
    highest_h = max(b['h'] for b in last_n)
    ce_long = highest_h - CH_MULTIPLIER * atr
    current = bars[-1]['c']
    print('Highest high last', CH_PERIOD, 'bars:', round(highest_h, 2))
    print('ATR:', round(atr, 4))
    print('Chandelier LONG stop:', round(ce_long, 4))
    print('Current ETH:', current)
    print('Gap to stop:', round(current - ce_long, 2), '=', round((current - ce_long)/current*100, 2), '%')
    if current > ce_long:
        print('Status: HOLD (above stop)')
    else:
        print('Status: CLOSE signal (below stop)!')
else:
    print('INACTIF: need', CH_PERIOD - len(bars_since), 'more bars')

bars_zec = c.get_klines_full('ZEC_USDT', 'Min1', 400)
entry_zec = 1747012505  # 01:15 UTC May 12
bars_zec_since = [b for b in bars_zec if b['t'] >= entry_zec]
n_left = CH_PERIOD - len(bars_zec_since)
print('\nZEC bars since entry:', len(bars_zec_since), '/ need', CH_PERIOD)
if n_left > 0:
    print('ZEC INACTIF:', n_left, 'bars left (~', n_left // 60, 'h', n_left % 60, 'm)')
else:
    print('ZEC chandelier ACTIVE')
