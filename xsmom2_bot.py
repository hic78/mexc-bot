#!/usr/bin/env python3
"""
xsmom2_bot.py — Cross-Sectional Momentum bot for MEXC Futures.
=================================================================
NOUVEAU bot, INDÉPENDANT de bot.py (C150) et de champion-v4. NE LES TOUCHE PAS.

Stratégie xsmom2 (backtest validé Sharpe ~2.4, holdout +1.11) :
  - Classe N coins liquides par momentum multi-horizon ÷ volatilité (168/336/720h ÷ vol168)
  - Long top Q / Short bottom Q, equal-weight, market-neutral
  - Rebalance toutes les 24h
  - Exécution MARKET (taker, code testé). Levier 2.
  - Kill-switch à -15% de l'équité.
  - DRY_RUN par défaut ON (passe de vérification AVANT tout ordre réel).

Logs HAUTE QUALITÉ (standard MAS 2026) :
  - xs_logs/xsmom2.log     : log détaillé rotatif (DEBUG, 10MB×5)
  - xs_logs/events.jsonl   : événements structurés JSON (signaux, ordres, erreurs)
  - console                : INFO+
Toute erreur est loggée avec traceback complet.
"""
import os, sys, time, json, math, logging, traceback
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

# --- réutilise le client + helpers TESTÉS (mexc-bot existant) ---
from mexc_client import MEXCRestClient
from config import to_mexc_symbol, get_contract_size, init_contract_sizes

# ===================== CONFIG (indépendante de l'ancien bot) =====================
UNIVERSE   = os.getenv('XS_UNIVERSE', 'BTC,ETH,SOL,XRP,DOGE,BNB,AVAX,LINK,LTC,ADA,DOT,NEAR,UNI,TRX,APT').split(',')
Q          = int(os.getenv('XS_Q', '5'))             # top/bottom Q (2Q positions au total)
LEVERAGE   = int(os.getenv('XS_LEV', '2'))           # levier
MARGIN_PCT = float(os.getenv('XS_MARGIN_PCT', '0.09'))  # marge par position (10 pos × 9% = 90% déployé)
HORIZONS   = [168, 336, 720]                          # heures (1sem/2sem/1mois)
VOL_WIN    = 168                                      # fenêtre vol (heures)
REBAL_H    = int(os.getenv('XS_REBAL_H', '24'))       # rebalance toutes les 24h
KILL_DD    = float(os.getenv('XS_KILL_DD', '0.15'))   # kill-switch -15%
DRY_RUN    = os.getenv('XS_DRY_RUN', '1') != '0'      # défaut ON (sécurité)
KLINES     = 800                                      # >720+vol
INTERVAL   = 'Min60'

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'xs_logs')
os.makedirs(LOG_DIR, exist_ok=True)

# ===================== LOGGING HAUTE QUALITÉ =====================
def setup_logging():
    lg = logging.getLogger('xsmom2'); lg.setLevel(logging.DEBUG); lg.handlers.clear()
    fmt = logging.Formatter('%(asctime)s | %(levelname)-7s | %(funcName)-18s | %(message)s', '%Y-%m-%d %H:%M:%S')
    fh = RotatingFileHandler(os.path.join(LOG_DIR, 'xsmom2.log'), maxBytes=10*1024*1024, backupCount=5)
    fh.setLevel(logging.DEBUG); fh.setFormatter(fmt)
    ch = logging.StreamHandler(sys.stdout); ch.setLevel(logging.INFO); ch.setFormatter(fmt)
    lg.addHandler(fh); lg.addHandler(ch); return lg
log = setup_logging()

def jlog(event, **kv):
    """Événement structuré JSON (MAS 2026)."""
    rec = {'ts': datetime.now(timezone.utc).isoformat(), 'event': event, **kv}
    try:
        with open(os.path.join(LOG_DIR, 'events.jsonl'), 'a') as f:
            f.write(json.dumps(rec, default=str) + '\n')
    except Exception as e:
        log.error(f'jlog erreur: {e}')

# --- Telegram (version SYNC, réutilise TG_TOKEN/TG_CHAT de l'ancien bot) ---
import requests
try:
    from config import TG_TOKEN, TG_CHAT
