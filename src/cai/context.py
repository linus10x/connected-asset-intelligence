"""Business-context derivation over a deliberately tiny ontology.

WHY SO SMALL
------------
Six concepts and five relationships. That is not a placeholder for a larger model; it
is the whole thing. Enterprise ontology platforms exist and are good, and building a
weaker one here would demonstrate nothing.

What a small graph *can* demonstrate is the part usually skipped: that "business
context" is a derivation with a provenance trail, not a label somebody attached to a
prediction. One transparent join path, every fact named, every temporal assumption
explicit.

THE CONCEPTS
    Asset · Component · Zone · LoadingWindow · Shipment · CustomerCommitment

THE RELATIONSHIPS
    Asset             HAS_COMPONENT  Component
    Asset             ASSIGNED_TO    Zone during [valid_from, valid_to)
    Zone              SUPPORTS       LoadingWindow
    LoadingWindow     LOADS          Shipment
    Shipment          FULFILLS       CustomerCommitment

THE ONE DERIVED RESULT
    A predicted failure horizon overlaps a loading window whose shipment fulfils a
    customer commitment.

WHY THE ASSIGNMENT IS TEMPORAL
------------------------------
`ASSIGNED_TO` carries a validity interval because asset-to-zone binding changes
constantly -- equipment moves between bays hourly. A derivation that ignores this
happily reports that a forklift will disrupt a loading window it was reassigned away
from a week earlier. That is not a hypothetical failure; it is the normal outcome of
joining on a relationship without asking when it was true.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .decision import TimeInterval
from .derivation import (
    ConsequenceDerivation,
    DerivationRelationship,
    DerivationStep,
    holds_at,
)

RULE_VERSION = "context-rules@0.8.0"


@dataclass(frozen=True)
class Assignment:
    """Asset assigned to a zone, valid over a half-open interval, known from a moment.

    Two clocks, for the same reason observations carry two. `valid_from`/`valid_to` say
    when the assignment was true in the yard. `recorded_at` says when this system first
    learned of it -- and reassignments are entered late constantly, because somebody
    moves a machine at 06:00 and the system finds out when a shift supervisor updates a
    sheet that afternoon.

    Without `recorded_at`, a relationship backdated after a decision is indistinguishable
    from one known at the time, and the reconstruction inherits knowledge the
    decision-maker did not have. The observation layer got this right from the start;
    for one revision the relationship layer did not, which made the bitemporal claim only
    half true.

    `recorded_at` is required, not defaulted. A default would let a caller keep the old
    half-bitemporal behaviour silently, which is the failure this field exists to remove.
    """

    asset_id: str
    zone_id: str
    valid_from: datetime
    recorded_at: datetime
    source_system: str = ""
    """Which system asserted this fact.

    The premise of the whole scenario is that these facts live in different systems, and
    a derivation that cannot say which one asserted a link leaves a reader unable to go
    and challenge it. Required in practice -- `DerivationStep` refuses an unsourced
    fact -- and defaulted here only so the field can be added without reordering the
    positional signature every construction site uses.
    """

    valid_to: datetime | None = None
    """None means still in force. Half-open: valid_to is exclusive."""

    def covers(self, moment: datetime) -> bool:
        """True in the world at `moment` -- says nothing about whether it was known.

        Delegates so the portable derivation, which must refuse exactly what this admits,
        cannot be checking a second hand-written copy of the same half-open rule.
        """
        return holds_at(
            valid_from=self.valid_from, valid_to=self.valid_to, moment=moment
        )

    def was_known_at(self, transaction_time: datetime) -> bool:
        """Whether this system had this relationship on record by `transaction_time`."""
        return self.recorded_at <= transaction_time


def known_at(fact: object, transaction_time: datetime) -> bool:
    """Whether this system had a fact on record by a given moment.

    Every fact the derivation walks needs this, not only the zone assignment. A loading
    schedule entered on day 14 cannot justify a day-12 conclusion any more than a zone
    reassignment can -- and for one revision only `ASSIGNED_TO` was filtered, so the
    commercial half of the walk quietly used whatever the graph knew today.
    """
    return fact.recorded_at <= transaction_time


@dataclass(frozen=True)
class Component:
    """A serviceable part of an asset -- the thing that actually degrades.

    The module claimed `Asset HAS_COMPONENT Component` for several revisions without
    modelling it, and the test that called itself a full walk of five relationships
    traversed four. That gap was not cosmetic: a claim about a battery pack was bound to
    the forklift and not to the pack, so the record could not distinguish a prediction
    about the battery from one about the hydraulics on the same machine. Two components
    on one asset fail differently, get serviced by different people, and carry different
    lead times.
    """

    component_id: str
    asset_id: str
    kind: str
    recorded_at: datetime
    source_system: str = ""
    installed_from: datetime | None = None
    removed_at: datetime | None = None
    """Components are swapped. A pack fitted after the decision was not the pack that
    produced the readings, and a pack removed before it cannot be what failed."""

    def fitted_at(self, moment: datetime) -> bool:
        """Whether the part was on the machine at `moment`. Same predicate as `covers`."""
        return holds_at(
            valid_from=self.installed_from, valid_to=self.removed_at, moment=moment
        )


@dataclass(frozen=True)
class LoadingWindow:
    window_id: str
    zone_id: str
    opens: datetime
    closes: datetime
    shipment_id: str
    recorded_at: datetime
    source_system: str = ""

    def overlaps(self, start: datetime, end: datetime) -> bool:
        return start < self.closes and end > self.opens


@dataclass(frozen=True)
class Shipment:
    shipment_id: str
    commitment_id: str
    recorded_at: datetime
    source_system: str = ""


@dataclass(frozen=True)
class CustomerCommitment:
    commitment_id: str
    description: str
    recorded_at: datetime
    source_system: str = ""


@dataclass(frozen=True)
class BusinessImpact:
    """A derived conclusion, carrying everything needed to check it.

    `missing_links` is as important as the conclusion. A derivation that silently
    returns nothing when a relationship is absent is indistinguishable from one that
    correctly found no impact, and the two demand opposite responses.
    """

    derived: bool
    commitment: CustomerCommitment | None
    steps: tuple[DerivationStep, ...]
    """The walk, as typed steps rather than rendered strings.

    `source_facts` used to be the storage AND the rendering, which meant the only durable
    record of the derivation was a tuple of labels: no source system, no knowledge time,
    no validity interval, nothing a reader could challenge. The strings are still
    available, derived from these.
    """

    rule_version: str
    prediction_horizon: tuple[datetime, datetime]
    transaction_time_cutoff: datetime
    missing_links: tuple[str, ...] = ()
    ambiguities: tuple[str, ...] = ()
    late_relationships: tuple[str, ...] = ()
    """Relationships that were true across the horizon but recorded after the cutoff.

    Reported rather than used. Their presence is the visible proof that the cutoff
    filters something -- a derivation that never names one is indistinguishable from a
    derivation that ignores transaction time entirely.
    """

    @property
    def source_facts(self) -> tuple[str, ...]:
        """The walk as labels. Derived from the steps, so the two cannot disagree."""
        return tuple(s.label() for s in self.steps)

    def derivation(self) -> ConsequenceDerivation:
        """The portable path a consequence must carry to justify itself.

        This is the object that used to be discarded. Everything the walk established --
        which facts, whose systems, known by when, under which rules, over which window --
        travels with the conclusion instead of dying inside this function.
        """
        return ConsequenceDerivation(
            rule_version=self.rule_version,
            knowledge_cutoff=self.transaction_time_cutoff,
            evaluated_window=TimeInterval(*self.prediction_horizon),
            steps=self.steps,
            ambiguities=self.ambiguities,
            late_relationships=self.late_relationships,
        )

    def blocking_reasons(self) -> tuple[str, ...]:
        """Why no impact was derived. Empty exactly when `derived` is True."""
        return tuple(self.missing_links) + tuple(self.ambiguities)

    # RESTORED on a Control Tower ruling. Deleted as dead code on the authority of §12(D),
    # which was scoped to the removable-guard reconciliation rather than to importable
    # methods. Zero call sites inside this repository does not establish that a name is
    # outside the package contract; there is no `__init__.py` declaring a surface.
    #
    # Untested rather than dead, so now tested.

    def business_context_text(self) -> str:
        """The context as a sentence, built from the walk -- never author-supplied.

        This exists so the release path cannot accept a hand-written context string.
        Rendering from `source_facts` means the prose and the derivation cannot drift:
        there is only one place the words can come from.
        """
        if not self.derived:
            reasons = "; ".join(self.blocking_reasons()) or "no derivation performed"
            return f"no business context derived ({reasons})"
        return "derived via " + " -> ".join(self.source_facts)

    def economic_consequence_text(self) -> str:
        """The consequence as a sentence, taken from the commitment actually reached."""
        if not self.derived or self.commitment is None:
            return "no customer commitment reached by derivation"
        return f"at risk: {self.commitment.description}"

    def as_record(self) -> dict[str, object]:
        return {
            "derived": self.derived,
            "commitment": self.commitment.description if self.commitment else None,
            "source_facts": list(self.source_facts),
            "rule_version": self.rule_version,
            "horizon": [t.isoformat() for t in self.prediction_horizon],
            "transaction_time_cutoff": self.transaction_time_cutoff.isoformat(),
            "missing_links": list(self.missing_links),
            "ambiguities": list(self.ambiguities),
            "late_relationships": list(self.late_relationships),
        }


@dataclass
class ContextGraph:
    components: dict[str, Component] = field(default_factory=dict)
    assignments: list[Assignment] = field(default_factory=list)
    windows: list[LoadingWindow] = field(default_factory=list)
    shipments: dict[str, Shipment] = field(default_factory=dict)
    commitments: dict[str, CustomerCommitment] = field(default_factory=dict)

    def derive_impact(
        self,
        *,
        asset_id: str,
        component_id: str | None = None,
        horizon_start: datetime,
        horizon_end: datetime,
        transaction_time_cutoff: datetime,
    ) -> BusinessImpact:
        """Walk the five relationships, naming every fact and every gap.

        `transaction_time_cutoff` *filters* the relationship layer, it does not merely
        annotate the result. An assignment entered into the system after the cutoff was
        not available to a decision made at the cutoff, however true it later proved to
        be, and joining on it produces a reconstruction that knows more than the
        decision-maker did.

        Relationships true across the horizon but recorded too late are reported in
        `late_relationships` rather than discarded silently -- the same treatment the
        observation layer gives a late reading.
        """
        steps: list[DerivationStep] = []
        missing: list[str] = []
        ambiguities: list[str] = []
        late: list[str] = []
        horizon = (horizon_start, horizon_end)

        def result(derived: bool, commitment: CustomerCommitment | None) -> BusinessImpact:
            return BusinessImpact(
                derived=derived,
                commitment=commitment,
                steps=tuple(steps),
                rule_version=RULE_VERSION,
                prediction_horizon=horizon,
                transaction_time_cutoff=transaction_time_cutoff,
                missing_links=tuple(missing),
                ambiguities=tuple(ambiguities),
                late_relationships=tuple(late),
            )

        # 1. HAS_COMPONENT -- bind the claim to the part that degrades, not the machine.
        if component_id is not None:
            component = self.components.get(component_id)
            if component is None:
                missing.append(f"no component record for {component_id}")
                return result(False, None)
            if not known_at(component, transaction_time_cutoff):
                late.append(
                    f"HAS_COMPONENT({asset_id},{component_id}) recorded "
                    f"{component.recorded_at.isoformat()}, after cutoff"
                )
                missing.append(f"component {component_id} not known at cutoff")
                return result(False, None)
            if not component.fitted_at(horizon_start):
                missing.append(
                    f"component {component_id} not fitted to {asset_id} at horizon start"
                )
                return result(False, None)
            if component.asset_id != asset_id:
                ambiguities.append(
                    f"component {component_id} belongs to {component.asset_id}, "
                    f"not {asset_id}"
                )
                return result(False, None)
            steps.append(DerivationStep(
                relationship=DerivationRelationship.HAS_COMPONENT,
                subject=asset_id,
                object=component_id,
                recorded_at=component.recorded_at,
                source_system=component.source_system,
                valid_from=component.installed_from,
                valid_to=component.removed_at,
            ))

        # 2. ASSIGNED_TO, valid across the horizon start AND on record by the cutoff.
        covering = [
            a for a in self.assignments
            if a.asset_id == asset_id and a.covers(horizon_start)
        ]
        live = [a for a in covering if a.was_known_at(transaction_time_cutoff)]
        for a in covering:
            if not a.was_known_at(transaction_time_cutoff):
                late.append(
                    f"ASSIGNED_TO({a.asset_id},{a.zone_id}) recorded "
                    f"{a.recorded_at.isoformat()}, after cutoff "
                    f"{transaction_time_cutoff.isoformat()}"
                )
        if not live:
            # Distinguish "never assigned" from "assigned, but we did not know yet".
            # They read the same in a log and demand opposite responses: one is a data
            # gap, the other is a reporting lag somebody can go and shorten.
            if covering:
                missing.append(
                    f"no zone assignment for {asset_id} known at cutoff "
                    f"({len(covering)} recorded later)"
                )
            else:
                missing.append(f"no zone assignment for {asset_id} valid at horizon start")
            return result(False, None)
        if len({a.zone_id for a in live}) > 1:
            # Two zones at once is a data defect, not a richer answer.
            ambiguities.append(
                f"{asset_id} assigned to multiple zones at horizon start: "
                + ",".join(sorted(a.zone_id for a in live))
            )
            return result(False, None)

        assignment = live[0]
        zone_id = assignment.zone_id
        steps.append(DerivationStep(
            relationship=DerivationRelationship.ASSIGNED_TO,
            subject=asset_id,
            object=zone_id,
            recorded_at=assignment.recorded_at,
            source_system=assignment.source_system,
            valid_from=assignment.valid_from,
            valid_to=assignment.valid_to,
        ))

        # 3. SUPPORTS -- windows in that zone overlapping the horizon.
        covering_windows = [
            w for w in self.windows
            if w.zone_id == zone_id and w.overlaps(horizon_start, horizon_end)
        ]
        overlapping = [w for w in covering_windows if known_at(w, transaction_time_cutoff)]
        for w in covering_windows:
            if not known_at(w, transaction_time_cutoff):
                late.append(
                    f"SUPPORTS({zone_id},{w.window_id}) recorded "
                    f"{w.recorded_at.isoformat()}, after cutoff"
                )
        if not overlapping:
            if covering_windows:
                missing.append(
                    f"no loading window in {zone_id} known at cutoff "
                    f"({len(covering_windows)} recorded later)"
                )
            else:
                missing.append(f"no loading window in {zone_id} overlapping the horizon")
            return result(False, None)
        if len(overlapping) > 1:
            # The same defect class as two zones at once, and previously resolved by list
            # order -- which meant the economic consequence depended on insertion order.
            ambiguities.append(
                f"{len(overlapping)} loading windows in {zone_id} overlap the horizon: "
                + ",".join(sorted(w.window_id for w in overlapping))
            )
            return result(False, None)
        window = overlapping[0]

        # The consequence happens at the window, not when the claim was issued. An asset
        # assigned at horizon start and reassigned before the window opens is not a risk
        # to that window, and saying otherwise is the same hindsight error in the other
        # direction. Re-check the bindings across the interval that actually matters.
        if not any(
            a.zone_id == zone_id and a.covers(window.opens)
            and a.was_known_at(transaction_time_cutoff)
            for a in self.assignments
            if a.asset_id == asset_id
        ):
            missing.append(
                f"{asset_id} is not assigned to {zone_id} when {window.window_id} opens "
                f"({window.opens.isoformat()})"
            )
            return result(False, None)
        if component_id is not None:
            part = self.components[component_id]
            if not part.fitted_at(window.opens):
                missing.append(
                    f"component {component_id} is not fitted when {window.window_id} "
                    f"opens ({window.opens.isoformat()})"
                )
                return result(False, None)

        steps.append(DerivationStep(
            relationship=DerivationRelationship.SUPPORTS,
            subject=zone_id,
            object=window.window_id,
            recorded_at=window.recorded_at,
            source_system=window.source_system,
            valid_from=window.opens,
            valid_to=window.closes,
        ))

        # 4. LOADS
        shipment = self.shipments.get(window.shipment_id)
        if shipment is None:
            missing.append(f"no shipment record for {window.shipment_id}")
            return result(False, None)
        if not known_at(shipment, transaction_time_cutoff):
            late.append(
                f"LOADS({window.window_id},{shipment.shipment_id}) recorded "
                f"{shipment.recorded_at.isoformat()}, after cutoff"
            )
            missing.append(f"shipment {shipment.shipment_id} not known at cutoff")
            return result(False, None)
        steps.append(DerivationStep(
            relationship=DerivationRelationship.LOADS,
            subject=window.window_id,
            object=shipment.shipment_id,
            recorded_at=shipment.recorded_at,
            source_system=shipment.source_system,
        ))

        # 5. FULFILLS
        commitment = self.commitments.get(shipment.commitment_id)
        if commitment is None:
            missing.append(f"no commitment record for {shipment.commitment_id}")
            return result(False, None)
        if not known_at(commitment, transaction_time_cutoff):
            late.append(
                f"FULFILLS({shipment.shipment_id},{commitment.commitment_id}) recorded "
                f"{commitment.recorded_at.isoformat()}, after cutoff"
            )
            missing.append(f"commitment {commitment.commitment_id} not known at cutoff")
            return result(False, None)
        steps.append(DerivationStep(
            relationship=DerivationRelationship.FULFILLS,
            subject=shipment.shipment_id,
            object=commitment.commitment_id,
            recorded_at=commitment.recorded_at,
            source_system=commitment.source_system,
        ))

        return result(True, commitment)
