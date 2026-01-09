"""Analyze @0x8dxd activity directly from Polymarket data API.

This script is intentionally lightweight and read-only.
It helps answer: trade frequency, size distribution, market concentration,
BUY vs SELL mix, and how often your current copy sizing would clamp to $1.

It can also estimate realized edge by pairing BUY/SELL trades per token
(FIFO lots) to compute an approximate realized PnL and ROI.

Notes / limitations:
- Uses activity trade price + size; does not model fees or execution slippage.
- Only computes realized PnL on closed lots (BUY lots that get SOLD later).
- If the API window doesn't contain enough SELLs, realized PnL will be sparse.
"""

from __future__ import annotations

import os
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Deque, Dict, Iterable, List, Optional, Tuple

import requests

DATA_API = os.getenv("DATA_API_HOST", "https://data-api.polymarket.com")
TARGET = os.getenv("TARGET_TRADER_ADDRESS", "0x63ce342161250d705dc0b16df89036c8e5f9ba9a")


@dataclass(frozen=True)
class CopySizing:
    copy_ratio: float = float(os.getenv("COPY_RATIO", "0.30"))
    btc_copy_ratio: float = float(os.getenv("BTC_COPY_RATIO", "0.02"))
    eth_copy_ratio: float = float(os.getenv("ETH_COPY_RATIO", "0.03"))
    sol_copy_ratio: float = float(os.getenv("SOL_COPY_RATIO", "0.04"))
    min_trade_amount: float = float(os.getenv("MIN_TRADE_AMOUNT", "1.0"))


@dataclass(frozen=True)
class Trade:
    ts: int
    side: str
    token_id: str
    condition_id: str
    price: float
    shares: float
    usdc_size: float
    title: str
    slug: str


@dataclass(frozen=True)
class Redeem:
    ts: int
    condition_id: str
    payout_usdc: float
    title: str
    slug: str
    tx: str


@dataclass
class Lot:
    ts: int
    shares: float
    price: float


def _dt(ts: int) -> datetime:
    return datetime.fromtimestamp(int(ts), tz=timezone.utc)


def fetch_activity(max_records: int = 5000, page_size: int = 500, timeout: float = 20.0) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    offset = 0

    while len(out) < max_records:
        limit = min(page_size, max_records - len(out))
        url = f"{DATA_API}/activity"
        params = {"user": TARGET, "limit": limit, "offset": offset}
        r = requests.get(url, params=params, timeout=timeout)
        r.raise_for_status()
        page = r.json()
        if not page:
            break
        out.extend(page)
        offset += len(page)

        # Safety: if API starts repeating identical pages, stop.
        if len(page) < limit:
            break

    return out


def _parse_trade(raw: Dict[str, Any]) -> Optional[Trade]:
    try:
        ts = int(raw.get("timestamp") or 0)
        if not ts:
            return None
        if (raw.get("type") or "").upper() != "TRADE":
            return None

        side = (raw.get("side") or "").upper().strip()
        if side not in {"BUY", "SELL"}:
            return None

        token_id = str(raw.get("asset") or "").strip()
        if not token_id:
            return None

        condition_id = str(raw.get("conditionId") or "").strip()
        if not condition_id:
            return None

        price = float(raw.get("price") or 0.0)
        usdc_size = float(raw.get("usdcSize") or 0.0)

        shares = float(raw.get("size") or 0.0)
        if shares <= 0 and price > 0 and usdc_size > 0:
            shares = usdc_size / price
        if shares <= 0 or price <= 0:
            return None

        return Trade(
            ts=ts,
            side=side,
            token_id=token_id,
            condition_id=condition_id,
            price=price,
            shares=shares,
            usdc_size=usdc_size,
            title=raw.get("title") or "",
            slug=raw.get("slug") or "",
        )
    except Exception:
        return None


