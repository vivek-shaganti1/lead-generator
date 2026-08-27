"""Two-agent adversarial review of a claimed gap.

The problem
-----------
Before we tell a business "you have no online booking", we had better be right.
Getting it wrong is not a small error: it proves to the recipient that nobody
looked at their site, and it is unrecoverable with that contact.

A single model asked "what is this site missing?" is a poor guard, because it is
being asked to confirm a hypothesis it just generated. It will happily agree
with itself.

The mechanism
-------------
Two agents argue the same evidence from fixed, opposing positions:

  * the **Proposer** argues the gap is real and commercially material;
  * the **Challenger** is instructed to *refute* it — to find the booking widget,
    the ordering link, the reason it does not matter for this trade.

They are then adjudicated. A gap is ``CONFIRMED`` only when the Challenger fails
to refute it. Disagreement means ``UNCERTAIN``, and uncertain gaps are never
pitched — with a finite send budget, the cost of skipping a real gap is one lost
lead, while the cost of pitching a false one is a burned contact.

Deterministic evidence wins
---------------------------
Neither agent can overrule :mod:`app.services.enrichment.capabilities`. If the
fetched HTML contains a Calendly script, the gap is rejected before either model
is called — a model that has not read the page does not get to overrule a page
that plainly contains the feature. The debate only runs on claims the
deterministic layer could not already settle, which also keeps the token cost
proportionate.

Degrading without a key
-----------------------
With no ``GROQ_API_KEY`` the debate cannot run. Rather than defaulting to
"confirmed", the verdict falls back to the deterministic evidence alone and is
marked ``EVIDENCE_ONLY``, which the caller may accept only for high-confidence
findings (a missing viewport tag is a fact; a missing booking system inferred
from prose is not).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from app.logging_config import get_logger
from app.services.ai.groq import GroqClient, GroqError
from app.services.enrichment.capabilities import (
    Capability,
    CapabilityFinding,
    CapabilityReport,
)
from app.services.enrichment.site_fetch import SiteFetch

log = get_logger(__name__)


class Verdict(str, Enum):
    CONFIRMED = "CONFIRMED"        # both agents agree the gap is real -> may pitch
    REJECTED = "REJECTED"          # refuted; the business already has it
    UNCERTAIN = "UNCERTAIN"        # they disagree -> do not pitch
    EVIDENCE_ONLY = "EVIDENCE_ONLY"  # no LLM available; deterministic only


@dataclass(slots=True)
class Argument:
    agent: str
    position: str
    reasoning: str
    confidence: float
    basis: str = ""   # challenger only: which ground the refutation rests on

    @property
    def is_weak(self) -> bool:
        """A refutation resting only on "it might be hidden" proves nothing."""
        return self.basis in _WEAK_GROUNDS

    def as_dict(self) -> dict:
        return {
            "agent": self.agent,
            "position": self.position,
            "reasoning": self.reasoning[:600],
            "confidence": round(self.confidence, 2),
            "basis": self.basis,
        }


@dataclass(slots=True)
class ConsensusResult:
    capability: Capability
    verdict: Verdict
    confidence: float
    rationale: str = ""
    arguments: list[Argument] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)

    @property
    def may_pitch(self) -> bool:
        return self.verdict is Verdict.CONFIRMED

    def as_dict(self) -> dict:
        return {
            "capability": self.capability.value,
            "verdict": self.verdict.value,
            "confidence": round(self.confidence, 2),
            "rationale": self.rationale[:500],
            "evidence": self.evidence[:6],
            "arguments": [a.as_dict() for a in self.arguments],
        }


# Capabilities whose absence is a verifiable fact about the markup rather than
# an inference. These are safe to accept on deterministic evidence alone.
_FACTUAL = {Capability.HTTPS, Capability.MOBILE_RESPONSIVE, Capability.CONTACT_FORM}


PROPOSER_SYSTEM = """You review small-business websites for a web development studio.

You will be given: the business, its trade, the capabilities detected on its
website, and one capability believed to be MISSING.

Your role is to argue that this gap is REAL and commercially material for this
specific trade. Be concrete about what it costs them in lost customers.

