#!/usr/bin/env python3
with open('/root/mexc-bot/config.py', 'r') as f:
    c = f.read()

c = c.replace("'3m': 'Min3'", "'3m': 'Min5'")
c = c.replace(
    "TF_CHANDELIER = '3m'  # Chandelier Exit → Min3",
    "TF_CHANDELIER = '3m'  # Chandelier Exit → Min5 (Min3 non supporté MEXC)",
)
c = c.replace(
    "CH_PERIOD       = 147     # Chandelier period (3m candles)",
    "CH_PERIOD       = 88      # Chandelier period (5m candles — 88×5m=440min ≈ 147×3m=441min)",
)

with open('/root/mexc-bot/config.py', 'w') as f:
    f.write(c)

print("config.py patched OK")
