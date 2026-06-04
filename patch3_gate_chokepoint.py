"""
patch3_gate_chokepoint.py — FIX: déplace le gate OPTIMUS dans open_position (point de passage commun).
Couvre les 2 chemins d'entrée (check_all_signals ET on_kline intrabar). Sécurité: backup, ancre exacte, py_compile.
"""
import shutil, py_compile, sys, time
BOT='/root/mexc-bot/bot.py'
bak=f'{BOT}.bak_chokepoint_{time.strftime("%Y%m%d-%H%M%S")}'
src=open(BOT).read()

find=("        self._opening_coins.add(coin)\n"
      "        await asyncio.sleep(optimus.MICRO_DELAY_SEC)  # C150-OPTIMUS: anti selection-adverse HFT\n"
      "        sym  = to_mexc_symbol(coin)")
repl=("        self._opening_coins.add(coin)\n"
      "        await asyncio.sleep(optimus.MICRO_DELAY_SEC)  # C150-OPTIMUS: anti selection-adverse HFT\n"
      "        # C150-OPTIMUS gate (point de passage commun: couvre scan ET intrabar)\n"
      "        if OPTIMUS_ACTIVE:\n"
      "            try:\n"
      "                _csr = {c: optimus.cs_return([x['c'] for x in list(self.candles[c]['1h'])]) for c in self.runtime_coins}\n"
      "                _css = optimus.cross_sectional_signed(_csr)\n"
      "                _keep, conv_mult, _rsn = optimus.optimus_gate(direction, coin, [x['c'] for x in list(self.candles[coin]['1h'])], _css)\n"
      "                log.info(f'[{coin}] OPTIMUS ACTIF: {direction} keep={_keep} conv_mult={conv_mult:.2f} {_rsn}')\n"
      "                if not _keep:\n"
      "                    self._opening_coins.discard(coin)\n"
      "                    return\n"
      "            except Exception as _ge:\n"
      "                log.warning(f'[{coin}] OPTIMUS gate erreur (ouvre sans gate): {_ge}')\n"
      "        sym  = to_mexc_symbol(coin)")

n=src.count(find)
if n!=1:
    print(f'ABORT: ancre trouvee {n} fois (attendu 1). Aucun changement.'); sys.exit(1)
src=src.replace(find,repl)
shutil.copy(BOT,bak); open(BOT,'w').write(src); print(f'OK + Backup: {bak}')
try:
    py_compile.compile(BOT,doraise=True); print('py_compile OK')
except py_compile.PyCompileError as e:
    shutil.copy(bak,BOT); print(f'SYNTAXE KO -> ROLLBACK: {e}'); sys.exit(1)
print('GATE deplace dans open_position (couvre les 2 chemins). check_all_signals garde son pre-gate (redondant, inoffensif).')
