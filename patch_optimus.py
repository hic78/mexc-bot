"""
patch_optimus.py — Patche /root/mexc-bot/bot.py pour intégrer optimus (Markov+CS-veto+conviction) en SHADOW.
Sécurité : backup, remplacements par ancres EXACTES, assert chaque = 1 occurrence, py_compile. Abort si problème.
SHADOW par défaut (OPTIMUS_ACTIVE non défini) = log seulement, ZÉRO changement de trading.
"""
import shutil, py_compile, sys, time, os

BOT='/root/mexc-bot/bot.py'
bak=f'{BOT}.bak_optimus_{time.strftime("%Y%m%d-%H%M%S")}'

src=open(BOT).read()
orig=src

EDITS=[
 # (description, find, replace)
 ('import optimus',
  'from telegram import tg_send, TelegramCommands\n',
  'from telegram import tg_send, TelegramCommands\nimport optimus\nOPTIMUS_ACTIVE = os.getenv(\'OPTIMUS_ACTIVE\', \'0\') == \'1\'\n'),

 ('cross-sectional precompute',
  "        for coin in self.runtime_coins:\n            bars_1h = list(self.candles[coin]['1h'])\n            bars_4h = list(self.candles[coin]['4h'])",
  "        # C150-OPTIMUS: classement cross-sectional (momentum relatif tous coins)\n"
  "        _cs_rets = {}\n"
  "        for _c in self.runtime_coins:\n"
  "            _bb = list(self.candles[_c]['1h'])\n"
  "            _cs_rets[_c] = optimus.cs_return([x['c'] for x in _bb]) if len(_bb) > optimus.CS_N else None\n"
  "        _cs_signed = optimus.cross_sectional_signed(_cs_rets)\n\n"
  "        for coin in self.runtime_coins:\n            bars_1h = list(self.candles[coin]['1h'])\n            bars_4h = list(self.candles[coin]['4h'])"),

 ('optimus gate',
  "            signal, atr_val = compute_signal(bars_1h, bars_4h, coin=coin)\n            if signal == 'NONE':\n                continue\n",
  "            signal, atr_val = compute_signal(bars_1h, bars_4h, coin=coin)\n            if signal == 'NONE':\n                continue\n\n"
  "            # C150-OPTIMUS gate: Markov regime + CS-veto + conviction\n"
  "            _keep, _convm, _reason = optimus.optimus_gate(signal, coin, [x['c'] for x in bars_1h], _cs_signed)\n"
  "            log.info(f'[{coin}] OPTIMUS {\"ACTIF\" if OPTIMUS_ACTIVE else \"SHADOW\"}: signal={signal} keep={_keep} {_reason}')\n"
  "            if OPTIMUS_ACTIVE and not _keep:\n"
  "                continue\n"
  "            _conv_mult = _convm if OPTIMUS_ACTIVE else 1.0\n"),

 ('open_position call + conv',
  "await self.open_position(coin, signal, atr_val)\n            except Exception:",
  "await self.open_position(coin, signal, atr_val, _conv_mult)\n            except Exception:"),

 ('open_position signature',
  "    async def open_position(self, coin: str, direction: str, atr_val: float = 0.0):",
  "    async def open_position(self, coin: str, direction: str, atr_val: float = 0.0, conv_mult: float = 1.0):"),

 ('conviction in calc_qty',
  "            qty         = calc_qty(balance, price, coin)",
  "            qty         = max(1, round(calc_qty(balance, price, coin) * conv_mult))"),
]

for desc, find, repl in EDITS:
    n=src.count(find)
    if n != 1:
        print(f'ABORT: ancre "{desc}" trouvée {n} fois (attendu 1). AUCUN changement écrit.')
        sys.exit(1)
    src=src.replace(find, repl)
    print(f'OK: {desc}')

# backup + write
shutil.copy(BOT, bak)
open(BOT,'w').write(src)
print(f'Backup: {bak}')

# syntax check
try:
    py_compile.compile(BOT, doraise=True)
    print('py_compile OK — syntaxe valide')
except py_compile.PyCompileError as e:
    print(f'SYNTAXE INVALIDE -> ROLLBACK: {e}')
    shutil.copy(bak, BOT)
    print('bot.py restauré depuis backup')
    sys.exit(1)
print('PATCH RÉUSSI (mode SHADOW — OPTIMUS_ACTIVE non défini = log seulement)')
