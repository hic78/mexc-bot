#!/usr/bin/env python3
# test_planorder.py — Debug SL plan orders MEXC
# Usage: python3 /root/mexc-bot/test_planorder.py

import sys, os, time, logging, json

sys.path.insert(0, '/root/mexc-bot')
os.environ['DRY_RUN'] = 'false'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler('/root/mexc-bot/test_planorder.log', mode='w'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('test_planorder')

from mexc_client import MEXCRestClient

client = MEXCRestClient()
SYM = 'DOGE_USDT'
QTY = 1
LEV = 4

# ── Step 1: Get current price ──────────────────────────
ticker = client.get_ticker(SYM)
price = float(ticker.get('lastPrice', 0))
log.info(f'Price: {price}')

# ── Step 2: Open a LONG position ───────────────────────
log.info('--- Opening LONG ---')
r = client.place_order(SYM, side=1, qty=QTY, leverage=LEV)
log.info(f'Open LONG: success={r.get("success")} code={r.get("code")} data={r.get("data")}')

if not r.get('success'):
    log.error('Cannot open position, aborting')
    sys.exit(1)

time.sleep(3)

# ── Step 3: Confirm position and get fill price ─────────
pos = client.get_positions(SYM)
if pos:
    fill_price = float(pos[0].get('openPrice', price))
    log.info(f'Fill price: {fill_price}')
else:
    fill_price = price
    log.warning('Position not found via API, using ticker price')

sl_price = round(fill_price * 0.90, 6)
log.info(f'SL price: {sl_price}')

# ── Step 4: Test plan order variants ───────────────────
log.info('=== Testing plan order body variants ===')

# Variant A — minimal body (no price field)
body_a = {
    'symbol': SYM,
    'vol': QTY,
    'side': 4,
    'type': 5,
    'openType': 1,
    'leverage': LEV,
    'stopPrice': sl_price,
    'planCategory': 1,
}
log.info(f'Variant A (no price): {json.dumps(body_a)}')
ra = client._post('/api/v1/private/planorder/place', body_a)
log.info(f'Variant A result: success={ra.get("success")} code={ra.get("code")} data={ra.get("data")} msg={ra.get("message")}')

if ra.get('success'):
    log.info('Variant A WORKS — cancelling and noting params')
    plan_id = ra.get('data')
    if plan_id:
        client.cancel_plan_order(str(plan_id))
    time.sleep(1)

# Variant B — with triggerType field
body_b = {
    'symbol': SYM,
    'vol': QTY,
    'side': 4,
    'type': 5,
    'openType': 1,
    'leverage': LEV,
    'stopPrice': sl_price,
    'planCategory': 1,
    'price': 0,
    'triggerType': 1,
}
log.info(f'Variant B (triggerType=1): {json.dumps(body_b)}')
rb = client._post('/api/v1/private/planorder/place', body_b)
log.info(f'Variant B result: success={rb.get("success")} code={rb.get("code")} data={rb.get("data")} msg={rb.get("message")}')

if rb.get('success'):
    plan_id = rb.get('data')
    if plan_id:
        client.cancel_plan_order(str(plan_id))
    time.sleep(1)

# Variant C — stop-limit: type=1 (limit) instead of 5 (market)
ticker2 = client.get_ticker(SYM)
price2 = float(ticker2.get('lastPrice', fill_price))
exec_price = round(sl_price * 0.99, 6)  # limit below SL
body_c = {
    'symbol': SYM,
    'vol': QTY,
    'side': 4,
    'type': 1,
    'openType': 1,
    'leverage': LEV,
    'stopPrice': sl_price,
    'price': exec_price,
    'planCategory': 1,
}
log.info(f'Variant C (stop-limit, type=1, price={exec_price}): {json.dumps(body_c)}')
rc = client._post('/api/v1/private/planorder/place', body_c)
log.info(f'Variant C result: success={rc.get("success")} code={rc.get("code")} data={rc.get("data")} msg={rc.get("message")}')

if rc.get('success'):
    plan_id = rc.get('data')
    if plan_id:
        client.cancel_plan_order(str(plan_id))
    time.sleep(1)

# ── Step 5: Test plan order LIST endpoints ─────────────
log.info('=== Testing plan order list endpoints ===')
endpoints = [
    '/api/v1/private/planorder/list/open',
    '/api/v1/private/planorder/list',
    '/api/v1/private/stopplanorder/list/open',
    '/api/v1/private/plan_order/list/open',
    '/api/v1/private/planorder/orders',
]
for ep in endpoints:
    try:
        result = client._get(ep, {'symbol': SYM})
        log.info(f'  {ep}: success={result.get("success")} code={result.get("code")} data_type={type(result.get("data")).__name__}')
        if result.get('data'):
            log.info(f'    data sample: {json.dumps(result.get("data"))[:200]}')
    except Exception as e:
        log.error(f'  {ep}: EXCEPTION {e}')

# ── Step 6: Close LONG ─────────────────────────────────
log.info('--- Closing LONG ---')
r2 = client.place_order(SYM, side=4, qty=QTY, leverage=LEV)
log.info(f'Close LONG: success={r2.get("success")} code={r2.get("code")} data={r2.get("data")}')

time.sleep(2)
bal = client.get_balance()
log.info(f'Final balance: {bal:.4f} USDT')
pos_final = client.get_positions(SYM)
log.info(f'Positions remaining: {len(pos_final)}')

log.info('=== TEST PLANORDER DONE ===')
