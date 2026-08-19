"""The REASON path, kept rather than discarded at the moment it stops being free.

WHAT WENT WRONG
---------------
The graph walk produced everything a reader needs to check a commercial conclusion:
which facts were joined, which systems asserted them, when this system learned each one,
which rule version did the joining, what was ambiguous, what arrived too late to use.
Then the consequence was constructed from the walk's *answer* and the walk itself was
dropped on the floor. The portable product carried "at risk: next-day delivery window,
customer A" and nothing whatever about why a battery temperature implies it.

That is the same defect as a hand-authored `business_context`, arrived at by a different
route. A conclusion whose derivation is not carried is a label, and this repository spent
a whole module refusing labels.

WHY THIS IS NOT AN ONTOLOGY
---------------------------
Six concepts, five relationships, one reference path. `DerivationStep` is deliberately
shapeless about WHAT a relationship means -- it records that one named thing stood in a
named relation to another, on some named system's authority, known by a particular
moment. Teaching it the semantics of each relationship would be building the enterprise
ontology platform this project explicitly declines to build, and it would not make the
record more checkable.

WHAT A READER CAN DO WITH IT
----------------------------
Answer WHY without the platform that produced it: read the chain, see which four systems
had to agree, check that every fact was on record by the cutoff, and see the conclusion
the chain terminates at. What they cannot do is re-run the walk -- the graph is not in
the envelope, and pretending otherwise would be the reconstruction-of-a-reconstruction
this codebase names as its worst failure elsewhere.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any

from .decision import TimeInterval


class DerivationRelationship(str, Enum):
    """The five relations v1 implements. A closed vocabulary, not an ontology.

    WHY THIS STOPPED BEING A FREE STRING
    ------------------------------------
    `relationship` was `str`, and the only structural rule over a walk was reachability:
    every step had to start somewhere an earlier step had reached. That refuses a path
    with a hole in it, which was the defect it was added for, and it says nothing about
    whether the sequence MEANS anything. A forger could keep the real entities, keep the
    walk connected, and relabel the relations -- LOADS(asset-4417, zone-3) followed by
    HAS_COMPONENT(zone-3, win-9) -- producing a connected, well-formed, entirely
    nonsensical derivation that every check passed.

    Five members and a predecessor table below. That is the whole vocabulary this
    reference implementation walks, and closing it costs nothing a real path needs.

    DELIBERATELY NOT AN ONTOLOGY. `DerivationStep` still records only that one named thing
    stood in a named relation to another, on some system's authority, known by a moment.
    What is added is which relation may follow which -- a five-entry table -- not what any
    relation means.
    """

    HAS_COMPONENT = "HAS_COMPONENT"
    ASSIGNED_TO = "ASSIGNED_TO"
    SUPPORTS = "SUPPORTS"
    LOADS = "LOADS"
    FULFILLS = "FULFILLS"


def holds_at(
    *, valid_from: datetime | None, valid_to: datetime | None, moment: datetime
) -> bool:
    """Whether a half-open validity interval contains `moment`. Either end may be open.

    ONE IMPLEMENTATION, AND THE ARROW ALREADY POINTED THIS WAY
    ----------------------------------------------------------
    `Assignment.covers` and `Component.fitted_at` in the graph module were two hand-written
    copies of this predicate, and the portable derivation was about to become a third. The
    import boundary has to apply exactly the rule the graph applied or the two paths admit
    different worlds -- which is the whole defect this correction closes -- so a second
    copy that agreed today and drifted on the day somebody changed one end from `<` to
    `<=` would reopen it silently.

    It lives here rather than in the graph module because `context` imports `derivation`
    and not the reverse. The graph's two methods now delegate to this.
    """
    if valid_from is not None and moment < valid_from:
        return False
    return valid_to is None or moment < valid_to


_UNSCOPED_RELATIONS = (
    DerivationRelationship.LOADS,
    DerivationRelationship.FULFILLS,
)
"""The relations whose reference types carry no validity interval, so the graph can only
ever emit them with both ends open."""


_ROOTED = object()
"""Sentinel for "this relation starts at the walk's root", used in the table below."""

_MAY_CONTINUE_FROM: dict[DerivationRelationship, tuple[object, ...]] = {
    # The asset is where a walk starts, and both of these leave from it.
    DerivationRelationship.HAS_COMPONENT: (_ROOTED,),
    DerivationRelationship.ASSIGNED_TO: (_ROOTED,),
    # ...and the commercial half continues, each step from what the previous one reached.
    DerivationRelationship.SUPPORTS: (DerivationRelationship.ASSIGNED_TO,),
    DerivationRelationship.LOADS: (DerivationRelationship.SUPPORTS,),
    DerivationRelationship.FULFILLS: (DerivationRelationship.LOADS,),
}
"""Which relation may pick up where which other one left off.