except Exception:
    TG_TOKEN, TG_CHAT = None, None
def tg(msg):
    try:
        if TG_TOKEN and TG_CHAT:
            requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                          json={'chat_id': TG_CHAT, 'text': f'🤖 xsmom2 | {msg}'}, timeout=8)
    except Exception as e:
        log.warning(f'tg erreur: {e}')

# ===================== SIGNAL =====================
def fetch_closes(client, coin):
    sym = to_mexc_symbol(coin)
    try:
        k = client.get_klines_full(sym, INTERVAL, KLINES)
        if not k or len(k) < max(HORIZONS) + 5:
            log.warning(f'[{coin}] klines insuffisants: {len(k) if k else 0} (besoin {max(HORIZONS)+5})')
            return None
        return [b['c'] for b in k]
    except Exception as e:
        log.error(f'[{coin}] fetch_closes EXCEPTION: {e}\n{traceback.format_exc()}')
        return None

def momentum_score(closes):
    n = len(closes)
    rets = [(closes[i]/closes[i-1]-1) for i in range(n-VOL_WIN, n) if closes[i-1] > 0]
    if len(rets) < VOL_WIN*0.8: return None
    mean = sum(rets)/len(rets)
    var = sum((r-mean)**2 for r in rets)/(len(rets)-1)
    vol = var**0.5
    if vol <= 0: return None
    s = 0.0
    for H in HORIZONS:
        if n-1-H < 0 or closes[-1-H] <= 0: return None
        s += (closes[-1]/closes[-1-H] - 1) / vol
    return s, vol, closes[-1]

def compute_targets(client):
    scores = {}; prices = {}
    for coin in UNIVERSE:
        closes = fetch_closes(client, coin)
        if not closes: continue
        ms = momentum_score(closes)
        if ms is None:
            log.warning(f'[{coin}] score invalide (skip)'); continue
        scores[coin] = ms[0]; prices[coin] = ms[2]
        log.debug(f'[{coin}] score={ms[0]:+.3f} vol={ms[1]:.5f} px={ms[2]:.6f}')
    if len(scores) < 2*Q:
        log.error(f'Coins valides {len(scores)} < {2*Q} requis — REBALANCE ANNULÉ.')
        jlog('rebalance_skip', reason='not_enough_coins', valid=len(scores)); return None, None
    ranked = sorted(scores, key=lambda c: scores[c])
    shorts = ranked[:Q]; longs = ranked[-Q:]
    log.info(f'📈 LONGS  (top {Q}): {longs}')
    log.info(f'📉 SHORTS (bot {Q}): {shorts}')
    jlog('targets', longs=longs, shorts=shorts, scores={c: round(scores[c],3) for c in scores})
    targets = {}
    for c in longs: targets[c] = 1
    for c in shorts: targets[c] = -1
    return targets, prices

# ===================== SIZING (formule TESTÉE de bot.py) =====================
def calc_qty(balance, price, coin):
    """qty contrats = round(balance * MARGIN_PCT * LEVERAGE / (price * contract_size))."""
    cs = get_contract_size(coin)
    if not cs or price <= 0:
        log.error(f'[{coin}] calc_qty: cs={cs} price={price} invalide'); return 0
    margin = balance * MARGIN_PCT
    notional = margin * LEVERAGE
    qty_raw = notional / (price * cs)
    qty = max(1, round(qty_raw))
    log.debug(f'[{coin}] calc_qty: bal={balance:.2f} margin={margin:.2f} notional={notional:.2f} px={price:.6f} cs={cs} raw={qty_raw:.3f} → {qty} contrats (≈${qty*price*cs:.1f})')
    return qty

# ===================== POSITIONS =====================
def current_positions(client):
    """Retourne {coin: (direction, volume)}. positionType MEXC: 1=long, 2=short."""
    out = {}
    try:
        for p in client.get_positions():
            sym = p.get('symbol', ''); coin = sym.replace('_USDT', '')
            ptype = p.get('positionType'); vol = float(p.get('holdVol', 0) or 0)
            if vol <= 0: continue
            d = 1 if ptype == 1 else -1
            out[coin] = (d, vol)
    except Exception as e:
        log.error(f'current_positions EXCEPTION: {e}\n{traceback.format_exc()}')
    return out

