
from trenchnet.graph import co_entry_strength, graph_summary_dict
from trenchnet.models import TradeEvent


def test_co_entry_jaccard_and_lead():
    a, b = "Wa", "Wb"
    tok = "T1"
    events = [
        TradeEvent("s1", a, tok, "buy", 1, 0.1, 1, 1000),
        TradeEvent("s2", b, tok, "buy", 1, 0.1, 2, 1000 + 60),  # 1 min later
        TradeEvent("s3", a, "T2", "buy", 1, 0.1, 3, 5000),
    ]
    co = co_entry_strength(events, window_minutes=30)
    assert len(co) == 1
    assert co[0].shared_tokens == 1
    assert co[0].lead == a
    assert co[0].jaccard > 0


def test_graph_summary_disclaimer():
    events = [
        TradeEvent("s1", "Wa", "T1", "buy", 1, 0.1, 1, 1000),
        TradeEvent("s2", "Wb", "T1", "buy", 1, 0.1, 2, 1060),
    ]
    g = graph_summary_dict(events, window_minutes=30)
    assert "ownership" in g["disclaimer"].lower()
    assert g["edge_count"] == 2
