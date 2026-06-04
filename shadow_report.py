#!/usr/bin/env python3
"""
shadow_report.py — Résumé quotidien des décisions OPTIMUS SHADOW envoyé sur Telegram (autonome, sans Claude).
À cron quotidiennement sur le VPS. Lit le capture + bot.log, compte keep/veto, kill switch, pm2, envoie TG.
"""
import os, re, json, subprocess, urllib.request, urllib.parse, datetime
from collections import Counter

BOT='/root/mexc-bot'
def env(k, d=''):
    try:
        for line in open(f'{BOT}/.env'):
            if line.startswith(k+'='): return line.split('=',1)[1].strip()
    except Exception: pass
    return d

TOKEN=env('TELEGRAM_TOKEN'); CHAT=env('TELEGRAM_CHAT_ID')

def collect_optimus_lines():
    lines=set()
    for fp in (f'{BOT}/optimus_shadow_capture.log', f'{BOT}/bot.log'):
        try:
            for l in open(fp, errors='ignore'):
                if 'OPTIMUS' in l or 'KILL SWITCH' in l:
                    lines.add(l.strip())
        except Exception: pass
    return lines

def main():
    lines=collect_optimus_lines()
    keep_t=sum(1 for l in lines if 'OPTIMUS' in l and 'keep=True' in l)
    keep_f=sum(1 for l in lines if 'OPTIMUS' in l and 'keep=False' in l)
    markov_block=sum(1 for l in lines if 'markov:' in l and 'bloqué' in l)
    cs_veto=sum(1 for l in lines if 'CS-veto' in l)
    kill=sum(1 for l in lines if 'KILL SWITCH' in l)
    # pm2
    try:
        pm=subprocess.run(['pm2','jlist'],capture_output=True,text=True,timeout=10)
        js=json.loads(pm.stdout); m=[x for x in js if x.get('name')=='mexc-bot']
        status=m[0]['pm2_env']['status'] if m else '?'
        restarts=m[0]['pm2_env'].get('restart_time','?') if m else '?'
    except Exception:
        status='?'; restarts='?'
    today=datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    total=keep_t+keep_f
    verdict = '✅ cohérent' if (total>0 and keep_t>0) else ('⏳ peu de signaux encore' if total==0 else '⚠️ tout vetoé')
    msg=(f'🌑 <b>OPTIMUS SHADOW — résumé {today}</b>\n'
         f'Bot: {status} (restarts {restarts})\n'
         f'Signaux gated: <b>{total}</b> | gardés: {keep_t} | vetoés: {keep_f}\n'
         f'  ↳ Markov bloqué: {markov_block} | CS-veto: {cs_veto}\n'
         f'Kill switch déclenché: {kill}\n'
         f'État modules: {verdict}\n'
         f'{"➡️ Si cohérent plusieurs jours: activer OPTIMUS_ACTIVE=1" if total>5 else "➡️ Attendre plus de signaux avant activation"}')
    if TOKEN and CHAT:
        try:
            data=urllib.parse.urlencode({'chat_id':CHAT,'text':msg,'parse_mode':'HTML'}).encode()
            urllib.request.urlopen(f'https://api.telegram.org/bot{TOKEN}/sendMessage',data=data,timeout=15)
            print('TG envoyé:',today,'| gated',total,'keep',keep_t,'veto',keep_f,'kill',kill)
        except Exception as e:
            print('TG erreur:',e)
    else:
        print('Pas de TOKEN/CHAT'); print(msg)

if __name__=='__main__': main()