Return STRICT JSON only:
  "position": "REAL" or "NOT_REAL"
  "reasoning": one or two sentences, max 45 words
  "confidence": number 0..1
  "business_impact": one sentence on what it costs them, max 25 words

If the evidence genuinely shows they already have this capability, you must say
"NOT_REAL". Do not argue for a gap that is not there."""


CHALLENGER_SYSTEM = """You are a skeptical reviewer. Your job is to REFUTE a claim
that a business's website is missing a capability.

You will be given: the business, its trade, the capabilities detected on its
website, and the claimed missing capability.

Refute the claim ONLY on one of these grounds, and say which one you used:

  EVIDENCE_PRESENT  - the supplied evidence shows the capability IS present
  TRADE_IRRELEVANT  - this capability is genuinely not expected for this trade
                      (e.g. online ordering for a solicitor)
  TOO_GENERIC       - the claim is so generic it would apply to any business and
                      is not worth an email

If none of those apply, you must answer "STANDS".

IMPORTANT: do NOT refute merely because the capability *might* exist in
JavaScript, behind a link that was not crawled, or on a page you cannot see.
That possibility has already been accounted for before you were asked: the
fetch quality is stated in the evidence, and claims are only put to you when the
page was fully readable server-rendered HTML. "It might be hidden somewhere" is
speculation, not refutation — if that is your only objection, answer "STANDS"
and set basis to "SPECULATIVE".

