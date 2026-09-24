
from trenchnet.models import TradeEvent
from trenchnet.pnl import compute_wallet_metrics


def test_realized_pnl_basic():
    w = "WalletA1111111111111111111111111111111111111"
    tok = "Token111111111111111111111111111111111111111"
    events = [
        TradeEvent("sigbuy1", w, tok, "buy", 100.0, 1.0, 1, 1000),
        TradeEvent("sigsell1", w, tok, "sell", 100.0, 1.5, 2, 1300),
    ]
    m = compute_wallet_metrics(w, "A", events)
    assert abs(m.realized_pnl_sol - 0.5) < 1e-9
    assert m.buy_count == 1 and m.sell_count == 1
    assert m.open_positions == 0
    assert "sigbuy1" in m.cited_signatures


def test_profit_concentration():
    w = "WalletB1111111111111111111111111111111111111"
    t1, t2 = "Tok1", "Tok2"
    events = [
        TradeEvent("b1", w, t1, "buy", 10, 1.0, 1, 1000),
        TradeEvent("s1", w, t1, "sell", 10, 3.0, 2, 1100),  # +2
        TradeEvent("b2", w, t2, "buy", 10, 1.0, 3, 1200),
        TradeEvent("s2", w, t2, "sell", 10, 1.5, 4, 1300),  # +0.5
    ]
    m = compute_wallet_metrics(w, "B", events)
    assert m.profit_concentration is not None
    assert abs(m.profit_concentration - (2.0 / 2.5)) < 1e-6
