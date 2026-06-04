#!/usr/bin/env python3
"""perf_report.py — Bilan PERFORMANCE live vs backtest (Telegram). Kill criteria NotebookLM. Cron hebdo VPS."""
import json, datetime, urllib.request, urllib.parse
BOT='/root/mexc-bot'
def env(k,d=''):
    try:
        for l in open(f'{BOT}/.env'):
            if l.startswith(k+'='): return l.split('=',1)[1].strip()
    except: pass
    return d
TOKEN=env('TELEGRAM_TOKEN'); CHAT=env('TELEGRAM_CHAT_ID')
DEPLOY='2026-06-04'
try: t=json.load(open(f'{BOT}/trades.json'))
except: t=[]
tr=[x for x in t if str(x.get('date','')) >= DEPLOY]
n=len(tr); wins=sum(1 for x in tr if x.get('pnl',0)>0)
wr=100*wins/n if n else 0
net=sum(x.get('pnl',0) for x in tr)
avg=net/n if n else 0
WR_BT=78.0
verdict='✅ conforme backtest'
if n>=20:
    if wr < WR_BT*0.5: verdict='🛑 KILL: WR sous 50% du backtest'
    elif net<0: verdict='⚠️ net négatif sur '+str(n)+' trades — surveiller'
    elif wr<60: verdict='⚠️ WR sous 60% — surveiller'
elif n>0: verdict=f'⏳ échantillon faible ({n} trades) — attendre 20+'
else: verdict='⏳ aucun trade clos depuis deploy'
today=datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
msg=('📊 <b>BILAN PERF C150-OPTIMUS</b> — '+today+'\n'
     'Depuis deploy '+DEPLOY+' :\n'
     'Trades clos: <b>'+str(n)+'</b> | WR: <b>'+f'{wr:.0f}'+'%</b> (backtest 78%)\n'
     'PnL net: <b>'+f'{net:+.2f}'+' USDT</b> | moy/trade: '+f'{avg:+.3f}'+'\n'
     'Verdict: '+verdict+'\n'
     'Kill criteria NLM: WR sous 39% OU net négatif (20+ trades) → revoir la strat.')
if TOKEN and CHAT:
    try:
        data=urllib.parse.urlencode({'chat_id':CHAT,'text':msg,'parse_mode':'HTML'}).encode()
        urllib.request.urlopen('https://api.telegram.org/bot'+TOKEN+'/sendMessage',data=data,timeout=15)
        print('TG perf OK:',today,'| n',n,'wr',round(wr),'net',round(net,2))
    except Exception as e: print('TG erreur:',e)
else: print(msg)
