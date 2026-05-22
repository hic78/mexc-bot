#!/usr/bin/env python3
# test_live.py — Test positions MEXC RÉEL (une position LONG + SHORT)
# Usage: python3 /root/mexc-bot/test_live.py
# ⚠️  OUVRE ET FERME DE VRAIES POSITIONS — frais réels

import sys, os, time, logging, json

sys.path.insert(0, '/root/mexc-bot')
os.environ['DRY_RUN'] = 'false'

# ── Logging DEBUG vers stdout + fichier ───────────────────────────────────────
LOG_FILE = '/root/mexc-bot/test_live.log'
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, mode='w'),
        logging.StreamHandler(sys.stdout),
    ]
)
log = logging.getLogger('test_live')

from mexc_client import MEXCRestClient

client  = MEXCRestClient()
SYM     = 'DOGE_USDT'
COIN    = 'DOGE'
LEV     = 4
QTY     = 1          # 1 contract = 100 DOGE ≈ $11
SL_PCT  = 0.10

SEP = '=' * 60

def section(title: str):
    log.info(SEP)
    log.info(f'  {title}')
    log.info(SEP)

def raw(label: str, data):
    try:
        log.debug(f'{label}: {json.dumps(data, indent=2)}')
    except Exception:
        log.debug(f'{label}: {data}')


# ─────────────────────────────────────────────────────────────────────────────
section('TEST 1 — PING')
ping = client.ping()
raw('ping', ping)
log.info(f'Ping OK: {ping}')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 2 — BALANCE & EQUITY')
bal_raw = client._get('/api/v1/private/account/assets')
raw('assets', bal_raw)
balance = client.get_balance()
equity  = client.get_equity()
log.info(f'Balance disponible : ${balance:.4f} USDT')
log.info(f'Equity             : ${equity:.4f} USDT')

if balance < 1.5:
    log.error(f'Balance trop faible ({balance:.2f}$) — test annulé')
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 3 — TICKER')
ticker = client.get_ticker(SYM)
raw('ticker', ticker)
price = float(ticker.get('lastPrice', 0))
log.info(f'Prix {COIN}: ${price:.6f}')
margin_needed = price * 100 * QTY / LEV
log.info(f'Margin nécessaire pour {QTY} contrat(s): ${margin_needed:.4f}')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 4 — SET LEVERAGE')
lev_r = client.set_leverage(SYM, LEV)
raw('set_leverage', lev_r)
log.info(f'Leverage {LEV}x: success={lev_r.get("success")} code={lev_r.get("code")}')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 5 — POSITIONS EXISTANTES')
existing = client.get_positions(SYM)
raw('positions_before', existing)
if existing:
    log.warning(f'{len(existing)} position(s) existante(s) — fermeture...')
    for p in existing:
        pt = p.get('positionType', 1)  # 1=LONG, 2=SHORT
        cs = 4 if pt == 1 else 2       # 4=Close Long, 2=Close Short
        ev = int(p.get('vol', 1))
        log.info(f'Fermeture existante: positionType={pt} → side={cs} vol={ev}')
        cr = client.place_order(SYM, cs, ev, LEV)
        raw('close_existing', cr)
        log.info(f'Fermeture existante: success={cr.get("success")} data={cr.get("data")}')
        time.sleep(2)
else:
    log.info('Aucune position existante')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 6 — OPEN LONG (side=1)')
open_r = client.place_order(SYM, side=1, qty=QTY, leverage=LEV)
raw('open_long', open_r)
log.info(f'Open LONG: success={open_r.get("success")} data={open_r.get("data")} code={open_r.get("code")} msg={open_r.get("message","")!r}')

if not open_r.get('success'):
    log.error(f'ÉCHEC ouverture LONG: {open_r}')
    sys.exit(1)

order_id = open_r.get('data')
log.info(f'Order ID: {order_id}')
time.sleep(2)

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 7 — CONFIRM POSITION SUR EXCHANGE')
ticker2    = client.get_ticker(SYM)
fill_price = float(ticker2.get('lastPrice', price))
log.info(f'Prix estimé fill: ${fill_price:.6f}')

pos2 = client.get_positions(SYM)
raw('positions_after_open', pos2)
if pos2:
    p = pos2[0]
    log.info(f'Position confirmée: vol={p.get("vol")} positionType={p.get("positionType")} '
             f'openPrice={p.get("openPrice")} margin={p.get("im","?")} '
             f'unrealPnl={p.get("unrealizedPnl","?")}')
else:
    log.warning('Position non trouvée via get_positions (peut être latence exchange)')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 8 — PLACE SL PLAN ORDER (side=4 = Close Long)')
sl_price = fill_price * (1 - SL_PCT)
log.info(f'SL price: ${sl_price:.6f} ({SL_PCT*100:.0f}% sous entrée @ ${fill_price:.6f})')
sl_r = client.place_plan_order(SYM, side=4, vol=QTY, stop_price=sl_price, leverage=LEV)
raw('place_plan_order', sl_r)
log.info(f'SL plan order: success={sl_r.get("success")} data={sl_r.get("data")} code={sl_r.get("code")} msg={sl_r.get("message","")!r}')

sl_id = sl_r.get('data') if sl_r.get('success') else None
if not sl_id:
    log.warning('SL plan order NON PLACÉ — continuer quand même pour tester la fermeture')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 9 — LIST PLAN ORDERS ACTIFS')
plan_orders = client.get_plan_orders(SYM)
raw('plan_orders', plan_orders)
log.info(f'Plan orders actifs: {len(plan_orders)}')
for po in plan_orders:
    log.info(f'  PlanOrder: id={po.get("orderId")} stopPrice={po.get("stopPrice")} '
             f'side={po.get("side")} vol={po.get("vol")} status={po.get("status")}')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 10 — PNL INTERMÉDIAIRE (attente 8s)')
