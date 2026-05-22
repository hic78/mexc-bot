# MEXC Bot — Instructions IA

## RÈGLE ABSOLUE N°1 — ISOLATION TOTALE

| Bot | Dossier VPS | Exchange | Status |
|-----|------------|----------|--------|
| Champion v4 | /root/champion-v4-bot/ | Hyperliquid | LIVE — JAMAIS TOUCHER |
| Aster Bot | /root/aster-bot/ | Aster DEX | FUTUR |
| MEXC Bot | /root/mexc-bot/ | MEXC Futures | EN CONSTRUCTION |

**JAMAIS modifier /root/champion-v4-bot/bot.py**
**JAMAIS modifier /root/champion-v4-bot/ quoi que ce soit**

## Exchange

- Exchange : MEXC Futures (CEX)
- REST : https://contract.mexc.com
- WebSocket : wss://contract.mexc.com/edge
- Frais : 0.00% maker / 0.02% taker

## Format API (DIFFÉRENT de Binance)

- Symboles : BTC_USDT (avec underscore)
- Intervalles : Min1, Min5, Min15, Min60, Hour4, Day1
- Auth : Headers ApiKey + Request-Time + Signature
- Réponse : {success: true, code: 0, data: {...}}

## Coins (volume validé)

SOL_USDT, DOGE_USDT, HYPE_USDT, ZEC_USDT

## Stack

Python 3.10+, pymexc, asyncio, websockets, python-dotenv

## Problèmes connus

- API order parfois under maintenance → utiliser bypass mexc_bypass.py
- Rate limit : 20 req/2s market, 2 req/2s orders
- KYC obligatoire pour futures
- Keys expirent 90j sans IP binding → binder l'IP VPS
