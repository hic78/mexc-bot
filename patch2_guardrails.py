"""
patch2_guardrails.py — Ajoute micro-délai + kill switch -15% dans bot.py. Sécurité: backup, ancres exactes, py_compile.
Ces garde-fous ne font que BLOQUER/ATTENDRE (aucun mauvais trade possible).
"""
import shutil, py_compile, sys, time
BOT='/root/mexc-bot/bot.py'
bak=f'{BOT}.bak_guardrails_{time.strftime("%Y%m%d-%H%M%S")}'
src=open(BOT).read()

EDITS=[
 ('micro-delay open_position',
  "        self._opening_coins.add(coin)\n        sym  = to_mexc_symbol(coin)",
  "        self._opening_coins.add(coin)\n        await asyncio.sleep(optimus.MICRO_DELAY_SEC)  # C150-OPTIMUS: anti selection-adverse HFT\n        sym  = to_mexc_symbol(coin)"),

 ('kill switch check_all_signals',
  "        _cs_signed = optimus.cross_sectional_signed(_cs_rets)\n\n        for coin in self.runtime_coins:",
  "        _cs_signed = optimus.cross_sectional_signed(_cs_rets)\n\n"
  "        # C150-OPTIMUS kill switch: circuit-breaker DD journalier (latch journee)\n"
  "        _kday = int(time.time()) // 86400\n"
  "        if getattr(self, '_killed_day', None) == _kday:\n"
  "            return\n"
  "        try:\n"
  "            _bal = self.rest.get_balance()\n"
  "            if optimus.kill_switch_triggered(_bal):\n"
  "                self._killed_day = _kday\n"
  "                log.error(f'KILL SWITCH: perte jour <= -{optimus.KILL_DD_PCT*100:.0f}% (pnl={optimus.today_realized_pnl():.2f} bal={_bal:.2f}) -> entrees STOPPEES')\n"
  "                await tg_send(f'\\U0001F6D1 KILL SWITCH (DD jour <= -{optimus.KILL_DD_PCT*100:.0f}%) - nouvelles entrees stoppees aujourd hui. Sorties continuent.')\n"
  "                return\n"
  "        except Exception as _ke:\n"
  "            log.warning(f'kill switch check: {_ke}')\n\n"
  "        for coin in self.runtime_coins:"),
]
for desc,find,repl in EDITS:
    n=src.count(find)
    if n!=1:
        print(f'ABORT: ancre "{desc}" trouvee {n} fois (attendu 1). Aucun changement.'); sys.exit(1)
    src=src.replace(find,repl); print(f'OK: {desc}')
shutil.copy(BOT,bak); open(BOT,'w').write(src); print(f'Backup: {bak}')
try:
    py_compile.compile(BOT,doraise=True); print('py_compile OK')
except py_compile.PyCompileError as e:
    shutil.copy(bak,BOT); print(f'SYNTAXE KO -> ROLLBACK: {e}'); sys.exit(1)
print('GARDE-FOUS AJOUTES (micro-delay 2s + kill switch -15%)')
