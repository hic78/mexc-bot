"""
patch4_clean.py — Architecture propre (reco NotebookLM): gate UNIQUE dans open_position lisant un snapshot
cross-sectional MIS EN CACHE 1x/cycle (self._cs_signed). Supprime le double-gate + le recompute par-ouverture.
Sécurité: backup, ancres exactes, assert, py_compile.
"""
import shutil, py_compile, sys, time
BOT='/root/mexc-bot/bot.py'
bak=f'{BOT}.bak_clean_{time.strftime("%Y%m%d-%H%M%S")}'
src=open(BOT).read()

EDITS=[
 # 1. Cache le snapshot CS comme attribut d'instance
 ('cache cs snapshot',
  "        _cs_signed = optimus.cross_sectional_signed(_cs_rets)",
  "        self._cs_signed = optimus.cross_sectional_signed(_cs_rets)  # snapshot 1x/cycle (lookup par open_position)"),

 # 2. Supprime le pre-gate de check_all_signals (gate unique = open_position)
 ('remove pre-gate check_all_signals',
  "            if signal == 'NONE':\n                continue\n\n            # C150-OPTIMUS gate: Markov regime + CS-veto + conviction\n            _keep, _convm, _reason = optimus.optimus_gate(signal, coin, [x['c'] for x in bars_1h], _cs_signed)\n            log.info(f'[{coin}] OPTIMUS {\"ACTIF\" if OPTIMUS_ACTIVE else \"SHADOW\"}: signal={signal} keep={_keep} {_reason}')\n            if OPTIMUS_ACTIVE and not _keep:\n                continue\n            _conv_mult = _convm if OPTIMUS_ACTIVE else 1.0\n",
  "            if signal == 'NONE':\n                continue\n"),

 # 3. Appel open_position sans _conv_mult (open_position calcule tout)
 ('open_position call clean',
  "await self.open_position(coin, signal, atr_val, _conv_mult)",
  "await self.open_position(coin, signal, atr_val)"),

 # 4. open_position lit le snapshot CACHÉ (pas de recompute)
 ('open_position cached lookup',
  "                _csr = {c: optimus.cs_return([x['c'] for x in list(self.candles[c]['1h'])]) for c in self.runtime_coins}\n                _css = optimus.cross_sectional_signed(_csr)\n",
  "                _css = getattr(self, '_cs_signed', None)\n                if not _css:\n                    _css = optimus.cross_sectional_signed({c: optimus.cs_return([x['c'] for x in list(self.candles[c]['1h'])]) for c in self.runtime_coins})\n"),
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
print('ARCHITECTURE PROPRE: gate unique (open_position) + snapshot CS cache 1x/cycle. Double-gate + recompute supprimes.')
