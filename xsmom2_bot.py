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
import os, sys, time, json, math, logging, traceback, statistics
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

# --- réutilise le client + helpers TESTÉS (mexc-bot existant) ---
from mexc_client import MEXCRestClient
from config import to_mexc_symbol, get_contract_size, init_contract_sizes, get_price_decimals

# ===================== CONFIG (indépendante de l'ancien bot) =====================
UNIVERSE   = os.getenv('XS_UNIVERSE', 'BTC,ETH,SOL,XRP,DOGE,BNB,AVAX,LINK,LTC,ADA,DOT,NEAR,UNI,TRX,APT').split(',')
Q          = int(os.getenv('XS_Q', '5'))             # top/bottom Q (2Q positions au total)
LEVERAGE   = int(os.getenv('XS_LEV', '2'))           # levier
MARGIN_PCT = float(os.getenv('XS_MARGIN_PCT', '0.09'))  # marge par position (10 pos × 9% = 90% déployé)
HORIZONS   = [168, 336, 720]                          # heures (1sem/2sem/1mois)
VOL_WIN    = 168                                      # fenêtre vol (heures)
REBAL_H    = int(os.getenv('XS_REBAL_H', '24'))       # rebalance toutes les 24h
KILL_DD    = float(os.getenv('XS_KILL_DD', '0.15'))   # kill-switch -15%
VT_TARGET  = 0.40                                      # vol cible annualisée (= backtest)
VT_MIN     = float(os.getenv('XS_VT_MIN', '0.40'))    # backtest=0.2 mais sous le min MEXC sur $110 → 0.4
VT_MAX     = float(os.getenv('XS_VT_MAX', '1.00'))    # backtest=3.0 mais sur-déploierait le compte → 1.0
DRY_RUN    = os.getenv('XS_DRY_RUN', '1') != '0'      # défaut ON (sécurité)
USE_MAKER  = os.getenv('XS_MAKER', '1') != '0'        # exécution MAKER (post-only limit) au lieu de market
MAKER_CHASE= int(os.getenv('XS_MAKER_CHASE', '3'))    # nb de re-post si pas rempli, puis fallback taker
MAKER_WAIT = int(os.getenv('XS_MAKER_WAIT', '6'))     # secondes d'attente de fill par essai
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

# --- Commandes Telegram interactives (comme l'ancien bot) ---
import threading
STOP_FLAG = {'stop': False}

def _tg_updates(offset):
    try:
        r = requests.get(f'https://api.telegram.org/bot{TG_TOKEN}/getUpdates',
                         params={'offset': offset, 'timeout': 15}, timeout=20)
        return r.json().get('result', [])
    except Exception: return []

