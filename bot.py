#!/usr/bin/env python3
# bot.py — MEXC Futures Bot (parité Champion v4)
# Strategie : Backtest v6 Optimal (C139) — D3 EMA(239/281) ATR-trail(0.24/0.0087) ADX(19min7.7) VP80 7x
# Exchange   : MEXC Futures (contract.mexc.com)
# ISOLATION  : NE JAMAIS TOUCHER /root/champion-v4-bot/
#
# Telegram: /status /balance /pnl /orders /trades /risk /config /logs /close /help

import asyncio
import json
import logging
import math
import os
import signal
import sys
import threading
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from config import (
    COINS, TF_SIGNAL, TF_CHANDELIER, TIMEFRAME_MAP,
    DONCHIAN_PERIOD, EMA_1H_PERIOD, EMA_4H_PERIOD, ATR_PERIOD,
    ADX_PERIOD, ADX_MIN, TRAIL_ACT, TRAIL_DIST, ATR_SL_MULT, MIN_HOLD_HOURS,
    LEVERAGE, CAPITAL_PCT, SL_PCT, TP_PCT, MARGIN_PCT, MAX_POSITIONS,
    MHH, VP_PCT, VP_WIN,
    DRY_RUN, TG_TOKEN, TG_CHAT,
    to_mexc_symbol, to_mexc_interval, get_contract_size, init_contract_sizes,
    USE_PARTIAL_EXIT, PARTIAL_TP_PCT, PARTIAL_EXIT_RATIO,
    USE_BREAKEVEN_MOVE, BREAKEVEN_TRIGGER_PCT,
    USE_TIME_DECAY_MHH, MHH_PROFIT_THRESHOLD, MHH_DECAY_HOURS,
    USE_MULTI_PARTIAL, MP_L1_PCT, MP_L1_RATIO, MP_L2_PCT, MP_L2_RATIO,
)
from mexc_client import MEXCRestClient, MEXCWebSocket
from telegram import tg_send, TelegramCommands

BOT_DIR     = Path('/root/mexc-bot')
STATE_FILE  = BOT_DIR / 'state.json'
LOG_FILE    = BOT_DIR / 'bot.log'
TRADES_FILE = BOT_DIR / 'trades.json'

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)-8s [%(name)s] %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
# Réduire le bruit des libs externes
logging.getLogger('urllib3').setLevel(logging.WARNING)
logging.getLogger('websockets').setLevel(logging.INFO)
logging.getLogger('asyncio').setLevel(logging.WARNING)
log = logging.getLogger('mexc')


# ── State persistence ─────────────────────────────────────────────────────────
def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}

def save_state(state: dict):
    tmp = STATE_FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(state, indent=2, default=str))
    tmp.replace(STATE_FILE)


# ── Watchdog ──────────────────────────────────────────────────────────────────
_watchdog_last_beat = time.time()

def watchdog_beat():
    global _watchdog_last_beat
    _watchdog_last_beat = time.time()

def start_watchdog(timeout_sec: int = 600):
    def _loop():
        log.info(f'Watchdog démarré (timeout={timeout_sec}s)')
        while True:
            time.sleep(30)
            elapsed = time.time() - _watchdog_last_beat
            if elapsed > timeout_sec:
                log.error(f'WATCHDOG: freeze détecté ({elapsed:.0f}s) → kill process')
                os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=_loop, daemon=True).start()


# ── Indicateurs ───────────────────────────────────────────────────────────────
def calc_ema(values: list, period: int) -> float:
    if len(values) < period:
        return 0.0
    k   = 2 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def calc_atr_series(candles: list, period: int) -> list:
    """ATR Wilder EMA (k=1/period) — identique bt_v6_multi_gen._precompute."""
    if len(candles) < period + 1:
        return []
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i]['h'], candles[i]['l'], candles[i-1]['c']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return []
    k = 1.0 / period          # Wilder smoothing: k=1/14=0.0714 (vs EMA standard k=2/15)
    atr = sum(trs[:period]) / period  # seed = SMA sur les 'period' premières TR
    atrs = [atr]
    for tr in trs[period:]:
        atr = tr * k + atr * (1 - k)
        atrs.append(atr)
    return atrs


def calc_adx(candles: list, period: int) -> float:
    """Wilder ADX — identique bt_v6_multi_gen._calc_adx. Retourne la derniere valeur."""
    period = max(2, int(period))
    n = len(candles)
    if n < 2 * period + 2:
        return 0.0
    highs  = [c['h'] for c in candles]
    lows   = [c['l'] for c in candles]
    closes = [c['c'] for c in candles]
    tr  = [0.0] * n
    pdm = [0.0] * n
    ndm = [0.0] * n
    for i in range(1, n):
        h, l, pc = highs[i], lows[i], closes[i-1]
        tr[i] = max(h - l, abs(h - pc), abs(l - pc))
        up   = highs[i] - highs[i-1]
        down = lows[i-1] - lows[i]
        if up > down and up > 0:
            pdm[i] = up
        if down > up and down > 0:
            ndm[i] = down
    atr_w = sum(tr[1:period+1])
    pdm_w = sum(pdm[1:period+1])
    ndm_w = sum(ndm[1:period+1])
    dx_vals = []
    for i in range(period + 1, n):
        atr_w = atr_w - atr_w / period + tr[i]
        pdm_w = pdm_w - pdm_w / period + pdm[i]
        ndm_w = ndm_w - ndm_w / period + ndm[i]
        pdi = 100 * pdm_w / atr_w if atr_w > 0 else 0.0
        ndi = 100 * ndm_w / atr_w if atr_w > 0 else 0.0
        dx_vals.append(100 * abs(pdi - ndi) / (pdi + ndi) if pdi + ndi > 0 else 0.0)
    if len(dx_vals) < period:
        return 0.0
    adx = sum(dx_vals[:period]) / period
    for dx in dx_vals[period:]:
        adx = (adx * (period - 1) + dx) / period
    return adx