# side codes place_order: 1=Open Long, 3=Open Short, 4=Close Long, 2=Close Short
def _order_retry(client, sym, side, qty, coin, max_try=4):
    """Place un ordre avec retry sur rate-limit (code 510) — backoff 1.5s/3s/5s."""
    r = {}
    for attempt in range(max_try):
        r = client.place_order(sym, side, qty, LEVERAGE)
        if r.get('success') or r.get('code') == 0:
            return r
        if r.get('code') == 510:  # rate limit
            wait = 1.5 * (attempt + 1)
            log.warning(f'[{coin}] rate-limit (510), retry {attempt+1}/{max_try} dans {wait:.1f}s')
            time.sleep(wait); continue
        return r  # autre erreur → on rend
    return r

def open_pos(client, coin, direction, qty):
    sym = to_mexc_symbol(coin); side = 1 if direction == 1 else 3
    if DRY_RUN:
        log.info(f'🔵 [DRY] OPEN {"LONG" if direction==1 else "SHORT"} {coin} qty={qty} (side={side}, lev={LEVERAGE})')
        jlog('order_dry', action='open', coin=coin, dir=direction, qty=qty, side=side); return {'dry': True}
    try:
        client.set_leverage(sym, LEVERAGE)
        r = _order_retry(client, sym, side, qty, coin)
        ok = r.get('success', False) or r.get('code') == 0
        log.info(f'{"✅" if ok else "❌"} OPEN {"LONG" if direction==1 else "SHORT"} {coin} qty={qty} → {r}')
        jlog('order', action='open', coin=coin, dir=direction, qty=qty, side=side, resp=r); return r
    except Exception as e:
        log.error(f'[{coin}] open_pos EXCEPTION: {e}\n{traceback.format_exc()}')
        jlog('order_error', action='open', coin=coin, err=str(e)); return None

def close_pos(client, coin, direction, qty):
    sym = to_mexc_symbol(coin); side = 4 if direction == 1 else 2  # 4=Close Long, 2=Close Short
    if DRY_RUN:
        log.info(f'🟠 [DRY] CLOSE {"LONG" if direction==1 else "SHORT"} {coin} qty={qty} (side={side})')
        jlog('order_dry', action='close', coin=coin, dir=direction, qty=qty, side=side); return {'dry': True}
    try:
        r = _order_retry(client, sym, side, qty, coin)
        ok = r.get('success', False) or r.get('code') == 0
        log.info(f'{"✅" if ok else "❌"} CLOSE {coin} qty={qty} → {r}')
        jlog('order', action='close', coin=coin, dir=direction, qty=qty, side=side, resp=r); return r
    except Exception as e:
        log.error(f'[{coin}] close_pos EXCEPTION: {e}\n{traceback.format_exc()}')
        jlog('order_error', action='close', coin=coin, err=str(e)); return None

