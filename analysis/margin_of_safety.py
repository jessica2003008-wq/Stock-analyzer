"""Step 6: Margin of Safety."""
from __future__ import annotations
from data.schemas import ValuationResult, MarginOfSafetyResult


def analyze_margin_of_safety(valuation: ValuationResult) -> MarginOfSafetyResult:
    """Compare intrinsic value to market price."""
    price = valuation.current_price
    base_iv = valuation.base.per_share_value
    bull_iv = valuation.bull.per_share_value
    bear_iv = valuation.bear.per_share_value

    evidence = []

    if price <= 0 or base_iv <= 0:
        return MarginOfSafetyResult(
            score=0,
            current_price=price,
            evidence=["Cannot compute margin of safety: price or IV is zero/negative"],
            rationale="Insufficient data for margin of safety calculation.",
        )

    # Margin of safety = (IV - Price) / IV
    mos_pct = (base_iv - price) / base_iv * 100
    bull_upside = (bull_iv - price) / price * 100 if price > 0 else 0
    bear_downside = (price - bear_iv) / price * 100 if price > 0 else 0

    evidence.append(f"Current price: ${price:,.2f}")
    evidence.append(f"Base IV: ${base_iv:,.2f}")
    evidence.append(f"Bull IV: ${bull_iv:,.2f}")
    evidence.append(f"Bear IV: ${bear_iv:,.2f}")
    evidence.append(f"Margin of Safety: {mos_pct:.1f}%")
    evidence.append(f"Bull upside: {bull_upside:.1f}%")
    evidence.append(f"Bear downside: {bear_downside:.1f}%")

    # Score
    if mos_pct >= 50:
        score = 100
    elif mos_pct >= 40:
        score = 90
    elif mos_pct >= 30:
        score = 75
    elif mos_pct >= 20:
        score = 60
    elif mos_pct >= 10:
        score = 45
    elif mos_pct >= 0:
        score = 25
    else:
        # Overvalued: scale from 15 down to 0
        score = max(0, int(15 + mos_pct))  # mos_pct is negative here

    # Verdict
    if mos_pct >= 15:
        verdict = "Undervalued"
    elif mos_pct >= -10:
        verdict = "Fairly Valued"
    else:
        verdict = "Overvalued"

    rationale = (
        f"At ${price:,.2f}, the stock trades at a {mos_pct:.1f}% "
        f"{'discount' if mos_pct > 0 else 'premium'} to base intrinsic value of ${base_iv:,.2f}. "
        f"Bull case offers {bull_upside:.0f}% upside to ${bull_iv:,.2f}. "
        f"Bear case implies {bear_downside:.0f}% downside to ${bear_iv:,.2f}. "
        f"Verdict: {verdict}."
    )

    return MarginOfSafetyResult(
        score=score,
        current_price=price,
        base_intrinsic_value=round(base_iv, 2),
        bull_intrinsic_value=round(bull_iv, 2),
        bear_intrinsic_value=round(bear_iv, 2),
        margin_of_safety_pct=round(mos_pct, 2),
        bull_upside_pct=round(bull_upside, 2),
        bear_downside_pct=round(bear_downside, 2),
        verdict=verdict,
        evidence=evidence,
        rationale=rationale,
    )
