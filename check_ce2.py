import sys
sys.path.insert(0, '/root/mexc-bot')
from dotenv import load_dotenv; load_dotenv('/root/mexc-bot/.env')
from mexc_client import MEXCRestClient
from config import CH_PERIOD, CH_MULTIPLIER, ATR_PERIOD
import json

def calc_atr_series(candles, period):
    if len(candles) < period + 1:
        return []
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['h'], candles[i]['l'], candles[i-1]['c']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return []
    atr = sum(trs[:period]) / period
    atrs = [atr]
    for tr in trs[period:]:
        atr = tr * (1/period) + atr * (1 - 1/period)
        atrs.append(atr)
    return atrs

def chandelier_exit(candles, period, mult):
    if len(candles) < period + 1:
        return 'HOLD', 0, 0, 0
    atr_series = calc_atr_series(candles, period)
    if not atr_series:
        return 'HOLD', 0, 0, 0
    atr = atr_series[-1]
    recent = candles[-period:]
    chan_long = max(c['h'] for c in recent) - mult * atr
    chan_short = min(c['l'] for c in recent) + mult * atr
    close = candles[-1]['c']
    result = 'HOLD'
    if close > chan_long:
        result = 'ABOVE'
    elif close < chan_short:
        result = 'BELOW'
    return result, chan_long, chan_short, atr

c = MEXCRestClient()

# ETH
bars = c.get_klines_full('ETH_USDT', 'Min1', 700)
print('ETH bars loaded:', len(bars))

entry_unix = 1747001040  # 22:04 UTC May 11
bars_since = [b for b in bars if b['t'] >= entry_unix]
print('Bars since entry:', len(bars_since))

if len(bars_since) >= CH_PERIOD + 1:
    ce, chan_l, chan_s, atr = chandelier_exit(bars_since, CH_PERIOD, CH_MULTIPLIER)
    current = bars[-1]['c']
    print('ATR(RMA-441):', round(atr, 4))
    print('Chan LONG stop:', round(chan_l, 4))
    print('Chan SHORT stop:', round(chan_s, 4))
    print('Current ETH:', current)
    print('Result:', ce)
    print('Exit trigger (LONG):', ce != 'ABOVE')
    if ce != 'ABOVE':
        print('*** CLOSE SIGNAL ACTIVE ***')
    else:
        print('Gap above chan_long:', round(current - chan_l, 2))
else:
    print('INACTIF: need', CH_PERIOD + 1 - len(bars_since), 'more bars')

# ZEC
bars_zec = c.get_klines_full('ZEC_USDT', 'Min1', 500)
entry_zec = 1747012505  # 01:15 UTC May 12
bars_zec_since = [b for b in bars_zec if b['t'] >= entry_zec]
n_left = CH_PERIOD - len(bars_zec_since)
print('\nZEC bars since entry:', len(bars_zec_since), '/ need', CH_PERIOD + 1)
if len(bars_zec_since) >= CH_PERIOD + 1:
    ce_z, chl_z, chs_z, atr_z = chandelier_exit(bars_zec_since, CH_PERIOD, CH_MULTIPLIER)
    current_z = bars_zec[-1]['c']
    print('ATR:', round(atr_z, 4), 'Chan SHORT stop:', round(chs_z, 4))
    print('Current ZEC:', current_z, '| Result:', ce_z)
    print('Exit trigger (SHORT):', ce_z != 'BELOW')
else:
    print('ZEC INACTIF:', max(0, n_left), 'bars left (~', max(0, n_left) // 60, 'h', max(0, n_left) % 60, 'm)')
