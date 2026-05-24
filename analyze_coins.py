import json
from collections import defaultdict

trades = json.loads(open('/root/mexc-bot/trades.json').read())
by_coin = defaultdict(list)
for t in trades:
    by_coin[t['coin']].append(t)

header = "COIN    N    WR%  AvgUSDT TotalUSDT  SL_n  AvgSL    VERDICT"
print(header)
print('-' * len(header))
for coin, ts in sorted(by_coin.items()):
    n = len(ts)
    wins = sum(1 for t in ts if t.get('pnl', 0) > 0)
    wr = wins / n * 100
    avg_pnl = sum(t.get('pnl', 0) for t in ts) / n
    total = sum(t.get('pnl', 0) for t in ts)
    sl_ts = [t for t in ts if t.get('reason') == 'SL_SOFT']
    sl_n = len(sl_ts)
    sl_avg = sum(t.get('pnl', 0) for t in sl_ts) / sl_n if sl_n else 0.0
    if sl_n >= 3:
        verdict = 'WHIPSAW FORT'
    elif sl_n >= 2:
        verdict = 'surveiller'
    elif wr < 60 and n >= 5:
        verdict = 'WR faible'
    elif total > 10:
        verdict = 'EXCELLENT'
    elif total > 3:
        verdict = 'BON'
    elif total > 0:
        verdict = 'OK'
    else:
        verdict = 'NEGATIF'
    print(f"{coin:<6} {n:>4} {wr:>6.1f} {avg_pnl:>8.4f} {total:>10.4f} {sl_n:>5} {sl_avg:>8.4f}  {verdict}")

print()
# Contract sizes from latest startup log
print("=== CONTRACT SIZES (dernier demarrage) ===")
import subprocess
result = subprocess.run(['grep', 'cs=', '/root/mexc-bot/bot.log'], capture_output=True, text=True)
for line in result.stdout.splitlines():
    if '22:02' in line and 'cs=' in line and 'INFO' in line and 'CONTRACT' not in line:
        print(line.split('INFO')[1].strip())
