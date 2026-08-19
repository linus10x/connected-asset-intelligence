"""What happens to an intelligence product after it is delivered.

WHY THIS IS NOT OPTIONAL
------------------------
Release governance proves an insight *may* be delivered. It says nothing about whether
the delivery mattered. A system that stops at release has demonstrated a gate, not a
product.

The interesting part is downstream: did anyone acknowledge it, did they act, and what
happened afterwards. Those three answers are also the only route to a learning loop —
without recorded dispositions and outcomes there is nothing to calibrate against, and
"our data improves the product" stays a slogan.

THE CAUSAL BOUNDARY, WHICH THIS MODULE REFUSES TO CROSS
-------------------------------------------------------
Recording that a recommendation was followed and no failure occurred is *not* evidence
that the recommendation prevented the failure. The failure might never have happened.
Establishing causation needs a counterfactual this system does not have.

So `attributed_effect` is fixed at NOT_ESTABLISHED and there is no code path that sets
it otherwise. The temptation to quietly upgrade correlation into prevention is exactly
how an honest telemetry product becomes a dishonest marketing claim, and the guard
belongs in the type system rather than in a style guide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class DispositionState(str, Enum):
    """Where a delivered product has got to. Ordered by progression, not severity."""

    DELIVERED = "DELIVERED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    ACCEPTED = "ACCEPTED"
    OVERRIDDEN = "OVERRIDDEN"
    """A human saw it and decided against it. A legitimate outcome, and often the most
    informative one.

    Read it as a diagnostic, never as a label on the signal. A cluster of overrides can
    mean the signal is wrong -- or that it arrives too late to act on, or lands on
    someone who cannot act, or duplicates something the crew already knew, or cuts
    against how the recipient is measured. Treating overrides as a verdict on model
    quality is how a team spends a quarter retuning a model that was right."""

    IGNORED = "IGNORED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    OUTCOME_OBSERVED = "OUTCOME_OBSERVED"


class AttributedEffect(str, Enum):
    """Deliberately single-valued. See the module docstring."""

    NOT_ESTABLISHED = "NOT_ESTABLISHED"


# Which transitions are legal. Anything absent is rejected rather than tolerated,
# because a lifecycle that accepts any sequence records history without describing it.
_ALLOWED: dict[DispositionState, tuple[DispositionState, ...]] = {
    DispositionState.DELIVERED: (
        DispositionState.ACKNOWLEDGED,
        DispositionState.IGNORED,
    ),
    DispositionState.ACKNOWLEDGED: (
        DispositionState.ACCEPTED,
        DispositionState.OVERRIDDEN,
        DispositionState.IGNORED,
    ),
    DispositionState.ACCEPTED: (DispositionState.ACTION_COMPLETED,),
    DispositionState.ACTION_COMPLETED: (DispositionState.OUTCOME_OBSERVED,),
    # An overridden or ignored recommendation still has an observable outcome, and it is
    # the most valuable kind: a naturally observed non-adoption case. Not a control arm --
    # nothing was randomised and the recipient chose, so the cases that get ignored are
    # exactly the ones somebody judged safe to ignore. Borrowing experimental vocabulary
    # for it would imply a causal warrant this design does not earn.
    DispositionState.OVERRIDDEN: (DispositionState.OUTCOME_OBSERVED,),
    DispositionState.IGNORED: (DispositionState.OUTCOME_OBSERVED,),
    DispositionState.OUTCOME_OBSERVED: (),
}


class IllegalTransition(ValueError):
    """A trail that does not describe a possible history.

    A `ValueError` since the import boundary began enforcing trail rules by
    reconstruction: every other refusal there is one, and a caller wrapping
    `import_envelope` in `except ValueError` would otherwise let a malformed trail through
    while catching everything else. Still catchable by its own name where the distinction
    matters.
    """


@dataclass(frozen=True)
class DispositionEvent:
    """One step of the trail. The single representation, in memory and on the wire.

    The envelope used to carry `tuple[dict[str, Any], ...]` beside this class, so the
    portable form of the LEARN boundary was a bag of strings that reconstructed into
    nothing -- two representations of one thing, which is the pattern the rest of this
    package spends its time removing.
    """

    state: DispositionState
    at: datetime
    actor: str
    note: str = ""

    def __post_init__(self) -> None:
        if self.at.tzinfo is None:
            raise ValueError("a disposition event's timestamp must be timezone-aware")
        if not self.actor:
            raise ValueError(
                "a disposition with no actor records that something happened and not who "
                "did it, which is the half a dispute needs"
            )

    def as_record(self) -> dict[str, object]:
        return {
            "state": self.state.value,
            "at": self.at.isoformat(),
            "actor": self.actor,
            "note": self.note,
        }

    @classmethod
    def from_record(cls, r: dict[str, object]) -> "DispositionEvent":
        return cls(
            state=DispositionState(r["state"]),
            at=datetime.fromisoformat(str(r["at"])),
            actor=str(r["actor"]),
            note=str(r.get("note") or ""),
        )


def check_trail(events: tuple[DispositionEvent, ...]) -> None:
    """Every rule `ProductLifecycle.advance` enforces, applied to a whole trail at once.

    Extracted so the import boundary enforces the same rules by calling the same code,
    rather than by a hand-written wire validator restating them -- which is what
    `validate_envelope_payload` was, and it drifted immediately: it checked order and
    transitions and never once looked at the actor or the timezone.
    """
    if not events:
        return
    if events[0].state is not DispositionState.DELIVERED:
        raise IllegalTransition(
            f"a trail opening at {events[0].state.value} describes a product "
            f"acknowledged before it was delivered"
        )
    for earlier, later in zip(events, events[1:]):
        if later.state not in _ALLOWED[earlier.state]:
            raise IllegalTransition(
                f"{earlier.state.value} -> {later.state.value} is not a permitted "
                f"transition"
            )
        if later.at < earlier.at:
            raise IllegalTransition(
                f"{later.state.value} timestamped {later.at.isoformat()} precedes the "
                f"previous event at {earlier.at.isoformat()}; a trail that can be written "
                f"out of chronological order cannot be replayed"
            )


@dataclass
class ProductLifecycle:
    """The disposition trail for one delivered product."""

    product_subject: str
    product_id: str = ""
    """Stable identity of the product these events belong to.

    Without it a trail is bound only to a subject, and one asset can carry many claims:
    two recommendations about the same forklift a week apart would share a lifecycle and
    the outcome of one would silently attach to the other.
    """

    events: list[DispositionEvent] = field(default_factory=list)
    attributed_effect: AttributedEffect = AttributedEffect.NOT_ESTABLISHED

    # `observed_outcome: str | None` and `record_outcome(outcome: str, ...)` are DELETED,
    # not deprecated.
    #
    # There were two outcome authorities. `OutcomeObservation` is a typed record with an
    # outcome type from a closed enum, a subject, an observation window, a source and --
    # the field the whole LEARN boundary exists for -- the id of the action it is about.
    # Beside it sat a free string on the lifecycle, set by a method that also advanced the
    # trail, and the reference scenario exercised BOTH: it recorded "degraded cell found;
    # pack swapped" as prose here and constructed the typed observation separately, with
    # nothing comparing them.
    #
    # A string cannot be grouped, counted or joined to a recommendation, so an evaluation
    # dataset built from it cannot separate "acted and no failure" from "ignored and no
    # failure" -- which is the entire value of collecting outcomes. Leaving it deprecated
    # would leave it settable, and a field that exists teaches every caller that filling
    # it means something.
    #
    # The lifecycle records STATE TRANSITIONS. The envelope carries the typed outcome. The
    # two are bound: `IntelligenceEnvelope` refuses a trail that reaches OUTCOME_OBSERVED
    # with no outcome, an outcome with no such trail, and -- since two timestamps for one
    # event is the same defect one layer down -- an OUTCOME_OBSERVED event whose moment is
    # not the outcome's own `observed_at`.

    @property
    def state(self) -> DispositionState | None:
        """The current state, or None before anything has been recorded.

        This used to report DELIVERED for an empty trail, which let a caller build a
        fresh lifecycle and advance straight to ACKNOWLEDGED -- recording that a customer
        acknowledged a product that had never been delivered. An empty history is not a
        delivery; it is an absence, and the type now says so.
        """
        return self.events[-1].state if self.events else None

    def advance(
        self, to: DispositionState, *, at: datetime, actor: str, note: str = ""
    ) -> None:
        """Move to a new state, or refuse and say why."""
        current = self.state
        if current is None:
            if to is not DispositionState.DELIVERED:
                raise IllegalTransition(
                    f"cannot open a lifecycle at {to.value}; the first event must be "
                    f"{DispositionState.DELIVERED.value}"
                )
            self.events.append(DispositionEvent(to, at, actor, note))
            return
        if to not in _ALLOWED[current]:
            raise IllegalTransition(
                f"{current.value} -> {to.value} is not a permitted transition; "
                f"allowed: {[s.value for s in _ALLOWED[current]]}"
            )
        # Time must move forward. A trail that can be written out of order cannot be
        # replayed, and replaying it is the only reason to keep it.
        last = self.events[-1].at
        if at < last:
            raise IllegalTransition(
                f"{to.value} timestamped {at.isoformat()} precedes the previous event "
                f"at {last.isoformat()}"
            )
        self.events.append(DispositionEvent(to, at, actor, note))

    def is_closed(self) -> bool:
        return self.state is DispositionState.OUTCOME_OBSERVED

    def as_record(self) -> dict[str, object]:
        return {
            "subject": self.product_subject,
            "product_id": self.product_id,
            "state": self.state.value if self.state else None,
            "attributed_effect": self.attributed_effect.value,
            "trail": [
                {"state": e.state.value, "at": e.at.isoformat(), "actor": e.actor,
                 "note": e.note}
                for e in self.events
            ],
        }
