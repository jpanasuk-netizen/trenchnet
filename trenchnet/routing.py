
"""Combine Jev answers into an observe route. Explicit rules; no trading."""

from __future__ import annotations

from typing import Any, Literal

Route = Literal["keep_observing", "send_for_analysis", "insufficient_evidence"]


def combine_jev_answers(answers: dict[str, Any], confidence: float | None = None) -> dict[str, Any]:
    """
    answers keys expected:
      behavior_fit: match | mismatch | unclear
      position_intent: exploratory | usual | unclear
      history_sufficient: yes | no | unresolved
      attention: still_valid | needs_update | new_situation
    """
    hist = str(answers.get("history_sufficient", "unresolved")).lower()
    fit = str(answers.get("behavior_fit", "unclear")).lower()
    intent = str(answers.get("position_intent", "unclear")).lower()
    attn = str(answers.get("attention", "needs_update")).lower()
    conf = confidence if confidence is not None else float(answers.get("confidence", 0.5) or 0.5)

    reasons: list[str] = []
    route: Route

    if hist in ("no", "unresolved") or conf < 0.35:
        route = "insufficient_evidence"
        reasons.append("history_insufficient_or_low_confidence")
    elif attn == "new_situation" and fit == "mismatch":
        route = "send_for_analysis"
        reasons.append("new_situation_with_behavior_mismatch")
    elif intent == "exploratory" and attn in ("new_situation", "needs_update"):
        route = "send_for_analysis"
        reasons.append("exploratory_entry_needs_analysis")
    elif fit == "match" and attn == "still_valid" and hist == "yes":
        route = "keep_observing"
        reasons.append("pattern_match_report_still_valid")
    elif attn == "needs_update":
        route = "send_for_analysis"
        reasons.append("attention_needs_update")
    else:
        # stay uncertain rather than force a strong call
        route = "insufficient_evidence"
        reasons.append("ambiguous_answers_default_uncertain")

    return {
        "route": route,
        "reasons": reasons,
        "answers": answers,
        "confidence": conf,
        "observe_only": True,
    }