def _parse_redeem(raw: Dict[str, Any]) -> Optional[Redeem]:
    """Parse REDEEM events as resolution payouts.

    Observed format: asset/outcome often blank, price=0, and usdcSize/size is the payout.
    We key by (tx, conditionId) for de-dup.
    """
    try:
        if (raw.get("type") or "").upper() != "REDEEM":
            return None
        ts = int(raw.get("timestamp") or 0)
        if not ts:
            return None
        condition_id = str(raw.get("conditionId") or "").strip()
        if not condition_id:
            return None
        tx = str(raw.get("transactionHash") or "").strip()
        payout = float(raw.get("usdcSize") or 0.0)
        if payout <= 0:
            payout = float(raw.get("size") or 0.0)
        if payout < 0:
            return None
        return Redeem(
            ts=ts,
            condition_id=condition_id,
            payout_usdc=payout,
            title=raw.get("title") or "",
            slug=raw.get("slug") or "",
            tx=tx,
        )
    except Exception:
        return None


def _quantiles(values: List[float], qs: Iterable[float]) -> Dict[float, Optional[float]]:
    if not values:
        return {q: None for q in qs}
    v = sorted(values)
    out: Dict[float, Optional[float]] = {}
    n = len(v)
    for q in qs:
        idx = int(q * (n - 1))
        out[q] = float(v[idx])
    return out


def _realized_pnl_fifo(
    trades: List[Trade],
    *,
    min_buy_usdc: float,
) -> Dict[str, float]:
    """Simulate copying only BUYs above threshold; SELLs close any included lots.

    Returns aggregate metrics:
    - buy_usdc_included: sum of included BUY notional (shares * price)
    - cost_basis_closed: cost basis of shares that were later sold
    - proceeds_closed: proceeds from SELLs that match included lots
    - pnl_realized: proceeds_closed - cost_basis_closed
    - roi_realized: pnl_realized / cost_basis_closed
    - max_open_cost: max running cost of open included lots
    - matched_shares: total shares sold that matched included lots
    - avg_hold_sec: share-weighted average holding time for matched shares
    """

    lots_by_token: Dict[str, Deque[Lot]] = defaultdict(deque)
    open_cost_by_token: Dict[str, float] = defaultdict(float)

    buy_usdc_included = 0.0
    cost_basis_closed = 0.0
    proceeds_closed = 0.0
    matched_shares = 0.0
    hold_sec_weighted = 0.0

    max_open_cost = 0.0

    for t in trades:
        if t.side == "BUY":
            # Filter only entries; always allow exits to close positions.
            if t.usdc_size < min_buy_usdc:
                continue
            lots_by_token[t.token_id].append(Lot(ts=t.ts, shares=t.shares, price=t.price))
            delta_cost = t.shares * t.price
            buy_usdc_included += delta_cost
            open_cost_by_token[t.token_id] += delta_cost
        else:  # SELL
            remaining = t.shares
            token_lots = lots_by_token.get(t.token_id)
            if not token_lots:
                continue
            while remaining > 1e-12 and token_lots:
                lot = token_lots[0]
                take = min(remaining, lot.shares)

                cost_basis_closed += take * lot.price
                proceeds_closed += take * t.price
                matched_shares += take
                hold_sec_weighted += take * float(t.ts - lot.ts)

                lot.shares -= take
                remaining -= take

                open_cost_by_token[t.token_id] -= take * lot.price
                if lot.shares <= 1e-12:
                    token_lots.popleft()

        total_open_cost = sum(v for v in open_cost_by_token.values() if v > 0)
        if total_open_cost > max_open_cost:
            max_open_cost = total_open_cost

    pnl_realized = proceeds_closed - cost_basis_closed
    roi_realized = (pnl_realized / cost_basis_closed) if cost_basis_closed > 0 else 0.0
    avg_hold_sec = (hold_sec_weighted / matched_shares) if matched_shares > 0 else 0.0

    return {
        "buy_usdc_included": buy_usdc_included,
        "cost_basis_closed": cost_basis_closed,
        "proceeds_closed": proceeds_closed,
        "pnl_realized": pnl_realized,
        "roi_realized": roi_realized,
        "max_open_cost": max_open_cost,
        "matched_shares": matched_shares,
        "avg_hold_sec": avg_hold_sec,
    }


