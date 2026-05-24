# config.py — MEXC Bot
# NE PAS CONFONDRE AVEC /root/champion-v4-bot/

import os, requests, logging
from dotenv import load_dotenv

load_dotenv()

# ── Credentials ──────────────────────────────────────
API_KEY    = os.getenv('MEXC_API_KEY', '')
SECRET_KEY = os.getenv('MEXC_SECRET_KEY', '')

# ── Exchange ──────────────────────────────────────────
BASE_REST = 'https://contract.mexc.com'
BASE_WS   = 'wss://contract.mexc.com/edge'

# ── Coins ─────────────────────────────────────────────
COINS = ['DOGE', 'SOL', 'US', 'ETH', 'BTC', 'ZEC', 'AVAX', 'RUNE', 'H', 'CHZ', 'XRP', 'TAO', 'BILL']

# ── Contract sizes (1 contrat = X token) ─────────────
CONTRACT_SIZES = {
    'SOL':  0.1,    # 1 contrat = 0.1 SOL
    'DOGE': 100.0,  # 1 contrat = 100 DOGE
    'HYPE': 0.1,    # 1 contrat = 0.1 HYPE
    'ZEC':  0.01,   # 1 contrat = 0.01 ZEC
    'JUP':  1.0,
    'BLUR': 1.0,
    'FET':  10.0,   # contractSize=10 (vérifié API MEXC 2026-05-24)
    'US':   10.0,   # 1 contrat = 10 US (vérifié API MEXC: contractSize=10)
    'LAB':  10.0,   # 1 contrat = 10 LAB (vérifié API MEXC: contractSize=10)
    'BTC':  0.0001,
    'ETH':  0.01,
    'XRP':  1.0,    # 1 contrat = 1 XRP (vérifié API MEXC: contractSize=1)
    'ADA':  10.0,
    'AVAX': 0.1,
    'MATIC':10.0,
    'LINK': 1.0,
    'LTC':  0.01,
    'ATOM': 1.0,
    'TAO':  0.01,   # 1 contrat = 0.01 TAO (vérifié API MEXC: contractSize=0.01)
    'CHZ':  1.0,    # 1 contrat = 1 CHZ (vérifié API MEXC: contractSize=1)
    'H':    1.0,    # 1 contrat = 1 H (vérifié API MEXC: contractSize=1)
    'BILL': 100.0,  # 1 contrat = 100 BILL (vérifié API MEXC: contractSize=100)
    'RUNE': 1.0,    # 1 contrat = 1 RUNE (vérifié API MEXC: contractSize=1)
    'EDEN': 1.0,    # 1 contrat = 1 EDEN (vérifié API MEXC: contractSize=1)
}

# ── Timeframes ────────────────────────────────────────
# MEXC utilise Min1/Min60/Hour4 — PAS 1m/1h comme Binance
# Min3 non supporté MEXC → Min1 utilisé à la place (441×1m = 441min ≡ 147×3m = 441min)
TF_SIGNAL     = '1h'   # Donchian signal → Min60
TF_CHANDELIER = '1m'   # Chandelier Exit → Min1

TIMEFRAME_MAP = {
    '1m': 'Min1', '3m': 'Min5', '5m': 'Min5',
    '15m': 'Min15', '30m': 'Min30', '1h': 'Min60',
    '4h': 'Hour4', '8h': 'Hour8', '1d': 'Day1',
}

# ── Stratégie — CONFIG#2 validée (parité Champion v4) ─
# Chandelier: 441×1m = 441min ≡ 147×3m = 441min (parité Champion v4)
DONCHIAN_PERIOD = 5       # D5
CH_MULTIPLIER   = 1.0     # Chandelier multiplier
CH_PERIOD       = 441     # 441×1m = 441min ≡ 147×3m (parité Champion v4)
EMA_1H_PERIOD   = 100     # Filtre EMA 1h
EMA_4H_PERIOD   = 38      # Filtre EMA 4h
ATR_PERIOD      = 14      # Période ATR

