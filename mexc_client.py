# mexc_client.py — Couche API MEXC Futures
# Auth HMAC-SHA256 + REST + WebSocket
# NE PAS CONFONDRE AVEC champion-v4-bot

import hmac
import hashlib
import logging
import time
import json
import asyncio
import requests
import websockets
from config import BASE_REST, BASE_WS, API_KEY, SECRET_KEY, get_price_decimals

log = logging.getLogger('mexc.client')


class MEXCRestClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'Content-Type': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
            'Origin': 'https://futures.mexc.com',
            'Referer': 'https://futures.mexc.com/',
            'Accept': 'application/json, text/plain, */*',
            'Accept-Language': 'en-US,en;q=0.9',
        })

    def _sign(self, timestamp: str, params_str: str) -> str:
        target = f'{API_KEY}{timestamp}{params_str}'
        return hmac.new(SECRET_KEY.encode(), target.encode(), hashlib.sha256).hexdigest()

    def _headers(self, timestamp: str, signature: str) -> dict:
        return {
            'ApiKey': API_KEY,
            'Request-Time': timestamp,
            'Signature': signature,
            'Content-Type': 'application/json',
        }

    def _get(self, endpoint: str, params: dict = None) -> dict:
        ts = str(int(time.time() * 1000))
        params = {k: v for k, v in (params or {}).items() if v is not None}
        params_str = '&'.join(f'{k}={v}' for k, v in sorted(params.items())) if params else ''
        sig = self._sign(ts, params_str)
        url = BASE_REST + endpoint + (f'?{params_str}' if params_str else '')
        log.debug(f'GET {endpoint} params={params_str or "{}"}')
        t0 = time.time()
        r = self.session.get(url, headers=self._headers(ts, sig), timeout=10)
        elapsed = (time.time() - t0) * 1000
        log.debug(f'GET {endpoint} → HTTP {r.status_code} ({elapsed:.0f}ms)')
        if r.status_code != 200:
            log.error(f'GET {endpoint} HTTP {r.status_code}: {r.text[:500]}')
            return {'success': False, 'code': r.status_code, 'message': r.text[:300]}
        try:
            resp = r.json()
        except Exception:
            log.error(f'GET {endpoint} réponse non-JSON: {r.text[:500]}')
            return {'success': False, 'code': -1, 'message': r.text[:300]}
        log.debug(f'GET {endpoint} success={resp.get("success")} code={resp.get("code")}')
        if not resp.get('success') and resp.get('code') not in (None, 0, 200):
            log.warning(f'GET {endpoint} ERREUR: code={resp.get("code")} msg={resp.get("message")!r}')
        return resp

    def _post(self, endpoint: str, body: dict) -> dict:
        ts = str(int(time.time() * 1000))
        body_str = json.dumps(body, separators=(',', ':'))
        sig = self._sign(ts, body_str)
        log.debug(f'POST {endpoint} body={body_str}')
        t0 = time.time()
        r = self.session.post(
            BASE_REST + endpoint,
            headers=self._headers(ts, sig),
            data=body_str,
            timeout=10,
        )
        elapsed = (time.time() - t0) * 1000
        log.debug(f'POST {endpoint} → HTTP {r.status_code} ({elapsed:.0f}ms) content-type={r.headers.get("content-type","?")}')
        if r.status_code != 200:
            log.error(f'POST {endpoint} HTTP {r.status_code}: {r.text[:500]}')
            return {'success': False, 'code': r.status_code, 'message': r.text[:300]}
        try:
            resp = r.json()
        except Exception:
            log.error(f'POST {endpoint} réponse non-JSON: {r.text[:500]}')
            return {'success': False, 'code': -1, 'message': r.text[:300]}
        log.debug(f'POST {endpoint} success={resp.get("success")} code={resp.get("code")} data={resp.get("data")}')
        if not resp.get('success'):
            log.warning(f'POST {endpoint} ERREUR: code={resp.get("code")} msg={resp.get("message")!r}')
        return resp

    # ── Market (public, pas d'auth) ───────────────────
    def ping(self) -> dict:
        r = self.session.get(f'{BASE_REST}/api/v1/contract/ping', timeout=5)
        return r.json()

    def get_klines_full(self, symbol: str, interval: str, limit: int = 200) -> list:
        r = self.session.get(
            f'{BASE_REST}/api/v1/contract/kline/{symbol}',
            params={'interval': interval, 'limit': limit},
            timeout=10,
        )
        data = r.json().get('data', {})
        if not data:
            return []
        candles = []
        times  = data.get('time', [])
        opens  = data.get('open', [])
        highs  = data.get('high', [])
        lows   = data.get('low', [])
        closes = data.get('close', [])
        vols   = data.get('vol', [])
        for i in range(len(times)):
            candles.append({
                't': times[i],
                'o': float(opens[i]),
                'h': float(highs[i]),
                'l': float(lows[i]),
                'c': float(closes[i]),
                'v': float(vols[i]),
            })
        return candles

    def get_ticker(self, symbol: str, retries: int = 3) -> dict:
        for attempt in range(retries):
            try:
                r = self.session.get(
                    f'{BASE_REST}/api/v1/contract/ticker',
                    params={'symbol': symbol},
                    timeout=5,
                )
                data = r.json().get('data', {})
                if data and float(data.get('lastPrice', 0)) > 0:
                    return data
                import time as _t; _t.sleep(0.5)
            except Exception:
                import time as _t; _t.sleep(0.5)
        return {}

    def get_funding_rate(self, symbol: str) -> dict:
        r = self.session.get(
            f'{BASE_REST}/api/v1/contract/funding_rate/{symbol}',
            timeout=5,
        )
        return r.json().get('data', {})

    # ── Account (prive, auth requise) ────────────────
    def get_balance(self) -> float:
        data = self._get('/api/v1/private/account/assets')
        for asset in (data.get('data') or []):
            if asset.get('currency') == 'USDT':
                return float(asset.get('availableBalance', 0))
        return 0.0

    def get_positions(self, symbol: str = None) -> list:
        params = {'symbol': symbol} if symbol else {}
        data = self._get('/api/v1/private/position/open_positions', params)
        return data.get('data') or []

    def get_open_orders(self, symbol: str) -> list:
        data = self._get(f'/api/v1/private/order/open_orders/{symbol}')
        return data.get('data') or []

    # ── Orders ────────────────────────────────────────
    def place_order(self, symbol: str, side: int, qty: float, leverage: int = 3, sl_price: float = None) -> dict:
        # side: 1=Open Long, 2=Close Short, 3=Open Short, 4=Close Long
        # Note: stopLossPrice dans order/submit retourne code=5003 (price tick invalide) — non utilisé
        body = {
            'symbol': symbol,
            'price': 0,
            'vol': qty,
            'side': side,
            'type': 5,       # Market order
            'openType': 1,   # Isolated margin
            'leverage': leverage,
        }
        return self._post('/api/v1/private/order/submit', body)

    def cancel_order(self, order_id: str) -> dict:
        return self._post('/api/v1/private/order/cancel', {'orderId': order_id})

    def set_leverage(self, symbol: str, leverage: int) -> dict:
        body = {'symbol': symbol, 'leverage': leverage, 'openType': 1}
        return self._post('/api/v1/private/position/change_leverage', body)

    # ── Plan orders (SL/TP exchange) ──────────────────
    def place_plan_order(self, symbol: str, side: int, vol: float,
                         stop_price: float, leverage: int = 3) -> dict:
        # side: 4=Close Long (SL for LONG), 2=Close Short (SL for SHORT)
        # triggerPrice = prix déclencheur (anciennement stopPrice — corrigé selon doc MEXC)
        # triggerType: 1=Mark Price, 2=Last Price
        # planCategory: 1=Stop-Loss, 2=Take-Profit
        body = {
            'symbol':       symbol,
            'vol':          vol,
            'side':         side,
            'type':         5,           # Market execution at trigger
            'openType':     1,           # Isolated margin
            'leverage':     leverage,
            'triggerPrice': round(stop_price, get_price_decimals(symbol.replace('_USDT', ''))),  # Nom corrigé (doc MEXC: triggerPrice)
            'triggerType':  2,           # 2=Last Price
            'planCategory': 1,           # 1=stop-loss
            'price':        0,
        }
        # Essayer d'abord le endpoint v1, puis v2 si échec code=9999
        result = self._post('/api/v1/private/planorder/place', body)
        if not result.get('success') and result.get('code') == 9999:
            log.info('plan_order v1 code=9999 → retry avec /planorder/place/v2')
            body2 = dict(body)
            result = self._post('/api/v1/private/planorder/place/v2', body2)
        return result

    def cancel_plan_order(self, order_id: str) -> dict:
        return self._post('/api/v1/private/planorder/cancel', {'orderId': order_id})

    def get_plan_orders(self, symbol: str = None) -> list:
        params = {'symbol': symbol} if symbol else {}
        data = self._get('/api/v1/private/planorder/list/open', params)
        if data.get('success'):
            return (data.get('data') or {}).get('resultList') or []
        # Endpoint 404 or permission denied — return empty list silently
        return []

    def get_recent_orders(self, symbol: str, page_size: int = 3) -> list:
        data = self._get('/api/v1/private/order/list/history_orders', {
            'symbol': symbol, 'pageSize': page_size
        })
        if data.get('success'):
            raw = data.get('data') or []
            return raw if isinstance(raw, list) else []
        return []

    def get_equity(self) -> float:
        data = self._get('/api/v1/private/account/assets')
        for asset in (data.get('data') or []):
            if asset.get('currency') == 'USDT':
                return float(asset.get('equity', asset.get('availableBalance', 0)))
        return 0.0


