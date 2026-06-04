"""
optimus.py — Modules C150-OPTIMUS pour le bot LIVE (numpy seul, autonome).
À déposer dans /root/mexc-bot/. Fournit : filtre régime Markov, conviction sizing, veto cross-sectional.
Logique IDENTIQUE au backtest (exp_markov_conviction.markov_conv) mais renvoie la décision de la DERNIÈRE barre.
Non-anticipant : matrice de transition construite sur le passé seul.
"""
import numpy as np

# Réglages C150-OPTIMUS (figés, validés DSR=1.0 + Monte Carlo)
MK_N    = 16     # fenêtre régime Markov
MK_KTH  = 0.3    # seuil états (× std glissant)
CS_N    = 24     # horizon momentum cross-sectional (heures)
SCALE   = 0.40   # échelle conviction sizing

def _rolling_std(x, win=200, minp=50):
    """std glissant numpy (équivalent pd.Series.rolling(win,min_periods).std().bfill())."""
    n=len(x); out=np.full(n, np.nan)
    for i in range(n):
        lo=max(0, i-win+1); w=x[lo:i+1]
        if len(w)>=minp: out[i]=w.std(ddof=1)
    # bfill
    val=None
    for i in range(n-1,-1,-1):
        if not np.isnan(out[i]): val=out[i]
        elif val is not None: out[i]=val
    # ffill résiduel
    val=None
    for i in range(n):
        if not np.isnan(out[i]): val=out[i]
        elif val is not None: out[i]=val
    return out

def markov_regime(closes, N=MK_N, kth=MK_KTH):
    """Décision régime pour la DERNIÈRE barre.
    Retourne (long_ok, short_ok, conv_long, conv_short).
    conv_long = max(P(bull)-P(bear),0) si long autorisé ; conv_short symétrique."""
    C=np.asarray(closes, float); n=len(C)
    if n < N+80:
        return True, True, 0.5, 0.5  # pas assez d'historique -> neutre (ne bloque pas)
    retN=np.zeros(n); retN[N:]=C[N:]/C[:-N]-1.0
    std=_rolling_std(retN, 200, 50)
    st=np.ones(n, np.int8)               # 1=sideways
    st[retN >  kth*std]=2                # 2=bull
    st[retN < -kth*std]=0                # 0=bear
    cnt=np.ones((3,3))                   # Laplace smoothing
    warm=N+60
    long_ok=short_ok=False; cL=cS=0.0
    for i in range(1,n):
        sp=st[i-1]; sc=st[i]
        if i>warm:
            row=cnt[sc]; tot=row.sum()
            pbear,pside,pbull=row[0]/tot,row[1]/tot,row[2]/tot
            # décision pour CETTE barre (sera la dernière à i=n-1)
            long_ok=short_ok=False; cL=cS=0.0
            if not (pside>=pbull and pside>=pbear):   # kill-switch sideways
                if pbull>=pbear: long_ok=True;  cL=pbull-pbear
                if pbear>pbull:  short_ok=True; cS=pbear-pbull
        cnt[sp,sc]+=1                     # MAJ matrice APRÈS (non-anticipant)
    return long_ok, short_ok, cL, cS

def conviction_mult(conv, scale=SCALE):
    """Multiplicateur de taille ∝ conviction. clip [0.3, 1.0] (jamais > base = 0 levier ajouté)."""
    return float(np.clip(conv/scale, 0.3, 1.0))

def cross_sectional_signed(coin_returns: dict):
    """coin_returns: {coin: rendement CS_N-barres}. Retourne {coin: rang signé -1..+1}.
    +1 = plus fort momentum de l'univers, -1 = plus faible."""
    items=[(c,r) for c,r in coin_returns.items() if r is not None and not np.isnan(r)]
    if len(items)<2:
        return {c:0.0 for c in coin_returns}
    items.sort(key=lambda x:x[1]); K=len(items); out={}
    for rank,(c,_) in enumerate(items):
        out[c]=2.0*rank/(K-1)-1.0
    for c in coin_returns:
        out.setdefault(c, 0.0)
    return out

def cs_return(closes, n=CS_N):
    """rendement n-barres de la dernière barre (pour le classement cross-sectional)."""
    C=np.asarray(closes, float)
    if len(C) <= n: return None
    return float(C[-1]/C[-1-n]-1.0)

def optimus_gate(signal, coin, closes_1h, cs_signed):
    """Applique Markov + CS-veto + conviction au signal Donchian.
    signal: 'LONG'|'SHORT'. cs_signed: rang signé du coin (de cross_sectional_signed).
    Retourne (keep: bool, conviction_mult: float, reason: str)."""
    long_ok, short_ok, cL, cS = markov_regime(closes_1h)
    sd = cs_signed.get(coin, 0.0)
    if signal == 'LONG':
        if not long_ok:           return False, 0.0, 'markov: long bloqué (régime)'
        if sd < 0:                return False, 0.0, f'CS-veto: coin faible (rang {sd:+.2f})'
        return True, conviction_mult(cL), f'OK long conv={cL:.2f} mult={conviction_mult(cL):.2f}'
    if signal == 'SHORT':
        if not short_ok:          return False, 0.0, 'markov: short bloqué (régime)'
        if -sd < 0:               return False, 0.0, f'CS-veto: coin fort (rang {sd:+.2f})'
        return True, conviction_mult(cS), f'OK short conv={cS:.2f} mult={conviction_mult(cS):.2f}'
    return True, 1.0, 'no-signal'
