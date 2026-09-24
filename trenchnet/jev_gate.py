
"""TypeSafe System One (Jev) gate ? observe routes only. No orders."""

from __future__ import annotations

import logging
from typing import Any

from trenchnet.routing import combine_jev_answers
from trenchnet.secrets import get_secret, secret_present

logger = logging.getLogger(__name__)
API_KEY_ENV = "TYPESAFE_API_KEY"


def build_questions() -> dict[str, Any]:
    from typesafe_sdk import Choice

    return {
        "behavior_fit": Choice(
            instructions=(
                "Given the compact snapshot of this trader's typical buy size, hold times, "
                "and the current buy, does the current buy MATCH their usual entry pattern, "
                "MISMATCH it, or is it UNCLEAR? Do not do arithmetic; use provided fields only."
            ),
            criteria={
                "match": "Current buy aligns with typical pattern fields provided.",
                "mismatch": "Current buy clearly diverges from typical pattern fields.",
                "unclear": "Cannot tell from the snapshot.",
            },
        ),
        "position_intent": Choice(
            instructions=(
                "Is this position EXPLORATORY (smaller/unusual), USUAL (in-family size), "
                "or UNCLEAR? Do not compute sizes; read the labeled fields."
            ),
            criteria={
                "exploratory": "Labeled as smaller/unusual vs typical.",
                "usual": "Labeled as in-family vs typical.",
                "unclear": "Cannot tell.",
            },
        ),
        "history_sufficient": Choice(
            instructions=(
                "Is history_sufficient YES, NO, or UNRESOLVED based on the provided "
                "history_flag and trade_count fields? Do not count yourself."
            ),
            criteria={
                "yes": "history_flag ok and enough trades labeled.",
                "no": "history_flag missing_history or empty.",
                "unresolved": "sparse or ambiguous.",
            },
        ),
        "attention": Choice(
            instructions=(
                "Should attention be STILL_VALID (no material change), NEEDS_UPDATE "
                "(material change to prior read), or NEW_SITUATION (first/novel cluster event)?"
            ),
            criteria={
                "still_valid": "No material change vs prior.",
                "needs_update": "Material change; refresh analysis.",
                "new_situation": "Novel vs prior sample.",
            },
        ),
    }


def _extract_answers(response: Any) -> dict[str, Any]:
    """Best-effort parse of TypeSafe response into flat answer dict."""
    answers: dict[str, Any] = {}
    conf = None
    # SDK shapes vary; try common attributes / dict
    raw = response
    if hasattr(response, "model_dump"):
        raw = response.model_dump()
    elif hasattr(response, "dict"):
        raw = response.dict()
    elif not isinstance(response, dict):
        raw = getattr(response, "__dict__", {"raw": str(response)})

    # look for answers / results / questions
    candidates = []
    if isinstance(raw, dict):
        for key in ("answers", "results", "questions", "outputs", "data"):
            if key in raw and isinstance(raw[key], dict):
                candidates.append(raw[key])
        candidates.append(raw)
    for cand in candidates:
        for k in ("behavior_fit", "position_intent", "history_sufficient", "attention"):
            if k in cand and k not in answers:
                v = cand[k]
                if isinstance(v, dict):
                    answers[k] = v.get("value") or v.get("answer") or v.get("choice") or str(v)
                    if conf is None and "confidence" in v:
                        try:
                            conf = float(v["confidence"])
                        except Exception:
                            pass
                else:
                    answers[k] = str(v)
        if "confidence" in cand and conf is None:
            try:
                conf = float(cand["confidence"])
            except Exception:
                pass
    if conf is not None:
        answers["confidence"] = conf
    return answers