def _handle_cmd(client, eq0, text):
    cmd = text.strip().split()[0].lower()
    ps = lambda: client.get_positions()
    if cmd in ('/status', '/positions', '/s'):
        p = ps(); eq = client.get_equity(); pnl = eq - eq0
        L = [x['symbol'].replace('_USDT','') for x in p if x.get('positionType')==1]
        S = [x['symbol'].replace('_USDT','') for x in p if x.get('positionType')==2]
        return f"📊 STATUS\nEquity ${eq:.2f} | P&L {pnl:+.2f}$ ({(pnl/eq0*100) if eq0 else 0:+.1f}%)\n📈 LONG: {','.join(L) or '—'}\n📉 SHORT: {','.join(S) or '—'}\n{len(p)} positions"
    if cmd in ('/balance', '/b'):
        return f"💰 Balance dispo: ${client.get_balance():.2f}\n💼 Equity: ${client.get_equity():.2f}"
    if cmd == '/pnl':
        lines = []
        for x in ps():
            c = x['symbol'].replace('_USDT',''); d = 'L' if x.get('positionType')==1 else 'S'
            up = x.get('unrealised', x.get('realised', 0))
            lines.append(f"{c}({d}): {float(up or 0):+.3f}$")
        return "📈 PnL par position:\n" + ("\n".join(lines) or '—')
    if cmd == '/risk':
        eq = client.get_equity(); dd = (1 - eq/eq0)*100 if eq0 else 0
        return f"🛡️ RISK\nEquity ${eq:.2f} (initial ${eq0:.2f})\nDrawdown actuel: {dd:+.1f}%\nKill-switch: -{KILL_DD*100:.0f}% (à ${eq0*(1-KILL_DD):.2f})\nLevier: {LEVERAGE}x | Q={Q}"
    if cmd == '/config':
        return f"⚙️ CONFIG\nUnivers ({len(UNIVERSE)}): {','.join(UNIVERSE)}\nQ={Q} LEV={LEVERAGE} MARGIN={MARGIN_PCT}\nRebal={REBAL_H}h | Horizons={HORIZONS}\nKill=-{KILL_DD*100:.0f}% | Exéc=MARKET | Barre=FERMÉE"
    if cmd in ('/coins', '/coin'):
        return f"🪙 Univers ({len(UNIVERSE)} coins):\n{', '.join(UNIVERSE)}"
    if cmd == '/orders':
        lines = []
        for x in ps():
            c = x['symbol'].replace('_USDT',''); d = 'LONG' if x.get('positionType')==1 else 'SHORT'
            ep = x.get('holdAvgPrice', x.get('openAvgPrice', '?')); vol = x.get('holdVol','?')
            lines.append(f"{c} {d} vol={vol} @ {ep}")
        return "📋 POSITIONS ouvertes:\n" + ("\n".join(lines) or '—') + "\n(xsmom2 = rebalance 24h, pas de SL fixe — sortie au prochain rebalance)"
    if cmd == '/trades':
        try:
            evs = [json.loads(l) for l in open(os.path.join(LOG_DIR,'events.jsonl')) if '"order"' in l or 'order_dry' in l]
            evs = [e for e in evs if e.get('event','').startswith('order')][-10:]
            lines = [f"{e['ts'][11:19]} {e.get('action','')} {e.get('coin','')} {('L' if e.get('dir')==1 else 'S')} qty={e.get('qty','')}" for e in evs]
            return "📜 10 derniers ordres:\n" + ("\n".join(lines) or '—')
        except Exception as e: return f"trades: {e}"
    if cmd == '/logs':
        try:
            ls = open(os.path.join(LOG_DIR,'xsmom2.log')).readlines()[-15:]
            return "📄 15 dernières lignes:\n" + ''.join(l.split('|',2)[-1] if '|' in l else l for l in ls)[-3500:]
        except Exception as e: return f"logs: {e}"
    if cmd == '/close':
        parts = text.split()
        if len(parts) < 2: return "Usage: /close COIN confirm"
        coin = parts[1].upper()
        if 'confirm' not in text.lower(): return f"⚠️ Fermer {coin} ? Confirme:\n/close {coin} confirm"
        for x in ps():
            if x['symbol'].replace('_USDT','') == coin:
                d = 1 if x.get('positionType')==1 else -1
                close_pos(client, coin, d, int(float(x.get('holdVol',0))))
                return f"✅ {coin} fermé manuellement."
        return f"❓ {coin} pas en position."
    if cmd == '/addcoin':
        parts = text.split()
        if len(parts) < 2: return "Usage: /addcoin COIN"
        coin = parts[1].upper()
        if coin in UNIVERSE: return f"{coin} déjà dans l'univers."
        UNIVERSE.append(coin); return f"✅ {coin} ajouté (effet au prochain rebalance). Univers: {len(UNIVERSE)}"
    if cmd == '/removecoin':
        parts = text.split()
        if len(parts) < 2: return "Usage: /removecoin COIN"
        coin = parts[1].upper()
        if coin not in UNIVERSE: return f"{coin} pas dans l'univers."
        UNIVERSE.remove(coin); return f"✅ {coin} retiré (effet au prochain rebalance). Univers: {len(UNIVERSE)}"
    if cmd == '/stop':
        if 'confirm' not in text.lower():
            return "⚠️ /stop ferme TOUTES les positions + arrête le bot.\nConfirme avec: /stop confirm"
        STOP_FLAG['stop'] = True
        for x in ps():
            c = x['symbol'].replace('_USDT',''); d = 1 if x.get('positionType')==1 else -1
            close_pos(client, c, d, int(float(x.get('holdVol', 0)))); time.sleep(0.8)
        return "🛑 STOP: toutes positions fermées. Bot s'arrête."
    if cmd in ('/help', '/h', '/start'):
        return ("📋 COMMANDES xsmom2\n"
                "/status  — positions + P&L\n/balance — solde dispo\n/pnl     — P&L par position\n"
                "/orders  — positions détaillées\n/trades  — 10 derniers ordres\n/coins   — univers\n"
                "/risk    — drawdown + kill-switch\n/config  — paramètres\n/logs    — 15 dernières lignes\n"
                "/close COIN confirm — ferme 1 position\n/addcoin COIN — ajoute un coin\n/removecoin COIN — retire un coin\n"
                "/stop confirm — ferme tout + arrête\n/help    — cette aide")
    return f"❓ Inconnue: {cmd}\n/help pour la liste"

