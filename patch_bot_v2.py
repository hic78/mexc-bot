#!/usr/bin/env python3
"""
patch_bot_v2.py — 3 fixes pour parité exacte avec backtest C139:
  1. VP filter: revert current_atr < → > (skip top 20% volatile, pas bottom 20%)
  2. calc_atr_series: SMA rolling → Wilder EMA (k=1/period)
  3. Supprime le dead code chandelier orphelin après aggregate_to_5m
"""
import sys, re

SRC = '/root/mexc-bot/bot.py'

with open(SRC, encoding='utf-8') as f:
    src = f.read()

orig = src
changes = []

# ─── FIX 1 : VP filter inverted ──────────────────────────────────────────────
# Wrong: if current_atr < vp_threshold  (notre erreur de session précédente)
# Right: if current_atr > vp_threshold  (parité backtest line 969)

old_vp_block = (
    '        if current_atr < vp_threshold:\n'
    '            log.info(f\'{tag} VP filter: ATR {current_atr:.6f} < {vp_threshold:.6f} — volatilite insuffisante, skip\')'
)
new_vp_block = (
    '        if current_atr > vp_threshold:\n'
    '            log.info(f\'{tag} VP filter: ATR {current_atr:.6f} > {vp_threshold:.6f} — trop volatil (top {100-VP_PCT}%), skip\')'
)

old_vp_comment = '    # VP filter: si ATR < VP_PCT percentile → trop calme, skip (parité backtest)'
new_vp_comment = '    # VP filter: si ATR > VP_PCT percentile → trop volatil, skip (parité backtest line 969: atr[i] > vol_thr[i])'

if old_vp_block in src:
    src = src.replace(old_vp_block, new_vp_block)
    src = src.replace(old_vp_comment, new_vp_comment)
    changes.append('FIX 1 ✅ VP filter: current_atr < → >')
else:
    print('FIX 1 ⚠️  VP filter anchor introuvable — déjà patché ou ancre changée', file=sys.stderr)
    # Check current state
    if 'current_atr > vp_threshold' in src:
        changes.append('FIX 1 ✅ VP filter: déjà correct (current_atr >)')
    else:
        print('ERREUR FIX 1: état inconnu du VP filter', file=sys.stderr)

# ─── FIX 2 : ATR SMA → Wilder EMA ────────────────────────────────────────────
old_atr_func = '''def calc_atr_series(candles: list, period: int) -> list:
    """Retourne la série d\'ATR (SMA rolling) — identique Champion v4 tr.rolling(14).mean()."""
    if len(candles) < period + 1:
        return []
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][\'h\'], candles[i][\'l\'], candles[i-1][\'c\']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return []
    atrs = []
    for i in range(period - 1, len(trs)):
        atrs.append(sum(trs[i - period + 1:i + 1]) / period)
    return atrs'''

new_atr_func = '''def calc_atr_series(candles: list, period: int) -> list:
    """ATR Wilder EMA (k=1/period) — identique bt_v6_multi_gen._precompute."""
    if len(candles) < period + 1:
        return []
    trs = []
    for i in range(1, len(candles)):
        h, l, pc = candles[i][\'h\'], candles[i][\'l\'], candles[i-1][\'c\']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(trs) < period:
        return []
    k = 1.0 / period          # Wilder smoothing: k=1/14=0.0714 (vs EMA standard k=2/15)
    atr = sum(trs[:period]) / period  # seed = SMA sur les 'period' premières TR
    atrs = [atr]
    for tr in trs[period:]:
        atr = tr * k + atr * (1 - k)
        atrs.append(atr)
    return atrs'''

if old_atr_func in src:
    src = src.replace(old_atr_func, new_atr_func)
    changes.append('FIX 2 ✅ calc_atr_series: SMA rolling → Wilder EMA (k=1/period)')
else:
    print('FIX 2 ⚠️  ATR anchor introuvable', file=sys.stderr)
    if 'Wilder EMA' in src and 'k = 1.0 / period' in src:
        changes.append('FIX 2 ✅ ATR Wilder EMA: déjà correct')
    else:
        print('ERREUR FIX 2: état inconnu ATR', file=sys.stderr)