# ── Risk management ───────────────────────────────────
LEVERAGE        = int(os.getenv('LEVERAGE', 8))       # 4x (demande user)
CAPITAL_PCT     = float(os.getenv('CAPITAL_PCT', 0.95))
SL_PCT          = float(os.getenv('SL_PCT', 0.10))    # Stop-loss -10% brut
TP_PCT          = float(os.getenv('TP_PCT', 0.72))    # Take-profit sécurité +72% brut
MAX_POSITIONS   = 15      # multi-coin live

# ── Stratégie avancée ─────────────────────────────────
MHH        = int(os.getenv('MHH', 96))              # Max hold hours
MARGIN_PCT = float(os.getenv('MARGIN_PCT', 0.10))   # 10% capital/trade × 3x = 30% notional
VP_PCT     = int(os.getenv('VP_PCT', 95))            # ATR percentile filter
VP_WIN     = int(os.getenv('VP_WIN', 500))           # Fenêtre ATR (barres 1h)

# ── CYCLE 6 TOGGLES (deploy 17/05/2026) ──────────────
USE_PARTIAL_EXIT       = os.getenv('USE_PARTIAL_EXIT', '0') == '1'
PARTIAL_TP_PCT         = float(os.getenv('PARTIAL_TP_PCT', 0.0122))
PARTIAL_EXIT_RATIO     = float(os.getenv('PARTIAL_EXIT_RATIO', 0.05))
USE_BREAKEVEN_MOVE     = os.getenv('USE_BREAKEVEN_MOVE', '0') == '1'
BREAKEVEN_TRIGGER_PCT  = float(os.getenv('BREAKEVEN_TRIGGER_PCT', 0.1111))
USE_TIME_DECAY_MHH     = os.getenv('USE_TIME_DECAY_MHH', '0') == '1'
MHH_PROFIT_THRESHOLD   = float(os.getenv('MHH_PROFIT_THRESHOLD', 0.1782))
MHH_DECAY_HOURS        = int(os.getenv('MHH_DECAY_HOURS', 48))
USE_MULTI_PARTIAL      = os.getenv('USE_MULTI_PARTIAL', '0') == '1'
MP_L1_PCT              = float(os.getenv('MP_L1_PCT', 0.0127))
MP_L1_RATIO            = float(os.getenv('MP_L1_RATIO', 0.55))
MP_L2_PCT              = float(os.getenv('MP_L2_PCT', 0.0155))
MP_L2_RATIO            = float(os.getenv('MP_L2_RATIO', 0.20))

# ── Mode ──────────────────────────────────────────────
DRY_RUN = os.getenv('DRY_RUN', 'true').lower() == 'true'

# ── Telegram ──────────────────────────────────────────
TG_TOKEN = os.getenv('TELEGRAM_TOKEN', '')
TG_CHAT  = os.getenv('TELEGRAM_CHAT_ID', '')

# ── Helpers ───────────────────────────────────────────
def to_mexc_symbol(coin: str) -> str:
    return f'{coin}_USDT'

def to_mexc_interval(tf: str) -> str:
    return TIMEFRAME_MAP[tf]

# Runtime dict — initialisé au démarrage par init_contract_sizes()
_CS_RUNTIME: dict = {}
_PS_RUNTIME: dict = {}
_cs_log = logging.getLogger('mexc')

