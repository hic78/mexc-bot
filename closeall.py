import xsmom2_bot as b, time
c=b.MEXCRestClient()
ps=c.get_positions()
print('positions à fermer:', len(ps))
for p in ps:
    sym=p['symbol']; coin=sym.replace('_USDT',''); pt=p.get('positionType'); v=int(float(p['holdVol']))
    side=4 if pt==1 else 2   # 4=close long, 2=close short
    # annuler d'abord tout ordre ouvert sur ce symbole
    try: c._post('/api/v1/private/order/cancel_all', {'symbol': sym})
    except Exception: pass
    time.sleep(0.5)
    r=b._order_retry(c, sym, side, v, coin)
    ok=(r.get('success') or r.get('code')==0)
    print('  CLOSE %-5s %-5s vol=%d -> %s' % (coin,'LONG' if pt==1 else 'SHORT',v,'OK' if ok else r))
    time.sleep(0.8)
