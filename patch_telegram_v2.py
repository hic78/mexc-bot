#!/usr/bin/env python3
"""
patch_telegram_v2.py — 4 fixes menus dynamiques telegram.py :
  1. Import CONTRACT_SIZES depuis config
  2. _addcoin: liste dispo dynamique (CONTRACT_SIZES - runtime_coins)
  3. _close: exemple coin dynamique + 📍 positions ouvertes
  4. _help: entête coins actifs dynamique
"""
import sys

SRC = '/root/mexc-bot/telegram.py'

with open(SRC, encoding='utf-8') as f:
    src = f.read()

orig = src
changes = []

# ─── FIX 1 : Import CONTRACT_SIZES ───────────────────────────────────────────
old_import = 'from config import TG_TOKEN, TG_CHAT, COINS, LEVERAGE, DONCHIAN_PERIOD, ADX_PERIOD, ADX_MIN, TRAIL_ACT, TRAIL_DIST, ATR_SL_MULT, MIN_HOLD_HOURS'
new_import = 'from config import TG_TOKEN, TG_CHAT, COINS, CONTRACT_SIZES, LEVERAGE, DONCHIAN_PERIOD, ADX_PERIOD, ADX_MIN, TRAIL_ACT, TRAIL_DIST, ATR_SL_MULT, MIN_HOLD_HOURS'

if old_import in src:
    src = src.replace(old_import, new_import)
    changes.append('FIX 1 ✅ Import CONTRACT_SIZES ajouté')
elif 'CONTRACT_SIZES' in src:
    changes.append('FIX 1 ✅ CONTRACT_SIZES déjà importé')
else:
    print('FIX 1 ⚠️  ancre import introuvable', file=sys.stderr)

# ─── FIX 2 : _addcoin liste dynamique ────────────────────────────────────────
old_addcoin = (
    "    async def _addcoin(self, full_text: str):\n"
    "        parts = full_text.split()\n"
    "        if len(parts) < 2:\n"
    "            await self._reply('Usage: /addcoin SOL\\nCoins disponibles: SOL HYPE ZEC JUP BLUR FET DOGE')\n"
    "            return"
)
new_addcoin = (
    "    async def _addcoin(self, full_text: str):\n"
    "        parts = full_text.split()\n"
    "        if len(parts) < 2:\n"
    "            available = sorted(set(CONTRACT_SIZES.keys()) - set(self.bot.runtime_coins))\n"
    "            await self._reply(\n"
    "                f'Usage: /addcoin SYMBOL\\n'\n"
    "                f'Dispo ({len(available)}): {\" \".join(available)}\\n'\n"
    "                f'Actifs ({len(self.bot.runtime_coins)}): {\" + \".join(self.bot.runtime_coins)}'\n"
    "            )\n"
    "            return"
)

if old_addcoin in src:
    src = src.replace(old_addcoin, new_addcoin)
    changes.append('FIX 2 ✅ _addcoin: liste dynamique CONTRACT_SIZES - runtime_coins')
elif 'CONTRACT_SIZES.keys()' in src:
    changes.append('FIX 2 ✅ _addcoin: déjà dynamique')
else:
    print('FIX 2 ⚠️  ancre _addcoin introuvable', file=sys.stderr)

# ─── FIX 3 : _close exemple dynamique + 📍 positions ─────────────────────────
old_close = (
    "            coins_str = ' | '.join(self.bot.runtime_coins)\n"
    "            await self._reply(\n"
    "                f'Usage: /close COIN confirm\\nCoins actifs: {coins_str}\\n\\n'\n"
    "                '⚠️ FERME LA POSITION AU MARCHÉ'\n"
    "            )"
)
new_close = (
    "            example = self.bot.runtime_coins[0] if self.bot.runtime_coins else 'COIN'\n"
    "            coins_str = ' | '.join(\n"
    "                c + (' 📍' if c in self.bot.positions else '') for c in self.bot.runtime_coins\n"
    "            )\n"
    "            await self._reply(\n"
    "                f'Usage: /close {example} confirm\\nCoins: {coins_str}\\n\\n'\n"
    "                '⚠️ FERME LA POSITION AU MARCHÉ'\n"
    "            )"
)

if old_close in src:
    src = src.replace(old_close, new_close)
    changes.append('FIX 3 ✅ _close: exemple dynamique + 📍 positions ouvertes')
elif 'runtime_coins[0] if self.bot.runtime_coins' in src:
    changes.append('FIX 3 ✅ _close: déjà dynamique')
else:
    print('FIX 3 ⚠️  ancre _close introuvable', file=sys.stderr)

# ─── FIX 4 : _help entête coins dynamique ────────────────────────────────────
old_help = (
    "    async def _help(self, _):\n"
    "        await self._reply(\n"
    "            '<b>MEXC Bot Commands</b>\\n\\n'"
)
new_help = (
    "    async def _help(self, _):\n"
    "        n = len(self.bot.runtime_coins)\n"
    "        coins_str = ' + '.join(self.bot.runtime_coins) if self.bot.runtime_coins else 'aucun'\n"
    "        await self._reply(\n"
    "            f'<b>MEXC Bot Commands</b>\\n'\n"
    "            f'Coins actifs ({n}): {coins_str}\\n\\n'"
)

if old_help in src:
    src = src.replace(old_help, new_help)
    changes.append('FIX 4 ✅ _help: entête coins actifs dynamique')
elif 'coins_str = \' + \'.join(self.bot.runtime_coins)' in src:
    changes.append('FIX 4 ✅ _help: déjà dynamique')
else:
    print('FIX 4 ⚠️  ancre _help introuvable', file=sys.stderr)

# ─── Résumé + écriture ───────────────────────────────────────────────────────
if src == orig:
    print('ATTENTION: aucune modification (tout déjà correct ou ancres manquantes)')
else:
    with open(SRC, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f'telegram.py patché — {len(changes)} fix(es):')

for c in changes:
    print(f'  {c}')

# Validation
problems = []
if "'SOL HYPE ZEC JUP BLUR FET DOGE'" in src:
    problems.append('❌ Liste coins hardcodée encore présente')
if 'CONTRACT_SIZES' not in src:
    problems.append('❌ CONTRACT_SIZES absent')
if 'CONTRACT_SIZES.keys()' not in src:
    problems.append('❌ _addcoin pas dynamique')
if "runtime_coins[0] if self.bot.runtime_coins" not in src:
    problems.append('❌ _close exemple pas dynamique')
if "coins_str = ' + '.join(self.bot.runtime_coins) if self.bot.runtime_coins" not in src:
    problems.append('❌ _help entête pas dynamique')

if problems:
    print('\nPROBLÈMES DÉTECTÉS:')
    for p in problems:
        print(f'  {p}')
    sys.exit(1)
else:
    print('\nValidation OK')
    import py_compile, tempfile, os
    tmp = tempfile.mktemp(suffix='.py')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(src)
    try:
        py_compile.compile(tmp, doraise=True)
        print('Syntax check: OK ✅')
    except py_compile.PyCompileError as e:
        print(f'SYNTAX ERROR: {e}')
        sys.exit(1)
    finally:
        os.unlink(tmp)
