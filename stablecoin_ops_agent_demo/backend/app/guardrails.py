from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ReleaseDecision:
    allowed: bool
    disposition: str
    reasons: list[str]


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def evaluate_release_decision(latest_row: dict[str, Any] | None) -> ReleaseDecision:
    if not latest_row:
        return ReleaseDecision(
            allowed=False,
            disposition="MUST_BE_ESCALATED",
            reasons=["No latest payment context row is available."],
        )

    payment_ops_state = str(latest_row.get("payment_ops_state", ""))
    compliance_state = str(latest_row.get("compliance_state", ""))
    wallet_risk_score = _as_int(latest_row.get("wallet_risk_score"))
    total_received_minor = _as_int(latest_row.get("total_received_minor"))
    expected_amount_minor = _as_int(latest_row.get("expected_amount_minor"))
    has_wrong_chain = _as_int(latest_row.get("has_wrong_chain"))
    has_wrong_token = _as_int(latest_row.get("has_wrong_token"))
    has_unexpected_payer_wallet = _as_int(latest_row.get("has_unexpected_payer_wallet"))

    reasons: list[str] = []

    if compliance_state.upper() == "BLOCKED":
        reasons.append("compliance_state is BLOCKED")
    if wallet_risk_score >= 85:
        reasons.append("wallet_risk_score is 85 or higher")
    if payment_ops_state.startswith("PAYMENT_EXCEPTION"):
        reasons.append("payment_ops_state starts with PAYMENT_EXCEPTION")
    if total_received_minor < expected_amount_minor:
        reasons.append("total_received_minor is less than expected_amount_minor")
    if has_wrong_chain == 1:
        reasons.append("has_wrong_chain is 1")
    if has_wrong_token == 1:
        reasons.append("has_wrong_token is 1")
    if has_unexpected_payer_wallet == 1:
        reasons.append("has_unexpected_payer_wallet is 1")

    if payment_ops_state != "VALID_PAYMENT_READY_TO_RELEASE":
        reasons.append("payment_ops_state is not VALID_PAYMENT_READY_TO_RELEASE")

    if reasons:
        return ReleaseDecision(
            allowed=False,
            disposition="MUST_NOT_RELEASE",
            reasons=reasons,
        )

    return ReleaseDecision(allowed=True, disposition="CAN_RELEASE", reasons=[])


def enforce_guardrail_suffix(answer_text: str, decision: ReleaseDecision) -> str:
    suffix_lines = [
        "",
        "Guardrail Decision:",
        f"- release_allowed: {str(decision.allowed).lower()}",
        f"- operational_disposition: {decision.disposition}",
    ]
    if decision.reasons:
        suffix_lines.append("- blocking_reasons: " + "; ".join(decision.reasons))
    else:
        suffix_lines.append("- blocking_reasons: none")
    return answer_text.strip() + "\n" + "\n".join(suffix_lines) + "\n"
