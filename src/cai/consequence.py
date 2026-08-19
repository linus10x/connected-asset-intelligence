"""What a prediction actually costs, as a typed consequence rather than a label.

THE DURABLE PRINCIPLE
---------------------
    No actionable, defensible business consequence -> no intelligence product.

Note what that is not. An earlier framing said "no customer commitment -> no product",
which reads as though the only consequence worth selling is a delivery promise. A machine
that will be down during the only maintenance window this month is consequential without a
single customer commitment attached.

WHY ONLY TWO TYPES
------------------
It is easy to write nine consequence classes and ship none of them. A reader who sees
SAFETY and COMPLIANCE in an enum will reasonably ask where the implementations and tests
are, and the honest answer would have been "there are none".

So two are implemented and exercised: `CustomerCommitmentConsequence` carries the hero, and
`DowntimeConsequence` exists to prove the abstraction is not shaped around the hero. The
rest -- COST, SAFETY, SLA, REVENUE, COMPLIANCE, CAPACITY, SERVICE_QUALITY -- are named in
the design document as extension points, which is what they are.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from .decision import TimeInterval
from .derivation import ConsequenceDerivation, DerivationRelationship


@dataclass(frozen=True)
class BusinessConsequence(ABC):
    """A named, defensible cost of the predicted event, and why it follows.

    Subclasses supply the vocabulary of their own domain. What every one must supply is a
    sentence an operator can act on, an interval the consequence falls in -- because a
    consequence with no window cannot be compared against a prediction that has one -- and
    the derivation that reached it.

    WHY THE PATH IS A FIELD AND NOT AN ARGUMENT SOMEWHERE ELSE
    ----------------------------------------------------------
    The graph walk produced a full provenance trail and the consequence was built from its
    answer, so the portable product carried the conclusion and not the reasoning. Holding
    the two in separate places lets them be recombined; a conclusion that cannot be
    constructed without its own path cannot be paired with somebody else's.
    """

    consequence_type: str
    exposure_window: TimeInterval
    derivation: ConsequenceDerivation

    def __post_init__(self) -> None:
        self._check_derivation()

    def _check_derivation(self) -> None:
        """The path must be a path, and it must be the path to THIS conclusion.

        Called from the base and re-called by every subclass, because a dataclass
        subclass defining `__post_init__` replaces its parent's rather than extending it,
        and a validation that silently stops running in subclasses is worse than one that
        was never written.
        """
        if not isinstance(self.derivation, ConsequenceDerivation):
            raise TypeError(
                f"derivation must be a ConsequenceDerivation, not "
                f"{type(self.derivation).__name__}; a consequence with no walk behind it "
                f"is the hand-authored business context this model already refused"
            )
        principal = self._principal_entity()
        if principal not in self.derivation.entities():
            raise ValueError(
                f"the derivation walks {self.derivation.explain()} and never reaches "
                f"{principal!r}; this is a real path attached to somebody else's "
                f"conclusion"
            )

    @abstractmethod
    def _principal_entity(self) -> str:
        """The thing this consequence is ABOUT, which the walk must have reached.

        Abstract so a new consequence type cannot be added without stating what its path
        has to arrive at -- which is the check that stops a path-shaped field from
        becoming decorative.
        """

    @abstractmethod
    def describe(self) -> str:
        """One line, rendered for a human. Never author-supplied."""

    @abstractmethod
    def is_actionable(self) -> bool:
        """Whether anything can still be done about it."""

    def _detail(self) -> dict[str, str]:
        """Subclass specifics, as strings so the record canonicalises."""
        return {}

    def as_record(self) -> dict[str, object]:
        return {
            "consequence_type": self.consequence_type,
            "exposure_window_start": self.exposure_window.start.isoformat(),
            "exposure_window_end": self.exposure_window.end.isoformat(),
            "description": self.describe(),
            "actionable": self.is_actionable(),
            "detail": self._detail(),
            "derivation": self.derivation.as_record(),
        }

    @staticmethod
    def from_record(r: dict[str, object]) -> "BusinessConsequence":
        """Dispatch on the declared type. Exactly two are implemented in v1.

        An unknown type is refused rather than degraded to a base consequence: the base is
        abstract precisely so that no consequence can exist without saying what it is, and
        silently widening the vocabulary on import would reintroduce that hole from the
        wire side.
        """
        window = TimeInterval(
            datetime.fromisoformat(str(r["exposure_window_start"])),
            datetime.fromisoformat(str(r["exposure_window_end"])),
        )
        detail = dict(r.get("detail") or {})  # type: ignore[arg-type]
        path = ConsequenceDerivation.from_record(r["derivation"])  # type: ignore[arg-type]
        kind = r["consequence_type"]
        rebuilt: BusinessConsequence
        if kind == "CUSTOMER_COMMITMENT":
            rebuilt = CustomerCommitmentConsequence(
                "CUSTOMER_COMMITMENT", window, path,
                commitment_id=str(detail["commitment_id"]),
                commitment_description=str(detail["commitment_description"]),
                counterparty=str(detail["counterparty"]),
            )
        elif kind == "DOWNTIME":
            rebuilt = DowntimeConsequence(
                "DOWNTIME", window, path,
                asset_id=str(detail["asset_id"]),
                expected_hours_lost=float(detail["expected_hours_lost"]),
                affected_operation=str(detail["affected_operation"]),
            )
        else:
            raise ValueError(
                f"{kind!r} is not a consequence type this system implements; v1 has "
                f"exactly two, and importing an unknown one would invent an ontology the "
                f"code cannot honour"
            )
        # `description` and `actionable` are DERIVED on the way out. Reading them back
        # would make the exported sentence an input; re-deriving them and silently
        # discarding what the payload said is the other half of the mistake, because the
        # bundle then imports as something other than the bytes it arrived as.
        for key, value in (
            ("description", rebuilt.describe()),
            ("actionable", rebuilt.is_actionable()),
        ):
            if key in r and r[key] != value:
                raise ValueError(
                    f"the consequence record's {key} is {r[key]!r} but the value derived "
                    f"from what it carries is {value!r}; a derived value free to disagree "
                    f"with its source is a second authority"
                )
        return rebuilt



@dataclass(frozen=True)
class CustomerCommitmentConsequence(BusinessConsequence):
    """A promise to a customer is exposed. The hero case."""

    commitment_id: str = ""
    commitment_description: str = ""
    counterparty: str = ""

    def __post_init__(self) -> None:
        if not self.commitment_id:
            raise ValueError("a commitment consequence must name the commitment")
        self._check_derivation()

    def _principal_entity(self) -> str:
        """The commitment the walk has to have reached. Not merely mentioned: the walk
        ends at FULFILLS, and this is what it ends at."""
        return self.commitment_id

    def _check_derivation(self) -> None:
        super()._check_derivation()
        if self.derivation.terminal_entity != self.commitment_id:
            raise ValueError(
                f"the derivation terminates at "
                f"{self.derivation.terminal_entity!r} but the consequence is about "
                f"{self.commitment_id!r}; the path does not arrive at this conclusion"
            )
        # THE WHOLE COMMERCIAL CHAIN, not merely a path whose last object is the right id.
        #
        # `terminal_entity == commitment_id` is satisfied by any walk that happens to end
        # at the commitment -- including a two-step ASSIGNED_TO(asset, commit-7), which is
        # nonsense the relation-continuation rules do not catch because ASSIGNED_TO may
        # leave the root and nothing said where it must arrive.
        #
        # These four are what makes a commitment consequence a commitment consequence.
        # SUPPORTS names the loading window the exposure falls in, LOADS names the
        # shipment, FULFILLS names the promise. Without all three, nothing in the record
        # establishes WHICH promise is exposed or why -- and `ContextGraph` returns
        # `derived=False` at exactly the step it cannot complete, so a partial walk is
        # never one it labelled a commitment.
        #
        # HAS_COMPONENT IS ABSENT FROM THIS LIST ON PURPOSE. `derive_impact` takes
        # `component_id: str | None = None` and emits the step only when one was supplied,
        # so a claim about a whole machine produces a legitimate four-step walk. Requiring
        # it would refuse a record the reference producer emits, which is the same defect
        # as accepting one it cannot -- pointing the other way.
        #
        # `ConsequenceDerivation` has already established at most one of each, so "present"
        # here means exactly one.
        present = {step.relationship for step in self.derivation.steps}
        required = (
            DerivationRelationship.ASSIGNED_TO,
            DerivationRelationship.SUPPORTS,
            DerivationRelationship.LOADS,
            DerivationRelationship.FULFILLS,
        )
        absent = [r.value for r in required if r not in present]
        if absent:
            raise ValueError(
                f"the commercial walk to {self.commitment_id!r} is missing "
                f"{', '.join(absent)}; a commitment consequence is derived by placing the "
                f"asset in a zone, that zone under a loading window, that window against a "
                f"shipment and that shipment against the promise, and a path with a link "
                f"missing does not establish which promise is exposed"
            )

    def describe(self) -> str:
        return (
            f"at risk: {self.commitment_description} ({self.counterparty})"
            if self.counterparty
            else f"at risk: {self.commitment_description}"
        )

    def is_actionable(self) -> bool:
        # A commitment already past its window cannot be protected, only reported.
        return True

    def _detail(self) -> dict[str, str]:
        return {
            "commitment_id": self.commitment_id,
            "commitment_description": self.commitment_description,
            "counterparty": self.counterparty,
        }


@dataclass(frozen=True)
class DowntimeConsequence(BusinessConsequence):
    """Capacity is lost, with or without a customer promise attached.

    Present specifically so the abstraction is exercised by something that is NOT the hero.
    A consequence model with one implementation is a class with extra steps.
    """

    asset_id: str = ""
    expected_hours_lost: float = 0.0
    affected_operation: str = ""

    def __post_init__(self) -> None:
        if self.expected_hours_lost < 0:
            raise ValueError("expected_hours_lost cannot be negative")
        # Written at two decimals and described with `:g`, so any value carrying more
        # precision than the wire form delivered honestly and then failed its own round
        # trip: the description says "3.456h" and the value re-derived from what the
        # record carries says "3.46h". Same class as the identity confidence and the
        # prediction inputs -- refused where the producer can still quantize it.
        if float(f"{self.expected_hours_lost:.2f}") != self.expected_hours_lost:
            raise ValueError(
                f"expected_hours_lost {self.expected_hours_lost!r} carries more precision "
                f"than the two-decimal wire form preserves, so this record would not "
                f"survive its own round trip; quantize it before it enters the consequence"
            )
        self._check_derivation()

    def _principal_entity(self) -> str:
        """Downtime is about the asset, and the walk must have established where that
        asset was and what it was serving. It does not need to reach a commitment --
        that is the whole reason this second type exists."""
        return self.asset_id

    def _check_derivation(self) -> None:
        super()._check_derivation()
        # ITS OWN BOUNDED SEMANTICS, stated rather than inherited by accident.
        #
        # `CustomerCommitmentConsequence` requires the walk to TERMINATE at the
        # commitment, which is a strong statement about where the path ends. Downtime has
        # no terminus to require -- it is about capacity lost on an asset, and the walk
        # may legitimately stop at the zone -- so the base check ("the asset is somewhere
        # in the entity set") was the only thing holding it, and a flat set is satisfied
        # by an asset the walk merely passes through.
        #
        # The rooted equivalent is the right shape: downtime on an asset is derived from a
        # walk that STARTS at that asset. It says where the path begins instead of where
        # it ends, which is the honest difference between the two consequence types.
        if self.derivation.root_entity != self.asset_id:
            raise ValueError(
                f"the derivation is rooted at {self.derivation.root_entity!r} but this "
                f"downtime is about {self.asset_id!r}; a walk that merely passes through "
                f"an asset does not establish what that asset's unavailability costs"
            )

    def describe(self) -> str:
        return (
            f"at risk: {self.expected_hours_lost:g}h of {self.affected_operation} "
            f"capacity on {self.asset_id}"
        )

    def is_actionable(self) -> bool:
        # Below a shift's worth, this is noise an operator should not be interrupted for.
        return self.expected_hours_lost >= 1.0

    def _detail(self) -> dict[str, str]:
        return {
            "asset_id": self.asset_id,
            "expected_hours_lost": f"{self.expected_hours_lost:.2f}",
            "affected_operation": self.affected_operation,
        }