def _realized_pnl_by_resolution(
    trades: List[Trade],
    redeems: List[Redeem],
    *,
    min_buy_usdc: float,
) -> Dict[str, float]:
    """Estimate realized PnL when positions are held to resolution.

    - Include only BUY trades whose usdcSize >= threshold.
    - Track open cost per conditionId.
    - When a REDEEM happens for that conditionId, treat payout_usdc as proceeds
      and close out all open cost for that condition.

    This matches the observed behavior where SELLs are rare, and "realization"
    is mostly via REDEEM events.
    """

    open_cost_by_condition: Dict[str, float] = defaultdict(float)
    first_buy_ts: Dict[str, int] = {}

    buy_usdc_included = 0.0
    cost_basis_closed = 0.0
    proceeds_closed = 0.0
    closed_markets = 0.0
    hold_sec_weighted = 0.0
    max_open_cost = 0.0

    events: List[Tuple[int, str, object]] = []
    for t in trades:
        if t.side == "BUY":
            events.append((t.ts, "BUY", t))
        elif t.side == "SELL":
            # Rare for this trader; resolution-based model ignores SELL for simplicity.
            continue
    best_redeems: Dict[Tuple[str, str], Redeem] = {}
    for r in redeems:
        key = (r.tx, r.condition_id)
        existing = best_redeems.get(key)
        if existing is None or r.payout_usdc > existing.payout_usdc:
            best_redeems[key] = r
    for r in best_redeems.values():
        events.append((r.ts, "REDEEM", r))

    events.sort(key=lambda x: x[0])

    for _, kind, obj in events:
        if kind == "BUY":
            t = obj  # type: ignore[assignment]
            if t.usdc_size < min_buy_usdc:
                continue
            cost = t.shares * t.price
            buy_usdc_included += cost
            open_cost_by_condition[t.condition_id] += cost
            if t.condition_id not in first_buy_ts:
                first_buy_ts[t.condition_id] = t.ts
        else:  # REDEEM
            r = obj  # type: ignore[assignment]
            open_cost = open_cost_by_condition.get(r.condition_id, 0.0)
            if open_cost <= 1e-12:
                continue
            cost_basis_closed += open_cost
            proceeds_closed += r.payout_usdc
            closed_markets += 1.0
            start_ts = first_buy_ts.get(r.condition_id)
            if start_ts is not None:
                hold_sec_weighted += open_cost * float(r.ts - start_ts)
            open_cost_by_condition[r.condition_id] = 0.0

        total_open_cost = sum(v for v in open_cost_by_condition.values() if v > 0)
        if total_open_cost > max_open_cost:
            max_open_cost = total_open_cost

    pnl_realized = proceeds_closed - cost_basis_closed
    roi_realized = (pnl_realized / cost_basis_closed) if cost_basis_closed > 0 else 0.0
    avg_hold_sec = (hold_sec_weighted / cost_basis_closed) if cost_basis_closed > 0 else 0.0

    return {
        "buy_usdc_included": buy_usdc_included,
        "cost_basis_closed": cost_basis_closed,
        "proceeds_closed": proceeds_closed,
        "pnl_realized": pnl_realized,
        "roi_realized": roi_realized,
        "max_open_cost": max_open_cost,
        "closed_markets": closed_markets,
        "avg_hold_sec": avg_hold_sec,
    }


def fetch_positions(size_threshold: float = 0.01, timeout: float = 20.0) -> List[Dict[str, Any]]:
    url = f"{DATA_API}/positions"
    params = {"user": TARGET, "sizeThreshold": size_threshold}
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def classify_market(title: str, slug: str) -> str:
    t = (title or "").lower()
    s = (slug or "").lower()

    if "up or down" in t or "updown" in s:
        # Try to infer 5m/15m from slug.
        if "15m" in s:
            return "crypto_updown_15m"
        if "5m" in s:
            return "crypto_updown_5m"
        return "crypto_updown"

    if "bitcoin" in t or t.startswith("btc"):
        return "btc_related"
    if "ethereum" in t or t.startswith("eth"):
        return "eth_related"
    if "solana" in t or t.startswith("sol"):
        return "sol_related"

    return "other"


def estimate_copy_amount(usdc_size: float, market_title: str, sizing: CopySizing) -> float:
    title = (market_title or "").lower()

    if "bitcoin" in title or "btc" in title:
        ratio = sizing.btc_copy_ratio
    elif "ethereum" in title or "eth" in title:
        ratio = sizing.eth_copy_ratio
    elif "solana" in title or "sol" in title:
        ratio = sizing.sol_copy_ratio
    else:
        ratio = sizing.copy_ratio

    amt = usdc_size * ratio
    if amt < sizing.min_trade_amount:
        return sizing.min_trade_amount
    return amt


