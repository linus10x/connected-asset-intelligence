"""The temporal authority every stage shares, and the typed claim built under it.

WHY ONE OBJECT
--------------
Time semantics used to arrive as loose parameters: `model_decision_time` here, `horizon_start`
there, `transaction_time_cutoff` somewhere else. Nothing stopped one layer from meaning
"the moment the claim was issued" while another quietly meant "the start of the window it
describes", and a reader could not tell which without reading both.

So there is one `DecisionContext`, constructed once and threaded through CONNECT, PREDICT,
REASON and PRODUCTIZE. Every stage answers to the same clock.

WHAT IS DELIBERATELY NOT HERE
-----------------------------
`valid_until` is not part of this. It describes how long the resulting intelligence stays
actionable, which is a property of the product, not of the historical context the decision
was formed under. Putting it here would let a lifetime decision masquerade as a fact about
the past.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


_MONTHS = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def format_moment(moment: datetime) -> str:
    """The operator-facing timestamp: one instant, one rendering, in UTC, saying so.

    WHAT WAS WRONG, AND IT WAS NOT THE LOCALE
    -----------------------------------------
    The locale half was already fixed. `strftime("%b")` reads `LC_TIME`, so a producer
    under `fr_FR.UTF-8` rendered "13 juin" into the delivered card while stamping
    `locale="en"` beside it, and every reader elsewhere refused the bundle because both
    strings are re-derived and compared on import. The explicit month table closed that.

    What it did not close is the OFFSET. `f"{moment:%H:%M}"` renders the local wall-clock
    face of an offset-aware datetime and drops the offset entirely, so the same instant
    stamped `03:00+00:00` and `04:00+01:00` rendered as "03:00" and "04:00" -- two
    different deadlines on two cards attesting one moment -- and neither said which zone
    it meant. An operator reading "act by 03:00" on a card produced three time zones away
    has been told something false, and the record cannot be used to show what they were
    told.

    Normalised to UTC and NAMED. Not the producer's offset, because a deadline whose
    meaning depends on where the producer sat is not portable; and named, because a
    timestamp without a zone invites the reader to supply one.

    The digests over every card containing a deadline move with this, and deliberately so.
    Preserving the old ones for compatibility would preserve an ambiguous rendering, and
    the old representation is the defect.
    """
    if moment.tzinfo is None:
        raise ValueError(
            "refusing to render a naive datetime; a timestamp with no zone has no single "
            "instant to normalise, and rendering its wall-clock face would put a deadline "
            "on an operator's card that means something different to each reader"
        )
    utc = moment.astimezone(timezone.utc)
    return f"{utc:%H:%M} UTC on {utc.day:02d} {_MONTHS[utc.month - 1]}"


@dataclass(frozen=True)
class TimeInterval:
    """A half-open interval, tz-aware at both ends.

    Typed because a bare (start, end) pair invites the caller to pass them in the wrong
    order, and an inverted prediction window silently produces a negative horizon that
    every downstream calculation then treats as real.
    """

    start: datetime
    end: datetime

    def __post_init__(self) -> None:
        for label, moment in (("start", self.start), ("end", self.end)):
            if moment.tzinfo is None:
                raise ValueError(f"{label} must be timezone-aware")
        if self.end < self.start:
            raise ValueError(
                f"interval ends {self.start - self.end} before it begins; a negative "
                f"prediction window is a bug wherever it came from"
            )
        if self.end == self.start:
            # `end < start` was refused and `end == start` was not, which left an instant
            # passing as an interval. A zero-length prediction window derives a zero
            # horizon, and the governing ruling requires a non-empty one: the claim would
            # describe a period during which nothing can happen, and every downstream
            # duration calculation would divide the evidence by no time at all.
            raise ValueError(
                f"interval at {self.start.isoformat()} has zero-length duration; an "
                f"instant is not an interval and a claim about it describes no period"
            )

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    def contains(self, moment: datetime) -> bool:
        return self.start <= moment < self.end

    def overlaps(self, other: "TimeInterval") -> bool:
        return self.start < other.end and self.end > other.start


@dataclass(frozen=True)
class DecisionContext:
    """The single temporal authority for the ANALYTICAL decision.

    `model_decision_time` when the model issued this claim
    `knowledge_cutoff`    what the system had received by then
    `evaluation_time`     the moment facts are evaluated as true-in-the-world
    `prediction_window`   the interval the claim is about

    The invariant that matters most is `knowledge_cutoff <= model_decision_time`. A
    decision cannot rest on evidence that had not arrived, and expressing that as a type
    rather than a convention means no stage can quietly widen it.

    WHY `model_` AND NOT JUST `decision_time`
    -----------------------------------------
    It was `decision_time`, and `AssuranceDecision` separately carried `decided_at`. Two
    names for what sounded like one thing, describing two different decisions, bound to
    each other by nothing -- so a record could say the model issued its call in 2099 and
    the release gate authorised it in 2026, and every check passed.

    They are not the same event and must not be collapsed into one. This clock is what
    the evidence cutoff and point-in-time correctness are judged against: it is a fact
    about the world the claim was computed from. `release_decision_time` is what the
    entitlement window and the policy thresholds are judged against: a fact about the
    rules in force when somebody decided to send it. The reference scenario performs both
    in one process at one instant, which is why the ambiguity survived this long.

    `IntelligenceProduct` binds the order -- the model decides first -- rather than the
    equality. See the comment there for why equality would have been the wrong rule.
    """

    model_decision_time: datetime
    knowledge_cutoff: datetime
    evaluation_time: datetime
    prediction_window: TimeInterval

    def __post_init__(self) -> None:
        stamps = {
            "model_decision_time": self.model_decision_time,
            "knowledge_cutoff": self.knowledge_cutoff,
            "evaluation_time": self.evaluation_time,
        }
        for label, moment in stamps.items():
            if moment.tzinfo is None:
                raise ValueError(f"{label} must be timezone-aware")
        # `evaluation_time` was the one member of the temporal triple bound to nothing:
        # the cutoff rule below was enforced and this accepted 2099. A decision cannot
        # have evaluated the world at a moment that had not happened when it was taken --
        # the same anachronism the cutoff refuses, on the third clock rather than the
        # second.
        if self.evaluation_time > self.model_decision_time:
            raise ValueError(
                f"facts are evaluated as true at {self.evaluation_time.isoformat()}, "
                f"which had not happened when the decision was taken at "
                f"{self.model_decision_time.isoformat()}"
            )
        if self.knowledge_cutoff > self.model_decision_time:
            raise ValueError(
                f"knowledge_cutoff {self.knowledge_cutoff.isoformat()} is after "
                f"model_decision_time {self.model_decision_time.isoformat()}; the decision would "
                f"rest on evidence that had not arrived when it was made"
            )

    @property
    def horizon(self) -> timedelta:
        """The claim's horizon, derived from the window rather than stated separately.

        Stating it twice is how the record came to hold a horizon in the inputs that was
        free to differ from the horizon in the claim.
        """
        return self.prediction_window.duration

    @classmethod
    def from_record(cls, r: dict[str, str]) -> "DecisionContext":
        """Rebuild from the wire. Every invariant this class owns runs on the way in.

        That is the point of reconstructing rather than validating: `knowledge_cutoff <=
        model_decision_time`, timezone-awareness and a non-negative interval are enforced by
        `__post_init__` here exactly as they are in memory, so the importer cannot drift
        from the domain. A hand-written wire validator would be a second semantics engine,
        and the two would disagree on the day it mattered.
        """
        return cls(
            model_decision_time=datetime.fromisoformat(r["model_decision_time"]),
            knowledge_cutoff=datetime.fromisoformat(r["knowledge_cutoff"]),
            evaluation_time=datetime.fromisoformat(r["evaluation_time"]),
            prediction_window=TimeInterval(
                datetime.fromisoformat(r["prediction_window_start"]),
                datetime.fromisoformat(r["prediction_window_end"]),
            ),
        )

    def as_record(self) -> dict[str, str]:
        return {
            "model_decision_time": self.model_decision_time.isoformat(),
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "evaluation_time": self.evaluation_time.isoformat(),
            "prediction_window_start": self.prediction_window.start.isoformat(),
            "prediction_window_end": self.prediction_window.end.isoformat(),
        }