def compute_signal(candles_1h: list, candles_4h: list, coin: str = '',
                   override_price: float = None):
    """Donchian D5 + EMA filter + VP filter (ATR percentile).
    override_price: si fourni, remplace le close 1H pour détection intra-barre 1m (parité Champion v4).
    Retourne ('LONG'|'SHORT'|'NONE', atr_value)."""
    tag = f'[{coin}]' if coin else ''
    min_bars = max(EMA_1H_PERIOD + 10, VP_WIN // 2, DONCHIAN_PERIOD + 1) + 5
    log.debug(f'{tag} compute_signal: 1h={len(candles_1h)} 4h={len(candles_4h)} need_1h≥{min_bars}')
    if len(candles_1h) < min_bars or len(candles_4h) < EMA_4H_PERIOD + 5:
        log.debug(f'{tag} pas assez de barres — NONE')
        return 'NONE', 0.0

    # ATR series pour VP filter
    atr_series = calc_atr_series(candles_1h, ATR_PERIOD)
    if not atr_series:
        log.debug(f'{tag} ATR series vide — NONE')
        return 'NONE', 0.0
    current_atr = atr_series[-1]

    # VP filter: si ATR > VP_PCT percentile → trop volatil, skip (parité backtest line 969: atr[i] > vol_thr[i])
    # Exclut la barre courante comme Champion v4 : atr_series.iloc[-VP_WIN-1:-1]
    atr_window = atr_series[-(VP_WIN + 1):-1]
    vp_threshold = None
    if len(atr_window) >= 50:
        vp_threshold = np.percentile(atr_window, VP_PCT)
        log.debug(f'{tag} VP filter: ATR={current_atr:.6f} threshold(p{VP_PCT})={vp_threshold:.6f} window={len(atr_window)}')
        if current_atr > vp_threshold:
            log.info(f'{tag} VP filter: ATR {current_atr:.6f} > {vp_threshold:.6f} — trop volatil (top {100-VP_PCT}%), skip')
            return 'NONE', 0.0

    # Donchian breakout (D5, sur closes précédents)
    prev    = candles_1h[-(DONCHIAN_PERIOD + 1):-1]
    dc_high = max(c['h'] for c in prev)
    dc_low  = min(c['l'] for c in prev)
    close   = override_price if override_price is not None else candles_1h[-1]['c']

    # EMA filters
    closes_1h = [c['c'] for c in candles_1h]
    closes_4h = [c['c'] for c in candles_4h]
    ema_1h    = calc_ema(closes_1h[:-1], EMA_1H_PERIOD)  # shift(1): barre précédente, identique Champion v4
    ema_4h    = calc_ema(closes_4h, EMA_4H_PERIOD)

    log.debug(f'{tag} Donchian D{DONCHIAN_PERIOD}: close={close:.6f} dc_high={dc_high:.6f} dc_low={dc_low:.6f}')
    log.debug(f'{tag} EMA: 1h({EMA_1H_PERIOD})={ema_1h:.6f} 4h({EMA_4H_PERIOD})={ema_4h:.6f}')
    vp_thresh_str = f'{vp_threshold:.6f}' if vp_threshold is not None else 'N/A'
    log.debug(f'{tag} ATR={current_atr:.6f} VP_thresh={vp_thresh_str}')

    if any(x == 0.0 for x in [ema_1h, ema_4h, current_atr]):
        log.debug(f'{tag} EMA/ATR zéro — NONE')
        return 'NONE', 0.0

    # ADX filter: skip ranging markets (entry only)
    if ADX_PERIOD > 0 and ADX_MIN > 0:
        adx_val = calc_adx(candles_1h[:-1], ADX_PERIOD)  # shift(1): barre precedente
        if adx_val < ADX_MIN:
            log.debug(f'{tag} ADX filter: {adx_val:.1f} < {ADX_MIN} — signal ignore')
            return 'NONE', 0.0
        log.debug(f'{tag} ADX={adx_val:.1f} >= {ADX_MIN} — OK')

    if close > dc_high and close > ema_1h and close > ema_4h:
        log.info(f'{tag} SIGNAL LONG: close {close:.6f} > dc_high {dc_high:.6f} | ema1h {ema_1h:.6f} | ema4h {ema_4h:.6f}')
        return 'LONG', current_atr
    elif close < dc_low and close < ema_1h and close < ema_4h:
        log.info(f'{tag} SIGNAL SHORT: close {close:.6f} < dc_low {dc_low:.6f} | ema1h {ema_1h:.6f} | ema4h {ema_4h:.6f}')
        return 'SHORT', current_atr

    log.debug(f'{tag} pas de breakout — NONE (close={close:.6f} dc_h={dc_high:.6f} dc_l={dc_low:.6f})')
    return 'NONE', 0.0


def aggregate_to_5m(bars_1m: list) -> list:
    """Agrège des barres 1m (timestamp en secondes) en barres 5m.
    Alignement sur frontière 5min : t5 = (t // 300) * 300."""
    if not bars_1m:
        return []
    buckets: dict = {}
    for b in bars_1m:
        t5 = (b['t'] // 300) * 300
        if t5 not in buckets:
            buckets[t5] = {'t': t5, 'o': b['o'], 'h': b['h'], 'l': b['l'], 'c': b['c'], 'v': b['v']}
        else:
            bk = buckets[t5]
            bk['h'] = max(bk['h'], b['h'])
            bk['l'] = min(bk['l'], b['l'])
            bk['c'] = b['c']
            bk['v'] += b['v']
    return [v for _, v in sorted(buckets.items())]



# ── Position sizing ───────────────────────────────────────────────────────────
def calc_qty(balance: float, price: float, coin: str) -> int:
    """Retourne le nombre de contrats MEXC (vol=entier).
    1 contrat = CONTRACT_SIZES[coin] tokens.
    Formule: qty = round(balance * MARGIN_PCT * LEVERAGE / (price * contract_size))
    Minimum: 1 contrat."""
    if price <= 0 or balance <= 0:
        log.warning(f'[{coin}] calc_qty: balance={balance} ou price={price} invalide')
        return 0
    cs       = get_contract_size(coin)
    margin   = balance * MARGIN_PCT
    notional = margin * LEVERAGE
    qty_raw  = notional / (price * cs)
    qty      = max(1, round(qty_raw))
    log.debug(f'[{coin}] calc_qty: balance={balance:.4f} margin={margin:.4f} notional={notional:.4f} '
              f'price={price:.6f} cs={cs} qty_raw={qty_raw:.4f} → qty={qty}')
    return qty


# ── Trade log ─────────────────────────────────────────────────────────────────
def append_trade(coin: str, direction: str, entry_price: float,
                 exit_price: float, reason: str, qty: float = 1.0):
    trades = []
    if TRADES_FILE.exists():
        try:
            trades = json.loads(TRADES_FILE.read_text())
        except Exception:
            pass
    pnl_pct  = 0.0
    pnl_usdt = 0.0
    if entry_price and exit_price:
        mult     = 1 if direction == 'LONG' else -1
        pnl_pct  = (exit_price - entry_price) / entry_price * mult * LEVERAGE * 100
        cs       = get_contract_size(coin)
        pnl_usdt = (exit_price - entry_price) * qty * cs * mult
    trades.append({
        'coin':        coin,
        'direction':   direction,
        'entry_price': entry_price,
        'exit_price':  exit_price,
        'qty':         qty,
        'pnl':         round(pnl_usdt, 4),
        'pnl_pct':     round(pnl_pct, 2),
        'reason':      reason,
        'date':        datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M'),
    })
    TRADES_FILE.write_text(json.dumps(trades[-200:], indent=2))


# ── Bot ───────────────────────────────────────────────────────────────────────
class MEXCBot:
    def __init__(self):
        self.rest            = MEXCRestClient()
        self._state          = load_state()
        # Sync runtime_coins: conserve TOUS les coins sauvegardés (incl. /addcoin dynamiques) + ajoute nouveaux config
        _saved = self._state.get('__coins__', COINS)
        self.runtime_coins = list(_saved) + [c for c in COINS if c not in set(_saved)]
        self.positions       = self._load_positions_from_state()
        self._opening_coins = set()  # lock anti-double-open
        self.candles    = {
            c: {'1h': deque(maxlen=VP_WIN + 100), '1m': deque(maxlen=700), '4h': deque(maxlen=EMA_4H_PERIOD + 50)}
            for c in self.runtime_coins
        }
        self.ws         = MEXCWebSocket(on_kline_callback=self.on_kline)
        self.start_time = datetime.now(timezone.utc)
        self.dry_run    = DRY_RUN
        self._entered_in_bar = {c: None for c in self.runtime_coins}

    def _load_positions_from_state(self) -> dict:
        positions = {}
        for coin in self.runtime_coins:
            pos = self._state.get(coin, {}).get('position')
            if pos:
                positions[coin] = pos
        return positions

    def _persist_positions(self):
        self._state['__coins__'] = self.runtime_coins  # persiste la liste dynamique
        for coin in self.runtime_coins:
            self._state.setdefault(coin, {})['position'] = self.positions.get(coin)
        # Purge les clés ghost (coins retirés de config.py)
        for _k in list(self._state.keys()):
            if _k != '__coins__' and _k not in self.runtime_coins:
                del self._state[_k]
        save_state(self._state)

    # ── Startup ───────────────────────────────────────────────────────────────
    async def sync_state_on_startup(self):
        """Sync state.json vs positions réelles sur exchange au démarrage."""
        log.info('Sync state au démarrage...')
        for coin in self.runtime_coins:
            pos = self.positions.get(coin)
            if not pos:
                continue
            try:
                sym  = to_mexc_symbol(coin)
                live = self.rest.get_positions(sym)
                if not live:
                    log.warning(f'{coin}: position dans state mais ABSENTE sur exchange → downtime close')
                    await tg_send(
                        f'⚠️ <b>{coin}: position fermée pendant downtime</b>\n'
                        f'State nettoyé automatiquement.'
                    )
                    self.positions.pop(coin, None)
                    self._persist_positions()
                else:
                    log.info(f'{coin}: position confirmée sur exchange')
                    await tg_send(f'✅ <b>{coin}: position récupérée après restart</b>')
            except Exception as e:
                log.warning(f'{coin}: sync erreur — {e}')
        log.info('Sync terminée')

    async def init(self):
        log.info(f'MEXC Bot démarrage — DRY_RUN={DRY_RUN}')
        log.info(f'Coins : {self.runtime_coins}')

        ping = self.rest.ping()
        log.info(f'Ping MEXC : {ping}')

        # Auto-fetch + valide les contract sizes depuis MEXC API (1 appel pour tous les coins)
        init_contract_sizes(self.runtime_coins)

        # Sync state vs exchange
        await self.sync_state_on_startup()
        self._persist_positions()  # persiste runtime_coins dès le boot

        # Set leverage per coin
        for coin in self.runtime_coins:
            if self.positions.get(coin):
                log.info(f"  set_leverage {coin}: skip (position active)")
                continue
            sym = to_mexc_symbol(coin)
            try:
                result = self.rest.set_leverage(sym, LEVERAGE)
                if result.get('success'):
                    log.info(f'  Leverage {LEVERAGE}x set: {coin}')
                elif result.get('code') == 600:
                    log.info(f'  set_leverage {coin}: code=600 — OK (leverage fixé à l\'ouverture du trade)')
                else:
                    log.warning(f'  set_leverage {coin}: code={result.get("code")} msg={result.get("message","")!r}')
            except Exception as e:
                log.warning(f'  set_leverage {coin}: {e}')

        # Load historical candles
        for coin in self.runtime_coins:
            sym = to_mexc_symbol(coin)
            for tf in ['1h', '1m', '4h']:
                try:
                    candles = self.rest.get_klines_full(sym, to_mexc_interval(tf), limit=VP_WIN + 50)
                    self.candles[coin][tf].extend(candles)
                    log.info(f'  {coin} {tf}: {len(candles)} candles chargées')
                except Exception as e:
                    log.error(f'  {coin} {tf}: ERREUR preload — {e}')

        # Balance for startup message
        bal_str = ''
        try:
            bal = self.rest.get_balance()
            bal_str = f' | Balance: ${bal:.2f} USDT'
        except Exception:
            pass

        c6_parts = []
        if USE_PARTIAL_EXIT:   c6_parts.append(f'PARTIAL+{PARTIAL_TP_PCT*100:.2f}%')
        if USE_MULTI_PARTIAL:  c6_parts.append(f'MP_L1+{MP_L1_PCT*100:.2f}%/{MP_L1_RATIO*100:.0f}% MP_L2+{MP_L2_PCT*100:.2f}%/{MP_L2_RATIO*100:.0f}%')
        if USE_BREAKEVEN_MOVE: c6_parts.append(f'BE+{BREAKEVEN_TRIGGER_PCT*100:.0f}%')
        if USE_TIME_DECAY_MHH: c6_parts.append(f'TD {MHH}h→{MHH_DECAY_HOURS}h@+{MHH_PROFIT_THRESHOLD*100:.0f}%')
        c6_str = '✅ ' + ' | '.join(c6_parts) if c6_parts else '❌ désactivé'
        cs_lines = ' '.join(f'{c}={get_contract_size(c)}' for c in self.runtime_coins)
        await tg_send(
            f'🚀 <b>MEXC Bot démarré</b>\n'
            f'Coins: {" + ".join(self.runtime_coins)}\n'
            f'DRY_RUN: {DRY_RUN}{bal_str}\n'
            f'Stratégie: BT v6 Optimal D{DONCHIAN_PERIOD} EMA({EMA_1H_PERIOD}/{EMA_4H_PERIOD}) Trail({TRAIL_ACT:.4f}/{TRAIL_DIST}) ADX({ADX_PERIOD}min{ADX_MIN}) VP{VP_PCT} {LEVERAGE}x\n'
            f'Cycle 6: {c6_str}\n'
            f'CS: {cs_lines}\n'
            f'/help pour les commandes'
        )

    # ── WebSocket callback ────────────────────────────────────────────────────
    async def on_kline(self, symbol: str, data: dict):
        watchdog_beat()
        coin = symbol.replace('_USDT', '')
        if coin not in self.runtime_coins:
            return
        closed = data.get('r', False)
        candle = {
            't': data.get('t'), 'o': float(data.get('o', 0)),
            'h': float(data.get('h', 0)), 'l': float(data.get('l', 0)),
            'c': float(data.get('c', 0)), 'v': float(data.get('v', 0)),
        }
        deque_1m = self.candles[coin]['1m']
        last_t   = deque_1m[-1]['t'] if deque_1m else None
        n_bars   = len(deque_1m)

        # MEXC ne renvoie jamais r=True → détection par changement de timestamp
        new_bar = closed or (last_t is not None and candle['t'] > last_t)

        if new_bar:
            action = 'CLOSED' if closed else 'NEW_BAR'
            log.debug(f'[{coin}] 1m {action}: t={candle["t"]} prev_t={last_t} '
                      f'o={candle["o"]} h={candle["h"]} l={candle["l"]} c={candle["c"]} '
                      f'v={candle["v"]:.2f} | total_bars={n_bars+1}')
            deque_1m.append(candle)
        else:
            log.debug(f'[{coin}] 1m tick: c={candle["c"]} | bars={n_bars}')
            if deque_1m:
                deque_1m[-1] = candle
        await self.check_exits(coin, bar_closed=new_bar)

        # Intrabar signal: vérifier Donchian sur chaque close 1m (parité Champion v4 override_price)
        # Champion v4 vérifie toutes les 3m — MEXC vérifie toutes les 1m (meilleure granularité)
        if (new_bar and not self.positions.get(coin)
                and len(self.positions) < MAX_POSITIONS
                and len(deque_1m) >= 2):
            bars_1h = list(self.candles[coin]['1h'])
            bars_4h = list(self.candles[coin]['4h'])
            if len(bars_1h) >= 20 and len(bars_4h) >= 5:
                current_1h_ts = bars_1h[-1]['t'] if bars_1h else None
                if self._entered_in_bar.get(coin) != current_1h_ts:
                    prev_close = list(deque_1m)[-2]['c']  # close de la barre 1m qui vient de fermer
                    signal, atr_val = compute_signal(bars_1h, bars_4h, coin=coin,
                                                     override_price=prev_close)
                    if signal != 'NONE':
                        log.info(f'[{coin}] INTRABAR SIGNAL {signal} @ {prev_close:.6f} (1m close)')
                        await tg_send(
                            f'📡 <b>Signal {signal} — {coin}</b> [intrabar 1m]\n'
                            f'Prix: ${prev_close:.4f} | ATR: {atr_val:.4f}\n'
                            f'VP filter: ✅ | Ouverture...'
                        )
                        self._entered_in_bar[coin] = current_1h_ts
                        try:
                            await self.open_position(coin, signal, atr_val)
                        except Exception:
                            self._entered_in_bar[coin] = None

    # ── Dynamic coin management ───────────────────────────────────────────────
    async def add_coin(self, coin: str) -> str:
        coin = coin.upper()
        if coin in self.runtime_coins:
            return f'{coin} déjà actif'
        sym = to_mexc_symbol(coin)
        self.runtime_coins.append(coin)
        self.candles[coin] = {
            '1h': deque(maxlen=VP_WIN + 100),
            '1m': deque(maxlen=700),
            '4h': deque(maxlen=EMA_4H_PERIOD + 50),
        }
        self._entered_in_bar[coin] = None
        loaded = {}
        for tf in ['1h', '1m', '4h']:
            try:
                bars = await asyncio.to_thread(
                    self.rest.get_klines_full, sym, to_mexc_interval(tf), VP_WIN + 50
                )
                self.candles[coin][tf].extend(bars)
                loaded[tf] = len(bars)
            except Exception as e:
                log.warning(f'add_coin {coin} {tf}: {e}')
                loaded[tf] = 0
        await self.ws.subscribe_coin(sym, to_mexc_interval('1m'))
        self._persist_positions()  # sauvegarde runtime_coins dans state.json
        msg = (f'{coin} ajouté ✅\n'
               f'1h: {loaded.get("1h",0)}b | 1m: {loaded.get("1m",0)}b | 4h: {loaded.get("4h",0)}b\n'
               f'Coins actifs: {" + ".join(self.runtime_coins)}')
        log.info(msg)
        return msg

    async def remove_coin(self, coin: str) -> str:
        coin = coin.upper()
        if coin not in self.runtime_coins:
            return f'{coin} pas dans la liste active'
        pos = self.positions.get(coin)
        closed_msg = ''
        if pos:
            await self.close_position(coin, pos['direction'], reason='REMOVE')
            closed_msg = ' | position fermée au marché'
        self.runtime_coins.remove(coin)
        self.candles.pop(coin, None)
        self._entered_in_bar.pop(coin, None)
        self._persist_positions()  # sauvegarde runtime_coins dans state.json
        msg = f'{coin} retiré ✅{closed_msg}\nCoins actifs: {" + ".join(self.runtime_coins) or "aucun"}'
        log.info(msg)
        return msg

    # ── Exit checks ───────────────────────────────────────────────────────────
    async def check_exits(self, coin: str, bar_closed: bool = False):
        pos = self.positions.get(coin)
        if not pos:
            return

        direction   = pos['direction']
        entry_price = pos.get('entry_price', 0)
        sl_price    = pos.get('sl_price', 0)
        atr_entry   = pos.get('atr_entry', 0.0)
        entry_time  = pos.get('entry_time', '')
        bars_1m     = list(self.candles[coin]['1m'])

        # === Cycle 6: PnL prix non leveraged (pour partials/BE/time-decay) ===
        cycle6_on = pos.get('cycle6_enabled', False)
        pnl_pct_price = 0.0
        if bars_1m and entry_price:
            cp = bars_1m[-1]['c']
            mult_dir = 1 if direction == 'LONG' else -1
            pnl_pct_price = (cp - entry_price) / entry_price * mult_dir  # mouvement prix brut (sans LEV)

        # 1. Time exit (MHH) — toujours
        hours_held = 0.0  # default si parsing entry_time echoue
        try:
            entry_dt   = datetime.fromisoformat(entry_time)
            if entry_dt.tzinfo is None:
                entry_dt = entry_dt.replace(tzinfo=timezone.utc)
            hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600
            # === Cycle 6: TIME_DECAY MHH (96h → 48h si profit > MHH_PROFIT_THRESHOLD) ===
            mhh_eff = MHH
            if cycle6_on and USE_TIME_DECAY_MHH and pnl_pct_price >= MHH_PROFIT_THRESHOLD:
                mhh_eff = MHH_DECAY_HOURS
                if not pos.get('time_decay_notified', False):
                    pos['time_decay_notified'] = True
                    self._persist_positions()
                    await tg_send(f'⏰ TIME_DECAY {coin}: MHH {MHH}h→{MHH_DECAY_HOURS}h actif (profit +{pnl_pct_price*100:.1f}% prix)')
            if hours_held >= mhh_eff:
                reason_time = 'TIME_DECAY' if mhh_eff < MHH else 'TIME'
                log.info(f'[{coin}] {reason_time} EXIT après {hours_held:.1f}h (mhh_eff={mhh_eff}h, profit={pnl_pct_price*100:.2f}%)')
                await self.close_position(coin, direction, reason=reason_time)
                return
        except Exception as e:
            log.warning(f'[{coin}] time exit calc: {e}')

        if not bars_1m:
            return
        current_price = bars_1m[-1]['c']
        n_bars = len(bars_1m)

        # === Cycle 6: BREAKEVEN MOVE (SL → entry_price si profit ≥ BREAKEVEN_TRIGGER_PCT) ===
        if cycle6_on and USE_BREAKEVEN_MOVE and not pos.get('breakeven_moved', False):
            if pnl_pct_price >= BREAKEVEN_TRIGGER_PCT:
                old_sl = pos.get('sl_price', 0)
                pos['sl_price'] = entry_price
                pos['breakeven_moved'] = True
                sl_price = entry_price  # update local
                self._persist_positions()
                log.info(f'[{coin}] BREAKEVEN: SL {old_sl:.6f} → entry {entry_price:.6f} (profit={pnl_pct_price*100:.2f}%)')
                await tg_send(f'🛡️ BE: {coin} SL→entry @ ${entry_price:.4f} (profit {pnl_pct_price*100:.1f}% prix)')

        # === Cycle 6: MULTI-PARTIAL L1 (vendre MP_L1_RATIO à MP_L1_PCT prix) ===
        if cycle6_on and USE_MULTI_PARTIAL and not pos.get('partial_lvl1', False):
            if pnl_pct_price >= MP_L1_PCT:
                qty_initial = pos.get('qty_initial', pos['qty'])
                qty_to_close = max(1, int(qty_initial * MP_L1_RATIO))
                if qty_to_close < pos['qty']:
                    log.info(f'[{coin}] MP_L1: close {qty_to_close}/{pos["qty"]} (ratio {MP_L1_RATIO}, profit={pnl_pct_price*100:.2f}%)')
                    await self._partial_close(coin, direction, qty_to_close, reason='MP_L1')
                    pos['partial_lvl1'] = True
                    self._persist_positions()

        # === Cycle 6: PARTIAL EXIT (vendre PARTIAL_EXIT_RATIO à PARTIAL_TP_PCT prix) ===
        if cycle6_on and USE_PARTIAL_EXIT and not pos.get('partial_done', False):
            if pnl_pct_price >= PARTIAL_TP_PCT:
                qty_initial = pos.get('qty_initial', pos['qty'])
                qty_to_close = max(1, int(qty_initial * PARTIAL_EXIT_RATIO))
                if qty_to_close < pos['qty']:
                    log.info(f'[{coin}] PARTIAL: close {qty_to_close}/{pos["qty"]} (ratio {PARTIAL_EXIT_RATIO}, profit={pnl_pct_price*100:.2f}%)')
                    await self._partial_close(coin, direction, qty_to_close, reason='PARTIAL_TP')
                    pos['partial_done'] = True
                    self._persist_positions()

        # === Cycle 6: MULTI-PARTIAL L2 (vendre MP_L2_RATIO à MP_L2_PCT prix) ===
        if cycle6_on and USE_MULTI_PARTIAL and not pos.get('partial_lvl2', False):
            if pnl_pct_price >= MP_L2_PCT:
                qty_initial = pos.get('qty_initial', pos['qty'])
                qty_to_close = max(1, int(qty_initial * MP_L2_RATIO))
                if qty_to_close < pos['qty']:
                    log.info(f'[{coin}] MP_L2: close {qty_to_close}/{pos["qty"]} (ratio {MP_L2_RATIO}, profit={pnl_pct_price*100:.2f}%)')
                    await self._partial_close(coin, direction, qty_to_close, reason='MP_L2')
                    pos['partial_lvl2'] = True
                    self._persist_positions()

        # 2. Soft SL check (intra-bar) — toujours (protection rapide -10%)
        if sl_price and entry_price:
            if direction == 'LONG' and current_price <= sl_price:
                log.info(f'[{coin}] SL_SOFT LONG @ {current_price:.6f} <= {sl_price:.6f}')
                await self.close_position(coin, direction, reason='SL_SOFT')
                return
            if direction == 'SHORT' and current_price >= sl_price:
                log.info(f'[{coin}] SL_SOFT SHORT @ {current_price:.6f} >= {sl_price:.6f}')
                await self.close_position(coin, direction, reason='SL_SOFT')
                return

        # 3. TP sécurité — après MIN_HOLD_HOURS (parity C139: TP_ACC=0.75/lev=7 = 10.714% brut = +75% lev)
        if entry_price and hours_held >= MIN_HOLD_HOURS:
            tp_price_long  = entry_price * (1 + TP_PCT)
            tp_price_short = entry_price * (1 - TP_PCT)
            if direction == 'LONG' and current_price >= tp_price_long:
                log.info(f'[{coin}] TP_SAFETY LONG @ {current_price:.6f} >= {tp_price_long:.6f} (+{TP_PCT*100:.1f}% brut = +{TP_PCT*LEVERAGE*100:.0f}% lev)')
                await self.close_position(coin, direction, reason='TP_SAFETY')
                return
            if direction == 'SHORT' and current_price <= tp_price_short:
                log.info(f'[{coin}] TP_SAFETY SHORT @ {current_price:.6f} <= {tp_price_short:.6f} (-{TP_PCT*100:.1f}% brut = -{TP_PCT*LEVERAGE*100:.0f}% lev)')
                await self.close_position(coin, direction, reason='TP_SAFETY')
                return

        # 4. ATR Trail exit — actif apres MIN_HOLD_HOURS depuis entree (Backtest v6 Optimal)
        # Activation: gain >= TRAIL_ACT * ATR_entry/entry_price
        # Stop: best_price - TRAIL_DIST * ATR_courant (LONG) / + (SHORT)

        # Mise a jour best_price sur chaque tick (intrabar et bar_closed)
        if bars_1m:
            if direction == 'LONG':
                pos['best_price'] = max(pos.get('best_price', entry_price), bars_1m[-1]['h'])
            else:
                pos['best_price'] = min(pos.get('best_price', entry_price), bars_1m[-1]['l'])
            self._persist_positions()
        best_price = pos.get('best_price', entry_price)

        if not bar_closed:
            return

        # Verifier le delai minimum
        try:
            entry_dt_tr = datetime.fromisoformat(entry_time)
            if entry_dt_tr.tzinfo is None:
                entry_dt_tr = entry_dt_tr.replace(tzinfo=timezone.utc)
            hours_held_tr = (datetime.now(timezone.utc) - entry_dt_tr).total_seconds() / 3600
        except Exception:
            hours_held_tr = 999.0

        if hours_held_tr < MIN_HOLD_HOURS:
            log.debug(f'[{coin}] trail INACTIF: {hours_held_tr:.1f}h < {MIN_HOLD_HOURS}h min')
            return

        # Calcul seuil d'activation
        if not entry_price or not atr_entry:
            return
        act_t = TRAIL_ACT * atr_entry / entry_price
        gain  = (best_price - entry_price) / entry_price * (1 if direction == 'LONG' else -1)

        if gain < act_t:
            log.debug(f'[{coin}] trail: gain={gain*100:.3f}% < act_t={act_t*100:.3f}% → HOLD')
            return

        # Trail actif — stop = best_price +/- TRAIL_DIST * ATR_courant
        bars_1h_t = list(self.candles[coin]['1h'])
        atr_1h_t  = calc_atr_series(bars_1h_t, ATR_PERIOD)
        atr_cur   = atr_1h_t[-1] if atr_1h_t else atr_entry

        if direction == 'LONG':
            trail_stop = best_price - TRAIL_DIST * atr_cur
            if current_price <= trail_stop:
                log.info(f'[{coin}] TRAIL EXIT LONG: price={current_price:.6f} <= trail={trail_stop:.6f} '
                         f'best={best_price:.6f} gain={gain*100:.2f}% atr={atr_cur:.6f}')
                await self.close_position(coin, direction, reason='TRAIL')
            else:
                pnl_pct_t = (current_price - entry_price) / entry_price * LEVERAGE * 100
                log.debug(f'[{coin}] TRAIL ACTIF LONG: trail={trail_stop:.6f} price={current_price:.6f} '
                          f'gain={gain*100:.2f}% pnl={pnl_pct_t:+.2f}%')
        else:
            trail_stop = best_price + TRAIL_DIST * atr_cur
            if current_price >= trail_stop:
                log.info(f'[{coin}] TRAIL EXIT SHORT: price={current_price:.6f} >= trail={trail_stop:.6f} '
                         f'best={best_price:.6f} gain={gain*100:.2f}% atr={atr_cur:.6f}')
                await self.close_position(coin, direction, reason='TRAIL')
            else:
                pnl_pct_t = (current_price - entry_price) / entry_price * (-1) * LEVERAGE * 100
                log.debug(f'[{coin}] TRAIL ACTIF SHORT: trail={trail_stop:.6f} price={current_price:.6f} '
                          f'gain={gain*100:.2f}% pnl={pnl_pct_t:+.2f}%')

    # ── Signal loop ───────────────────────────────────────────────────────────
    async def signal_loop(self):
        while True:
            try:
                watchdog_beat()
                await self.check_all_signals()
            except Exception as e:
                log.error(f'signal_loop: {e}')
                await tg_send(f'⚠️ ERREUR bot: {e}')
            # Smart sleep: sync avec le close de la barre 1h
            now          = datetime.now(timezone.utc)
            secs_in_hour = now.minute * 60 + now.second
            secs_to_next = 3600 - secs_in_hour
            sleep_secs   = (secs_to_next + 30) if secs_to_next < 90 else 60
            await asyncio.sleep(sleep_secs)

    async def check_all_signals(self):
        # Reload 1h, 4h et 1m via REST (garantit les bougies fermées — parité Champion v4)
        for coin in self.runtime_coins:
            sym = to_mexc_symbol(coin)
            for tf in ['1h', '4h', '1m']:
                try:
                    candles = self.rest.get_klines_full(sym, to_mexc_interval(tf), limit=VP_WIN + 50)
                    self.candles[coin][tf].clear()
                    self.candles[coin][tf].extend(candles)
                except Exception as e:
                    log.warning(f'fetch {tf} {coin}: {e}')

        for coin in self.runtime_coins:
            bars_1h = list(self.candles[coin]['1h'])
            bars_4h = list(self.candles[coin]['4h'])

            if len(bars_1h) < 20:
                continue
            if coin in self.positions:
                continue
            if len(self.positions) >= MAX_POSITIONS:
                log.info(f'Max positions atteint ({len(self.positions)}/{MAX_POSITIONS})')
                break

            # No re-entry on same 1h bar
            current_1h_ts = bars_1h[-1]['t'] if bars_1h else None
            if self._entered_in_bar.get(coin) == current_1h_ts:
                continue

            signal, atr_val = compute_signal(bars_1h, bars_4h, coin=coin)
            if signal == 'NONE':
                continue

            log.info(f'[{coin}] SIGNAL {signal} détecté! ATR={atr_val:.6f}')
            await tg_send(
                f'📡 <b>Signal {signal} — {coin}</b>\n'
                f'Prix: ${bars_1h[-1]["c"]:.4f} | ATR: {atr_val:.4f}\n'
                f'VP filter: ✅ passé | Ouverture...'
            )
            self._entered_in_bar[coin] = current_1h_ts
            try:
                await self.open_position(coin, signal, atr_val)
            except Exception:
                self._entered_in_bar[coin] = None

    # ── Open position ─────────────────────────────────────────────────────────
    async def open_position(self, coin: str, direction: str, atr_val: float = 0.0):
        if coin in self.positions or coin in self._opening_coins:
            log.warning(f"[{coin}] open_position: position deja ouverte — double-open ignore")
            return
        self._opening_coins.add(coin)
        sym  = to_mexc_symbol(coin)
        side = 1 if direction == 'LONG' else 3  # 1=Open Long, 3=Open Short

        try:
            ticker = self.rest.get_ticker(sym)
            price  = float(ticker.get('lastPrice', 0))
            if price <= 0:
                log.warning(f'[{coin}] ticker lastPrice=0, retry...')
                await asyncio.sleep(1)
                ticker = self.rest.get_ticker(sym)
                price  = float(ticker.get('lastPrice', 0))
            if price <= 0:
                bars_fb = list(self.candles[coin]['1m'])
                price = bars_fb[-1]['c'] if bars_fb else 0
                log.warning(f'[{coin}] ticker toujours 0 → fallback 1m close={price}')
            if price <= 0:
                log.error(f'[{coin}] price=0 impossible à résoudre → abandon ouverture')
                await tg_send(f'⚠️ {coin}: prix=0 (API glitch) → ouverture annulée')
                return
            balance     = self.rest.get_balance()
            qty         = calc_qty(balance, price, coin)
            mult        = 1 if direction == 'LONG' else -1
            sl_price    = (price - mult * ATR_SL_MULT * atr_val
                          if atr_val > 0 else price * (1 - mult * SL_PCT))

            log.info(f'[{coin}] open_position: direction={direction} price={price:.6f} '
                     f'balance={balance:.4f} qty={qty} sl_price={sl_price:.6f}')

            if qty <= 0:
                log.warning(f'[{coin}] qty invalide: balance={balance:.2f} price={price:.6f}')
                return

            notional   = price * get_contract_size(coin) * qty
            margin_used = notional / LEVERAGE
            margin_pct  = margin_used / balance * 100 if balance > 0 else 0
            if margin_pct > 80:
                log.warning(f'[{coin}] marge élevée: {margin_pct:.0f}% du capital')
                await tg_send(f'⚠️ Marge élevée: {margin_pct:.0f}% capital utilisé')

            if DRY_RUN:
                pos_new = {
                    'direction':   direction,
                    'entry_price': price,
                    'entry_time':  datetime.now(timezone.utc).isoformat(),
                    'atr_entry':   atr_val,
                    'sl_price':    sl_price,
                    'sl_id':       None,
                    'qty':         qty,
                    'best_price':  price,
                }
                self.positions[coin] = pos_new
                self._persist_positions()
                mult_dry    = 1 if direction == 'LONG' else -1
                tp_price_dry = price * (1 + mult_dry * TP_PCT)
                log.info(f'[DRY_RUN] OPEN {direction} {sym} @ {price:.4f} qty={qty} sl={sl_price:.4f} tp={tp_price_dry:.4f}')
                await tg_send(
                    f'[DRY_RUN] ✅ <b>OPEN {direction} {coin}</b>\n'
                    f'Prix: ${price:.4f} | Qty: {qty}\n'
                    f'SL: ${sl_price:.4f}  (-{SL_PCT*100:.0f}% prix → -{SL_PCT*LEVERAGE*MARGIN_PCT*100:.1f}% capital)\n'
                    f'TP: ${tp_price_dry:.4f} (+{TP_PCT*100:.0f}% prix → +{TP_PCT*LEVERAGE*MARGIN_PCT*100:.1f}% capital)\n'
                    f'Notional: ${balance*MARGIN_PCT*LEVERAGE:.1f} USDT | Marge: ${balance*MARGIN_PCT:.1f} USDT'
                )
                return

            log.info(f'[{coin}] place_order: sym={sym} side={side} qty={qty} lev={LEVERAGE}')
            result = self.rest.place_order(sym, side=side, qty=qty, leverage=LEVERAGE)
            log.info(f'[{coin}] place_order réponse: success={result.get("success")} '
                     f'data={result.get("data")} code={result.get("code")} msg={result.get("message","")!r}')
            if not result.get('success'):
                log.error(f'[{coin}] Erreur ordre complet: {json.dumps(result)}')
                await tg_send(f'ERREUR ouverture {coin}: code={result.get("code")} {result.get("message","")!r}')
                return

            # Prix après fill
            ticker2    = self.rest.get_ticker(sym)
            fill_price = float(ticker2.get('lastPrice', price))
            sl_price   = (fill_price - mult * ATR_SL_MULT * atr_val
                         if atr_val > 0 else fill_price * (1 - mult * SL_PCT))
            log.info(f'[{coin}] fill estimé: {fill_price:.6f} sl={sl_price:.6f}')

            # SL sur exchange (plan order)
            sl_side   = 4 if direction == 'LONG' else 2
            log.info(f'[{coin}] place_plan_order: sym={sym} side={sl_side} vol={qty} stopPrice={sl_price:.6f}')
            sl_result = self.rest.place_plan_order(sym, sl_side, qty, sl_price, LEVERAGE)
            sl_id     = sl_result.get('data') if sl_result.get('success') else None
            log.info(f'[{coin}] plan_order réponse: success={sl_result.get("success")} '
                     f'data={sl_result.get("data")} code={sl_result.get("code")} msg={sl_result.get("message","")!r}')
            if not sl_result.get('success'):
                log.info(f'[{coin}] SL exchange non disponible (code={sl_result.get("code")}) — client-side SL actif @ {sl_price:.6f}')

            # Vérifier position sur exchange (retry x3 — lag exchange ~1-3s)
            pos_live = None
            for _chk in range(3):
                await asyncio.sleep(1)
                pos_live = self.rest.get_positions(sym)
                if pos_live:
                    break
            if pos_live:
                p = pos_live[0]
                log.info(f'[{coin}] position confirmée exchange: vol={p.get("vol")} '
                         f'type={p.get("positionType")} openPrice={p.get("openPrice")} '
                         f'margin={p.get("im","?")} unrealPnl={p.get("unrealizedPnl","?")}')
            else:
                log.warning(f'[{coin}] position non trouvée sur exchange après 3 tentatives')

            pos_new = {
                'direction':   direction,
                'entry_price': fill_price,
                'entry_time':  datetime.now(timezone.utc).isoformat(),
                'atr_entry':   atr_val,
                'sl_price':    sl_price,
                'sl_id':       sl_id,
                'qty':         qty,
                'qty_initial': qty,
                'best_price':  fill_price,
                # Cycle 6 desactive (Backtest v6 Optimal)
                'cycle6_enabled':  False,
                'partial_done':    True,
                'partial_lvl1':    True,
                'partial_lvl2':    True,
                'breakeven_moved': True,
            }
            self.positions[coin] = pos_new
            self._persist_positions()
            log.info(f'[{coin}] state sauvegardé: {json.dumps(pos_new, default=str)}')
            if qty < 5:
                log.warning(f'[{coin}] qty={qty} < 5 → trail actif, position sous-optimale')

            tp_price = fill_price * (1 + (TP_PCT if direction == 'LONG' else -TP_PCT))
            log.info(f'[{coin}] OPEN {direction} {LEVERAGE}x @ {fill_price:.6f} qty={qty} '
                     f'sl={sl_price:.6f} tp={tp_price:.6f} sl_id={sl_id}')
            c6_open = f'\nTrail: activation a {TRAIL_ACT*atr_val/fill_price*100:.3f}% gain | SL ATR x{ATR_SL_MULT:.2f}' if atr_val > 0 and fill_price > 0 else ''
            await tg_send(
                f'OPEN {direction} {coin} {LEVERAGE}x\n'
                f'Prix: ${fill_price:.4f} | Qty: {qty} (cs={get_contract_size(coin)})\n'
                f'SL: ${sl_price:.4f}  (-{SL_PCT*100:.0f}% prix → -{SL_PCT*LEVERAGE*MARGIN_PCT*100:.1f}% capital)\n'
                f'TP: ${tp_price:.4f} (+{TP_PCT*100:.0f}% prix → +{TP_PCT*LEVERAGE*MARGIN_PCT*100:.1f}% capital)\n'
                f'Notional: ~${fill_price * get_contract_size(coin) * qty:.2f} USDT'
                + c6_open
                + ('' if sl_id else '\nSL exchange N/A → client-side actif')
            )

        except Exception as e:
            log.error(f'[{coin}] Exception open: {e}', exc_info=True)
            await tg_send(f'EXCEPTION ouverture {coin}: {e}')
        finally:
            self._opening_coins.discard(coin)

    # ── Cycle 6: Partial close ────────────────────────────────────────────────
    async def _partial_close(self, coin: str, direction: str, qty_to_close: int, reason: str):
        """Ferme une partie de la position. Garde la position avec qty restante."""
        pos = self.positions.get(coin)
        if not pos:
            return
        if qty_to_close >= pos['qty']:
            log.warning(f'[{coin}] partial_close: qty_to_close {qty_to_close} >= pos qty {pos["qty"]} → full close')
            await self.close_position(coin, direction, reason=reason)
            return

        sym        = to_mexc_symbol(coin)
        close_side = 4 if direction == 'LONG' else 2
        entry_price = pos.get('entry_price', 0)

        try:
            ticker     = self.rest.get_ticker(sym)
            exit_price = float(ticker.get('lastPrice', 0))
        except Exception:
            exit_price = 0.0

        pnl_pct = 0
        if entry_price and exit_price:
            mult = 1 if direction == 'LONG' else -1
            pnl_pct = (exit_price - entry_price) / entry_price * mult * LEVERAGE * 100

        if DRY_RUN:
            append_trade(coin, direction, entry_price, exit_price, reason, qty_to_close)
            pos['qty'] -= qty_to_close
            self._persist_positions()
            log.info(f'[DRY_RUN] PARTIAL_CLOSE {direction} {coin} qty={qty_to_close} (remaining={pos["qty"]}) reason={reason}')
            await tg_send(f'[DRY_RUN] {reason} {coin} qty={qty_to_close} @ ${exit_price:.4f} ({pnl_pct:+.1f}%)')
            return

        log.info(f'[{coin}] PARTIAL CLOSE [{reason}]: side={close_side} qty={qty_to_close} ep={entry_price:.6f} exit~{exit_price:.6f}')
        for attempt in range(1, 4):
            try:
                result = self.rest.place_order(sym, side=close_side, qty=qty_to_close, leverage=LEVERAGE)
                if result.get('success'):
                    log.info(f'[{coin}] PARTIAL CLOSE OK [{reason}]: orderId={result.get("data")} qty={qty_to_close}')
                    pos['qty'] -= qty_to_close
                    self._persist_positions()
                    append_trade(coin, direction, entry_price, exit_price, reason, qty_to_close)
                    await tg_send(f'{reason} {coin} qty={qty_to_close}/{pos.get("qty_initial", qty_to_close)} @ ${exit_price:.4f} ({pnl_pct:+.1f}% capital)')
                    return
                else:
                    log.warning(f'[{coin}] PARTIAL attempt={attempt} failed: {result.get("code")} {result.get("message","")!r}')
                    await asyncio.sleep(15 if result.get('code') == 510 else 2)
            except Exception as e:
                log.error(f'[{coin}] PARTIAL exception attempt={attempt}: {e}')
                await asyncio.sleep(2)
        log.error(f'[{coin}] PARTIAL CLOSE [{reason}] FAILED 3 attempts')

    # ── Close position ────────────────────────────────────────────────────────
    async def close_position(self, coin: str, direction: str, reason: str = 'TRAIL'):
        pos = self.positions.get(coin)
        if not pos:
            return

        sym        = to_mexc_symbol(coin)
        close_side = 4 if direction == 'LONG' else 2  # 4=Close Long, 2=Close Short
        entry_price = pos.get('entry_price', 0)
        qty         = pos.get('qty', 1)
        sl_id       = pos.get('sl_id')

        try:
            ticker     = self.rest.get_ticker(sym)
            exit_price = float(ticker.get('lastPrice', 0))
        except Exception:
            exit_price = 0.0

        pnl_str = ''
        if entry_price and exit_price:
            mult        = 1 if direction == 'LONG' else -1
            pnl_pct     = (exit_price - entry_price) / entry_price * mult * LEVERAGE * 100
            cs          = get_contract_size(coin)
            pnl_usdt    = (exit_price - entry_price) * qty * cs * mult
            capital_pct = pnl_pct * MARGIN_PCT
            emoji       = '✅' if pnl_pct > 0 else '❌'
            pnl_str = (
                f'\nPnL: {pnl_usdt:+.2f} USDT {emoji}'
                f'\nPnL marge:  {pnl_pct:+.1f}%'
                f'\nPnL capital:{capital_pct:+.2f}% du capital total'
            )

        if DRY_RUN:
            append_trade(coin, direction, entry_price, exit_price, reason, qty)
            self.positions.pop(coin, None)
            self._persist_positions()
            log.info(f'[DRY_RUN] CLOSE {direction} {sym} [{reason}]')
            await tg_send(f'[DRY_RUN] 🔒 <b>CLOSE {direction} {coin}</b>\nRaison: {reason}{pnl_str}')
            return

        log.info(f'[{coin}] close_position: direction={direction} reason={reason} '
                 f'close_side={close_side} qty={qty} ep={entry_price:.6f} exit_est={exit_price:.6f}')

        # Annuler le SL exchange avant de fermer
        if sl_id:
            try:
                cancel_r = self.rest.cancel_plan_order(str(sl_id))
                log.info(f'[{coin}] cancel SL {sl_id}: success={cancel_r.get("success")} code={cancel_r.get("code")}')
            except Exception as e:
                log.warning(f'[{coin}] Cancel SL error: {e}')

        # Retry loop: MEXC peut accepter l'ordre (success=True) sans l'exécuter
        # (bug connu sur micro-notional + protection price deviation rate)
        MAX_CLOSE_ATTEMPTS = 3
        confirmed = False
        for attempt in range(1, MAX_CLOSE_ATTEMPTS + 1):
            try:
                log.info(f'[{coin}] place_order CLOSE attempt={attempt}: sym={sym} side={close_side} qty={qty}')
                result = self.rest.place_order(sym, side=close_side, qty=qty, leverage=LEVERAGE)
                log.info(f'[{coin}] close réponse: success={result.get("success")} '
                         f'data={result.get("data")} code={result.get("code")} msg={result.get("message","")!r}')
                if not result.get('success'):
                    log.error(f'[{coin}] ERREUR fermeture attempt={attempt}: {json.dumps(result)}')
                    await asyncio.sleep(2)
                    continue
            except Exception as e:
                log.error(f'[{coin}] Exception fermeture attempt={attempt}: {e}', exc_info=True)
                await asyncio.sleep(2)
                continue

            # Vérification réelle sur exchange (2s puis check)
            await asyncio.sleep(2)
            try:
                pos_live = self.rest.get_positions(sym)
            except Exception:
                pos_live = [1]  # en cas d'erreur API, on réessaie

            if not pos_live:
                confirmed = True
                log.info(f'[{coin}] position fermée confirmée (attempt={attempt})')
                break
            else:
                # Diagnostic: interroger l'historique pour savoir pourquoi l'ordre n'a pas exécuté
                _ORDER_STATE = {1: 'pending', 2: 'cancelled', 3: 'filled', 4: 'partial', 5: 'invalid'}
                try:
                    recent = self.rest.get_recent_orders(sym, page_size=3)
                    last_order_id = str(result.get('data', ''))
                    matched = next((o for o in recent if str(o.get('orderId')) == last_order_id), None)
                    if matched:
                        st = _ORDER_STATE.get(matched.get('state'), f"state={matched.get('state')}")
                        deal = matched.get('dealVol', 0)
                        vol  = matched.get('vol', qty)
                        log.warning(f'[{coin}] ordre {last_order_id}: {st} dealVol={deal}/{vol} '
                                    f'dealPrice={matched.get("dealAvgPrice")} fee={matched.get("takerFee")}')
                    else:
                        log.warning(f'[{coin}] ordre {last_order_id} introuvable dans historique récent')
                except Exception as diag_e:
                    log.warning(f'[{coin}] diagnostic ordre échoué: {diag_e}')
                log.warning(f'[{coin}] position encore ouverte après close attempt={attempt} — retry...')
                await asyncio.sleep(1)

        if confirmed:
            append_trade(coin, direction, entry_price, exit_price, reason, qty)
            self.positions.pop(coin, None)
            self._persist_positions()
            log.info(f'[{coin}] CLOSE {direction} [{reason}] @ {exit_price:.6f}{pnl_str}')
            await tg_send(f'CLOSE {direction} {coin}\nRaison: {reason}{pnl_str}')
        else:
            log.error(f'[{coin}] IMPOSSIBLE de fermer après {MAX_CLOSE_ATTEMPTS} tentatives — position conservée en state')
            await tg_send(
                f'⚠️ ALERTE {coin}: fermeture échouée x{MAX_CLOSE_ATTEMPTS}\n'
                f'Position LONG/SHORT toujours ouverte sur MEXC!\nFerme manuellement sur l\'app.'
            )

    # ── Hourly notification ───────────────────────────────────────────────────
    async def hourly_notif_loop(self):
        while True:
            await asyncio.sleep(3600)
            for coin, pos in list(self.positions.items()):
                try:
                    direction   = pos['direction']
                    ep          = pos.get('entry_price', 0)
                    entry_time  = pos.get('entry_time', '')
                    bars_1m     = list(self.candles[coin]['1m'])

                    entry_dt = datetime.fromisoformat(entry_time)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                    hours_held = (datetime.now(timezone.utc) - entry_dt).total_seconds() / 3600

                    ticker = self.rest.get_ticker(to_mexc_symbol(coin))
                    price  = float(ticker.get('lastPrice', 0))

                    mult = 1 if direction == 'LONG' else -1
                    pnl_pct = (price - ep) / ep * mult * LEVERAGE * 100 if ep else 0
                    sign = '+' if pnl_pct >= 0 else ''

                    ce_str = ''
                    atr_entry_h = pos.get('atr_entry', 0.0)
                    best_h = pos.get('best_price', ep)
                    if atr_entry_h > 0 and ep > 0:
                        act_t_h = TRAIL_ACT * atr_entry_h / ep
                        gain_h  = (best_h - ep) / ep * (1 if direction == 'LONG' else -1)
                        trail_s = 'ACTIF' if gain_h >= act_t_h else f'attente gain {act_t_h*100:.2f}%'
                        ce_str  = f'\nTrail: {trail_s} (best={best_h:.4f})'

                    c6_hourly = ''
                    if pos.get('cycle6_enabled'):
                        qi = pos.get('qty_initial', pos.get('qty', 1))
                        qc = pos.get('qty', 1)
                        ep_h = pos.get('entry_price', ep)
                        mult_h = 1 if direction == 'LONG' else -1
                        def tgt(pct): return ep_h * (1 + mult_h * pct)
                        lvl1 = '✅' if pos.get('partial_lvl1') else f'@${tgt(MP_L1_PCT):.4f}(+{MP_L1_PCT*100:.2f}%)'
                        lvl2 = '✅' if pos.get('partial_lvl2') else f'@${tgt(MP_L2_PCT):.4f}(+{MP_L2_PCT*100:.2f}%)'
                        part = '✅' if pos.get('partial_done') else f'@${tgt(PARTIAL_TP_PCT):.4f}(+{PARTIAL_TP_PCT*100:.2f}%)'
                        be_s = '✅' if pos.get('breakeven_moved') else f'@${tgt(BREAKEVEN_TRIGGER_PCT):.4f}(+{BREAKEVEN_TRIGGER_PCT*100:.0f}%)'
                        td_s = '✅' if pos.get('time_decay_notified') else f'@+{MHH_PROFIT_THRESHOLD*100:.0f}%→{MHH_DECAY_HOURS}h'
                        c6_hourly = (
                            f'\nC6 qty:{qi}→{qc} | L1:{lvl1} L2:{lvl2}'
                            f'\n   PART:{part} BE:{be_s} TD:{td_s}'
                        )
                    await tg_send(
                        f'[SUIVI] <b>{coin} {direction}</b>\n'
                        f'Entrée: ${ep:.4f} | Prix: ${price:.4f}\n'
                        f'PnL: {sign}{pnl_pct:.1f}%\n'
                        f'Hold: {hours_held:.1f}h / {MHH}h max'
                        + ce_str + c6_hourly
                    )
                except Exception as e:
                    log.warning(f'hourly_notif {coin}: {e}')

    # ── Run ───────────────────────────────────────────────────────────────────
    async def run(self):
        start_watchdog(600)
        await self.init()
        symbols_1m = [to_mexc_symbol(c) for c in self.runtime_coins]
        tg_cmds    = TelegramCommands(bot=self)
        await asyncio.gather(
            self.ws.subscribe_klines(symbols_1m, to_mexc_interval('1m')),
            self.signal_loop(),
            tg_cmds.start(),
            self.hourly_notif_loop(),
        )


if __name__ == '__main__':
    bot = MEXCBot()
    asyncio.run(bot.run())
