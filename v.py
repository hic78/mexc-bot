import xsmom2_bot as b
c=b.MEXCRestClient()
ps=c.get_positions()
ph=sum(len([o for o in (c._get('/api/v1/private/order/list/open_orders/'+b.to_mexc_symbol(x)).get('data') or []) if isinstance(o,dict) and o.get('state')==2]) for x in b.UNIVERSE)
print('POSITIONS OUVERTES:', len(ps), '->', 'TOUT FERMÉ ✅' if len(ps)==0 else [p['symbol'] for p in ps])
print('ORDRES OUVERTS:', ph if ph else 'AUCUN ✅')
print('EQUITY (cash, plus de positions): $%.2f' % c.get_equity())
print('BALANCE libre: $%.2f' % c.get_balance())