Judge only what the evidence supports."""


def _evidence_block(
    business: dict, report: CapabilityReport, fetch: SiteFetch, gap: CapabilityFinding
) -> str:
    present = ", ".join(c.value for c in report.present()) or "none detected"
    missing = ", ".join(c.value for c in report.missing()) or "none"
    return (
        f"BUSINESS: {business.get('name', 'unknown')}\n"
        f"TRADE: {business.get('category', 'unknown')}\n"
        f"COUNTRY: {business.get('country_code', 'unknown')}\n"
        f"WEBSITE: {fetch.final_url or fetch.url}\n"
        f"FETCH QUALITY: {fetch.quality.value} "
        f"(pages crawled: {len(fetch.pages)}, readable text: {fetch.visible_text_chars} chars)\n"
        f"CAPABILITIES DETECTED AS PRESENT: {present}\n"
        f"CAPABILITIES NOT DETECTED: {missing}\n"
        f"CLAIMED MISSING CAPABILITY: {gap.capability.value}\n"
        f"DETECTION BASIS: {gap.source} (confidence {gap.confidence:.2f})\n"
    )


# Refutation grounds. SPECULATIVE is deliberately included so the model has an
# honest place to put "it might be hidden somewhere" — which we then discount,
# rather than letting it masquerade as a real refutation.
REFUTATION_GROUNDS = ["EVIDENCE_PRESENT", "TRADE_IRRELEVANT", "TOO_GENERIC", "SPECULATIVE"]
_WEAK_GROUNDS = {"SPECULATIVE"}


def _verdict_schema(
    positions: list[str], *, impact: bool = False, basis: bool = False
) -> dict:
    """Constrained-decoding schema so a reviewer can only return a real verdict."""
    props: dict = {
        "position": {"type": "string", "enum": positions},
        "reasoning": {"type": "string"},
        "confidence": {"type": "number"},
    }
    required = ["position", "reasoning", "confidence"]
    if impact:
        props["business_impact"] = {"type": "string"}
        required.append("business_impact")
    if basis:
        props["basis"] = {"type": "string", "enum": REFUTATION_GROUNDS}
        required.append("basis")
    return {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }


def _ask(
    client: GroqClient, system: str, evidence: str, agent: str, schema: dict
) -> Argument | None:
    try:
        raw = client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": evidence},
            ],
            max_tokens=1500,  # reasoning models think before they emit; see GroqClient.chat
            schema=schema,
            schema_name=f"{agent}_verdict",
        )
        data = json.loads(raw)
    except (GroqError, json.JSONDecodeError, TypeError) as exc:
        log.warning("gap_consensus.agent_failed", agent=agent, error=str(exc)[:200])
        return None

    position = str(data.get("position", "")).strip().upper()
    if position not in {"REAL", "NOT_REAL", "REFUTED", "STANDS"}:
        log.warning("gap_consensus.bad_position", agent=agent, position=position[:40])
        return None

    try:
        confidence = float(data.get("confidence", 0.5))
    except (TypeError, ValueError):
        confidence = 0.5

    reasoning = str(data.get("reasoning", "")).strip()
    impact = str(data.get("business_impact", "")).strip()
    if impact:
        reasoning = f"{reasoning} Impact: {impact}"
    basis = str(data.get("basis", "")).strip().upper()

    return Argument(agent, position, reasoning, max(0.0, min(confidence, 1.0)), basis)


def evaluate_gap(
    business: dict,
    report: CapabilityReport,
    fetch: SiteFetch,
    gap: CapabilityFinding,
    *,
    client: GroqClient | None = None,
) -> ConsensusResult:
    """Run the debate on one claimed gap and return an adjudicated verdict."""
    cap = gap.capability

    # --- deterministic vetoes, before any model is consulted ----------------
    if not fetch.can_judge_absence:
        return ConsensusResult(
            cap, Verdict.REJECTED, 1.0,
            f"fetch quality {fetch.quality.value} cannot support a claim of absence",
            evidence=[f"fetch quality: {fetch.quality.value}"],
        )

    existing = report.findings.get(cap)
    if existing and existing.present:
        return ConsensusResult(
            cap, Verdict.REJECTED, existing.confidence,
            "capability was detected on the site",
            evidence=existing.evidence,
        )

    client = client or GroqClient()
    if not client.enabled:
        # No debate possible. Only facts about the markup are safe unaided.
        verdict = Verdict.EVIDENCE_ONLY if cap in _FACTUAL else Verdict.UNCERTAIN
        return ConsensusResult(
            cap, verdict, gap.confidence,
            "no LLM configured; deterministic evidence only",
            evidence=gap.evidence,
        )

    evidence = _evidence_block(business, report, fetch, gap)
    proposer = _ask(
        client, PROPOSER_SYSTEM, evidence, "proposer",
        _verdict_schema(["REAL", "NOT_REAL"], impact=True),
    )
    challenger = _ask(
        client, CHALLENGER_SYSTEM, evidence, "challenger",
        _verdict_schema(["REFUTED", "STANDS"], basis=True),
    )
    arguments = [a for a in (proposer, challenger) if a]

    # If either agent could not be reached we have no debate, only an assertion.
    if proposer is None or challenger is None:
        return ConsensusResult(
            cap, Verdict.UNCERTAIN, 0.3,
            "debate incomplete: an agent did not return a usable verdict",
            arguments, gap.evidence,
        )

    proposer_says_real = proposer.position == "REAL"
    # A refutation whose only ground is "it might be hidden somewhere" is not a
    # refutation. Without this, the challenger can veto every claim on a
    # universal escape hatch and nothing is ever confirmed — the debate would
    # look rigorous while quietly blocking the entire pipeline.
    if challenger.position == "REFUTED" and challenger.is_weak:
        log.debug("gap_consensus.weak_refutation_discounted", capability=cap.value)
        challenger.position = "STANDS"
    challenger_says_stands = challenger.position == "STANDS"

    if proposer_says_real and challenger_says_stands:
        confidence = min(proposer.confidence, challenger.confidence)
        result = ConsensusResult(
            cap, Verdict.CONFIRMED, confidence,
            f"both agents agree: {proposer.reasoning}", arguments, gap.evidence,
        )
    elif not proposer_says_real and not challenger_says_stands:
        result = ConsensusResult(
            cap, Verdict.REJECTED, max(proposer.confidence, challenger.confidence),
            f"both agents reject the gap: {challenger.reasoning}", arguments, gap.evidence,
        )
    else:
        # They disagree. With a finite send budget, silence beats a wrong claim.
        result = ConsensusResult(
            cap, Verdict.UNCERTAIN, 0.4,
            f"agents disagree — proposer:{proposer.position} challenger:{challenger.position}",
            arguments, gap.evidence,
        )

    log.info(
        "gap_consensus.verdict",
        business=business.get("name"),
        capability=cap.value,
        verdict=result.verdict.value,
        confidence=round(result.confidence, 2),
    )
    return result
