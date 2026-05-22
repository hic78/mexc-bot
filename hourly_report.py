#!/usr/bin/env python3
"""
hourly_report.py — Rapport horaire automatique MEXC Bot
Envoie un résumé Telegram complet : positions, PnL, santé bot
"""
import json, os, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path
import urllib.request

BOT_DIR    = Path('/root/mexc-bot')
STATE_FILE = BOT_DIR / 'state.json'
ENV_FILE   = BOT_DIR / '.env'

CONTRACT_SIZES = {
    'SOL':0.1,'DOGE':100.0,'ZEC':0.01,'US':10.0,'LAB':10.0,
    'BTC':0.0001,'ETH':0.01,'XRP':1.0,'AVAX':0.1,'TAO':0.01,
    'CHZ':1.0,'H':1.0,'BILL':100.0,'RUNE':1.0,'HYPE':0.1,'EDEN':1.0,
}
LEVERAGE = 8

def load_env():
    env = {}
    try:
        for line in ENV_FILE.read_text().splitlines():
            line = line.strip()
            if '=' in line and not line.startswith('#'):
                k, _, v = line.partition('=')
                env[k.strip()] = v.strip()
    except Exception:
        pass
    return env

def get_price(symbol):
    try:
        url = f'https://contract.mexc.com/api/v1/contract/ticker?symbol={symbol}_USDT'
        req = urllib.request.urlopen(url, timeout=5)
        data = json.loads(req.read())
        return float(data['data']['lastPrice'])
    except Exception:
        return None

def tg_send(token, chat_id, msg):
    try:
        payload = json.dumps({'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data=payload, headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f'TG error: {e}')

def pm2_status():
    try:
        r = subprocess.run(['pm2', 'jlist'], capture_output=True, text=True, timeout=10)
        procs = json.loads(r.stdout)
        for p in procs:
            if p.get('name') == 'mexc-bot':
                penv = p.get('pm2_env', {})
                status = penv.get('status', '?')
                uptime_ms = penv.get('pm_uptime', 0)
                restarts = penv.get('restart_time', 0)
                now_ms = datetime.now().timestamp() * 1000
                uptime_min = int((now_ms - uptime_ms) / 60000)
                return status, uptime_min, restarts
    except Exception:
        pass
    return 'unknown', 0, 0

def format_hold(entry_time_str):
    try:
        entry = datetime.fromisoformat(entry_time_str.replace('+00:00','').replace('Z',''))
        entry = entry.replace(tzinfo=timezone.utc)
        diff = datetime.now(timezone.utc) - entry
        h = int(diff.total_seconds() // 3600)
        m = int((diff.total_seconds() % 3600) // 60)
        return f'{h}h{m:02d}m'
    except Exception:
        return '?'

def cycle6_str(pos):
    qty      = pos.get('qty', 0)
    qty_init = pos.get('qty_initial', qty)
    if qty_init < 5:
        return 'C6:OFF(qty&lt;5)'
    p1 = 'L1v' if pos.get('partial_lvl1') else 'L1.'
    pt = 'TPv' if pos.get('partial_done') else 'TP.'
    p2 = 'L2v' if pos.get('partial_lvl2') else 'L2.'
    be = 'BEv' if pos.get('breakeven_moved') else 'BE.'
    sold = int((1 - qty / qty_init) * 100) if qty_init else 0
    return f'C6:{p1}{pt}{p2}{be} -{sold}%'

def main():
    env = load_env()
    token   = env.get('TELEGRAM_TOKEN', '')
    chat_id = env.get('TELEGRAM_CHAT_ID', '')
    if not token or not chat_id:
        sys.exit('No Telegram config')

    now_str = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    pm2_st, uptime_min, restarts = pm2_status()
    pm2_icon = '🟢' if pm2_st == 'online' else '🔴'
    uptime_str = f'{uptime_min // 60}h{uptime_min % 60:02d}m'

    try:
        state = json.loads(STATE_FILE.read_text())
    except Exception:
        tg_send(token, chat_id, f'<b>MONITOR</b> {now_str}\nstate.json illisible!')
        sys.exit(1)

    positions = []
    for coin, data in state.items():
        if coin.startswith('__') or not isinstance(data, dict):
            continue
        pos = data.get('position')
        if not pos:
            continue
        price = get_price(coin)
        cs    = CONTRACT_SIZES.get(coin, 1.0)
        entry = pos.get('entry_price', 0)
        qty   = pos.get('qty', 0)
        direction = pos.get('direction', '?')
        sl    = pos.get('sl_price', 0)

        if price and entry:
            pnl_pct  = (price - entry) / entry if direction == 'LONG' else (entry - price) / entry
            pnl_usdt = pnl_pct * entry * qty * cs * LEVERAGE
        else:
            pnl_pct = pnl_usdt = 0
            price = 0

        sl_dist = abs(price - sl) / price * 100 if price and sl else 0

        positions.append({
            'coin': coin, 'dir': direction, 'entry': entry,
            'price': price, 'pnl_pct': pnl_pct, 'pnl_usdt': pnl_usdt,
            'qty': qty, 'qty_init': pos.get('qty_initial', qty),
            'sl_dist': sl_dist, 'c6': cycle6_str(pos),
            'hold': format_hold(pos.get('entry_time', '')),
        })

    positions.sort(key=lambda x: x['pnl_usdt'], reverse=True)
    total_pnl  = sum(p['pnl_usdt'] for p in positions)
    total_icon = '🟢' if total_pnl >= 0 else '🔴'
    c6_on  = sum(1 for p in positions if 'OFF' not in p['c6'])
    c6_off = sum(1 for p in positions if 'OFF' in p['c6'])

    lines = [
        f'📊 <b>MEXC Bot — Rapport Horaire</b>',
        f'🕐 {now_str}',
        f'{pm2_icon} pm2: {pm2_st} | up {uptime_str} | {restarts} restarts',
        f'',
        f'<b>{len(positions)} positions | PnL: {total_icon} {total_pnl:+.2f} USDT</b>',
        f'Cycle6: {c6_on} actif | {c6_off} dégradé',
        f'',
    ]

    for p in positions:
        icon = '🔼' if p['dir'] == 'LONG' else '🔽'
        pnl_icon = '🟢' if p['pnl_pct'] >= 0 else '🔴'
        sl_flag = ' 🚨' if p['sl_dist'] < 2 else (' ⚠️' if p['sl_dist'] < 4 else '')
        lines.append(
            f'{icon}<b>{p["coin"]}</b> {pnl_icon}{p["pnl_pct"]*100:+.1f}%'
            f' ({p["pnl_usdt"]:+.2f}$) {p["hold"]}{sl_flag}'
        )
        lines.append(
            f'  ep={p["entry"]:.5g} now={p["price"]:.5g}'
            f' q={p["qty"]}/{p["qty_init"]} SL∆{p["sl_dist"]:.1f}%'
        )
        lines.append(f'  {p["c6"]}')

    alerts = [
        f'🚨 <b>{p["coin"]}</b> SL à {p["sl_dist"]:.1f}%!'
        for p in positions if p['sl_dist'] < 2
    ]
    if alerts:
        lines += ['', '<b>ALERTES:</b>'] + alerts

    tg_send(token, chat_id, '\n'.join(lines))
    print(f'[{now_str}] Sent — {len(positions)} pos, PnL={total_pnl:+.2f}$')

if __name__ == '__main__':
    main()
