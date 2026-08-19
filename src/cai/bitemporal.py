"""Bitemporal observation records.

WHY THIS EXISTS
---------------
Connected assets do not report in real time. A device buffers while out of coverage,
in a yard, in a basement, or simply switched off, and then delivers a backlog when it
reconnects. Delivery is at-least-once, so the same reading can arrive twice. Device
clocks drift, and some report timestamps that are wrong in ways only detectable
relative to ingest.

The consequence is that "what did the system know on day 40" and "what do we now
believe was true on day 40" are different questions with different answers, and a
system that keeps only one timestamp cannot tell them apart. That is fatal for a
record whose entire purpose is reconstructing a past decision: a claim made on day 40
must be judged against the evidence available on day 40, not against evidence that
arrived on day 49.

So every observation carries two times:

    valid_time       when the thing happened in the world
    transaction_time when this system first learned of it

Late arrival is therefore not an error path. It is the normal case, and it is the
reason this module exists.

WHAT THIS DELIBERATELY DOES NOT DO
----------------------------------
No watermarking or windowing policy. Those are stream-processing concerns that belong
to whatever engine ingests the data, and reimplementing them here would be exactly the
kind of platform imitation this project is trying not to be. This module models the
temporal record, not the pipeline.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

VALUE_WIRE_PRECISION = 6
"""Decimal places a reading's value keeps when it crosses the wire.