def telegram_loop(eq0):
    """Thread séparé : écoute les commandes Telegram (client indépendant, thread-safe)."""
    cli = MEXCRestClient()
    off = 0
    u = _tg_updates(0)
    if u: off = u[-1]['update_id'] + 1   # ignore les vieux messages
    log.info('📱 Commandes Telegram ACTIVES (/status /balance /pnl /risk /config /stop /help)')
    while True:
        try:
            for upd in _tg_updates(off):
                off = upd['update_id'] + 1
                m = upd.get('message', {}); txt = m.get('text', '')
                if str(m.get('chat', {}).get('id')) != str(TG_CHAT): continue  # owner only
                if txt.startswith('/'):
                    log.info(f'📱 commande: {txt}')
                    try: tg(_handle_cmd(cli, eq0, txt))
                    except Exception as e:
                        log.error(f'cmd err: {e}\n{traceback.format_exc()}'); tg(f'Erreur: {str(e)[:100]}')
        except Exception as e:
            log.warning(f'telegram_loop: {e}')
        time.sleep(2)

# ===================== SIGNAL =====================
def fetch_closes(client, coin):
    sym = to_mexc_symbol(coin)
    try:
        k = client.get_klines_full(sym, INTERVAL, KLINES)
        if not k or len(k) < max(HORIZONS) + 6:
            log.warning(f'[{coin}] klines insuffisants: {len(k) if k else 0} (besoin {max(HORIZONS)+6})')
            return None
        # ⚠️ PARITÉ BACKTEST: on DROP la dernière barre (EN COURS, pas fermée).
        # Sinon le signal diffère du backtest (cf project_mode_1h_strict: barre fermée obligatoire).
        return [b['c'] for b in k][:-1]
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

# ===================== VOL-TARGETING (parité backtest, adapté au compte) =====================
VT_HIST = os.path.join(LOG_DIR, 'equity_history.jsonl')
def vt_scale(eq):
    """Scale = clip(0.40/vol_réalisée_20j, VT_MIN, VT_MAX). Réduit l'expo en turbulence (= backtest).
    1 point/jour. Warm-up 20j → scale 1.0. Borné [0.4, 1.0] car $110 ne peut pas faire 0.2-3.0."""
    try:
        hist = []
        if os.path.exists(VT_HIST):
            hist = [json.loads(l) for l in open(VT_HIST) if l.strip()][-40:]
        # 1 enregistrement / jour max (évite la pollution si restarts multiples)
        if not hist or (time.time() - hist[-1].get('ts', 0)) > 20*3600:
            hist.append({'ts': time.time(), 'eq': eq})
            with open(VT_HIST, 'w') as f:
                for h in hist[-40:]: f.write(json.dumps(h) + '\n')
        eqs = [h['eq'] for h in hist[-21:]]
        if len(eqs) < 21:
            log.info(f'📐 vol-targeting: warm-up {max(0,len(eqs)-1)}/20 jours → scale=1.00'); return 1.0
        rets = [eqs[i]/eqs[i-1]-1 for i in range(1, len(eqs)) if eqs[i-1] > 0]
        vol = statistics.stdev(rets) * math.sqrt(365)
        s = max(VT_MIN, min(VT_MAX, VT_TARGET/(vol+1e-9)))
        log.info(f'📐 vol-targeting: vol_réalisée={vol*100:.0f}% → scale={s:.2f} (cible {VT_TARGET*100:.0f}%)')
        jlog('vol_target', vol=round(vol,4), scale=round(s,3))
        return s
    except Exception as e:
        log.error(f'vt_scale EXCEPTION: {e}\n{traceback.format_exc()}'); return 1.0

