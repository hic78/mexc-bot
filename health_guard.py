#!/usr/bin/env python3
"""
health_guard.py — Vérificateur horaire de santé du bot MEXC C150-OPTIMUS.
Vérifie 8 points. Envoie une alerte Telegram UNIQUEMENT si un problème est détecté
(silencieux sinon = best practice anti-spam). Log dans health_guard.log.
Cron: 30 * * * * (décalé du hourly_report à :00).
"""
import sys, os, json, time, subprocess, urllib.request, urllib.parse
from datetime import datetime, timezone

sys.path.insert(0, '/root/mexc-bot')
from dotenv import load_dotenv
load_dotenv('/root/mexc-bot/.env')

BOT_DIR = '/root/mexc-bot'
LOG = '/root/mexc-bot/health_guard.log'
TG_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
TG_CHAT = os.getenv('TELEGRAM_CHAT_ID', '')

# Valeurs de config ATTENDUES (drift detection)
EXPECTED = {
    'TIME_STOP_ACTIVE': '1', 'OPTIMUS_ACTIVE': '1', 'LEVERAGE': '5',
    'VP_PCT': '90', 'MARGIN_PCT': '0.15', 'DRY_RUN': 'false',
}

def logline(msg):
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    with open(LOG, 'a') as f:
        f.write(f'{ts} | {msg}\n')

def tg_alert(msg):
    if not TG_TOKEN or not TG_CHAT:
        return
    try:
        data = urllib.parse.urlencode({'chat_id': TG_CHAT, 'text': msg, 'parse_mode': 'HTML'}).encode()
        req = urllib.request.Request(f'https://api.telegram.org/bot{TG_TOKEN}/sendMessage', data=data)
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        logline(f'TG send failed: {e}')

