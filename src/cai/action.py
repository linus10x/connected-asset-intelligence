"""What the recipient is asked to do, and what was later observed.

WHY THESE ARE NOT STRINGS
-------------------------
`recommended_action = "inspect before next shift"` reads well and cannot be evaluated. No
machine can later ask whether the thing recommended was the thing done, which means the
outcome loop has no join: a disposition says somebody accepted *something*, an outcome says
*something* happened, and nothing connects the two to a specific instruction.

A human-readable sentence is good UI. It must not be the system of record, so it is
rendered from these types rather than stored instead of them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .decision import TimeInterval, format_moment


class ActionType(str, Enum):
    """Deliberately small. Each is something a person can be dispatched to do."""

    INSPECT = "INSPECT"
    SERVICE = "SERVICE"
    REPLACE = "REPLACE"
    RESCHEDULE = "RESCHEDULE"
    MONITOR = "MONITOR"


class Priority(str, Enum):
    ROUTINE = "ROUTINE"
    BEFORE_NEXT_USE = "BEFORE_NEXT_USE"
    IMMEDIATE = "IMMEDIATE"


@dataclass(frozen=True)
class ActionRecommendation:
    """A specific instruction, addressed to somebody, with a deadline.

    `due_by` is separate from `operational_window` on purpose. The deadline is when the
    action must be complete; the window is when the consequence lands. Collapsing them
    reads fine until the two differ, which is the ordinary case -- inspect before the
    03:00 shift so the machine is available for the 05:00 window.
    """

    action_id: str
    action_type: ActionType
    target: str
    responsible_role: str
    due_by: datetime
    operational_window: TimeInterval
    reason: str
    priority: Priority = Priority.ROUTINE
    prerequisites: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ValueError("an action with no id cannot be joined to its outcome")
        if self.due_by.tzinfo is None:
            raise ValueError("due_by must be timezone-aware")
        if self.due_by > self.operational_window.end:
            raise ValueError(
                f"action due {self.due_by.isoformat()} falls after the operational "
                f"window closes at {self.operational_window.end.isoformat()}; it could "
                f"not change the outcome it claims to prevent"
            )

    def rendered_text(self) -> str:
        """The operator-facing sentence, derived from the fields above.

        PREREQUISITES ARE PART OF THE INSTRUCTION, AND THEY WERE NOT.
        --------------------------------------------------------------
        They sat on this type, travelled in the record, and never reached the card. So
        the delivered artifact -- the one thing in the bundle a human literally read, and
        the only part whose digest attests what they were shown -- omitted "isolate the
        pack" and "lock out the charger" while the record carried them.

        Two ways to read that, and only one is honest. Either they are internal metadata,
        in which case a reader must never treat them as evidence of what an operator was
        told; or they are instructions, in which case a prerequisite the operator never
        saw is not a prerequisite. They are safety steps that must happen FIRST. They are
        instructions.

        So they render, which puts them inside the card, inside its digest, and inside the
        comparison the import boundary already performs. Nothing new had to be built for
        that -- the artifact was already the authority on what was shown; it was simply
        being shown less than the record claimed.
        """
        sentence = (
            f"{self.action_type.value.lower()} {self.target} "
            f"by {format_moment(self.due_by)} ({self.responsible_role})"
        )
        if not self.prerequisites:
            return sentence
        return sentence + " -- first: " + ", ".join(self.prerequisites)

    def as_record(self) -> dict[str, object]:
        return {
            "action_id": self.action_id,
            "action_type": self.action_type.value,
            "target": self.target,
            "responsible_role": self.responsible_role,
            "due_by": self.due_by.isoformat(),
            "operational_window_start": self.operational_window.start.isoformat(),
            "operational_window_end": self.operational_window.end.isoformat(),
            "reason": self.reason,
            "priority": self.priority.value,
            "prerequisites": list(self.prerequisites),
            "rendered_text": self.rendered_text(),
        }

    @classmethod
    def from_record(cls, r: dict[str, object]) -> "ActionRecommendation":
        """`rendered_text` is NOT read back as an input -- and is not ignored either.

        Not reading it back is right: a rendering that can be supplied is a second source
        of truth free to disagree with the action it describes. But silently re-deriving
        it and discarding whatever the payload said is the other half of the mistake, and
        on this field it is the more dangerous half. This sentence is what a human was
        SHOWN. A bundle claiming the operator was told to replace a pack immediately would
        import cleanly, be re-exported as an instruction to inspect it, and carry a freshly
        computed digest over the version nobody saw.

        So it is re-derived AND compared, and a disagreement is refused rather than
        normalised.
        """
        rebuilt = cls(
            action_id=str(r["action_id"]),
            action_type=ActionType(r["action_type"]),
            target=str(r["target"]),
            responsible_role=str(r["responsible_role"]),
            due_by=datetime.fromisoformat(str(r["due_by"])),
            operational_window=TimeInterval(
                datetime.fromisoformat(str(r["operational_window_start"])),
                datetime.fromisoformat(str(r["operational_window_end"])),
            ),
            reason=str(r["reason"]),
            priority=Priority(r["priority"]),
            prerequisites=tuple(r.get("prerequisites") or ()),  # type: ignore[arg-type]
        )
        if "rendered_text" in r and r["rendered_text"] != rebuilt.rendered_text():
            raise ValueError(
                f"the action record's rendered_text is {r['rendered_text']!r} but the "
                f"sentence its own typed fields render is {rebuilt.rendered_text()!r}; "
                f"this is the text a human was shown, and quietly replacing it would "
                f"re-export a different instruction under a freshly computed digest"
            )
        return rebuilt


class OutcomeType(str, Enum):
    FAILURE_OCCURRED = "FAILURE_OCCURRED"
    NO_FAILURE_OBSERVED = "NO_FAILURE_OBSERVED"
    DEFECT_FOUND_ON_INSPECTION = "DEFECT_FOUND_ON_INSPECTION"
    NO_DEFECT_FOUND = "NO_DEFECT_FOUND"
    NOT_OBSERVED = "NOT_OBSERVED"


@dataclass(frozen=True)
class OutcomeObservation:
    """What was observed afterwards, in a form a machine can group and count.

    `related_action_id` is the join the prose version could never provide. Without it an
    evaluation dataset cannot separate "acted and no failure" from "ignored and no
    failure", and those two rows are the entire value of collecting outcomes.

    Note what is still absent by design: any field asserting the recommendation CAUSED the
    outcome. Nothing was randomised and the recipient chose.
    """

    outcome_id: str
    outcome_type: OutcomeType
    subject: str
    observation_window: TimeInterval
    observed_at: datetime
    source: str
    related_action_id: str | None = None
    metric: str | None = None
    value: float | None = None
    severity: str | None = None
    note: str = ""

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone-aware")
        if not self.outcome_id:
            raise ValueError("an outcome with no id cannot be cited")
        if not self.subject:
            raise ValueError("an outcome with no subject cannot be attached to anything")
        # HALF-OPEN, both ends. `TimeInterval` is half-open everywhere else in this
        # package -- `contains` is `start <= moment < end` -- and only the opening half was
        # enforced here, so an outcome could be observed after its own window closed, or
        # exactly at the boundary where it belongs to the NEXT window. An observation
        # outside the period it claims to describe is a row an evaluation dataset counts
        # against the wrong interval.
        if not self.observation_window.contains(self.observed_at):
            raise ValueError(
                f"observed at {self.observed_at.isoformat()}, outside the half-open "
                f"observation window "
                f"[{self.observation_window.start.isoformat()}, "
                f"{self.observation_window.end.isoformat()}); an outcome recorded outside "
                f"the period it claims to describe belongs to a different observation"
            )

    def describe(self) -> str:
        base = self.outcome_type.value.replace("_", " ").lower()
        return f"{base} for {self.subject}" + (f": {self.note}" if self.note else "")

    @classmethod
    def from_record(cls, r: dict[str, object]) -> "OutcomeObservation":
        """Rebuild the typed outcome, and CHECK the derived sentence travelling with it.

        `description` is rendered from the fields. Reading it back would make the exported
        sentence an input; discarding a contradictory one silently would import the bundle
        as something other than the bytes it arrived as.
        """
        value = r.get("value")
        rebuilt = cls(
            outcome_id=str(r["outcome_id"]),
            outcome_type=OutcomeType(r["outcome_type"]),
            subject=str(r["subject"]),
            observation_window=TimeInterval(
                datetime.fromisoformat(str(r["observation_window_start"])),
                datetime.fromisoformat(str(r["observation_window_end"])),
            ),
            observed_at=datetime.fromisoformat(str(r["observed_at"])),
            source=str(r["source"]),
            related_action_id=(
                str(r["related_action_id"]) if r.get("related_action_id") else None
            ),
            metric=str(r["metric"]) if r.get("metric") else None,
            value=float(value) if value is not None else None,  # type: ignore[arg-type]
            severity=str(r["severity"]) if r.get("severity") else None,
            note=str(r.get("note") or ""),
        )
        if "description" in r and r["description"] != rebuilt.describe():
            raise ValueError(
                f"the outcome record's description is {r['description']!r} but the "
                f"sentence its own fields render is {rebuilt.describe()!r}"
            )
        return rebuilt

    def as_record(self) -> dict[str, object]:
        return {
            "outcome_id": self.outcome_id,
            "outcome_type": self.outcome_type.value,
            "subject": self.subject,
            "observation_window_start": self.observation_window.start.isoformat(),
            "observation_window_end": self.observation_window.end.isoformat(),
            "observed_at": self.observed_at.isoformat(),
            "source": self.source,
            "related_action_id": self.related_action_id,
            "metric": self.metric,
            "value": None if self.value is None else f"{self.value:.6f}",
            "severity": self.severity,
            "note": self.note,
            "description": self.describe(),
        }