# ===================== SIZING (formule TESTÉE de bot.py + vol-targeting) =====================
def calc_qty(balance, price, coin, vts=1.0):
    """qty contrats = round(balance * MARGIN_PCT * LEVERAGE * vol_target_scale / (price * contract_size))."""
    cs = get_contract_size(coin)
    if not cs or price <= 0:
        log.error(f'[{coin}] calc_qty: cs={cs} price={price} invalide'); return 0
    margin = balance * MARGIN_PCT
    notional = margin * LEVERAGE * vts   # vts = scale vol-targeting (parité backtest)
    qty_raw = notional / (price * cs)
    qty = max(1, round(qty_raw))
    log.debug(f'[{coin}] calc_qty: bal={balance:.2f} margin={margin:.2f} vts={vts:.2f} notional={notional:.2f} px={price:.6f} cs={cs} raw={qty_raw:.3f} → {qty} contrats (≈${qty*price*cs:.1f})')
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

def _pos_vol(client, sym):
    """Volume de position (contrats) pour ce symbole. 0 si pas de position."""
    try:
        for p in client.get_positions(sym):
            if p.get('symbol') == sym: return float(p.get('holdVol', 0) or 0)
    except Exception: pass
    return 0.0

def _open_orders_state2(client, sym):
    """Liste des ordres ouverts (state==2) du symbole. Source : REST open_orders (peut laguer 1-5s)."""
    try:
        raw = client._get('/api/v1/private/order/open_orders/' + sym)
        return [o for o in (raw.get('data') or []) if isinstance(o, dict) and o.get('state') == 2]
    except Exception:
        return []

def _cancel_open_orders(client, sym, coin='', tries=4):
    """BULLETPROOF : annule TOUS les ordres ouverts du symbole via cancel_all (atomique, documenté MEXC),
    et VÉRIFIE qu'il n'en reste aucun. Évite les ordres limit fantômes (position surdimensionnée).

    3 leçons recherche (NLM MEXC + docs officielles, 2026-06-13) :
    - cancel_all prend {"symbol": sym} et annule TOUS les ordres non complétés du contrat en 1 appel atomique
      (plus fiable que cancel oid-par-oid qui attend un TABLEAU ["id"], pas {"orderId": id}).
    - Mode "Under Maintenance" : code 9999/510 fréquent sur cancel → retry agressif.
    - Latence cache REST : après success=True, get_open_orders peut montrer state=2 encore 1-5s
      (FAUX positif). On tolère ce lag (sleep 1.2s) avant de re-vérifier — la VÉRITÉ d'un fill
      reste le delta de POSITION (géré dans place_maker), pas le state REST de l'ordre."""
    for k in range(tries):
        # 1) cancel_all atomique (avec retry maintenance)
        try:
            r = client._post('/api/v1/private/order/cancel_all', {'symbol': sym})
            if r.get('code') in (9999, 510):       # maintenance / rate-limit
                log.warning(f'[{coin}] cancel_all maintenance/limit (code {r.get("code")}), retry'); time.sleep(1.0 + k); continue
        except Exception:
            pass
        time.sleep(1.2)   # laisser le cache REST se synchroniser (anti faux-positif)
        # 2) vérification
        left = _open_orders_state2(client, sym)
        if not left:
            return True   # plus rien d'ouvert ✅
        # 3) fallback ciblé par oid si cancel_all n'a pas suffi (maintenance partielle)
        for o in left:
            try: client.cancel_order(o.get('orderId'))
            except Exception: pass
        time.sleep(1.0)
    # dernier verdict après tolérance cache
    time.sleep(1.0)
    left = _open_orders_state2(client, sym)
    if left:
        log.error(f'[{coin}] ⚠️ {len(left)} ordre(s) state=2 PERSISTANT après cancel_all+oid+{tries} essais — vérifier maintenance MEXC. ids={[o.get("orderId") for o in left]}')
        return False
    return True

