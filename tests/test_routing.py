
from trenchnet.routing import combine_jev_answers


def test_insufficient_on_low_history():
    r = combine_jev_answers({
        "behavior_fit": "match",
        "position_intent": "usual",
        "history_sufficient": "no",
        "attention": "still_valid",
        "confidence": 0.9,
    })
    assert r["route"] == "insufficient_evidence"


def test_send_on_mismatch_new():
    r = combine_jev_answers({
        "behavior_fit": "mismatch",
        "position_intent": "exploratory",
        "history_sufficient": "yes",
        "attention": "new_situation",
        "confidence": 0.7,
    })
    assert r["route"] == "send_for_analysis"


def test_keep_observing():
    r = combine_jev_answers({
        "behavior_fit": "match",
        "position_intent": "usual",
        "history_sufficient": "yes",
        "attention": "still_valid",
        "confidence": 0.8,
    })
    assert r["route"] == "keep_observing"


def test_low_confidence_uncertain():
    r = combine_jev_answers({
        "behavior_fit": "match",
        "position_intent": "usual",
        "history_sufficient": "yes",
        "attention": "still_valid",
        "confidence": 0.2,
    })
    assert r["route"] == "insufficient_evidence"
