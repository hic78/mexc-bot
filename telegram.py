# telegram.py — Notifications + Commandes Telegram pour MEXC Bot
# Même fonctionnalité que Champion v4 (adapté MEXC)

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import aiohttp

from config import TG_TOKEN, TG_CHAT, COINS, LEVERAGE, DONCHIAN_PERIOD, CH_PERIOD, CH_MULTIPLIER
from config import EMA_1H_PERIOD, EMA_4H_PERIOD, SL_PCT, TP_PCT, MARGIN_PCT, CAPITAL_PCT, MAX_POSITIONS, DRY_RUN, MHH, VP_PCT, VP_WIN

BOT_DIR  = Path('/root/mexc-bot')
LOG_FILE = BOT_DIR / 'bot.log'
log = logging.getLogger('mexc')


async def tg_send(msg: str):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        async with aiohttp.ClientSession() as s:
            await s.post(
                f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                json={'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'},
                timeout=aiohttp.ClientTimeout(total=10),
            )
    except Exception as e:
        log.warning(f'TG send error: {e}')


class TelegramCommands:
    def __init__(self, bot):
        self.token    = TG_TOKEN
        self.chat_id  = TG_CHAT
        self.bot      = bot
        self.base_url = f'https://api.telegram.org/bot{TG_TOKEN}'
        self._update_id = 0
        self._running   = True

    async def start(self):
        if not self.token or not self.chat_id:
            return
        connector = aiohttp.TCPConnector(limit=5)
        self._session = aiohttp.ClientSession(connector=connector)
        try:
            async with self._session.get(
                f'{self.base_url}/getUpdates',
                params={'timeout': 0, 'offset': -1},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                data = await r.json()
                results = data.get('result', [])
                if results:
                    self._update_id = results[-1]['update_id'] + 1
        except Exception:
            pass

        log.info('Telegram command polling started')
        try:
            while self._running:
                try:
                    await self._poll()
                except (aiohttp.ServerTimeoutError, aiohttp.ClientConnectionError):
                    await asyncio.sleep(5)
                except Exception as e:
                    log.debug(f'TG poll: {e}')
                    await asyncio.sleep(5)
                else:
                    await asyncio.sleep(2)
        finally:
            await self._session.close()

    async def _poll(self):
        async with self._session.get(
            f'{self.base_url}/getUpdates',
            params={
                'timeout': 10,
                'offset': self._update_id,
                'allowed_updates': '["message"]',
            },
            timeout=aiohttp.ClientTimeout(total=20),
        ) as r:
            if r.status != 200:
                return
            data = await r.json()

        for update in data.get('result', []):
            self._update_id = update['update_id'] + 1
            msg = update.get('message', {})
            if str(msg.get('chat', {}).get('id', '')) != self.chat_id:
                continue
            text = msg.get('text', '').strip()
            if text.startswith('/'):
                await self._dispatch(text.lower().split()[0], text)

    async def _reply(self, msg: str):
        await tg_send(msg)

    async def _dispatch(self, cmd: str, full_text: str):
        log.info(f'TG command: {full_text}')
        handlers = {
            '/status':     self._status,
            '/balance':    self._balance,
            '/pnl':        self._pnl,
            '/orders':     self._orders,
            '/trades':     self._trades,
            '/risk':       self._risk,
            '/config':     self._config,
            '/logs':       self._logs,
            '/close':      self._close,
            '/coins':      self._coins,
            '/addcoin':    self._addcoin,
            '/removecoin': self._removecoin,
            '/help':       self._help,
        }
        fn = handlers.get(cmd)
        if fn:
            try:
                await fn(full_text)
            except Exception as e:
                await self._reply(f'Erreur {cmd}: {e}')
        else:
            await self._reply(f'Commande inconnue: {cmd}\nUtilise /help')

    async def _status(self, _):
        uptime = datetime.now(timezone.utc) - self.bot.start_time
        h = int(uptime.total_seconds()) // 3600
        m = (int(uptime.total_seconds()) % 3600) // 60
        lines = [f'<b>MEXC Bot Status</b>\nUptime: {h}h {m}m\nDRY_RUN: {DRY_RUN}\n']

        if not self.bot.positions:
            lines.append('Aucune position ouverte')
        else:
            for coin, pos in self.bot.positions.items():
                direction   = pos['direction']
                entry_price = pos.get('entry_price')
                entry_time  = pos.get('entry_time', '?')
                sl_price    = pos.get('sl_price', 0)
                mult        = 1 if direction == 'LONG' else -1
                tp_price    = entry_price * (1 + mult * TP_PCT) if entry_price else 0

                hours_held = '?'
                try:
                    entry_dt = datetime.fromisoformat(entry_time)
                    if entry_dt.tzinfo is None:
                        entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                    held_s = (datetime.now(timezone.utc) - entry_dt).total_seconds()
                    hours_held = f'{held_s / 3600:.1f}h'
                except Exception:
                    pass

                n_bars     = len(self.bot.candles.get(coin, {}).get('1m', []))
                chan_hours  = n_bars / 60
                chan_ok     = '✅' if n_bars >= CH_PERIOD else f'⚠️ {n_bars}/{CH_PERIOD}'

                try:
                    ticker = await asyncio.to_thread(
                        self.bot.rest.get_ticker, f'{coin}_USDT'
                    )
                    price = float(ticker.get('lastPrice', 0))
                    if entry_price and price:
                        pnl         = (price - entry_price) / entry_price * mult * LEVERAGE * 100
                        capital_pct = pnl * MARGIN_PCT
                        emoji       = '✅' if pnl > 0 else '❌'
                        pnl_str = f'{pnl:+.1f}% marge {emoji} ({capital_pct:+.2f}% capital)'
                    else:
                        pnl_str = 'N/A'
                except Exception:
                    price, pnl_str = 0, 'N/A'

                lines.append(
                    f'<b>{coin} {direction} {LEVERAGE}x</b>\n'
                    + (f'  Entree: ${entry_price:.4f}\n' if entry_price else '')
                    + f'  Prix: ${price:.4f}  PnL: {pnl_str}\n'
                    + (f'  SL: ${sl_price:.4f} (-{SL_PCT*100:.0f}% prix) | TP: ${tp_price:.4f} (+{TP_PCT*100:.0f}% prix)\n' if sl_price and tp_price else '')
                    + f'  Tenu: {hours_held} / {MHH}h\n'
                    + f'  Chan: {CH_PERIOD}×1m = {chan_hours:.1f}h {chan_ok}\n'
                )
        await self._reply('\n'.join(lines))

    async def _balance(self, _):
        try:
            bal = await asyncio.to_thread(self.bot.rest.get_balance)
            await self._reply(f'<b>Balance MEXC</b>\nUSDT disponible: ${bal:.2f}')
        except Exception as e:
            await self._reply(f'Erreur balance: {e}')

    async def _pnl(self, _):
        lines = ['<b>PnL détaillé</b>']
        if not self.bot.positions:
            lines.append('Aucune position ouverte')
        else:
            for coin, pos in self.bot.positions.items():
                direction   = pos['direction']
                entry_price = pos.get('entry_price')
                sl_price    = pos.get('sl_price', 0)
                mult        = 1 if direction == 'LONG' else -1
                tp_price    = entry_price * (1 + mult * TP_PCT) if entry_price else 0
                n_bars     = len(self.bot.candles.get(coin, {}).get('1m', []))
                chan_hours  = n_bars / 60
                chan_ok     = '✅' if n_bars >= CH_PERIOD else f'⚠️ {n_bars}/{CH_PERIOD}'
                try:
                    ticker = await asyncio.to_thread(
                        self.bot.rest.get_ticker, f'{coin}_USDT'
                    )
                    price = float(ticker.get('lastPrice', 0))
                    if entry_price and price:
                        pnl_pct     = (price - entry_price) / entry_price * mult * LEVERAGE * 100
                        capital_pct = pnl_pct * MARGIN_PCT
                        emoji       = '✅' if pnl_pct > 0 else '❌'
                        lines.append(
                            f'<b>{coin} {direction} {LEVERAGE}x</b>\n'
                            f'  Entree: ${entry_price:.4f} | Actuel: ${price:.4f}\n'
                            f'  PnL marge:  {pnl_pct:+.1f}% {emoji}\n'
                            f'  PnL capital:{capital_pct:+.2f}% du capital total\n'
                            + (f'  SL: ${sl_price:.4f} (-{SL_PCT*100:.0f}% prix) | TP: ${tp_price:.4f} (+{TP_PCT*100:.0f}% prix)\n' if sl_price and tp_price else '')
                            + f'  Chan: {CH_PERIOD}×1m = {chan_hours:.1f}h {chan_ok}'
                        )
                    else:
                        lines.append(f'{coin} {direction}: prix entrée non dispo')
                except Exception as e:
                    lines.append(f'{coin}: erreur: {e}')
        await self._reply('\n'.join(lines))

    async def _trades(self, _):
        lines = ['<b>Historique trades (10 derniers)</b>']
        trade_log = BOT_DIR / 'trades.json'
        if trade_log.exists():
            try:
                trades = json.loads(trade_log.read_text())[-10:]
                for t in reversed(trades):
                    pnl   = t.get('pnl', 0)
                    emoji = '✅' if pnl > 0 else '❌'
                    lines.append(
                        f"{emoji} {t.get('coin','?')} {t.get('direction','?')} "
                        f"[{t.get('reason','?')}] {pnl:+.1f}% "
                        f"({t.get('date','?')})"
                    )
            except Exception:
                lines.append('Erreur lecture trades.json')
        else:
            lines.append('Aucun historique (trades.json absent)')
        await self._reply('\n'.join(lines))

    async def _orders(self, _):
        lines = ['<b>Ordres / Positions MEXC</b>']
        if not self.bot.positions:
            lines.append('Aucune position ouverte (état interne)')
        else:
            for coin, pos in self.bot.positions.items():
                direction   = pos['direction']
                entry_price = pos.get('entry_price', 0)
                mult = 1 if direction == 'LONG' else -1
                sl_price = entry_price * (1 - mult * SL_PCT) if entry_price else 0
                lines.append(
                    f'<b>{coin} {direction}</b>\n'
                    + (f'  Entree: ${entry_price:.4f}\n' if entry_price else '')
                    + (f'  SL soft: ${sl_price:.4f} ({SL_PCT*100:.0f}%)\n' if sl_price else '')
                    + f'  Depuis: {pos.get("entry_time", "?")}'
                )
        # Positions live exchange (si API key configurée)
        try:
            live = await asyncio.to_thread(self.bot.rest.get_positions)
            if live:
                lines.append('\n<b>Positions exchange (live):</b>')
                for p in live:
                    lines.append(
                        f"  {p.get('symbol','?')} vol={p.get('vol','?')} "
                        f"side={p.get('positionType','?')} ep={p.get('openPrice','?')}"
                    )
        except Exception:
            pass
        await self._reply('\n'.join(lines))

    async def _risk(self, _):
        lines = ['<b>Risk Metrics</b>']
        try:
            bal = await asyncio.to_thread(self.bot.rest.get_balance)
            lines.append(f'Balance USDT: ${bal:.2f}')
        except Exception:
            pass
        if not self.bot.positions:
            lines.append('Aucune position ouverte')
        else:
            liq_dist = (1 / LEVERAGE - 0.002) * 100
            for coin, pos in self.bot.positions.items():
                direction   = pos['direction']
                entry_price = pos.get('entry_price', 0)
                if not entry_price:
                    lines.append(f'{coin}: prix entrée non disponible')
                    continue
                mult     = 1 if direction == 'LONG' else -1
                sl_price = entry_price * (1 - mult * SL_PCT)
                sl_dist  = SL_PCT * 100
                try:
                    ticker = await asyncio.to_thread(
                        self.bot.rest.get_ticker, f'{coin}_USDT'
                    )
                    price  = float(ticker.get('lastPrice', 0))
                    to_sl  = abs(price - sl_price) / price * 100
                    sl_capital = sl_dist / 100 * LEVERAGE * MARGIN_PCT * 100
                    lines.append(
                        f'<b>{coin} {direction}</b>\n'
                        f'  SL: ${sl_price:.4f}\n'
                        f'    → -{sl_dist:.0f}% du prix (brut)\n'
                        f'    → -{sl_capital:.1f}% du capital total si déclenché\n'
                        f'  Distance SL actuelle: {to_sl:.1f}% du prix\n'
                        f'  Liq approx: {liq_dist:.0f}% de l\'entrée'
                    )
                except Exception as e:
                    lines.append(f'{coin}: erreur: {e}')
        await self._reply('\n'.join(lines))

    async def _config(self, _):
        runtime = self.bot.runtime_coins
        max_pos = len(runtime)
        await self._reply(
            f'<b>MEXC Bot Config</b>\n'
            f'Coins actifs ({max_pos}): {" + ".join(runtime)}\n'
            f'Levier: {LEVERAGE}x\n'
            f'SL: {SL_PCT*100:.0f}% | TP sécurité: {TP_PCT*100:.0f}% brut\n'
            f'Marge/trade: {MARGIN_PCT*100:.0f}% capital (×{LEVERAGE}={MARGIN_PCT*LEVERAGE*100:.0f}% notional)\n'
            f'Max positions simultanées: {max_pos} (1 par coin)\n'
            f'Donchian: D{DONCHIAN_PERIOD} barres 1h\n'
            f'Chandelier: {CH_PERIOD}×1m × {CH_MULTIPLIER}×ATR ({CH_PERIOD}min = {CH_PERIOD//60}h{CH_PERIOD%60}m)\n'
            f'EMA 1h: {EMA_1H_PERIOD} | EMA 4h: {EMA_4H_PERIOD}\n'
            f'VP filter: {VP_PCT}e pct sur {VP_WIN} barres 1h | Max hold: {MHH}h\n'
            f'DRY_RUN: {DRY_RUN}'
        )

    async def _logs(self, _):
        try:
            lines = LOG_FILE.read_text().splitlines()[-15:]
            await self._reply('<b>Derniers logs</b>\n<pre>' + '\n'.join(lines) + '</pre>')
        except Exception as e:
            await self._reply(f'Erreur logs: {e}')

    async def _close(self, full_text: str):
        parts = full_text.split()
        if len(parts) >= 3 and parts[2].lower() == 'confirm':
            coin = parts[1].upper() if len(parts) >= 2 else None
            if not coin:
                await self._reply('Usage: /close SOL confirm')
                return
            await self._emergency_close(coin)
        elif len(parts) >= 2:
            coin = parts[1].upper()
            await self._reply(f'⚠️ Fermer {coin}? Confirme avec:\n/close {coin} confirm')
        else:
            coins_str = ' | '.join(self.bot.runtime_coins)
            await self._reply(
                f'Usage: /close COIN confirm\nCoins actifs: {coins_str}\n\n'
                '⚠️ FERME LA POSITION AU MARCHÉ'
            )

    async def _emergency_close(self, coin: str):
        pos = self.bot.positions.get(coin)
        if not pos:
            await self._reply(f'{coin}: aucune position ouverte')
            return
        direction = pos['direction']
        qty       = pos.get('qty', 1)
        sl_id     = pos.get('sl_id')
        sym  = f'{coin}_USDT'
        side = 4 if direction == 'LONG' else 2  # 4=Close Long, 2=Close Short
        try:
            if DRY_RUN:
                self.bot.positions.pop(coin, None)
                self.bot._persist_positions()
                await self._reply(f'[DRY_RUN] ✅ FERMETURE URGENCE {coin} {direction}')
                log.info(f'EMERGENCY CLOSE {coin} via Telegram (DRY_RUN)')
            else:
                if sl_id:
                    try:
                        await asyncio.to_thread(self.bot.rest.cancel_plan_order, str(sl_id))
                    except Exception:
                        pass
                result = await asyncio.to_thread(
                    self.bot.rest.place_order, sym, side, qty, LEVERAGE
                )
                if result.get('success'):
                    self.bot.positions.pop(coin, None)
                    self.bot._persist_positions()
                    await self._reply(f'✅ FERMETURE URGENCE {coin} {direction} effectuée (qty={qty})')
                    log.info(f'EMERGENCY CLOSE {coin} via Telegram qty={qty}')
                else:
                    await self._reply(f'❌ Erreur fermeture {coin}: {result}')
        except Exception as e:
            await self._reply(f'Exception fermeture {coin}: {e}')

    async def _coins(self, _):
        coins = self.bot.runtime_coins
        await self._reply(
            f'<b>Coins actifs ({len(coins)})</b>\n'
            + '\n'.join(f'  • {c}' + (' 📍' if c in self.bot.positions else '') for c in coins)
            + '\n\n/addcoin COIN — ajouter\n/removecoin COIN — retirer'
        )

    async def _addcoin(self, full_text: str):
        parts = full_text.split()
        if len(parts) < 2:
            await self._reply('Usage: /addcoin SOL\nCoins disponibles: SOL HYPE ZEC JUP BLUR FET DOGE')
            return
        coin = parts[1].upper()
        await self._reply(f'⏳ Ajout {coin} en cours...')
        result = await self.bot.add_coin(coin)
        await self._reply(result)

    async def _removecoin(self, full_text: str):
        parts = full_text.split()
        if len(parts) < 2:
            await self._reply(f'Usage: /removecoin COIN\nActifs: {" ".join(self.bot.runtime_coins)}')
            return
        coin = parts[1].upper()
        if coin in self.bot.positions:
            await self._reply(f'⚠️ {coin} a une position ouverte. Confirme avec:\n/removecoin {coin} confirm')
            if len(parts) < 3 or parts[2].lower() != 'confirm':
                return
        result = await self.bot.remove_coin(coin)
        await self._reply(result)

    async def _help(self, _):
        await self._reply(
            '<b>MEXC Bot Commands</b>\n\n'
            '/status  — Positions, PnL en cours\n'
            '/balance — Balance USDT disponible\n'
            '/pnl     — PnL détaillé par position\n'
            '/orders  — Positions + SL actifs\n'
            '/trades  — 10 derniers trades\n'
            '/risk    — Métriques risque + liquidation\n'
            '/config  — Configuration actuelle\n'
            '/logs    — 15 dernières lignes de log\n'
            '/close COIN confirm — Fermeture urgence\n'
            '/coins        — Liste coins actifs\n'
            '/addcoin COIN — Ajouter un coin live\n'
            '/removecoin COIN — Retirer un coin\n'
            '/help    — Cette aide\n\n'
            f'Exchange: MEXC Futures | DRY_RUN: {DRY_RUN}\n'
            '⚠️ SL = client-side (planorder MEXC en maintenance)'
        )