def place_maker(client, sym, coin, side, qty):
    """Exécution MAKER ROBUSTE (anti-race) : limit post-only (type=2) au bid/ask.
    À chaque essai : poste → attend → ANNULE TOUJOURS → vérifie la POSITION réelle (pas l'ordre).
    Re-poste le reliquat non rempli (chase). Fallback taker pour le reste après MAKER_CHASE essais."""
    try: dec = get_price_decimals(coin)
    except Exception: dec = 4
    vol0 = _pos_vol(client, sym)          # position AVANT (référence)
    remaining = qty; got_maker = False
    for attempt in range(MAKER_CHASE):
        tk = client.get_ticker(sym)
        bid = float(tk.get('bid1', 0) or 0); ask = float(tk.get('ask1', 0) or 0)
        if bid <= 0 or ask <= 0:
            log.warning(f'[{coin}] pas de bid/ask → fallback taker'); break
        price = round(bid if side in (1, 2) else ask, dec)   # achat→bid, vente→ask = maker
        body = {'symbol': sym, 'price': price, 'vol': remaining, 'side': side, 'type': 2, 'openType': 1, 'leverage': LEVERAGE}
        r = client._post('/api/v1/private/order/submit', body)
        if r.get('code') == 510:
            log.warning(f'[{coin}] maker rate-limit, attente 2s'); time.sleep(2); continue
        if not (r.get('success') or r.get('code') == 0):
            log.warning(f'[{coin}] maker rejeté ({r.get("code")}: {r.get("message","")}) → fallback taker'); break
        oid = r.get('data')
        log.info(f'[{coin}] 📬 MAKER posté @ {price} vol={remaining} (essai {attempt+1}/{MAKER_CHASE}), attente {MAKER_WAIT}s...')
        time.sleep(MAKER_WAIT)
        # ANTI-RACE + ANTI-FANTÔME : on annule TOUS les ordres ouverts du symbole, AVEC vérification
        # (si déjà rempli, il n'y a rien à annuler ; sinon on garantit zéro ordre limit fantôme)
        _cancel_open_orders(client, sym, coin)
        time.sleep(0.6)   # laisser le fill se stabiliser
        # combien rempli ? (delta de POSITION réelle, pas de l'ordre)
        vol_now = _pos_vol(client, sym)
        filled = (vol_now - vol0) if side in (1, 3) else (vol0 - vol_now)   # open=+, close=-
        filled = max(0.0, filled)
        remaining = max(0, qty - round(filled))
        if filled > 0: got_maker = True
        log.info(f'[{coin}] rempli {filled:.0f}/{qty} en maker, reste {remaining}')
        if remaining <= 0:
            log.info(f'[{coin}] ✅ entièrement rempli en MAKER (0% frais)')
            return {'success': True, 'code': 0, 'maker': True}
        vol0 = vol_now   # nouvelle référence pour le prochain essai
    # SÉCURITÉ FINALE : avant de partir, garantir 0 ordre limit fantôme qui traîne
    _cancel_open_orders(client, sym, coin)
    # fallback TAKER pour le reliquat
    if remaining > 0:
        log.info(f'[{coin}] ⚡ fallback TAKER pour le reste ({remaining} contrats)')
        rt = _order_retry(client, sym, side, remaining, coin)
        rt['maker'] = got_maker   # maker partiel ?
        return rt
    return {'success': True, 'code': 0, 'maker': got_maker}