def init_contract_sizes(coins: list) -> None:
    """
    Initialise les contract sizes au démarrage :
    1. Charge le dict hardcoded CONTRACT_SIZES
    2. Bulk-fetch depuis MEXC API (1 seul appel) pour valider + compléter
    3. Detecte les mismatch hardcoded vs API (bug prevention)
    4. Pour les coins manquants du hardcoded : auto-fetch + WARNING
    """
    global _CS_RUNTIME, _PS_RUNTIME
    _CS_RUNTIME = dict(CONTRACT_SIZES)

    # Bulk fetch toutes les specs MEXC en 1 appel
    api_sizes = {}
    try:
        r = requests.get('https://contract.mexc.com/api/v1/contract/detail', timeout=15)
        data = r.json()
        if not data:
            raise ValueError('reponse API vide ou None')
        if data.get('success') and isinstance(data.get('data'), list):
            api_sizes = {
                c['symbol'].replace('_USDT', ''): float(c['contractSize'])
                for c in data['data']
                if c.get('symbol', '').endswith('_USDT') and c.get('contractSize') is not None
            }
            _PS_RUNTIME.update({
                c['symbol'].replace('_USDT', ''): int(c.get('priceScale', 4))
                for c in data['data']
                if c.get('symbol', '').endswith('_USDT')
            })
            if not api_sizes:
                _cs_log.warning('CONTRACT_SIZES: liste vide -- hardcoded seul')
            else:
                _cs_log.info(f'CONTRACT_SIZES: {len(api_sizes)} coins fetched depuis API MEXC')
        else:
            raise ValueError(f'API error: {data.get('code')}')
    except Exception as e:
        _cs_log.error(f'CONTRACT_SIZES bulk fetch FAILED: {e} — hardcoded dict seul utilisé')

    # Valide hardcoded vs API — détecte les bugs comme XRP 10→1
    for coin in coins:
        api_cs = api_sizes.get(coin)
        hard_cs = CONTRACT_SIZES.get(coin)
        if api_cs is not None and hard_cs is not None:
            if abs(hard_cs - api_cs) / api_cs > 0.01:  # >1% écart = bug
                _cs_log.error(
                    f'[{coin}] CS MISMATCH: config.py={hard_cs} vs API={api_cs} → '
                    f'CORRECTION AUTO (API = source de vérité). Mettez à jour config.py!')
                _CS_RUNTIME[coin] = api_cs  # API prime sur hardcoded incorrect

    # Auto-complète les coins absents du hardcoded
    missing = [c for c in coins if c not in CONTRACT_SIZES]
    for coin in missing:
        if coin in api_sizes:
            _CS_RUNTIME[coin] = api_sizes[coin]
            _cs_log.warning(
                f'[{coin}] cs={api_sizes[coin]} AUTO-FETCHED API → '
                f'AJOUTER à config.py CONTRACT_SIZES pour pérenniser!')
        else:
            _CS_RUNTIME[coin] = 1.0
            _cs_log.error(
                f'[{coin}] INTROUVABLE sur MEXC Futures! Fallback cs=1.0 → '
                f'qty probablement INCORRECT. Vérifiez le symbole.')

    # Log récap
    for coin in coins:
        _cs_log.info(f'  {coin}: cs={_CS_RUNTIME.get(coin, '?')}')


def get_contract_size(coin: str) -> float:
    if coin in _CS_RUNTIME:
        return _CS_RUNTIME[coin]
    if coin in CONTRACT_SIZES:
        return CONTRACT_SIZES[coin]
    # Fallback dynamique: nouveau listing absent au demarrage
    try:
        r = requests.get(
            f'https://contract.mexc.com/api/v1/contract/detail?symbol={coin}_USDT',
            timeout=5
        )
        data = r.json()
        if not data:
            raise ValueError('reponse API vide ou None')
        if data.get('success') and isinstance(data.get('data'), list) and data['data']:
            cs = float(data['data'][0].get('contractSize', 1.0))
            _CS_RUNTIME[coin] = cs
            _cs_log.warning(f'[{coin}] cs={cs} fetche dynamiquement -> ajouter a CONTRACT_SIZES')
            return cs
    except Exception as e:
        _cs_log.error(f'[{coin}] API fallback FAILED: {e}')
    _cs_log.error(f'[{coin}] CONTRACT_SIZE inconnu -- fallback cs=1.0')
    return 1.0


def get_price_decimals(coin: str) -> int:
    return _PS_RUNTIME.get(coin, 4)
