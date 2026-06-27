import xsmom2_bot as b
c=b.MEXCRestClient()
print('Params bot live: HORIZONS=%s VOL_WIN=%s Q=%s REBAL=%sh VT=%s KLINES=%s' % (b.HORIZONS,b.VOL_WIN,b.Q,b.REBAL_H,b.VT_TARGET,b.KLINES))
sc={}
for coin in b.UNIVERSE:
    cl=b.fetch_closes(c,coin)
    r=b.momentum_score(cl) if cl else None
    if r: sc[coin]=r[0]
rank=sorted(sc,key=lambda x:sc[x])
Q=b.Q
longs=set(rank[-Q:]); shorts=set(rank[:Q])
print('Coins scorés: %d/%d' % (len(sc),len(b.UNIVERSE)))
print('SIGNAL top%d LONG : %s' % (Q,','.join(sorted(longs))))
print('SIGNAL bot%d SHORT: %s' % (Q,','.join(sorted(shorts))))
# positions réelles
ps=c.get_positions()
pL=set(p['symbol'].replace('_USDT','') for p in ps if p.get('positionType')==1)
pS=set(p['symbol'].replace('_USDT','') for p in ps if p.get('positionType')==2)
print('LIVE     LONG : %s' % ','.join(sorted(pL)))
print('LIVE     SHORT: %s' % ','.join(sorted(pS)))
print('--> LONG match: %s | SHORT match: %s' % (longs==pL, shorts==pS))
