"""Shared price-proximity gate used by both tiers.

A ticker is "outside proximity" when a target price *and* a proximity percentage
are configured and the current price is farther than that percentage away from
the target. Tier 1 (#5) uses it to skip the cheap scan; Tier 2 (#15) uses it to
skip the expensive daily LLM pipeline.

Returns False (i.e. never skip) whenever the feature isn't fully configured,
there's no price, or the target is non-positive — the conservative default is to
run rather than risk missing something.
"""

from __future__ import annotations


def is_outside_proximity(
    price: float | None,
    target_price: float | None,
    proximity_pct: float | None,
) -> bool:
    """True if a target/proximity is configured and price is too far from target."""
    if target_price is None or proximity_pct is None:
        return False
    if not price or target_price <= 0:
        return False
    distance_pct = abs(price - target_price) / target_price * 100
    return distance_pct > proximity_pct
