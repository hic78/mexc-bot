import sys
from dotenv import load_dotenv
load_dotenv("/root/mexc-bot/.env")
sys.path.insert(0, "/root/mexc-bot")
from mexc_client import MEXCRestClient
c = MEXCRestClient()
pos = c.get_positions()
eq = c.get_equity()
print(f"Equity: ${eq:.4f}")
print(f"Positions ouvertes: {len(pos)}")
for p in pos:
    print(f"  {p.get('symbol')} holdVol={p.get('holdVol')} entry={p.get('openAvgPrice')} pnl%={p.get('profitRatio')}")
