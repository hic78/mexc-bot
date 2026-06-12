import sys; sys.path.insert(0,'/root/mexc-bot')
import os; os.environ['XS_DRY_RUN']='1'
import xsmom2_bot as b, statistics as st
cli=b.MEXCRestClient()
print('========== AUDIT PARITÉ COMPLET (live vs backtest) ==========')
print()
print('[1] SIGNAL — parité sur TOUS les coins de l univers')
diffs=[]; scores_bot={}; scores_bt={}
for coin in b.UNIVERSE:
    cl=b.fetch_closes(cli,coin)   # ce que le bot utilise (barre fermée)
    if not cl: print('  %-5s : pas de data'%coin); continue
    ms=b.momentum_score(cl)
    if ms is None: print('  %-5s : score invalide'%coin); continue
    sb=ms[0]
    # recalcul backtest-style indépendant
    rets=[cl[i]/cl[i-1]-1 for i in range(len(cl)-168,len(cl))]; vol=st.stdev(rets)
    sbt=sum((cl[-1]/cl[-1-H]-1)/vol for H in (168,336,720))
    scores_bot[coin]=sb; scores_bt[coin]=sbt; diffs.append(abs(sb-sbt))
print('  écart MAX bot vs backtest sur %d coins: %.6f' % (len(diffs), max(diffs) if diffs else -1))
print('  → SIGNAL %s' % ('IDENTIQUE ✅' if diffs and max(diffs)<1e-6 else 'DIFFÉRENT ❌'))
print()
print('[2] SÉLECTION — top5/bottom5 identique ?')
o=sorted(scores_bt,key=lambda c:scores_bt[c])
L_bt=set(o[-5:]); S_bt=set(o[:5])
ob=sorted(scores_bot,key=lambda c:scores_bot[c])
L_bot=set(ob[-5:]); S_bot=set(ob[:5])
print('  LONG  backtest:',sorted(L_bt)); print('  LONG  bot     :',sorted(L_bot))
print('  SHORT backtest:',sorted(S_bt)); print('  SHORT bot     :',sorted(S_bot))
print('  → SÉLECTION %s' % ('IDENTIQUE ✅' if L_bt==L_bot and S_bt==S_bot else 'DIFFÉRENTE ❌'))
print()
print('[3] VOL-TARGETING — le backtest scale les positions, le bot ?')
import inspect
src=inspect.getsource(b.calc_qty)
has_vt='scale' in src or 'voltgt' in src or '0.40' in src
print('  Backtest : OUI (scale=clip(0.40/vol_20j, 0.2, 3.0))')
print('  Bot      : %s' % ('OUI' if has_vt else 'NON — sizing FIXE (MARGIN_PCT constant)'))
print('  → %s' % ('PARITÉ ✅' if has_vt else 'ÉCART: le bot NE fait PAS le vol-targeting dynamique'))
print()
print('[4] PARAMÈTRES')
print('  Horizons:',b.HORIZONS,'| VOL_WIN:',b.VOL_WIN,'| Q:',b.Q,'| REBAL_H:',b.REBAL_H,'| LEV:',b.LEVERAGE)
print('  Backtest: [168,336,720] | 168 | 5 | 24 | 2  → %s' % ('IDENTIQUE ✅' if b.HORIZONS==[168,336,720] and b.VOL_WIN==168 and b.Q==5 and b.REBAL_H==24 else 'VÉRIFIER'))