def main():
    problems = []
    infos = []

    # 1. Bot online (pm2) = LE vrai indicateur de vie
    restarts = 0
    try:
        out = subprocess.run(['pm2', 'jlist'], capture_output=True, text=True, timeout=15).stdout
        procs = json.loads(out)
        mexc = next((p for p in procs if p.get('name') == 'mexc-bot'), None)
        if not mexc or mexc.get('pm2_env', {}).get('status') != 'online':
            problems.append('🔴 BOT DOWN (pm2 status != online)')
        else:
            restarts = mexc.get('pm2_env', {}).get('restart_time', 0)
            uptime_ms = mexc.get('pm2_env', {}).get('pm_uptime', 0)
            # uptime trop court = crash récent
            up_min = (time.time()*1000 - uptime_ms) / 60000 if uptime_ms else 999
            if up_min < 3:
                problems.append(f'⚠️ Bot redémarré il y a {up_min:.0f} min (vérifier si crash)')
    except Exception as e:
        problems.append(f'🔴 pm2 check failed: {e}')

    # 2. Crash-loop detection — restarts qui augmentent vite (PAS le mtime de bot.log:
    #    le bot ne logge en INFO que les signaux → silence normal en marché calme, faux positifs)
    try:
        marker = '/tmp/health_guard_restarts'
        prev = 0
        if os.path.exists(marker):
            try: prev = int(open(marker).read().strip())
            except Exception: prev = 0
        # +3 restarts depuis le dernier passage (1h) = crash-loop
        if restarts - prev >= 3:
            problems.append(f'🔴 CRASH-LOOP: {restarts - prev} restarts en 1h (total {restarts})')
        open(marker, 'w').write(str(restarts))
    except Exception as e:
        infos.append(f'crash-loop check skip: {e}')

    # 3+4. Positions: state vs exchange + time-stop check
    try:
        from mexc_client import MEXCRestClient
        from config import TRAIL_ACT, MIN_HOLD_HOURS, get_contract_size, LEVERAGE, MARGIN_PCT
        r = MEXCRestClient()
        s = json.load(open(os.path.join(BOT_DIR, 'state.json')))
        state_pos = {c: v['position'] for c, v in s.items()
                     if c != '__coins__' and isinstance(v, dict) and v.get('position')}
        # exchange avec retry (401 intermittent)
        ex_pos = {}
        for _ in range(4):
            try:
                e = r.get_positions()
                if e is not None:
                    ex_pos = {p['symbol'].replace('_USDT', ''): p for p in e}
                    break
            except Exception:
                pass
            time.sleep(2)
        # 3. cohérence
        sset, eset = set(state_pos), set(ex_pos)
        if sset != eset:
            orphan_ex = eset - sset   # sur exchange mais pas dans state = DANGER (pas de SL)
            orphan_st = sset - eset   # dans state mais pas exchange = fantôme
            if orphan_ex:
                problems.append(f'🔴 POSITION ORPHELINE exchange (pas de protection bot): {sorted(orphan_ex)}')
            if orphan_st:
                problems.append(f'⚠️ Position fantôme state (fermée exchange): {sorted(orphan_st)}')
        # 4. time-stop: positions perdantes > MIN_HOLD+1.5h qui traînent
        total_margin = 0
        for coin, p in state_pos.items():
            ep = p.get('entry_price', 0); atr = p.get('atr_entry', 0); best = p.get('best_price', ep)
            d = p.get('direction'); qty = p.get('qty', 0)
            mult = 1 if d == 'LONG' else -1
            # hold
            try:
                et = datetime.fromisoformat(p.get('entry_time', ''))
                if et.tzinfo is None: et = et.replace(tzinfo=timezone.utc)
                hold = (datetime.now(timezone.utc) - et).total_seconds() / 3600
            except Exception:
                hold = 0
            if ep and atr:
                act_t = TRAIL_ACT * atr / ep
                gain = (best - ep) / ep * mult
                # si hold > MIN_HOLD+1.5h ET jamais profitable → le time-stop aurait dû fermer
                if hold > MIN_HOLD_HOURS + 1.5 and gain < act_t:
                    problems.append(f'🔴 TIME_STOP non appliqué: {coin} {d} hold={hold:.1f}h gain={gain*100:.2f}%<{act_t*100:.2f}%')
            # marge
            try:
                cs = get_contract_size(coin)
                # prix approx via entry (suffisant pour estimer la marge)
                total_margin += ep * cs * qty / LEVERAGE
            except Exception:
                pass
        # 8. marge totale
        bal = 0
        try: bal = r.get_balance()
        except Exception: pass
        if bal > 0 and total_margin > 0.98 * bal:
            problems.append(f'⚠️ Marge élevée: {total_margin:.1f}$ / {bal:.1f}$ ({total_margin/bal*100:.0f}%)')
    except Exception as e:
        problems.append(f'⚠️ positions check failed: {e}')

    # 5. Config drift
    try:
        for k, want in EXPECTED.items():
            got = os.getenv(k, '')
            if str(got).lower() != str(want).lower():
                problems.append(f'🔴 CONFIG DRIFT: {k}={got} (attendu {want})')
    except Exception as e:
        problems.append(f'⚠️ config check failed: {e}')

    # 6. Erreurs critiques répétées (dernière heure, hors normaux)
    try:
        bl = os.path.join(BOT_DIR, 'bot.log')
        lines = subprocess.run(['tail', '-300', bl], capture_output=True, text=True, timeout=10).stdout.splitlines()
        NORMAL = ('code=9999', 'planorder', 'plan_order', 'SL exchange non disponible',
                  'WS erreur', 'reconnexion', 'set_leverage', 'CancelledError', 'received 1005')
        errs = [l for l in lines if ('Error' in l or 'ERROR' in l or 'CRITICAL' in l or 'Traceback' in l)
                and not any(n in l for n in NORMAL)]
        if len(errs) >= 5:
            problems.append(f'🔴 {len(errs)} erreurs anormales dans bot.log récent')
            infos.append('Exemple: ' + errs[-1][-120:])
    except Exception as e:
        problems.append(f'⚠️ log error check failed: {e}')

    # 7. Kill switch déclenché aujourd'hui
    try:
        bl = os.path.join(BOT_DIR, 'bot.log')
        lines = subprocess.run(['tail', '-500', bl], capture_output=True, text=True, timeout=10).stdout.splitlines()
        today = datetime.now().strftime('%Y-%m-%d')
        ks = [l for l in lines if 'KILL SWITCH' in l and today in l]
        if ks:
            infos.append(f'🛑 KILL SWITCH actif aujourd hui ({len(ks)} fois) — entrées stoppées')
    except Exception:
        pass

    # Résultat
    if problems:
        msg = '🚨 <b>MEXC Bot — ALERTE santé</b>\n' + '\n'.join(problems)
        if infos:
            msg += '\n\n' + '\n'.join(infos)
        tg_alert(msg)
        logline('ALERTE: ' + ' | '.join(problems))
    else:
        line = 'OK — bot sain'
        if infos:
            line += ' | ' + ' | '.join(infos)
            tg_alert('ℹ️ <b>MEXC Bot</b>\n' + '\n'.join(infos))
        logline(line)

if __name__ == '__main__':
    main()