def summarize_activity(trades: List[Dict[str, Any]], sizing: CopySizing) -> None:
    if not trades:
        print("No trades returned.")
        return

    # Normalize + sort by timestamp ascending for time deltas.
    normalized = []
    for t in trades:
        ts = int(t.get("timestamp") or 0)
        if not ts:
            continue
        normalized.append(t)
    normalized.sort(key=lambda x: int(x.get("timestamp")))

    first_ts = int(normalized[0]["timestamp"])
    last_ts = int(normalized[-1]["timestamp"])
    span_sec = max(1, last_ts - first_ts)

    # Rate stats.
    trades_per_hour = len(normalized) / (span_sec / 3600)

    # Distribution + grouping.
    sides = Counter(
        (t.get("side") or "").upper()
        for t in normalized
        if (t.get("type") or "").upper() == "TRADE"
    )
    by_market = defaultdict(lambda: {"count": 0, "volume": 0.0, "slug": "", "title": ""})
    bucket = Counter()

    clamp_to_min = 0
    total_volume = 0.0

    deltas = []
    prev_ts: Optional[int] = None
    for t in normalized:
        ts = int(t.get("timestamp"))
        if prev_ts is not None:
            deltas.append(ts - prev_ts)
        prev_ts = ts

        title = t.get("title") or ""
        slug = t.get("slug") or ""
        usdc = float(t.get("usdcSize") or 0.0)
        total_volume += usdc

        m = by_market[title]
        m["count"] += 1
        m["volume"] += usdc
        m["slug"] = slug
        m["title"] = title

        kind = classify_market(title, slug)
        bucket[kind] += 1

        # Copy clamp rate estimate
        if estimate_copy_amount(usdc, title, sizing) <= sizing.min_trade_amount + 1e-9:
            clamp_to_min += 1

    def pct(x: float) -> float:
        return 100.0 * x / max(1.0, len(normalized))

    # Delta stats
    deltas_sorted = sorted(deltas)
    def quantile(q: float) -> Optional[float]:
        if not deltas_sorted:
            return None
        idx = int(q * (len(deltas_sorted) - 1))
        return float(deltas_sorted[idx])

    print("=" * 90)
    print(f"@0x8dxd activity via {DATA_API}")
    print(f"User: {TARGET}")
    print("=" * 90)

    print(f"Window: {_dt(first_ts).isoformat()} -> {_dt(last_ts).isoformat()} (UTC)")
    print(f"Trades analyzed: {len(normalized)}")
    print(f"Approx trade rate: {trades_per_hour:.1f} trades/hour")
    print(f"BUY vs SELL: {dict(sides)}")
    print(f"Total volume (target): ${total_volume:,.2f}")

    print("\nMarket-type breakdown (by trade count):")
    for k, v in bucket.most_common():
        print(f"  - {k:>18}: {v:>5} ({pct(v):5.1f}%)")

    print("\nTime between trades (seconds, median-ish):")
    q10 = quantile(0.10)
    q50 = quantile(0.50)
    q90 = quantile(0.90)
    if q50 is not None:
        print(f"  p10={q10:.2f}s  p50={q50:.2f}s  p90={q90:.2f}s")

    print("\nCopy sizing stress test (your constraints):")
    print(
        f"  Using ratios: base={sizing.copy_ratio:.2f}, BTC={sizing.btc_copy_ratio:.2f}, "
        f"ETH={sizing.eth_copy_ratio:.2f}, SOL={sizing.sol_copy_ratio:.2f}; min=${sizing.min_trade_amount:.2f}"
    )
    print(f"  Estimated trades that clamp to min order: {clamp_to_min}/{len(normalized)} ({pct(clamp_to_min):.1f}%)")

    print("\nTop 10 markets by target volume:")
    top = sorted(by_market.values(), key=lambda x: x["volume"], reverse=True)[:10]
    for m in top:
        print(f"  ${m['volume']:>10.2f} | {m['count']:>4} trades | {m['title'][:60]}")