# ===================== REBALANCE =====================
def rebalance(client, equity0):
    log.info('═'*60); log.info('🔄 REBALANCE — début')
    bal = client.get_balance(); eq = client.get_equity()
    log.info(f'💰 Balance={bal:.2f} Equity={eq:.2f} USDT (initial={equity0:.2f})')
    jlog('cycle_start', balance=bal, equity=eq, equity0=equity0)

    # --- KILL-SWITCH ---
    if equity0 > 0 and eq < equity0 * (1 - KILL_DD):
        log.error(f'🛑 KILL-SWITCH: equity {eq:.2f} < {equity0*(1-KILL_DD):.2f} (-{KILL_DD*100:.0f}%). FERMETURE TOTALE + STOP.')
        jlog('kill_switch', equity=eq, equity0=equity0)
        tg(f'🛑 KILL-SWITCH déclenché ! Equity ${eq:.2f} (-{(1-eq/equity0)*100:.1f}%). Fermeture totale + arrêt.')
        for coin, (d, vol) in current_positions(client).items(): close_pos(client, coin, d, int(vol)); time.sleep(0.8)
        return False  # stop

    targets, prices = compute_targets(client)
    if targets is None: return True  # skip ce cycle, continue

    cur = current_positions(client)
    log.info(f'Positions actuelles: { {c: ("L" if d>0 else "S")+str(int(v)) for c,(d,v) in cur.items()} }')

    # 1) FERMER ce qui n'est plus dans la cible (ou mauvais sens)
    for coin, (d, vol) in cur.items():
        if coin not in targets or targets[coin] != d:
            log.info(f'➡️  Fermeture {coin} (plus dans la cible ou sens inversé)')
            close_pos(client, coin, d, int(vol)); time.sleep(0.8)

    # 2) OUVRIR les nouvelles cibles (pas déjà tenues dans le bon sens)
    for coin, direction in targets.items():
        if coin in cur and cur[coin][0] == direction:
            log.debug(f'[{coin}] déjà en position {"L" if direction>0 else "S"}, on garde'); continue
        price = prices.get(coin)
        if not price: log.warning(f'[{coin}] pas de prix, skip open'); continue
        qty = calc_qty(bal, price, coin)
        if qty < 1: log.warning(f'[{coin}] qty={qty} < 1, skip'); continue
        open_pos(client, coin, direction, qty); time.sleep(0.8)

    log.info('🔄 REBALANCE — fin'); log.info('═'*60)
    jlog('cycle_end', n_targets=len(targets))
    pnl = eq - equity0; longs = [c for c,d in targets.items() if d>0]; shorts = [c for c,d in targets.items() if d<0]
    tg(f"Rebalance OK | Equity ${eq:.2f} | P&L {pnl:+.2f}$ ({(pnl/equity0*100) if equity0 else 0:+.1f}%)\n📈 {','.join(longs)}\n📉 {','.join(shorts)}")
    return True

# ===================== MAIN =====================
def main():
    log.info('╔'+'═'*58+'╗')
    log.info(f'║ xsmom2_bot DÉMARRAGE — DRY_RUN={DRY_RUN} LEV={LEVERAGE} Q={Q} MARGIN={MARGIN_PCT} ║')
    log.info(f'║ Univers ({len(UNIVERSE)}): {",".join(UNIVERSE)}')
    log.info(f'║ Rebalance={REBAL_H}h | Kill-switch=-{KILL_DD*100:.0f}% | Horizons={HORIZONS}')
    log.info('╚'+'═'*58+'╝')
    if DRY_RUN:
        log.info('⚠️  MODE DRY_RUN : AUCUN ordre réel ne sera placé. Passe de VÉRIFICATION.')
        log.info('   Pour passer en RÉEL : export XS_DRY_RUN=0 puis relancer.')

    client = MEXCRestClient()
    try:
        init_contract_sizes([c for c in UNIVERSE])
    except Exception as e:
        log.error(f'init_contract_sizes erreur (continue): {e}')
    eq0 = client.get_equity()
    log.info(f'💰 Équité initiale: {eq0:.2f} USDT')
    jlog('boot', equity0=eq0, dry_run=DRY_RUN, lev=LEVERAGE, q=Q, universe=UNIVERSE)
    if not DRY_RUN: tg(f'🚀 Démarré | Equity ${eq0:.2f} | LEV={LEVERAGE} Q={Q} | rebal {REBAL_H}h | kill -{KILL_DD*100:.0f}%')

    if DRY_RUN:
        # passe unique de vérification
        rebalance(client, eq0)
        log.info('✅ VÉRIFICATION TERMINÉE. Regarde les ordres [DRY] ci-dessus + xs_logs/xsmom2.log.')
        log.info('   Si tout est correct (coins, sens, tailles) → export XS_DRY_RUN=0 et relance pour le RÉEL.')
        return

    # boucle réelle
    while True:
        try:
            cont = rebalance(client, eq0)
            if not cont:
                log.error('🛑 Arrêt (kill-switch).'); break
        except Exception as e:
            log.error(f'BOUCLE EXCEPTION: {e}\n{traceback.format_exc()}')
            jlog('loop_error', err=str(e)); tg(f'⚠️ Erreur boucle: {str(e)[:120]}')
        log.info(f'😴 Sommeil {REBAL_H}h jusqu\'au prochain rebalance...')
        time.sleep(REBAL_H * 3600)

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log.info('Interruption manuelle (Ctrl-C).')
    except Exception as e:
        log.error(f'FATAL: {e}\n{traceback.format_exc()}')
        sys.exit(1)
