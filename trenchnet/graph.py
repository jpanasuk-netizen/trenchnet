
"""Wallet-token graph + co-entry / lead-follow analysis."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from trenchnet.models import TradeEvent


@dataclass
class CoEntry:
    wallet_a: str
    wallet_b: str
    shared_tokens: int
    jaccard: float
    a_first: int
    b_first: int
    lead: str | None  # which usually first


@dataclass
class TokenEventSummary:
    token_mint: str
    participants: list[str]
    order: list[str]  # entry order by first buy time
    cluster_type: str  # recurring_cluster | newcomer_low_overlap | mixed | single
    notes: str


def build_edges(events: Iterable[TradeEvent]) -> list[dict[str, Any]]:
    edges = []
    for e in events:
        if e.side not in ("buy", "sell"):
            continue
        edges.append({
            "wallet": e.wallet,
            "token": e.token_mint,
            "side": e.side,
            "size_sol": e.amount_sol,
            "size_token": e.amount_token,
            "time": e.block_time,
            "signature": e.signature,
        })
    return edges


def co_entry_strength(
    events: Iterable[TradeEvent],
    window_minutes: int = 30,
) -> list[CoEntry]:
    """Jaccard over tokens where both wallets bought within window of each other."""
    evs = [e for e in events if e.side == "buy" and e.block_time]
    by_wallet_token: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    tokens_by_wallet: dict[str, set[str]] = defaultdict(set)
    for e in evs:
        by_wallet_token[e.wallet][e.token_mint].append(e.block_time)
        tokens_by_wallet[e.wallet].add(e.token_mint)

    wallets = sorted(tokens_by_wallet.keys())
    window = window_minutes * 60
    results: list[CoEntry] = []
    for i, a in enumerate(wallets):
        for b in wallets[i + 1 :]:
            shared = 0
            a_first = b_first = 0
            for tok in tokens_by_wallet[a] & tokens_by_wallet[b]:
                times_a = sorted(by_wallet_token[a][tok])
                times_b = sorted(by_wallet_token[b][tok])
                # any pair within window?
                hit = False
                best_lead = None
                for ta in times_a:
                    for tb in times_b:
                        if abs(ta - tb) <= window:
                            hit = True
                            if ta < tb:
                                best_lead = "a"
                            elif tb < ta:
                                best_lead = "b"
                            break
                    if hit:
                        break
                if hit:
                    shared += 1
                    if best_lead == "a":
                        a_first += 1
                    elif best_lead == "b":
                        b_first += 1
            union = len(tokens_by_wallet[a] | tokens_by_wallet[b])
            j = (shared / union) if union else 0.0
            if shared == 0 and j == 0:
                continue
            lead = None
            if a_first > b_first:
                lead = a
            elif b_first > a_first:
                lead = b
            results.append(CoEntry(
                wallet_a=a, wallet_b=b, shared_tokens=shared,
                jaccard=round(j, 4), a_first=a_first, b_first=b_first, lead=lead,
            ))
    results.sort(key=lambda c: (-c.jaccard, -c.shared_tokens))
    return results


def summarize_token_events(
    events: Iterable[TradeEvent],
    prior_pairs: set[tuple[str, str]] | None = None,
) -> list[TokenEventSummary]:
    """Compact relationship summary per token. Never claims common ownership."""
    prior_pairs = prior_pairs or set()
    buys = [e for e in events if e.side == "buy" and e.block_time]
    by_tok: dict[str, list[TradeEvent]] = defaultdict(list)
    for e in buys:
        by_tok[e.token_mint].append(e)

    out: list[TokenEventSummary] = []
    for tok, lst in by_tok.items():
        # first buy per wallet
        first: dict[str, TradeEvent] = {}
        for e in sorted(lst, key=lambda x: x.block_time or 0):
            if e.wallet not in first:
                first[e.wallet] = e
        order = [w for w, _ in sorted(first.items(), key=lambda kv: kv[1].block_time or 0)]
        participants = order
        # recurring if any pair previously co-appeared
        recurring = False
        for i, a in enumerate(participants):
            for b in participants[i + 1 :]:
                pair = tuple(sorted((a, b)))
                if pair in prior_pairs:
                    recurring = True
        if len(participants) <= 1:
            ctype = "single"
            notes = "Only one roster wallet observed buying this token in the sample."
        elif recurring:
            ctype = "recurring_cluster"
            notes = "Multiple roster wallets; at least one pair has prior co-entry in sample. Not evidence of common ownership."
        else:
            ctype = "newcomer_low_overlap"
            notes = "Multiple roster wallets enter; no prior co-entry pair in sample. Not evidence of common ownership."
        out.append(TokenEventSummary(
            token_mint=tok,
            participants=participants,
            order=order,
            cluster_type=ctype,
            notes=notes,
        ))
    return out


def graph_summary_dict(
    events: list[TradeEvent],
    window_minutes: int = 30,
) -> dict[str, Any]:
    edges = build_edges(events)
    co = co_entry_strength(events, window_minutes=window_minutes)
    # build prior pairs from co-entries with shared>=1 for token summaries
    pairs = {(tuple(sorted((c.wallet_a, c.wallet_b)))) for c in co if c.shared_tokens >= 1}
    tok_sums = summarize_token_events(events, prior_pairs=pairs)
    return {
        "edge_count": len(edges),
        "edges_sample": edges[:50],
        "co_entries": [asdict(c) for c in co[:50]],
        "token_summaries": [asdict(t) for t in tok_sums[:50]],
        "disclaimer": "Co-entry and lead/follow are observational timing patterns only. Never claim common ownership.",
    }