time.sleep(8)
ticker3    = client.get_ticker(SYM)
raw('ticker_mid', ticker3)
mid_price  = float(ticker3.get('lastPrice', fill_price))
pnl_pct    = (mid_price - fill_price) / fill_price * LEV * 100
log.info(f'Prix intermédiaire : ${mid_price:.6f}')
log.info(f'PnL LONG {LEV}x     : {pnl_pct:+.4f}%')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 11 — CANCEL SL PLAN ORDER')
if sl_id:
    cancel_r = client.cancel_plan_order(str(sl_id))
    raw('cancel_plan_order', cancel_r)
    log.info(f'Cancel SL: success={cancel_r.get("success")} code={cancel_r.get("code")}')
    time.sleep(1)
else:
    log.info('Pas de sl_id à annuler')

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 12 — CLOSE LONG (side=4 = Close Long)')
close_r = client.place_order(SYM, side=4, qty=QTY, leverage=LEV)
raw('close_long', close_r)
log.info(f'Close LONG: success={close_r.get("success")} data={close_r.get("data")} code={close_r.get("code")} msg={close_r.get("message","")!r}')

if not close_r.get('success'):
    log.error('ÉCHEC FERMETURE — POSITION PEUT ENCORE ÊTRE OUVERTE!')
    log.error(f'Réponse complète: {close_r}')
    sys.exit(1)

time.sleep(2)

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 13 — OPEN SHORT (side=3)')
ticker4    = client.get_ticker(SYM)
raw('ticker_before_short', ticker4)
short_price = float(ticker4.get('lastPrice', mid_price))
log.info(f'Prix pour SHORT: ${short_price:.6f}')

open_short = client.place_order(SYM, side=3, qty=QTY, leverage=LEV)
raw('open_short', open_short)
log.info(f'Open SHORT: success={open_short.get("success")} data={open_short.get("data")} code={open_short.get("code")} msg={open_short.get("message","")!r}')

if not open_short.get('success'):
    log.warning(f'SHORT échoué — possible: frais, liquidité, etc. {open_short}')
    short_ok = False
else:
    short_ok = True
    log.info('SHORT ouvert')
    time.sleep(2)

if short_ok:
    # Confirm short
    pos_short = client.get_positions(SYM)
    raw('positions_after_short', pos_short)
    if pos_short:
        ps = pos_short[0]
        log.info(f'Position SHORT confirmée: vol={ps.get("vol")} type={ps.get("positionType")} openPrice={ps.get("openPrice")}')

    # SL for short (side=2 = Close Short)
    sl_short_price = short_price * (1 + SL_PCT)
    log.info(f'SL SHORT: ${sl_short_price:.6f} ({SL_PCT*100:.0f}% au-dessus entrée)')
    sl_short_r = client.place_plan_order(SYM, side=2, vol=QTY, stop_price=sl_short_price, leverage=LEV)
    raw('sl_short', sl_short_r)
    log.info(f'SL SHORT: success={sl_short_r.get("success")} data={sl_short_r.get("data")}')
    sl_short_id = sl_short_r.get('data') if sl_short_r.get('success') else None

    time.sleep(5)

    # Cancel short SL
    if sl_short_id:
        cancel_short_sl = client.cancel_plan_order(str(sl_short_id))
        raw('cancel_sl_short', cancel_short_sl)
        log.info(f'Cancel SL SHORT: success={cancel_short_sl.get("success")}')
        time.sleep(1)

    # Close SHORT (side=2 = Close Short)
    section('TEST 14 — CLOSE SHORT (side=2)')
    close_short_r = client.place_order(SYM, side=2, qty=QTY, leverage=LEV)
    raw('close_short', close_short_r)
    log.info(f'Close SHORT: success={close_short_r.get("success")} data={close_short_r.get("data")} code={close_short_r.get("code")}')

    if not close_short_r.get('success'):
        log.error('ÉCHEC FERMETURE SHORT!')
        log.error(f'{close_short_r}')
    else:
        log.info('SHORT fermé OK')

    time.sleep(2)

# ─────────────────────────────────────────────────────────────────────────────
section('TEST 15 — SOLDE FINAL + VÉRIFICATION')
bal_final    = client.get_balance()
equity_final = client.get_equity()
ticker5      = client.get_ticker(SYM)
raw('ticker_final', ticker5)
exit_price   = float(ticker5.get('lastPrice', mid_price))

pnl_long = (exit_price - fill_price) / fill_price * LEV * 100

log.info(f'Balance finale   : ${bal_final:.4f} USDT')
log.info(f'Equity finale    : ${equity_final:.4f} USDT')
log.info(f'Delta balance    : {bal_final - balance:+.4f} USDT')
log.info(f'PnL LONG estimé  : {pnl_long:+.4f}%')

positions_final = client.get_positions(SYM)
raw('positions_final', positions_final)
if positions_final:
    log.error(f'⚠️ POSITION ENCORE OUVERTE: {positions_final}')
    log.error('Vérifier sur exchange manuellement!')
else:
    log.info('Aucune position ouverte — ✓')

plan_final = client.get_plan_orders(SYM)
if plan_final:
    log.warning(f'Plan orders encore actifs: {len(plan_final)} — nettoyer manuellement')
    raw('plan_orders_final', plan_final)

section('RÉSUMÉ TEST LIVE')
log.info(f'LONG  : open=${fill_price:.6f} | estimé close=${exit_price:.6f} | pnl={pnl_long:+.4f}%')
log.info(f'Balance initiale : ${balance:.4f} → finale : ${bal_final:.4f} (delta: {bal_final-balance:+.4f})')
log.info(f'Log complet → {LOG_FILE}')
log.info('TEST TERMINÉ')