Six, like every other float in this contract. It is stated as a constant because the
number is now load-bearing in two directions: `as_record` formats to it, and
`__post_init__` refuses a reading that would not survive it. A value quantized on export
but hashed at full precision produces a `content_digest` that changes across the wire,
and the digest is the only thing binding a claim to the reading it was computed from.
"""


@dataclass(frozen=True)
class Observation:
    """A single reading, with both times it needs to be reasoned about.

    `observation_id` is the natural key. Because delivery is at-least-once, the same
    id may legitimately arrive more than once; see `ObservationLog.record`.

    WHY THE CONSTRUCTOR REFUSES THINGS IT ONCE TOLERATED
    ----------------------------------------------------
    Readings did not cross the wire. Now they do -- release evidence travels inside the
    envelope so an importer can reproduce the assessment -- and three states that were
    merely untidy in memory became forgery surface or round-trip failures on the wire:

      * a naive timestamp hashes differently depending on who reads it. `content_digest`
        refused one; the object could still hold one, and every other consumer of
        `valid_time` compared it happily.
      * an `int` value seats fine in a `float` field, and `repr(1236) != repr(1236.0)`,
        so the same reading digested differently either side of the wire.
      * a value carrying more precision than the wire form preserves produced an honest
        product whose own importer refused it -- the defect `PredictionInputs`,
        `IdentityAssertion` and `DowntimeConsequence` each closed at their own boundary.

    Refused here, at the one place a reading enters the system, rather than at each of
    the boundaries that later have to trust it.
    """

    observation_id: str
    subject: str
    metric: str
    value: float
    valid_time: datetime
    transaction_time: datetime
    source_system: str
    supersedes: str | None = None
    """The observation this one corrects, if any.

    An append-only log says corrections arrive as new observations, and for one revision
    that was all it said -- there was no way to express *which* reading a correction
    replaced. So a corrected value and the value it corrected both appeared in the
    retrospective view, and a reader averaging or counting them silently double-counted
    a single event.

    Naming the superseded id keeps the append-only property (the old reading stays
    visible, which is the point of an evidence log) while letting the retrospective view
    show current belief rather than every belief ever held.
    """

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("a reading with no id cannot be cited by a claim")
        if not self.subject:
            raise ValueError("a reading with no subject is a number about nothing")
        if not self.metric:
            raise ValueError("a reading with no metric is a number with no meaning")
        if not self.source_system:
            raise ValueError(
                f"{self.observation_id!r} names no source system; a reading nobody is "
                f"recorded as having sent cannot be licensed, challenged or corrected"
            )
        for label, moment in (
            ("valid_time", self.valid_time),
            ("transaction_time", self.transaction_time),
        ):
            if moment.tzinfo is None:
                raise ValueError(
                    f"{label} must be timezone-aware; a timestamp without a zone hashes "
                    f"and orders differently depending on who reads it"
                )
        # `float(...)` rather than a type refusal: an integer reading is ordinary
        # telemetry (a charge-cycle count), and the field is declared `float`. Normalising
        # once here is what makes `repr(self.value)` -- and therefore the content digest --
        # the same value before and after the wire.
        value = float(self.value)
        if not math.isfinite(value):
            raise ValueError(f"reading {self.observation_id!r} has value {self.value!r}")
        if float(f"{value:.{VALUE_WIRE_PRECISION}f}") != value:
            raise ValueError(
                f"reading {self.observation_id!r} carries value {value!r}, more precision "
                f"than the {VALUE_WIRE_PRECISION}-decimal wire form preserves, so its "
                f"content digest would not survive its own round trip; quantize the "
                f"reading before it enters the log rather than after"
            )
        object.__setattr__(self, "value", value)

    def arrival_lag(self) -> timedelta:
        """How late this reading was. Non-negative in a well-behaved feed."""
        return self.transaction_time - self.valid_time

    def is_late(self, threshold: timedelta) -> bool:
        return self.arrival_lag() > threshold

    def has_implausible_clock(self) -> bool:
        """True when the device claims an event that had not happened yet on arrival.

        A negative lag means the device clock is ahead of the ingest clock. It is a
        clock-skew signal, not a paradox, and it matters because such a reading can
        silently appear inside a knowledge window it should not belong to.
        """
        return self.arrival_lag() < timedelta(0)

    def content_digest(self) -> str:
        """SHA-256 over this reading's values, not over its identifier.

        An evidence snapshot that stores only `observation_id` stores a pointer. A
        pointer proves nothing about what it points at: change the value behind the id
        and every pointer still resolves, every digest over the record still verifies,
        and the reconstruction quietly describes a reading that no longer exists.

        `repr` on a float round-trips exactly in CPython, so the digest is stable
        across processes.

        The naive-datetime refusal that used to open this method is gone, and deleted
        rather than kept as belt-and-braces: `__post_init__` now refuses a naive
        timestamp, so no `Observation` can reach this method holding one. A guard no
        input can reach reads as protection and proves nothing, which is the pattern this
        package spends its time removing.
        """
        parts = (
            self.observation_id,
            self.subject,
            self.metric,
            repr(self.value),
            self.valid_time.isoformat(),
            self.transaction_time.isoformat(),
            self.source_system,
            self.supersedes or "",
        )
        # Unit separator: a delimiter that cannot occur in these fields, so
        # ("ab","c") and ("a","bc") cannot collide into the same digest.
        return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()

    def as_record(self) -> dict[str, Any]:
        """The language-neutral form of one reading.

        The value travels as a fixed six-decimal string like every other float in this
        contract -- the canonicalizer refuses non-integer floats outright rather than risk
        two implementations formatting one number two ways. `__post_init__` refuses a
        reading this form would lose, so the digest computed here and the digest computed
        by a reader holding only these bytes are the same digest.
        """
        return {
            "observation_id": self.observation_id,
            "subject": self.subject,
            "metric": self.metric,
            "value": f"{self.value:.{VALUE_WIRE_PRECISION}f}",
            "valid_time": self.valid_time.isoformat(),
            "transaction_time": self.transaction_time.isoformat(),
            "source_system": self.source_system,
            "supersedes": self.supersedes,
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "Observation":
        """Rebuild a reading, running this type's own invariants on the way in.

        Reconstruction rather than validation, for the reason every other boundary in
        this package gives: a hand-written wire validator is a second semantics engine,
        and the day it disagrees with the constructor is the day the portable form stops
        meaning what the in-memory form means.
        """
        return cls(
            observation_id=r["observation_id"],
            subject=r["subject"],
            metric=r["metric"],
            value=float(r["value"]),
            valid_time=datetime.fromisoformat(r["valid_time"]),
            transaction_time=datetime.fromisoformat(r["transaction_time"]),
            source_system=r["source_system"],
            supersedes=r.get("supersedes") or None,
        )


def digest_observations(observations: Iterable[Observation]) -> str:
    """An order-independent digest binding a set of readings to a decision record.

    Sorted so that two systems holding the same evidence agree regardless of storage
    order, and so a consumer can re-derive it from observations they hold and detect
    substitution.

    WHAT THIS IS NOT
    ----------------
    Not a signature. Anyone who alters the underlying readings can recompute this
    digest and the record will verify. It detects a record and its evidence drifting
    apart; it does not detect a party who controls both and changes them together.
    That requires a signature over the pair, which this project deliberately does not
    implement rather than implement badly.
    """
    per_observation = sorted(o.content_digest() for o in observations)
    joined = "\x1e".join(per_observation)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EvidenceBundle:
    """The readings a release rests on, together with the contradictions found in them.

    WHY ONE OBJECT AND NOT TWO ARGUMENTS
    ------------------------------------
    `ObservationLog` detected same-id/different-payload conflicts from the day it was
    written. `assess_evidence` could consume them, through an OPTIONAL argument. And
    `formation.release` never supplied it -- so the module-level test proving conflicts
    were detected stayed green for the entire life of the feature while the actual product
    path released without ever seeing one.

    An optional verification argument is one a caller forgets. This one was forgotten by
    the only caller that mattered. Binding the two together means there is no arrangement
    of arguments in which the release path sees the evidence and not the disagreement
    about it: to get the readings you take the bundle, and the bundle carries both.

    WHO IS ALLOWED TO ISSUE ONE
    ---------------------------
    In memory, `ObservationLog.evidence_for` is the only issuer that matters, and
    `formation.release` no longer has a parameter through which any other bundle could
    reach it -- so a hand-built bundle cannot be laundered into a release. The public
    constructor remains, because reconstruction from the wire needs it: an importer must
    be able to rebuild the evidence a release carried in order to recompute the assessment
    over it. What closes the wire side is not who may call this constructor but that the
    rebuilt bundle has to reproduce the recorded `EvidenceAssessment` exactly.

    The invariants below are therefore written for a bundle whose contents a reader did
    not watch being assembled. A conflict must be ABOUT a reading this bundle carries, it
    must name the reading this bundle carries rather than some other version of it, and it
    must actually be a conflict.
    """

    observations: tuple[Observation, ...]
    integrity_conflicts: tuple[tuple[Observation, Observation], ...] = ()
    """Pairs of (kept, rejected) that share an id and disagree about the payload."""

    def __post_init__(self) -> None:
        by_id: dict[str, Observation] = {}
        for observation in self.observations:
            if observation.observation_id in by_id:
                raise ValueError(
                    f"the bundle carries {observation.observation_id!r} twice; a log "
                    f"keeps one reading per id, and two would make 'which reading did "
                    f"this claim rest on' a question the evidence cannot answer"
                )
            by_id[observation.observation_id] = observation
        for kept, rejected in self.integrity_conflicts:
            carried = by_id.get(kept.observation_id)
            if carried is None:
                raise ValueError(
                    f"the bundle carries a conflict about {kept.observation_id!r}, which "
                    f"is not among the readings it contains; a conflict about evidence "
                    f"this claim does not rest on would withhold a product for somebody "
                    f"else's problem"
                )
            if carried.content_digest() != kept.content_digest():
                raise ValueError(
                    f"the conflict kept for {kept.observation_id!r} is not the reading "
                    f"the bundle carries under that id; a disagreement recorded against "
                    f"one version of a reading and shipped beside another describes a "
                    f"contradiction nobody can reconcile"
                )
            if rejected.observation_id != kept.observation_id:
                raise ValueError(
                    f"a conflict pairs {kept.observation_id!r} with "
                    f"{rejected.observation_id!r}; an integrity conflict is one id whose "
                    f"payload two sources disagree about, not two different readings"
                )
            if rejected.content_digest() == kept.content_digest():
                raise ValueError(
                    f"the conflict recorded for {kept.observation_id!r} pairs a reading "
                    f"with itself; an identical redelivery is ordinary at-least-once "
                    f"traffic and withholding a product for it is a refusal nobody can act "
                    f"on"
                )

    def conflict_descriptions(self) -> tuple[str, ...]:
        """Named, so a refusal says which reading two sources disagree about."""
        return tuple(
            f"{kept.observation_id}: {kept.source_system} and {rejected.source_system} "
            f"disagree about the payload"
            for kept, rejected in self.integrity_conflicts
        )

    def as_record(self) -> dict[str, Any]:
        """The evidence itself, not a citation of it.

        `EvidenceSnapshot` already crossed the wire, and it is a set of pointers: ids, an
        aggregate digest, a list of source systems. A reader holding only pointers can
        check that the record agrees with itself and nothing else -- they cannot re-derive
        the digest, cannot confirm the bound inputs are the readings they name, and cannot
        see a contradiction the producer chose not to mention. The portable form was
        therefore strictly weaker than the in-memory form, on an artifact whose whole
        proposition is that the decision survives the platform that produced it.
        """
        return {
            "observations": [o.as_record() for o in self.observations],
            "integrity_conflicts": [
                {"kept": kept.as_record(), "rejected": rejected.as_record()}
                for kept, rejected in self.integrity_conflicts
            ],
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "EvidenceBundle":
        return cls(
            observations=tuple(
                Observation.from_record(o) for o in r.get("observations") or ()
            ),
            integrity_conflicts=tuple(
                (
                    Observation.from_record(pair["kept"]),
                    Observation.from_record(pair["rejected"]),
                )
                for pair in r.get("integrity_conflicts") or ()
            ),
        )


class ObservationLog:
    """Append-only observation store supporting as-of queries.

    Append-only because a decision record that can be edited is not evidence. A
    correction is a new observation, and the superseded reading stays visible.
    """

    def __init__(self) -> None:
        self._observations: list[Observation] = []
        self._by_id: dict[str, Observation] = {}
        self._conflicts: list[tuple[Observation, Observation]] = []

    def record(self, observation: Observation) -> bool:
        """Append an observation. Returns False if it was a duplicate delivery.

        At-least-once delivery makes duplicates ordinary traffic rather than a fault,
        so an identical redelivery is reported and ignored instead of raising.

        A redelivery that is *not* identical is a different animal. The log used to
        deduplicate on `observation_id` alone, so a reading arriving with the same id and
        a changed value, timestamp or source was discarded as an ordinary retry -- the
        system silently kept the first version and never mentioned that two sources
        disagreed about the same event. That is data loss disguised as idempotency, and
        in a record whose purpose is defending a past decision it is the worst kind:
        invisible.
        """
        existing = self._by_id.get(observation.observation_id)
        if existing is not None:
            if existing.content_digest() != observation.content_digest():
                self._conflicts.append((existing, observation))
            return False
        self._by_id[observation.observation_id] = observation
        self._observations.append(observation)
        return True

    def integrity_conflicts(self) -> tuple[tuple[Observation, Observation], ...]:
        """Same identifier, different payload. Never empty by accident.

        Each pair is (what was kept, what was rejected). The first is retained because
        an append-only log does not rewrite history; the disagreement is surfaced here so
        somebody can go and find out which source is wrong.
        """
        return tuple(self._conflicts)

    def evidence_for(
        self,
        *,
        knowledge_cutoff: datetime,
        evaluation_time: datetime | None = None,
        subject: str | None = None,
    ) -> EvidenceBundle:
        """The bundle a release path consumes: the point-in-time view AND its conflicts.

        THIS IS NOW THE ONLY ISSUER, AND THAT IS A STRUCTURAL FACT
        ----------------------------------------------------------
        It used to be the only issuer by convention. `formation.release` took an
        `EvidenceBundle` parameter, and a hand-built one carrying `integrity_conflicts=()`
        type-checked perfectly -- so a caller could hand the release path the readings
        while withholding the contradictions the log had found in them, and the release
        docstring called that state impossible. It was not; the wrapper was enforced and
        its contents were a convention.

        `release` now takes the LOG and calls this method itself. There is no parameter
        left through which a bundle could arrive, so the readings and the disagreements
        about them cannot be separated on the way in.

        Conflicts are filtered to the readings actually returned. A disagreement about an
        observation this claim does not rest on would withhold a product for somebody
        else's problem, which is a refusal the operator cannot act on.

        AND FILTERED TO WHAT HAD ARRIVED, WHICH IS THE HALF THAT WAS MISSING
        -------------------------------------------------------------------
        The readings went through the point-in-time view and the conflicts did not. Only
        the KEPT side was checked, and only for membership -- so a contradicting
        redelivery arriving on the 14th attached itself to the evidence issued for a
        decision taken on the 12th, and integrity went BROKEN retrospectively. A decision
        that was honest when it was taken became a refusal two days later because
        somebody's second system finally sent its copy.

        That is the exact anachronism this whole file exists to refuse, running backwards.
        The rejected reading carries its own `transaction_time`; a conflict is part of a
        historical decision's evidence only if that reading had arrived by the cutoff the
        decision rested on. Later conflicts stay in the log -- they are real, and they
        belong to every later decision whose cutoff reaches them -- they are simply not
        evidence about what was knowable on the 12th.
        """
        observations = self.point_in_time_view(
            knowledge_cutoff=knowledge_cutoff,
            evaluation_time=evaluation_time,
            subject=subject,
        )
        ids = {o.observation_id for o in observations}
        return EvidenceBundle(
            observations=observations,
            integrity_conflicts=tuple(
                (kept, rejected)
                for kept, rejected in self._conflicts
                if kept.observation_id in ids
                and rejected.transaction_time <= knowledge_cutoff
            ),
        )

    def __len__(self) -> int:
        return len(self._observations)

    def decision_time_view(
        self, *, transaction_time: datetime, subject: str | None = None
    ) -> tuple[Observation, ...]:
        """What this system had actually received by a given moment.

        This is the query that makes decision reconstruction honest. It deliberately
        excludes observations that describe earlier events but arrived later: they
        were not available to the decision, and including them would produce a
        flattering reconstruction of what was knowable.
        """
        return tuple(
            o
            for o in self._observations
            if o.transaction_time <= transaction_time
            and (subject is None or o.subject == subject)
        )

    def current_best_known_view(
        self, *, valid_time: datetime, subject: str | None = None
    ) -> tuple[Observation, ...]:
        """Everything now on record as effective at a given moment.

        Deliberately NOT called `true_as_of`. Valid time records when a source
        *asserts* a fact was effective -- not that the assertion is correct. A late
        record may itself be wrong, contested, or superseded later. Calling this view
        "truth" would smuggle an epistemic claim into a method name.

        Distinct from `decision_time_view`: this includes readings that arrived late,
        which makes it right for analysis and wrong for judging a past decision.

        Superseded readings are excluded. They remain in the log -- an evidence store
        that deletes is not evidence -- but a view of what is *currently believed* should
        not return both a correction and the value it corrected, which is what a reader
        averaging or counting them would silently double-count.
        """
        superseded = {
            o.supersedes
            for o in self._observations
            if o.supersedes and o.valid_time <= valid_time
        }
        return tuple(
            o
            for o in self._observations
            if o.valid_time <= valid_time
            and o.observation_id not in superseded
            and (subject is None or o.subject == subject)
        )

    def superseded_ids(self) -> frozenset[str]:
        """Every observation some later reading claims to correct."""
        return frozenset(o.supersedes for o in self._observations if o.supersedes)

    def point_in_time_view(
        self,
        *,
        knowledge_cutoff: datetime,
        evaluation_time: datetime | None = None,
        subject: str | None = None,
    ) -> tuple[Observation, ...]:
        """The view a prediction should actually be computed from.

        `decision_time_view` filters on transaction time alone, which is correct as far
        as it goes and leaves a hole: a device with a skewed clock can stamp a reading
        with a valid_time in the future, deliver it before the decision, and land inside
        the decision-time view describing an event that had not happened. The reading was
        genuinely received in time; it is the event it claims to describe that had not
        occurred.

        So this requires both clocks to agree that the evidence was usable:

            transaction_time <= knowledge_cutoff     it had arrived
            valid_time       <= evaluation_time   it had happened

        and drops records whose two clocks contradict each other outright. Those are not
        filtered silently -- `has_implausible_clock` names them, and a caller building a
        feature vector should be reporting how many it excluded.

        `evaluation_time` defaults to `knowledge_cutoff`, which is the ordinary case.
        """
        cutoff = evaluation_time if evaluation_time is not None else knowledge_cutoff
        # A correction that had arrived by the decision supersedes what it corrects, in
        # the decision-time view as well as the retrospective one -- otherwise the
        # predictor consumes both the corrected reading and the reading it corrected.
        # A correction that arrived later must NOT reach back and rewrite the decision,
        # so the superseding set is itself filtered by transaction time.
        superseded_by_then = {
            o.supersedes
            for o in self._observations
            if o.supersedes and o.transaction_time <= knowledge_cutoff
        }
        return tuple(
            o
            for o in self._observations
            if o.transaction_time <= knowledge_cutoff
            and o.valid_time <= cutoff
            and o.observation_id not in superseded_by_then
            and not o.has_implausible_clock()
            and (subject is None or o.subject == subject)
        )

    def excluded_for_clock_skew(
        self, *, knowledge_cutoff: datetime, subject: str | None = None
    ) -> tuple[Observation, ...]:
        """Readings that arrived in time but claim an event that had not happened."""
        return tuple(
            o
            for o in self._observations
            if o.transaction_time <= knowledge_cutoff
            and o.has_implausible_clock()
            and (subject is None or o.subject == subject)
        )

    def late_arrivals(
        self, *, since: datetime, until: datetime, threshold: timedelta
    ) -> tuple[Observation, ...]:
        """Observations about the window that only arrived after it closed.

        These are exactly the readings that make a naive reconstruction look better
        informed than the decision-maker actually was.
        """
        return tuple(
            o
            for o in self._observations
            if since <= o.valid_time <= until
            and o.transaction_time > until
            and o.is_late(threshold)
        )

    def knowledge_gap(
        self, *, knowledge_cutoff: datetime, subject: str
    ) -> tuple[Observation, ...]:
        """What was learned about the pre-decision period only after the decision.

        If this is non-empty, a reconstruction of that decision must say so. The
        decision was made without this evidence, and judging it as though the
        evidence were present is a form of hindsight that a claim's author does not
        deserve to benefit from and an investigator should not be denied.
        """
        return tuple(
            o
            for o in self._observations
            if o.subject == subject
            and o.valid_time <= knowledge_cutoff
            and o.transaction_time > knowledge_cutoff
        )
