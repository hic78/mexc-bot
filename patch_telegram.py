#!/usr/bin/env python3
"""Patch telegram.py: replace CH_PERIOD/CH_MULTIPLIER with ATR trail + ADX vars."""
import sys

SRC = '/root/mexc-bot/telegram.py'

with open(SRC, encoding='utf-8') as f:
    src = f.read()

orig = src

# 1. Import line — remove CH_PERIOD, CH_MULTIPLIER; add trail/ADX params
src = src.replace(
    'from config import TG_TOKEN, TG_CHAT, COINS, LEVERAGE, DONCHIAN_PERIOD, CH_PERIOD, CH_MULTIPLIER',
    'from config import TG_TOKEN, TG_CHAT, COINS, LEVERAGE, DONCHIAN_PERIOD, ADX_PERIOD, ADX_MIN, TRAIL_ACT, TRAIL_DIST, ATR_SL_MULT, MIN_HOLD_HOURS'
)

# 2. _status: replace 3-line chandelier block with trail status
src = src.replace(
    "                n_bars     = len(self.bot.candles.get(coin, {}).get('1m', []))\n"
    "                chan_hours  = n_bars / 60\n"
    "                chan_ok     = '✅' if n_bars >= CH_PERIOD else f'⚠️ {n_bars}/{CH_PERIOD}'",
    "                atr_e_h    = pos.get('atr_entry', 0.0)\n"
    "                best_h     = pos.get('best_price', entry_price or 0.0)\n"
    "                ep         = entry_price or 0.0\n"
    "                if atr_e_h > 0 and ep > 0:\n"
    "                    act_t  = TRAIL_ACT * atr_e_h / ep\n"
    "                    gain   = (best_h - ep) / ep * mult\n"
    "                    trail_ok = '✅ ACTIF' if gain >= act_t else f'⏳ {gain*100:.2f}%/{act_t*100:.2f}%'\n"
    "                else:\n"
    "                    trail_ok = '⏳ init'"
)

# 3. _status: replace Chan display line
src = src.replace(
    "                    + f'  Chan: {CH_PERIOD}×1m = {chan_hours:.1f}h {chan_ok}\\n'",
    "                    + f'  Trail: {trail_ok} | min_hold={MIN_HOLD_HOURS}h\\n'"
)

# 4. _pnl: replace 3-line chandelier block with trail status
src = src.replace(
    "                n_bars     = len(self.bot.candles.get(coin, {}).get('1m', []))\n"
    "                chan_hours  = n_bars / 60\n"
    "                chan_ok     = '✅' if n_bars >= CH_PERIOD else f'⚠️ {n_bars}/{CH_PERIOD}'",
    "                atr_e_h    = pos.get('atr_entry', 0.0)\n"
    "                best_h     = pos.get('best_price', entry_price or 0.0)\n"
    "                ep         = entry_price or 0.0\n"
    "                if atr_e_h > 0 and ep > 0:\n"
    "                    act_t  = TRAIL_ACT * atr_e_h / ep\n"
    "                    gain   = (best_h - ep) / ep * mult\n"
    "                    trail_ok = '✅ ACTIF' if gain >= act_t else f'⏳ {gain*100:.2f}%/{act_t*100:.2f}%'\n"
    "                else:\n"
    "                    trail_ok = '⏳ init'"
)

# 5. _pnl: replace Chan display line (no trailing \n — end of f-string concat)
src = src.replace(
    "                            + f'  Chan: {CH_PERIOD}×1m = {chan_hours:.1f}h {chan_ok}'",
    "                            + f'  Trail: {trail_ok} | min_hold={MIN_HOLD_HOURS}h'"
)

# 6. _config: replace Chandelier line with Trail + ADX lines
src = src.replace(
    "            f'Chandelier: {CH_PERIOD}×1m × {CH_MULTIPLIER}×ATR ({CH_PERIOD}min = {CH_PERIOD//60}h{CH_PERIOD%60}m)\\n'",
    "            f'Trail: act={TRAIL_ACT} dist={TRAIL_DIST} SL={ATR_SL_MULT}×ATR | min_hold={MIN_HOLD_HOURS}h\\n'\n"
    "            f'ADX: period={ADX_PERIOD} min={ADX_MIN}\\n'"
)

if src == orig:
    print('ERROR: aucun remplacement effectué — vérifier les ancres', file=sys.stderr)
    sys.exit(1)

# Count replacements
import re
ch_remaining = len(re.findall(r'CH_PERIOD|CH_MULTIPLIER', src))
if ch_remaining > 0:
    print(f'WARNING: {ch_remaining} référence(s) CH_PERIOD/CH_MULTIPLIER restantes!', file=sys.stderr)
    for i, line in enumerate(src.splitlines(), 1):
        if 'CH_PERIOD' in line or 'CH_MULTIPLIER' in line:
            print(f'  Line {i}: {line}', file=sys.stderr)

with open(SRC, 'w', encoding='utf-8') as f:
    f.write(src)

print(f'OK — telegram.py patched, {ch_remaining} CH_PERIOD refs remaining')