def mock_jev_answers(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Clearly labeled dry-run judge when TYPESAFE_API_KEY is absent."""
    flag = str(snapshot.get("history_flag", "unresolved"))
    trade_count = int(snapshot.get("trade_count") or 0)
    size = snapshot.get("current_buy_sol")
    typical = snapshot.get("typical_buy_size_sol")
    if flag == "missing_history" or trade_count == 0:
        hist = "no"
    elif flag == "sparse":
        hist = "unresolved"
    else:
        hist = "yes"
    fit = "unclear"
    intent = "unclear"
    if size is not None and typical is not None and typical > 0:
        ratio = float(size) / float(typical)
        if 0.5 <= ratio <= 2.0:
            fit, intent = "match", "usual"
        elif ratio < 0.5:
            fit, intent = "mismatch", "exploratory"
        else:
            fit, intent = "mismatch", "exploratory"
    attn = snapshot.get("attention_hint") or "needs_update"
    score_bits = snapshot.get("wallet_score") or snapshot.get("numeric_features") or {}
    return {
        "behavior_fit": fit,
        "position_intent": intent,
        "history_sufficient": hist,
        "attention": attn,
        "confidence": 0.4,
        "dry_run": True,
        "numeric_features": score_bits,
        "label": "DRY-RUN / MOCK JEV ? TYPESAFE_API_KEY not set",
    }


def judge_snapshot(snapshot: dict[str, Any], model: str = "jev-latest") -> dict[str, Any]:
    get_secret(API_KEY_ENV)  # load into env if present in hermes/.env
    if not secret_present(API_KEY_ENV):
        answers = mock_jev_answers(snapshot)
        routed = combine_jev_answers(answers, confidence=float(answers.get("confidence", 0.4)))
        routed["jev_mode"] = "dry_run_mock"
        return routed

    try:
        from typesafe_sdk import TypeSafeClient

        questions = build_questions()
        logger.info("Calling TypeSafe system_one model=%s questions=%s", model, list(questions))
        http_status = None
        with TypeSafeClient() as client:
            response = client.system_one(state=snapshot, model=model, questions=questions)
            # Best-effort status from SDK response / underlying httpx
            for attr in ("status_code", "http_status", "status"):
                if hasattr(response, attr):
                    try:
                        http_status = int(getattr(response, attr))
                        break
                    except Exception:
                        pass
            if http_status is None and hasattr(response, "response"):
                try:
                    http_status = int(getattr(response.response, "status_code", None) or 0) or None
                except Exception:
                    pass
            if http_status is None:
                http_status = 200  # call returned without raising
        answers = _extract_answers(response)
        for k, default in (
            ("behavior_fit", "unclear"),
            ("position_intent", "unclear"),
            ("history_sufficient", "unresolved"),
            ("attention", "needs_update"),
        ):
            answers.setdefault(k, default)
        answers["numeric_features"] = snapshot.get("wallet_score") or snapshot.get("numeric_features") or {}
        routed = combine_jev_answers(answers)
        routed["jev_mode"] = "typesafe_live"
        routed["jev_call_ok"] = True
        routed["jev_http_status"] = http_status
        return routed
    except Exception as exc:
        http_status = None
        # Pull status from httpx-like exceptions without leaking bodies/keys
        for attr in ("status_code", "code"):
            if hasattr(exc, attr):
                try:
                    http_status = int(getattr(exc, attr))
                    break
                except Exception:
                    pass
        resp = getattr(exc, "response", None)
        if resp is not None and hasattr(resp, "status_code"):
            try:
                http_status = int(resp.status_code)
            except Exception:
                pass
        # Scrub any secret material from error text
        err = str(exc)
        key = get_secret(API_KEY_ENV) or ""
        if key and key in err:
            err = err.replace(key, "REDACTED")
        answers = mock_jev_answers(snapshot)
        answers["fallback_error"] = err[:240]
        answers["label"] = "DRY-RUN / MOCK JEV — live TypeSafe call failed"
        answers["numeric_features"] = snapshot.get("wallet_score") or snapshot.get("numeric_features") or {}
        routed = combine_jev_answers(answers, confidence=0.3)
        routed["jev_mode"] = "dry_run_after_error"
        routed["jev_call_ok"] = False
        routed["jev_http_status"] = http_status
        return routed