Read it as the reference path: the asset has a component and is assigned to a zone, the
zone supports a loading window, the window loads a shipment, the shipment fulfils a
commitment. Reachability alone permitted any of those in any order over any entities.
"""


@dataclass(frozen=True)
class DerivationStep:
    """One relationship traversed, with the provenance needed to challenge it.

    `recorded_at` is knowledge time, not valid time: when this system learned the fact.
    It is what makes the cutoff filter checkable by a reader rather than something they
    have to take on faith, and a step recorded after the cutoff has no business in a walk
    that claims to describe what was knowable.
    """

    relationship: DerivationRelationship
    subject: str
    object: str
    recorded_at: datetime
    source_system: str
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    """When the relationship held in the world. None/None means the fact is not
    time-scoped -- a shipment fulfils a commitment, and does not stop."""

    def __post_init__(self) -> None:
        # Accepts the enum or its value, and refuses anything else BY NAME. Coercing here
        # rather than at each construction site is what makes the vocabulary closed at the
        # wire boundary too: `from_record` gets the refusal for free.
        try:
            relationship = DerivationRelationship(self.relationship)
        except ValueError as exc:
            raise ValueError(
                f"{self.relationship!r} is not a relationship this system walks; v1 "
                f"implements {[r.value for r in DerivationRelationship]}, and an open "
                f"vocabulary lets a connected walk mean anything at all"
            ) from exc
        object.__setattr__(self, "relationship", relationship)
        if not self.subject or not self.object:
            raise ValueError("a derivation step must name a relationship and both ends")
        if not self.source_system:
            raise ValueError(
                f"{self.relationship}({self.subject},{self.object}) names no source "
                f"system; a fact nobody is recorded as having asserted cannot be checked "
                f"against anything or corrected by anyone"
            )
        for label, moment in (
            ("recorded_at", self.recorded_at),
            ("valid_from", self.valid_from),
            ("valid_to", self.valid_to),
        ):
            if moment is not None and moment.tzinfo is None:
                raise ValueError(f"derivation step {label} must be timezone-aware")
        if (
            self.valid_from is not None
            and self.valid_to is not None
            and self.valid_to <= self.valid_from
        ):
            raise ValueError("a relationship valid over no interval was never true")

    def label(self) -> str:
        """The compact form the walk has always rendered. One authority for the words."""
        return f"{self.relationship.value}({self.subject},{self.object})"

    def as_record(self) -> dict[str, Any]:
        return {
            "relationship": self.relationship.value,
            "subject": self.subject,
            "object": self.object,
            "recorded_at": self.recorded_at.isoformat(),
            "source_system": self.source_system,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "DerivationStep":
        return cls(
            relationship=r["relationship"],
            subject=r["subject"],
            object=r["object"],
            recorded_at=datetime.fromisoformat(r["recorded_at"]),
            source_system=r["source_system"],
            valid_from=(
                datetime.fromisoformat(r["valid_from"]) if r.get("valid_from") else None
            ),
            valid_to=(
                datetime.fromisoformat(r["valid_to"]) if r.get("valid_to") else None
            ),
        )


@dataclass(frozen=True)
class ConsequenceDerivation:
    """The whole walk: the steps, the rules that joined them, the clock they ran under.

    Carried BY the consequence rather than beside it, because the pairing is the point.
    A path in one field and a conclusion in another can be recombined; a conclusion that
    cannot exist without its path cannot.
    """

    rule_version: str
    knowledge_cutoff: datetime
    evaluated_window: TimeInterval
    steps: tuple[DerivationStep, ...]
    ambiguities: tuple[str, ...] = ()
    late_relationships: tuple[str, ...] = ()
    """Relationships true across the window but recorded after the cutoff.

    Reported rather than used, and carried out rather than summarised: a reader looking at
    a thin conclusion deserves to know that three relevant facts existed and arrived too
    late to be used, which is a very different situation from three that never existed.
    """

    def __post_init__(self) -> None:
        if not self.rule_version:
            raise ValueError(
                "a derivation that cannot say which rules produced it compares against "
                "today's rules and reaches a confident wrong answer"
            )
        if self.knowledge_cutoff.tzinfo is None:
            raise ValueError("knowledge_cutoff must be timezone-aware")
        if not self.steps:
            raise ValueError(
                "a derivation with no steps is a conclusion with no path; that is the "
                "label this type exists to replace"
            )
        late = [s.label() for s in self.steps if s.recorded_at > self.knowledge_cutoff]
        if late:
            raise ValueError(
                f"{','.join(late)} was recorded after the cutoff "
                f"{self.knowledge_cutoff.isoformat()}; a walk cannot use a fact the "
                f"decision-maker had not received"
            )
        # HOW MANY OF EACH, which topology and temporal validity between them never asked.
        #
        # Both of those are properties of a step or of a pair of steps, so a walk could
        # satisfy every one of them TWICE. Two complete commercial branches from one zone
        # -- two loading windows, two shipments, two fulfilments -- is a connected walk of
        # correctly-ordered relations over real entities, each interval in force at every
        # moment the joins are rechecked. Nothing looked at how many there were.
        #
        # `ContextGraph.derive_impact` emits AT MOST ONE step per relationship, and does so
        # by refusing rather than by choosing: two zones at horizon start is "a data defect,
        # not a richer answer" and returns underived; two loading windows overlapping the
        # horizon is an ambiguity and returns underived. So a walk carrying two of anything
        # is a walk the producer would not have emitted, whatever consequence it is
        # attached to -- which is why this is stated here, once, rather than per type.
        #
        # Deliberately NOT a general graph framework. This counts; it does not model. The
        # question of WHICH relations a complete path must contain belongs to the
        # consequence that claims the path, and lives there.
        seen: dict[DerivationRelationship, DerivationStep] = {}
        for step in self.steps:
            first = seen.get(step.relationship)
            if first is not None:
                raise ValueError(
                    f"the walk carries {first.label()} and {step.label()}; the graph "
                    f"emits at most one {step.relationship.value} step and refuses "
                    f"outright when the facts admit two, so a derivation carrying a "
                    f"second branch is one no supported producer could have walked"
                )
            seen[step.relationship] = step
        # A walk has to GO somewhere from where it started. `entities()` is a flat set and
        # `terminal_entity` is only the last step's object, so every check that consumed
        # this path -- principal in entities, terminal is the commitment, the observed
        # subject appears -- was satisfied by steps that join to nothing. An auditor kept
        # the step naming the asset and the step naming the commitment, deleted the three
        # in between, and reached DELIVERED with `explain()` rendering `->` between links
        # with no shared end.
        #
        # Reachability rather than a single-file chain, because the real walk branches:
        # HAS_COMPONENT and ASSIGNED_TO both start at the asset. Requiring
        # `steps[i].object == steps[i+1].subject` would refuse the reference path.
        #
        # REACHABILITY WAS NOT ENOUGH, AND THE GAP IS WORTH NAMING.
        # It refuses a path with a hole in it, which is what it was added for. It says
        # nothing about whether a connected path MEANS anything: keep the real entities,
        # keep every step joined, and relabel the relations -- LOADS(asset-4417,zone-3)
        # then HAS_COMPONENT(zone-3,win-9) -- and you have a well-formed, fully connected,
        # entirely nonsensical derivation that reachability alone accepts.
        #
        # So each step must also continue from a relation `_MAY_CONTINUE_FROM` permits.
        # Five entries. The commercial half is a chain by relation as well as by entity,
        # and the two relations that leave the asset must leave the ROOT rather than
        # anywhere the walk happens to have got to.
        root = self.steps[0].subject
        reached_by: dict[str, set[object]] = {root: {_ROOTED}}
        for step in self.steps:
            arrived = reached_by.get(step.subject)
            if arrived is None:
                raise ValueError(
                    f"{step.label()} starts at {step.subject!r}, which nothing earlier in "
                    f"the walk reached; a path with a hole in it is a conclusion with a "
                    f"hole in it, and it reads as a chain to anyone who prints it"
                )
            permitted = _MAY_CONTINUE_FROM[step.relationship]
            if not arrived & set(permitted):
                expected = ", ".join(
                    "the walk's root" if p is _ROOTED else p.value  # type: ignore[union-attr]
                    for p in permitted
                )
                raise ValueError(
                    f"{step.label()} continues from "
                    f"{sorted(getattr(a, 'value', 'the walk root') for a in arrived)}, but "
                    f"{step.relationship.value} may only continue from {expected}; a "
                    f"connected walk whose relations do not follow one another is a "
                    f"sequence of true facts that justifies nothing"
                )
            reached_by.setdefault(step.object, set()).add(step.relationship)

        # THE VALIDITY INTERVALS, CHECKED AGAINST THE JOINS THE GRAPH ACTUALLY MAKES.
        #
        # `valid_from`/`valid_to` say when a relationship held in the world. For one
        # revision they crossed the wire checked against nothing, so a reader could be told
        # an assignment held across 2099. That was closed with a generic rule -- the
        # interval must overlap the evaluated window -- and the generic rule was still too
        # weak, in a way that is worth writing down because it is the whole shape of this
        # defect class.
        #
        # The graph does not check overlap. It checks MEMBERSHIP AT TWO SPECIFIC MOMENTS:
        #
        #     covers(horizon_start)  and  covers(window.opens)      for ASSIGNED_TO
        #     fitted_at(horizon_start) and fitted_at(window.opens)  for HAS_COMPONENT
        #
        # and the second of each pair exists because the consequence happens AT THE WINDOW.
        # An asset assigned when the horizon opens and reassigned away before the loading
        # window opens is not a risk to that window, and the graph says so in as many
        # words.
        #
        # So take the concrete counterexample. Evaluated window opens 12 Jun 07:00 and runs
        # to the 15th. The assignment holds 12 Jun 07:00 to 13 Jun 04:00. The loading
        # window opens 13 Jun 05:00. The assignment overlaps the evaluated window, so the
        # generic rule passed it -- while the graph refuses the consequence outright,
        # because the forklift left that zone an hour before the truck arrived. Strict
        # import admitted a derivation the release path could not have emitted, which is
        # the governing rule of this whole repository, failed.
        #
        # The loading-window opening does not need the graph to be recovered: the SUPPORTS
        # step CARRIES it, as `valid_from`. The information already crossed the wire and
        # nothing was reading it.
        #
        # This is the smallest thing that closes it. Two moments, four checks, one shape
        # rule per relation. Not an ontology -- no relation is told what it MEANS, only
        # which instants its interval has to contain, which is exactly what the reference
        # walk already guarantees.
        window_openings = tuple(
            step.valid_from
            for step in self.steps
            if step.relationship is DerivationRelationship.SUPPORTS
            and step.valid_from is not None
        )
        for step in self.steps:
            if step.relationship in _UNSCOPED_RELATIONS:
                # A shipment loads a window and fulfils a commitment; neither stops. The
                # graph emits these with both ends open because the reference types carry
                # no interval at all, so a scoped one is not a stricter claim -- it is a
                # claim about a fact the producing system has no field to hold.
                if step.valid_from is not None or step.valid_to is not None:
                    raise ValueError(
                        f"{step.label()} carries a validity interval, and "
                        f"{step.relationship.value} is not a time-scoped relation in this "
                        f"system; the record asserts a temporal fact no source could have "
                        f"supplied"
                    )
                continue

            if step.relationship is DerivationRelationship.SUPPORTS:
                # SUPPORTS *is* the loading window. Both ends are structural -- the graph
                # copies `opens` and `closes` straight off the window record -- and a
                # half-scoped one would leave the opening this walk is checked against
                # undefined, which is the check silently not running.
                if step.valid_from is None or step.valid_to is None:
                    raise ValueError(
                        f"{step.label()} is a loading window with an open end; a window "
                        f"that does not say when it opens and closes cannot be the moment "
                        f"the rest of the walk is checked against"
                    )
                if not (
                    self.evaluated_window.start < step.valid_to
                    and self.evaluated_window.end > step.valid_from
                ):
                    raise ValueError(
                        f"{step.label()} runs [{step.valid_from.isoformat()}, "
                        f"{step.valid_to.isoformat()}), which does not overlap the window "
                        f"this walk was evaluated over "
                        f"[{self.evaluated_window.start.isoformat()}, "
                        f"{self.evaluated_window.end.isoformat()}); the graph only selects "
                        f"windows overlapping the horizon"
                    )
                continue

            if (
                step.relationship is DerivationRelationship.ASSIGNED_TO
                and step.valid_from is None
            ):
                # `Assignment.valid_from` is a required field on the graph's own record,
                # so an assignment that never says when it began is a shape the producing
                # system cannot hold.
                raise ValueError(
                    f"{step.label()} does not say when the assignment began; the graph "
                    f"requires it and a walk without it cannot be checked at any moment"
                )

            for label, moment in (
                ("the evaluated window opens", self.evaluated_window.start),
                *(("the loading window opens", o) for o in window_openings),
            ):
                if not holds_at(
                    valid_from=step.valid_from, valid_to=step.valid_to, moment=moment
                ):
                    raise ValueError(
                        f"{step.label()} held ["
                        f"{step.valid_from.isoformat() if step.valid_from else '-'}, "
                        f"{step.valid_to.isoformat() if step.valid_to else '-'}) and so "
                        f"was not in force when {label} ({moment.isoformat()}); the graph "
                        f"rechecks this join at that moment and would not have emitted "
                        f"this walk"
                    )

    @property
    def root_entity(self) -> str:
        """Where the walk starts. The thing the whole derivation is about.

        `entities()` is a flat set, so "the observed asset appears in the walk" was
        satisfied by an asset mentioned anywhere -- including as the object of a step that
        arrived at it from somewhere else entirely.
        """
        return self.steps[0].subject

    @property
    def terminal_entity(self) -> str:
        """What the chain arrives at -- the thing the consequence is about."""
        return self.steps[-1].object

    def entities(self) -> frozenset[str]:
        return frozenset(
            e for s in self.steps for e in (s.subject, s.object)
        )

    def source_systems(self) -> tuple[str, ...]:
        """Every system that had to be joined, in walk order. Duplicates kept: which
        step came from where is the interesting part, not the set."""
        return tuple(s.source_system for s in self.steps)

    def explain(self) -> str:
        return " -> ".join(s.label() for s in self.steps)

    def as_record(self) -> dict[str, Any]:
        """The portable walk. `ambiguities` and `late_relationships` do NOT travel.

        Both are the producer's account of what it found and neither can be checked by a
        reader: the graph is not in the envelope, so "three relevant facts arrived after
        the cutoff" and "two candidate zones were on record" are assertions with nothing
        behind them. A strict portable record that carries them overstates what it has
        verified -- a forger can empty the late list, or invent an ambiguity, and every
        check still passes.

        Removing them is the smaller intervention. The alternative is carrying the graph,
        which is the ontology platform this project declines to build, to verify two
        fields no decision reads.

        They remain on the in-memory type, where the walk that produced them is the
        authority and a caller can act on them at the moment they are derived. What
        changes is that they are no longer asserted to a reader who cannot check them.
        """
        return {
            "rule_version": self.rule_version,
            "knowledge_cutoff": self.knowledge_cutoff.isoformat(),
            "evaluated_window_start": self.evaluated_window.start.isoformat(),
            "evaluated_window_end": self.evaluated_window.end.isoformat(),
            "steps": [s.as_record() for s in self.steps],
        }

    @classmethod
    def from_record(cls, r: dict[str, Any]) -> "ConsequenceDerivation":
        return cls(
            rule_version=r["rule_version"],
            knowledge_cutoff=datetime.fromisoformat(r["knowledge_cutoff"]),
            evaluated_window=TimeInterval(
                datetime.fromisoformat(r["evaluated_window_start"]),
                datetime.fromisoformat(r["evaluated_window_end"]),
            ),
            steps=tuple(DerivationStep.from_record(s) for s in r["steps"]),
        )