def open_pos(client, coin, direction, qty):
    sym = to_mexc_symbol(coin); side = 1 if direction == 1 else 3
    if DRY_RUN:
        log.info(f'🔵 [DRY] OPEN {"LONG" if direction==1 else "SHORT"} {coin} qty={qty} ({"MAKER" if USE_MAKER else "MARKET"}, side={side}, lev={LEVERAGE})')
        jlog('order_dry', action='open', coin=coin, dir=direction, qty=qty, side=side); return {'dry': True}
    try:
        client.set_leverage(sym, LEVERAGE)
        r = place_maker(client, sym, coin, side, qty) if USE_MAKER else _order_retry(client, sym, side, qty, coin)
        ok = r.get('success', False) or r.get('code') == 0
        mk = ' [MAKER]' if r.get('maker') else (' [taker]' if USE_MAKER else '')
        log.info(f'{"✅" if ok else "❌"} OPEN {"LONG" if direction==1 else "SHORT"} {coin} qty={qty}{mk} → {r}')
        jlog('order', action='open', coin=coin, dir=direction, qty=qty, side=side, maker=bool(r.get('maker')), resp=r); return r
    except Exception as e:
        log.error(f'[{coin}] open_pos EXCEPTION: {e}\n{traceback.format_exc()}')
        jlog('order_error', action='open', coin=coin, err=str(e)); return None

def close_pos(client, coin, direction, qty):
    sym = to_mexc_symbol(coin); side = 4 if direction == 1 else 2  # 4=Close Long, 2=Close Short
    if DRY_RUN:
        log.info(f'🟠 [DRY] CLOSE {"LONG" if direction==1 else "SHORT"} {coin} qty={qty} (side={side})')
        jlog('order_dry', action='close', coin=coin, dir=direction, qty=qty, side=side); return {'dry': True}
    try:
        # CLOSE = toujours TAKER (fiable) : le maker close ne remplit quasi jamais (test live) → fallback taker de toute façon
        r = _order_retry(client, sym, side, qty, coin)
        ok = r.get('success', False) or r.get('code') == 0
        log.info(f'{"✅" if ok else "❌"} CLOSE {coin} qty={qty} [taker] → {r}')
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

    vts = vt_scale(eq)   # scale vol-targeting (parité backtest : réduit l'expo en turbulence)
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
        qty = calc_qty(bal, price, coin, vts)
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

    # thread commandes Telegram (écoute /status /balance /pnl /stop ...)
    if TG_TOKEN and TG_CHAT:
        threading.Thread(target=telegram_loop, args=(eq0,), daemon=True).start()

    # boucle réelle
    while not STOP_FLAG['stop']:
        try:
            cont = rebalance(client, eq0)
            if not cont:
                log.error('🛑 Arrêt (kill-switch).'); break
        except Exception as e:
            log.error(f'BOUCLE EXCEPTION: {e}\n{traceback.format_exc()}')
            jlog('loop_error', err=str(e)); tg(f'⚠️ Erreur boucle: {str(e)[:120]}')
        log.info(f'😴 Sommeil {REBAL_H}h jusqu\'au prochain rebalance (interruptible par /stop)...')
        slept = 0
        while slept < REBAL_H * 3600 and not STOP_FLAG['stop']:
            time.sleep(5); slept += 5
    if STOP_FLAG['stop']:
        log.info('🛑 Arrêt demandé via Telegram /stop.'); tg('Bot arrêté via /stop. Plus de trading.')

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        log.info('Interruption manuelle (Ctrl-C).')
    except Exception as e:
        log.error(f'FATAL: {e}\n{traceback.format_exc()}')
        sys.exit(1)