# ─── FIX 3 : Supprime dead code chandelier orphelin ──────────────────────────
# Block orphelin après le return de aggregate_to_5m — Python l'ignore mais pollue
dead_block = (
    '\n\n'
    '    if atr_entry <= 0:\n'
    '        log.debug(f\'[{coin}] chandelier: atr_entry invalide ({atr_entry})\')\n'
    '        return \'HOLD\'\n'
    '    recent     = candles_1m[-(period + 1):]  # CH_P+1 barres — identique Champion v4: H[ws:j+1]\n'
    '    chan_long  = max(c[\'h\'] for c in recent) - mult * atr_entry\n'
    '    chan_short = min(c[\'l\'] for c in recent) + mult * atr_entry\n'
    '    if direction == \'LONG\':\n'
    '        wick = candles_1m[-1][\'l\']\n'
    '        if wick <= chan_long and (sl_price <= 0 or chan_long > sl_price):\n'
    '            log.debug(f\'[{coin}] chandelier LONG EXIT: low={wick:.6f} <= chan={chan_long:.6f} atr_entry={atr_entry:.6f}\')\n'
    '            return \'EXIT\'\n'
    '    elif direction == \'SHORT\':\n'
    '        wick = candles_1m[-1][\'h\']\n'
    '        if wick >= chan_short and (sl_price <= 0 or chan_short < sl_price):\n'
    '            log.debug(f\'[{coin}] chandelier SHORT EXIT: high={wick:.6f} >= chan={chan_short:.6f} atr_entry={atr_entry:.6f}\')\n'
    '            return \'EXIT\'\n'
    '    log.debug(f\'[{coin}] chandelier({period},{mult}): chan_long={chan_long:.6f} chan_short={chan_short:.6f} atr_entry={atr_entry:.6f} → HOLD\')\n'
    '    return \'HOLD\'\n'
)

# Le bloc se trouve entre la fin de aggregate_to_5m et le séparateur # ── Position sizing ──
# On cherche le marqueur exact de fin de aggregate_to_5m + début du dead code
anchor_end = "    return [v for _, v in sorted(buckets.items())]\n"
anchor_after = "\n\n# ── Position sizing ─"

# Trouver le dead block entre anchor_end et anchor_after
pos_end = src.find(anchor_end)
pos_after = src.find(anchor_after, pos_end)

if pos_end != -1 and pos_after != -1:
    between = src[pos_end + len(anchor_end):pos_after]
    if between.strip():  # il y a du contenu à supprimer
        # Remplacer le bloc complet par une ligne vide (séparation propre)
        src = src[:pos_end + len(anchor_end)] + '\n' + src[pos_after:]
        changes.append('FIX 3 ✅ Dead code chandelier orphelin supprimé (~20 lignes)')
    else:
        changes.append('FIX 3 ✅ Dead code: déjà propre')
else:
    # Fallback: cherche le dead block littéralement
    if 'candles_1m[-(period + 1):]  # CH_P+1' in src:
        # Chercher depuis la fin de aggregate_to_5m
        marker = '    return [v for _, v in sorted(buckets.items())]\n\n\n    if atr_entry <= 0:'
        marker_end = '    return \'HOLD\'\n\n\n# ── Position sizing ─'
        pos1 = src.find('    return [v for _, v in sorted(buckets.items())]')
        if pos1 != -1:
            pos2 = src.find('# ── Position sizing ─', pos1)
            if pos2 != -1:
                src = src[:pos1 + len('    return [v for _, v in sorted(buckets.items())]\n')] + '\n' + src[pos2:]
                changes.append('FIX 3 ✅ Dead code chandelier supprimé (fallback)')
    else:
        changes.append('FIX 3 ✅ Dead code: déjà absent')

# ─── Résumé ───────────────────────────────────────────────────────────────────
if src == orig:
    print('ATTENTION: aucune modification appliquée (tout déjà correct ou anchres manquantes)')
else:
    with open(SRC, 'w', encoding='utf-8') as f:
        f.write(src)
    print(f'bot.py patché — {len(changes)} fix(es) appliqués:')

for c in changes:
    print(f'  {c}')

# Validation finale: vérifier qu'il ne reste pas de références erronées
problems = []
if 'current_atr < vp_threshold' in src:
    problems.append('❌ VP filter ENCORE inversé!')
if 'SMA rolling' in src and 'Wilder EMA' not in src:
    problems.append('❌ ATR encore SMA rolling')
if 'candles_1m[-(period + 1):]  # CH_P+1' in src:
    problems.append('❌ Dead code chandelier encore présent')

# Vérifier que les bonnes versions sont là
if 'current_atr > vp_threshold' not in src:
    problems.append('❌ VP filter: > absent')
if 'k = 1.0 / period' not in src:
    problems.append('❌ Wilder k=1/period absent')

if problems:
    print('\nPROBLÈMES DÉTECTÉS:')
    for p in problems:
        print(f'  {p}')
    sys.exit(1)
else:
    print('\nValidation OK — 0 problème détecté')
    # Quick syntax check
    import py_compile, tempfile, os
    tmp = tempfile.mktemp(suffix='.py')
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(src)
    try:
        py_compile.compile(tmp, doraise=True)
        print('Syntax check: OK ✅')
    except py_compile.PyCompileError as e:
        print(f'SYNTAX ERROR: {e}')
        sys.exit(1)
    finally:
        os.unlink(tmp)