class MEXCWebSocket:
    def __init__(self, on_kline_callback):
        self.on_kline  = on_kline_callback
        self._ws       = None       # connexion active (pour subscribe dynamique)
        self._symbols  = []         # liste complète (initiale + ajoutées)
        self._interval = 'Min1'
        self._log      = logging.getLogger('mexc.ws')

    async def subscribe_coin(self, symbol: str, interval: str):
        """Souscrit un nouveau coin sur la connexion WS existante."""
        if symbol not in self._symbols:
            self._symbols.append(symbol)
        if self._ws is not None:
            try:
                sub = json.dumps({'method': 'sub.kline', 'param': {'symbol': symbol, 'interval': interval}})
                await self._ws.send(sub)
                self._log.info(f'WS +subscribe {symbol} @ {interval}')
            except Exception as e:
                self._log.warning(f'WS send erreur ({e}) — {symbol} sera souscrit à la prochaine reconnexion')
        else:
            self._log.warning(f'WS non connecté — {symbol} sera souscrit à la prochaine reconnexion')

    async def subscribe_klines(self, symbols: list, interval: str):
        self._symbols  = list(symbols)
        self._interval = interval
        while True:
            try:
                self._log.info(f'WS connecting {BASE_WS}')
                async with websockets.connect(BASE_WS, ping_interval=20, ping_timeout=10) as ws:
                    self._ws = ws
                    for sym in self._symbols:  # inclut les coins ajoutés dynamiquement
                        sub = json.dumps({'method': 'sub.kline', 'param': {'symbol': sym, 'interval': interval}})
                        await ws.send(sub)
                        self._log.debug(f'WS subscribe: {sub}')
                    self._log.info(f'WS subscribed: {self._symbols} @ {interval}')
                    last_ping = time.time()
                    async for raw in ws:
                        msg = json.loads(raw)
                        ch  = msg.get('channel', '')
                        if time.time() - last_ping > 20:
                            await ws.send(json.dumps({'method': 'ping'}))
                            last_ping = time.time()
                            self._log.debug('WS ping sent')
                        if ch == 'push.kline':
                            d = msg.get('data', {})
                            self._log.debug(f'WS kline {msg["symbol"]} t={d.get("t")} c={d.get("c")} closed={d.get("r")}')
                            await self.on_kline(msg['symbol'], d)
                        elif ch not in ('', 'pong'):
                            self._log.debug(f'WS msg channel={ch!r}: {json.dumps(msg)[:200]}')
            except Exception as e:
                self._ws = None
                self._log.error(f'WS erreur: {e} — reconnexion dans 5s')
                await asyncio.sleep(5)
