#!/usr/bin/env python3
"""
xsmom2_monitor.py — Moniteur santé du bot xsmom2 (cron toutes les 15 min).
Alerte Telegram SI problème (cooldown anti-spam). Heartbeat OK 1×/jour.
Checks : pm2 online | positions présentes & équilibrées | drawdown proche kill-switch.
"""
import subprocess, json, time, os, sys, requests, re
sys.path.insert(0, '/root/mexc-bot'); os.chdir('/root/mexc-bot')
try:
    from config import TG_TOKEN, TG_CHAT
except Exception:
    TG_TOKEN = TG_CHAT = None
import mexc_client as _m
ClientCls = getattr(_m, re.search(r'class (\w+)', open('/root/mexc-bot/mexc_client.py').read()).group(1))

KILL_DD   = 0.30   # élargi: parité backtest (pire mois -27%), ne fire que sur catastrophe
EQ0_FILE  = '/root/mexc-bot/xs_logs/equity0.txt'
CD_FILE   = '/root/mexc-bot/xs_logs/monitor_cooldown.json'

def tg(msg):
    try:
        if TG_TOKEN and TG_CHAT:
            requests.post(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage',
                          json={'chat_id': TG_CHAT, 'text': f'🩺 xsmom2-monitor | {msg}'}, timeout=8)
    except Exception: pass

def can_alert(key, mins=60):
    """Cooldown : ne re-alerte pas le même problème avant 'mins' minutes (anti-spam)."""
    d = {}
    try: d = json.load(open(CD_FILE))
    except Exception: pass
    now = time.time()
    if now - d.get(key, 0) < mins*60: return False
    d[key] = now
    try: json.dump(d, open(CD_FILE, 'w'))
    except Exception: pass
    return True

# 1) pm2 online ?
online = False
try:
    j = json.loads(subprocess.run(['pm2', 'jlist'], capture_output=True, text=True, timeout=15).stdout)
    for p in j:
        if p.get('name') == 'xsmom2':
            online = p.get('pm2_env', {}).get('status') == 'online'
except Exception:
    pass
_TS = time.strftime('%Y-%m-%d %H:%M:%S')
if not online:
    print(f'{_TS} | 🔴 DOWN — pm2 xsmom2 != online')
    if can_alert('down', 30):
        tg('🔴 BOT DOWN — pm2 "xsmom2" != online ! Relance: pm2 restart xsmom2 (ou XS_DRY_RUN=0 ... pm2 start)')
    sys.exit(0)

# 2) positions + equity
try:
    c = ClientCls(); ps = c.get_positions(); eq = c.get_equity()
    L = sum(1 for p in ps if p.get('positionType') == 1)
    S = sum(1 for p in ps if p.get('positionType') == 2)
except Exception as e:
    print(f'{_TS} | ⚠️ API_ERROR: {str(e)[:80]}')
    if can_alert('api', 30): tg(f'⚠️ Erreur API (monitor): {str(e)[:100]}')
    sys.exit(0)

# equity initiale (persistée)
eq0 = eq
try:
    eq0 = float(open(EQ0_FILE).read().strip())
except Exception:
    try: open(EQ0_FILE, 'w').write(str(eq))
    except Exception: pass
dd = (1 - eq/eq0) * 100 if eq0 else 0
print(f'{_TS} | ✅ online | {len(ps)} pos ({L}L/{S}S) | eq={eq:.2f} | dd={dd:+.1f}%')  # heartbeat log

# 3) checks → alertes (avec cooldown)
problem = False
if len(ps) == 0:
    problem = True
    if can_alert('nopos', 30): tg(f'⚠️ 0 position ! (devrait être ~10). Equity ${eq:.2f}. Vérifie le bot.')
elif abs(L - S) > 2:
    problem = True
    if can_alert('unbal', 60): tg(f'⚠️ Déséquilibré: {L} LONG / {S} SHORT (devrait être ~5/5). Equity ${eq:.2f}')
if eq < eq0 * (1 - KILL_DD * 0.8):   # à 80% du chemin vers le kill-switch
    problem = True
    if can_alert('dd', 30): tg(f'⚠️ Drawdown {dd:+.1f}% — PROCHE du kill-switch (-{KILL_DD*100:.0f}% à ${eq0*(1-KILL_DD):.2f}). Equity ${eq:.2f}')

# 4) heartbeat OK 1×/jour (confirme que le moniteur tourne)
if not problem and can_alert('daily_ok', 60*23):
    tg(f'✅ OK | online | {len(ps)} pos ({L}L/{S}S) | equity ${eq:.2f} ({dd:+.1f}%)')
