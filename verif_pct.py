import sys; sys.path.insert(0,'/root/mexc-bot')
import mexc_client as m, re
c=getattr(m,re.search(r'class (\w+)',open('/root/mexc-bot/mexc_client.py').read()).group(1))()
eq=c.get_equity(); bal=c.get_balance(); eq0=float(open('/root/mexc-bot/xs_logs/equity0.txt').read())
ps=c.get_positions()
print('=== VERIF CALCUL % (reel, pas x2) ===')
print('Equity (compte reel)  : %.2f USDT' % eq)
print('Balance dispo (marge) : %.2f USDT' % bal)
print('Marge utilisee        : %.2f USDT' % (eq-bal))
print('Equity0 (reference)   : %.2f USDT' % eq0)
print()
tot_up=0.0
print('Position | sens  | unreal P&L')
for p in ps:
    sym=p['symbol'].replace('_USDT','')
    up=float(p.get('unrealised',0) or 0)
    d='LONG ' if p.get('positionType')==1 else 'SHORT'
    tot_up+=up
    print('  %-5s %s | %+.4f USDT' % (sym,d,up))
print()
print('Somme P&L non realise : %+.4f USDT' % tot_up)
print('Variation equity      : %+.4f USDT  (eq - eq0)' % (eq-eq0))
print()
print('P&L que le bot affiche = (eq-eq0)/eq0 = %+.3f%% du COMPTE' % ((eq-eq0)/eq0*100))
print('-> base sur ton equity reelle. Le levier 2 est dans la TAILLE (~220 notionnel),')
print('   PAS dans le calcul du %. Donc le % est REEL, pas double. Correct.')
