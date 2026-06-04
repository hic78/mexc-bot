#!/usr/bin/env python3
"""
verify_alignment.py — À exécuter sur le VPS /root/mexc-bot/. Vérifie que CHAQUE coin est bien aligné
avec le bon graphique (bonnes données, fraîches) et diagnostique POURQUOI pas de signal (VP-skip vs NONE vs bug).
Utilise le code EXACT du bot (config + mexc_client + compute_signal) = fidélité totale.
"""
import sys, time, json
sys.path.insert(0, '/root/mexc-bot')
import config as C
from config import to_mexc_symbol, to_mexc_interval, get_contract_size
from mexc_client import MEXCRestClient
import bot as B  # pour compute_signal

rest = MEXCRestClient()
coins = json.load(open('/root/mexc-bot/state.json')).get('__coins__', C.COINS)
now = time.time()
print(f'{"COIN":5s}|{"bars1h":>6s}|{"age_h":>5s}|{"close_bot":>11s}|{"ticker_MEXC":>11s}|{"ecart%":>6s}|{"signal":>6s}|diag')
print('-'*92)
nb_skip=nb_none=nb_sig=nb_bug=0
for coin in coins:
    sym = to_mexc_symbol(coin)
    try:
        k1h = rest.get_klines_full(sym, to_mexc_interval('1h'), limit=1400)
        k4h = rest.get_klines_full(sym, to_mexc_interval('4h'), limit=1400)
        if not k1h:
            print(f'{coin:5s}| AUCUNE BOUGIE -> PROBLEME SYMBOLE/DATA'); nb_bug+=1; continue
        last = k1h[-1]
        age_h = (now - last['t']) / 3600.0
        close_bot = last['c']
        try:
            tk = rest.get_ticker(sym); ticker = float(tk.get('lastPrice', 0))
        except Exception:
            ticker = 0.0
        ecart = abs(close_bot - ticker)/ticker*100 if ticker>0 else 999
        sig, atr = B.compute_signal(k1h, k4h, coin=coin)
        # diag
        flag = 'OK' if (ecart<3 and age_h<3 and len(k1h)>200) else '!!!'
        if len(k1h)<=200: flag='PEU_BARRES'
        if age_h>=3: flag='PERIME'
        if ecart>=3 and ticker>0: flag='DESALIGNE'
        if sig!='NONE': nb_sig+=1
        elif flag!='OK': nb_bug+=1
        else: nb_none+=1
        print(f'{coin:5s}|{len(k1h):>6d}|{age_h:>5.1f}|{close_bot:>11.5f}|{ticker:>11.5f}|{ecart:>5.2f}%|{sig:>6s}|{flag}')
    except Exception as e:
        print(f'{coin:5s}| ERREUR: {str(e)[:50]}'); nb_bug+=1
    time.sleep(0.15)
print('-'*92)
print(f'RESUME: {nb_sig} signaux | {nb_none} NONE-legitimes | problemes/desalignes: {nb_bug}')
print('Si ecart% < 3 ET age_h < 2 ET bars>1000 pour tous -> coins BIEN alignes, pas de signal = NORMAL (filtre).')