def summarize_realized_edge(trades: List[Dict[str, Any]]) -> None:
    parsed: List[Trade] = []
    redeems: List[Redeem] = []
    for t in trades:
        pt = _parse_trade(t)
        if pt is not None:
            parsed.append(pt)
            continue
        pr = _parse_redeem(t)
        if pr is not None:
            redeems.append(pr)

    if not parsed and not redeems:
        print("\nNo parsable trades/redeems for realized PnL.")
        return

    parsed.sort(key=lambda x: x.ts)
    redeems.sort(key=lambda x: x.ts)
    sides = Counter(t.side for t in parsed)
    buy_sizes = [t.usdc_size for t in parsed if t.side == "BUY" and t.usdc_size > 0]
    q = _quantiles(buy_sizes, [0.10, 0.50, 0.90])

    thresholds_env = os.getenv("CONVICTION_THRESHOLDS_USDC", "")
    if thresholds_env.strip():
        thresholds = [float(x.strip()) for x in thresholds_env.split(",") if x.strip()]
    else:
        thresholds = [0.0, 5.0, 10.0, 25.0, 50.0, 100.0, 200.0, 500.0]

    print("\n" + "=" * 90)
    print("Approx realized edge")
    print("=" * 90)
    print(
        f"Parsed: trades={len(parsed)} (BUY={sides.get('BUY', 0)} SELL={sides.get('SELL', 0)}), "
        f"redeems={len(redeems)}"
    )
    if buy_sizes:
        print(
            "BUY usdcSize quantiles: "
            f"p10={q[0.10]:.2f}  p50={q[0.50]:.2f}  p90={q[0.90]:.2f}"
        )

    if sides.get("SELL", 0) > 0:
        print("\nConviction filter (SELL pairing): include BUYs >= threshold; SELLs close included lots")
        print("Threshold | Included_BUY_$ | Closed_Cost_$ | Realized_PnL_$ | ROI_% | Max_Open_$ | Avg_Hold_s")
        print("-" * 90)
        for thr in thresholds:
            m = _realized_pnl_fifo(parsed, min_buy_usdc=thr)
            roi_pct = 100.0 * m["roi_realized"]
            print(
                f"{thr:8.2f} | "
                f"{m['buy_usdc_included']:13.2f} | "
                f"{m['cost_basis_closed']:12.2f} | "
                f"{m['pnl_realized']:14.2f} | "
                f"{roi_pct:5.2f} | "
                f"{m['max_open_cost']:9.2f} | "
                f"{m['avg_hold_sec']:10.1f}"
            )
    else:
        print("\nSELL pairing: no SELL trades in this window (cannot compute realized via SELL closes)")

    if redeems:
        print("\nConviction filter (resolution pairing): include BUYs >= threshold; REDEEM closes by conditionId")
        print("Threshold | Included_BUY_$ | Closed_Cost_$ | Redeem_$ | Realized_PnL_$ | ROI_% | Max_Open_$ | Avg_Hold_s")
        print("-" * 110)
        for thr in thresholds:
            m = _realized_pnl_by_resolution(parsed, redeems, min_buy_usdc=thr)
            roi_pct = 100.0 * m["roi_realized"]
            print(
                f"{thr:8.2f} | "
                f"{m['buy_usdc_included']:13.2f} | "
                f"{m['cost_basis_closed']:12.2f} | "
                f"{m['proceeds_closed']:8.2f} | "
                f"{m['pnl_realized']:14.2f} | "
                f"{roi_pct:5.2f} | "
                f"{m['max_open_cost']:9.2f} | "
                f"{m['avg_hold_sec']:10.1f}"
            )

        # Market-level conviction analysis: total BUY per market vs total REDEEM.
        # This is often a better "conviction" proxy than per-trade size, since the trader
        # slices positions into many small BUYs.
        buy_by_cond: Dict[str, float] = defaultdict(float)
        title_by_cond: Dict[str, str] = {}
        for t in parsed:
            if t.side == "BUY":
                buy_by_cond[t.condition_id] += t.shares * t.price
                if t.condition_id not in title_by_cond and t.title:
                    title_by_cond[t.condition_id] = t.title

        # Dedup redeems by (tx, condition) and keep the maximum payout.
        redeem_by_cond: Dict[str, float] = defaultdict(float)
        best_redeems: Dict[Tuple[str, str], Redeem] = {}
        for r in redeems:
            key = (r.tx, r.condition_id)
            existing = best_redeems.get(key)
            if existing is None or r.payout_usdc > existing.payout_usdc:
                best_redeems[key] = r
        for r in best_redeems.values():
            redeem_by_cond[r.condition_id] += r.payout_usdc
            if r.condition_id not in title_by_cond and r.title:
                title_by_cond[r.condition_id] = r.title

        markets = []
        for cid, buy_amt in buy_by_cond.items():
            redeem_amt = redeem_by_cond.get(cid, 0.0)
            if buy_amt <= 0 or redeem_amt <= 0:
                continue
            pnl = redeem_amt - buy_amt
            roi = pnl / buy_amt
            markets.append((buy_amt, redeem_amt, pnl, roi, cid))

        if markets:
            markets.sort(key=lambda x: x[0])  # by buy_amt
            total_buy = sum(m[0] for m in markets)
            total_pnl = sum(m[2] for m in markets)
            w_roi = (total_pnl / total_buy) if total_buy > 0 else 0.0

            print("\nMarket-level realized ROI (only markets with BUY+REDEEM observed in window):")
            print(f"  Markets: {len(markets)} | Total buy: ${total_buy:,.2f} | Total pnl: ${total_pnl:,.2f} | Weighted ROI: {100.0*w_roi:.2f}%")

            # Tertile buckets by market buy amount.
            n = len(markets)
            cuts = [n // 3, 2 * n // 3]
            buckets = [markets[: cuts[0]], markets[cuts[0] : cuts[1]], markets[cuts[1] :]]
            labels = ["low", "mid", "high"]
            for label, bucket in zip(labels, buckets):
                if not bucket:
                    continue
                b_buy = sum(x[0] for x in bucket)
                b_pnl = sum(x[2] for x in bucket)
                b_roi = (b_pnl / b_buy) if b_buy > 0 else 0.0
                min_buy = min(x[0] for x in bucket)
                max_buy = max(x[0] for x in bucket)
                print(
                    f"  {label:>4} conviction (by market total BUY): n={len(bucket):>2} "
                    f"range=${min_buy:,.2f}-${max_buy:,.2f} weighted_ROI={100.0*b_roi:6.2f}%"
                )

            # Show a few extremes for intuition.
            markets_by_roi = sorted(markets, key=lambda x: x[3])
            print("\n  Worst 3 markets (ROI):")
            for buy_amt, redeem_amt, pnl, roi, cid in markets_by_roi[:3]:
                print(f"   ROI={100.0*roi:7.2f}% pnl=${pnl:9.2f} buy=${buy_amt:9.2f} title={title_by_cond.get(cid,'')[:60]}")
            print("  Best 3 markets (ROI):")
            for buy_amt, redeem_amt, pnl, roi, cid in markets_by_roi[-3:][::-1]:
                print(f"   ROI={100.0*roi:7.2f}% pnl=${pnl:9.2f} buy=${buy_amt:9.2f} title={title_by_cond.get(cid,'')[:60]}")
    else:
        print("\nResolution pairing: no REDEEM events in this window")


def main() -> None:
    sizing = CopySizing()
    max_records = int(os.getenv("MAX_ACTIVITY_RECORDS", "5000"))
    trades = fetch_activity(max_records=max_records)
    summarize_activity(trades, sizing)
    summarize_realized_edge(trades)

    try:
        positions = fetch_positions()
        if positions:
            print("\nOpen positions snapshot (count only):")
            print(f"  Positions returned: {len(positions)}")
            # Show a few largest
            def pos_value(p: Dict[str, Any]) -> float:
                return float(p.get("value") or 0.0)

            for p in sorted(positions, key=pos_value, reverse=True)[:5]:
                title = p.get("title") or p.get("marketTitle") or ""
                outcome = p.get("outcome") or ""
                avg_price = p.get("avgPrice") or p.get("averagePrice")
                value = float(p.get("value") or 0.0)
                print(f"  ${value:>9.2f} | {outcome:<6} | {title[:60]} | avg={avg_price}")
    except Exception as e:
        print(f"\nPositions fetch failed: {type(e).__name__}: {e}")


if __name__ == "__main__":
    main()
