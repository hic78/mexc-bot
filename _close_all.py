"""
Ferme TOUTES les positions ouvertes en live MEXC avant deploy Cycle 6.
À exécuter sur le VPS dans /root/mexc-bot/.
"""
import json, sys, time
sys.path.insert(0, '/root/mexc-bot')
from mexc_client import MEXCRestClient
from config import LEVERAGE

print('=== CLOSE ALL POSITIONS (deploy Cycle 6) ===', flush=True)
client = MEXCRestClient()

with open('/root/mexc-bot/state.json') as f:
    state = json.load(f)

closed = []
errors = []
for coin, data in state.items():
    if coin == '__coins__':
        continue
    pos = data.get('position')
    if not pos:
        continue
    direction = pos['direction']
    qty = pos['qty']
    sym = f'{coin}_USDT'
    close_side = 4 if direction == 'LONG' else 2

    print(f'\n>>> Closing {coin} {direction} qty={qty}', flush=True)
    for attempt in range(3):
        try:
            result = client.place_order(sym, side=close_side, qty=qty, leverage=LEVERAGE)
            if result.get('success'):
                print(f'  OK closed: order_id={result.get("data")}', flush=True)
                closed.append({'coin': coin, 'dir': direction, 'qty': qty})
                # Reset position in state
                state[coin]['position'] = None
                break
            else:
                print(f'  attempt {attempt+1} failed: {result}', flush=True)
                time.sleep(2)
        except Exception as e:
            print(f'  attempt {attempt+1} error: {e}', flush=True)
            time.sleep(2)
    else:
        errors.append({'coin': coin, 'dir': direction})

# Save state with positions cleared
with open('/root/mexc-bot/state.json', 'w') as f:
    json.dump(state, f, indent=2)

print(f'\n=== RESULT ===', flush=True)
print(f'Closed: {len(closed)}', flush=True)
for c in closed:
    print(f'  - {c["coin"]} {c["dir"]} qty={c["qty"]}', flush=True)
print(f'Errors: {len(errors)}', flush=True)
for e in errors:
    print(f'  - {e["coin"]} {e["dir"]}', flush=True)
print('\nstate.json reset (positions=null)', flush=True)
