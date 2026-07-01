import xsmom2_bot as b
c=b.MEXCRestClient(); b.init_contract_sizes(b.UNIVERSE)
ps=c.get_positions(); eq=c.get_equity()
L=[p['symbol'].replace('_USDT','') for p in ps if p.get('positionType')==1]
S=[p['symbol'].replace('_USDT','') for p in ps if p.get('positionType')==2]
ph=sum(len([o for o in (c._get('/api/v1/private/order/list/open_orders/'+b.to_mexc_symbol(x)).get('data') or []) if isinstance(o,dict) and o.get('state')==2]) for x in b.UNIVERSE)
print('POSITIONS %d (%dL/%dS): LONG %s | SHORT %s' % (len(ps),len(L),len(S),','.join(sorted(L)),','.join(sorted(S))))
print('EQUITY $%.2f | depuis deploy $109.28 = %+.2f%% | fantomes: %s' % (eq,(eq/109.28-1)*100,ph if ph else 'AUCUN'))
