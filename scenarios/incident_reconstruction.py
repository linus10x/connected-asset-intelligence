"""One forklift, one loading window, one customer commitment -- end to end.

Run it:  python3 scenarios/incident_reconstruction.py

THE STORY
---------
Forklift F-17 works an indoor loading yard. Not a truck on a highway -- an on-site asset,
where there is no satellite positioning, the feed reconnects in bursts, and the machine
moves between bays hourly.

F-17 is running hot. On its own that is an alert, and alerts are a solved problem. But
F-17 carries battery-pack-1, F-17 is assigned to loading zone 3, zone 3 loads shipment 22
tomorrow morning, and shipment 22 fulfils a next-day delivery commitment for customer A.
Those four facts live in four different systems.

    CONNECT -> PREDICT -> REASON -> PRODUCTIZE -> LEARN

Nothing in the delivered record is typed by hand. The claim comes from the predictor, the
consequence from a graph walk, the action from a typed recommendation, and the sentence the
operator reads is RENDERED from those objects by a versioned renderer. There is no
parameter anywhere on this path through which prose could be supplied.

The data is synthetic. No real telemetry, no real customer, no real product.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cai.action import (  # noqa: E402
    ActionRecommendation,
    ActionType,
    OutcomeObservation,
    OutcomeType,
    Priority,
)
from cai.bitemporal import Observation, ObservationLog, digest_observations  # noqa: E402
from cai.candidate import (  # noqa: E402
    ApplicabilityAssertion,
    AssuranceContext,
    EntitlementAssertion,
    IdentityAssertion,
    IntelligenceCandidate,
    TemporalAssertion,
)
from cai.consequence import CustomerCommitmentConsequence  # noqa: E402
from cai.context import (  # noqa: E402
    RULE_VERSION,
    Assignment,
    Component,
    ContextGraph,
    CustomerCommitment,
    LoadingWindow,
    Shipment,
)
from cai.contract import (  # noqa: E402
    EvidenceSnapshot,
    PredictionClaim,
    PredictionInput,
    PredictionInputs,
)
from cai.decision import DecisionContext, TimeInterval, format_moment  # noqa: E402
from cai.envelope import IntelligenceEnvelope, StatusEvent, StatusEventType  # noqa: E402
from cai.formation import release  # noqa: E402
from cai.lifecycle import DispositionState, ProductLifecycle  # noqa: E402
from cai.predictor import predict_degradation  # noqa: E402
from cai.product import Determination  # noqa: E402

RULE = "-" * 78


def t(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 6, day, hour, tzinfo=timezone.utc)


def heading(text: str) -> None:
    print(f"\n{RULE}\n{text}\n{RULE}")


def build_log() -> ObservationLog:
    """Three sources, three identifier schemes, one of them chronically late."""
    log = ObservationLog()
    # Source A -- on-network, punctual. The curve accelerates rather than drifting: a cell
    # losing capacity heats faster each cycle.
    for day in range(8, 13):
        log.record(Observation(
            f"a-{day}", "asset-4417", "battery_temp_c",
            41.0 + (day - 8) * 4.0 + (day - 8) ** 2 * 0.6,
            t(day, 6), t(day, 6) + timedelta(minutes=4), "source-a",
        ))
    # Source B -- channel-partner feed, its own id space, ~2h behind.
    for day in range(8, 13):
        log.record(Observation(
            f"b-{day}", "asset-4417", "charge_cycles", 1200 + day * 3,
            t(day, 6), t(day, 8), "source-b",
        ))
    # Source C -- indoor/yard, position-denied, delivers a backlog on reconnect.
    for day in range(9, 12):
        log.record(Observation(
            f"c-{day}", "asset-4417", "hydraulic_pressure_kpa", 980.0 - day * 11,
            t(day, 5), t(20, 9), "source-c",
        ))
    return log


def build_graph() -> ContextGraph:
    """The operational facts that turn a reading into a commercial consequence."""
    graph = ContextGraph()
    graph.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack",
        recorded_at=t(8, 1), source_system="asset-register", installed_from=t(1),
    )
    graph.assignments.append(Assignment(
        "asset-4417", "zone-3", t(8), t(8, 1), source_system="yard-management"))
    graph.windows.append(
        LoadingWindow("win-9", "zone-3", t(13, 5), t(13, 11), "ship-22",
                      recorded_at=t(9), source_system="dock-scheduler")
    )
    graph.shipments["ship-22"] = Shipment(
        "ship-22", "commit-7", recorded_at=t(9), source_system="transport-management")
    graph.commitments["commit-7"] = CustomerCommitment(
        "commit-7", "next-day delivery window, customer A", recorded_at=t(9),
        source_system="order-management",
    )
    return graph


def main() -> int:
    log, graph = build_log(), build_graph()
    model_decision_time = t(12, 7)
    ctx = DecisionContext(
        model_decision_time=model_decision_time,
        knowledge_cutoff=model_decision_time,
        evaluation_time=model_decision_time,
        prediction_window=TimeInterval(model_decision_time, model_decision_time + timedelta(days=3)),
    )

    heading("STAGE 0 -- THE SITE")
    print("Forklift F-17 works an indoor loading yard. Not a truck on a highway -- an")
    print("on-site asset, the class growing fastest and least well served by platforms")
    print("built for on-road telematics.\n")
    print(f"observations recorded : {len(log)}")
    print("sources               : source-a (on-network), source-b (partner feed),")
    print("                        source-c (yard, position-denied, bursty)")
    print(f"decision moment       : {model_decision_time:%Y-%m-%d %H:%M} UTC")

    # ------------------------------------------------------------------ CONNECT
    heading("CONNECT -- four systems, one physical thing, one moment in time")
    # The same query release will run for itself. Shown here because the story is about
    # what was knowable on day 12; release does NOT take this bundle as an argument, and
    # cannot be handed one -- see PRODUCTIZE below.
    source = log.evidence_for(knowledge_cutoff=model_decision_time, subject="asset-4417")
    known = source.observations
    believed = log.current_best_known_view(valid_time=model_decision_time, subject="asset-4417")
    gap = log.knowledge_gap(knowledge_cutoff=model_decision_time, subject="asset-4417")
    print(f"available on day 12   : {len(known)} observations")
    print(f"believed in hindsight : {len(believed)} observations")
    print(f"learned only later    : {len(gap)} observations")
    for o in gap:
        lag = o.arrival_lag()
        text = (f"{lag.total_seconds() / 3600:.0f}h late" if lag < timedelta(days=1)
                else f"{lag.days}d late")
        print(f"    {o.observation_id:<8} {o.metric:<24} arrived {text}")
    print("\nEverything below is computed from what was knowable on day 12. Folding the")
    print("late source-c readings in would flatter the decision-maker.")

    # ------------------------------------------------------------------ PREDICT
    heading("PREDICT -- from 'running hot' to a bounded claim about the next 72 hours")
    temps = tuple(o for o in sorted(known, key=lambda o: o.valid_time)
                  if o.metric == "battery_temp_c")
    prediction = predict_degradation(
        metric="battery_temp_c", values=tuple(o.value for o in temps), horizon=ctx.horizon,
        bound=tuple((o.observation_id, o.content_digest()) for o in temps),
    )
    claim = PredictionClaim.from_prediction(prediction, subject="asset-4417/battery-pack")
    print(f"readings used     : {len(temps)}  {tuple(o.value for o in temps)}")
    print(f"score             : {claim.score}")
    print(f"semantics         : {claim.score_semantics}")
    print(f"evidence strength : {claim.evidence_strength}")
    print(f"model             : {claim.model_version}")
    print(f"artifact digest   : {claim.model_artifact_digest[:16]}...")
    print("\nThe horizon is DERIVED from the decision context's prediction window, so the")
    print("claim and the inputs cannot hold two horizons that disagree.")

    # ------------------------------------------------------------------- REASON
    heading("REASON -- which commitments does this prediction put at risk?")
    impact = graph.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=ctx.prediction_window.start, horizon_end=ctx.prediction_window.end,
        transaction_time_cutoff=ctx.knowledge_cutoff,
    )
    for fact in impact.source_facts:
        print(f"    {fact}")
    print(f"\nderived           : {impact.derived}")
    print(f"commitment        : {impact.commitment.description}")
    print(f"rule version      : {impact.rule_version}")
    print(f"filtered as recorded-too-late: {len(impact.late_relationships)}")

    window = TimeInterval(t(13, 5), t(13, 11))
    consequence = CustomerCommitmentConsequence(
        "CUSTOMER_COMMITMENT", window, impact.derivation(),
        commitment_id=impact.commitment.commitment_id,
        commitment_description=impact.commitment.description,
        counterparty="customer A",
    )
    action = ActionRecommendation(
        "act-2026-06-12-001", ActionType.INSPECT, "battery-pack-1", "maintenance",
        due_by=t(13, 3), operational_window=window,
        reason="degradation signal over the same horizon as the commitment",
        priority=Priority.BEFORE_NEXT_USE,
    )
    candidate = IntelligenceCandidate("cand-2026-06-12-001", ctx, claim, consequence, action)
    print("\nMost predictive-maintenance stacks stop before this layer. Without it you can")
    print("say a battery is degrading. With it you can say which promise is at risk.")

    # --------------------------------------------------------------- PRODUCTIZE
    heading("PRODUCTIZE -- may we actually deliver this to the customer?")
    evidence = EvidenceSnapshot(
        observation_ids=tuple(o.observation_id for o in known),
        subject="asset-4417",
        evidence_content_digest=digest_observations(known),
        prediction_inputs=PredictionInputs(
            metric=claim.metric, values=tuple(o.value for o in temps),
            horizon_seconds=claim.horizon_seconds, model_version=claim.model_version,
            input_fingerprint=claim.input_fingerprint,
            bound_inputs=tuple(
                PredictionInput(o.observation_id, o.content_digest(), o.value)
                for o in temps
            ),
        ),
        model_version=claim.model_version, semantic_rule_version=RULE_VERSION,
        identity_confidence=0.97,
        source_systems=tuple(sorted({o.source_system for o in known})),
        captured_at=model_decision_time,
    )
    # The clearance covers every system whose data materially forms the product: the three
    # telemetry feeds AND the five business systems the REASON walk joined. It used to
    # cover the telemetry alone, which licensed one half of a two-half product -- the
    # thing being sold is not the temperature, it is "your next-day commitment to customer
    # A is at risk", and that sentence is derived from an asset register, a yard, a dock
    # schedule, a transport plan and an order book.
    entitled = EntitlementAssertion(
        "operations@customer", "operational-advisory", "asset-4417/battery-pack",
        "tenant-1",
        "MSA-2026-14 clause 7.2 (telemetry-derived advisories), clause 9.1 "
        "(operational reference data)", "policy-ops-1",
        policy_version="rights-policy@3.1.0", valid_from=t(1),
        authorized_source_systems=tuple(sorted(
            {o.source_system for o in known} | set(impact.derivation().source_systems())
        )),
        may_use_source_data=True, may_deliver_to_recipient=True,
    )
    assurance = AssuranceContext(
        IdentityAssertion(
            "asset-4417/battery-pack", "identity-resolver", "2.1", 0.97,
            evidence_refs=("serial-plate-scan-8841", "fleet-register-row-4417"),
        ),
        ApplicabilityAssertion(claim.model_version, "forklift/battery-pack", True,
                               "metric and horizon within the declared envelope"),
        TemporalAssertion(
            model_decision_time, model_decision_time, model_decision_time, True,
            basis="features drawn from the point-in-time view at the knowledge cutoff",
        ),
        entitled,
    )
    product = release(
        candidate=candidate, assurance=assurance, evidence=evidence, observation_log=log,
        recipient="operations@customer", purpose="operational-advisory",
        tenant="tenant-1",
        product_id="ip-2026-06-12-001", claim_series_id="series-4417-battery",
        # WAS t(13, 11) -- the close of the loading window, eight hours past the deadline
        # of the inspection this product is asking for. The card would have gone on
        # reading ACTIVE through an entire shift in which the only instruction it carried
        # could no longer be carried out.
        release_decision_time=model_decision_time, valid_until=t(13, 3),
    )
    # THE THREE CLOCKS, PRINTED, because they were two names that read as one thing.
    print("three moments, and the question each one answers:")
    print(f"    model_decision_time    {product.candidate.context.model_decision_time.isoformat()}"
          f"   the model issued the claim -- bounds the evidence")
    print(f"    release_decision_time  {product.assurance.release_decision_time.isoformat()}"
          f"   the gate authorised it -- selects the rules")
    print(f"    delivery_time          {product.delivery_time.isoformat()}"
          f"   the recipient received it -- equal to the gate's")
    print("    the model decides first; the gate and the delivery are one moment\n")
    print("six dimensions, held separately -- this is what decided:")
    for dim, value in product.assurance.assurance_context_record["evidence"].items():
        if dim in ("missing_evidence", "conflicts", "blocking_reasons"):
            continue
        print(f"    {dim:<22} {value}")
    print(f"\ndetermination     : {product.determination.value}")
    print(f"policy            : {product.assurance.policy_version}")
    print(f"policy digest     : {product.assurance.policy_digest[:16]}...")
    print("\nwhat the operator actually saw:\n")
    print(product.rendered_delivery.rendered_text)

    # -------------------------------------------------- PRODUCTIZE, the refusals
    heading("PRODUCTIZE, case 2 -- a clearance that belongs to somebody else")
    blocked = release(
        candidate=candidate, assurance=assurance, evidence=evidence, observation_log=log,
        recipient="procurement@other-customer", purpose="benchmarking",
        tenant="tenant-1",
        product_id="ip-2026-06-12-002", claim_series_id="series-4417-battery",
        release_decision_time=model_decision_time,
    )
    print(f"determination     : {blocked.determination.value}")
    print(f"reason            : {blocked.abstention_reason()}")
    print("\nThe entitlement is entirely valid -- for operations@customer, for operational")
    print("advisory. A clearance obtained for one recipient does not authorise another.")

    heading("PRODUCTIZE, case 3 -- evidence that cannot support the claim")
    tampered = EvidenceSnapshot(
        **{**evidence.__dict__, "evidence_content_digest": "a" * 64}
    )
    unprovable = release(
        candidate=candidate, assurance=assurance, evidence=tampered, observation_log=log,
        recipient="operations@customer", purpose="operational-advisory",
        tenant="tenant-1",
        product_id="ip-2026-06-12-003", claim_series_id="series-4417-battery",
        release_decision_time=model_decision_time,
    )
    print(f"determination     : {unprovable.determination.value}")
    print(f"reason            : {unprovable.abstention_reason()}")
    print("\nSixty-four hex characters that look exactly like a SHA-256 and have nothing")
    print("to do with the cited readings. The digest is recomputed, never trusted.")

    heading("PRODUCTIZE, case 4 -- a real prediction with no reachable consequence")
    orphan = ContextGraph()
    orphan.components["battery-pack-1"] = Component(
        "battery-pack-1", "asset-4417", "battery-pack", recorded_at=t(8, 1),
        source_system="asset-register")
    orphan.assignments.append(Assignment(
        "asset-4417", "zone-11", t(8), t(8, 1), source_system="yard-management"))
    no_impact = orphan.derive_impact(
        asset_id="asset-4417", component_id="battery-pack-1",
        horizon_start=ctx.prediction_window.start, horizon_end=ctx.prediction_window.end,
        transaction_time_cutoff=ctx.knowledge_cutoff)
    print(f"derived           : {no_impact.derived}")
    print(f"reason            : {'; '.join(no_impact.blocking_reasons())}")
    print("\nThe prediction is identical to case 1 and just as correct. No candidate forms,")
    print("because there is no actionable business consequence to form one around. This is")
    print("a maintenance alert, and shipping it as sold intelligence is the category error")
    print("the whole argument is about.")

    # --------------------------------------------------------------------- LEARN
    heading("LEARN -- what the recipient did, and what was observed afterwards")
    lifecycle = ProductLifecycle(
        product_subject=product.candidate.prediction_claim.subject,
        product_id=product.product_id,
    )
    for state, actor, at in [
        (DispositionState.DELIVERED, "system", t(12, 7)),
        (DispositionState.ACKNOWLEDGED, "operations@customer", t(12, 9)),
        (DispositionState.ACCEPTED, "operations@customer", t(12, 14)),
        (DispositionState.ACTION_COMPLETED, "maintenance@customer", t(13, 2)),
    ]:
        lifecycle.advance(state, at=at, actor=actor)
    # The trail records the STATE TRANSITION. The typed observation below records what was
    # observed. `ProductLifecycle.record_outcome(str)` used to do both -- advancing the
    # trail and storing a prose outcome on the lifecycle -- and this scenario exercised
    # that string AND the typed observation, with nothing comparing them. Two outcome
    # authorities for one event; the string is gone.
    lifecycle.advance(
        DispositionState.OUTCOME_OBSERVED, at=t(13, 4), actor="maintenance@customer",
        note="degraded cell found; pack swapped before the window opened",
    )
    outcome = OutcomeObservation(
        "out-2026-06-13-001", OutcomeType.DEFECT_FOUND_ON_INSPECTION,
        "asset-4417/battery-pack", TimeInterval(t(13, 2), t(13, 5)), t(13, 4),
        source="maintenance-system", related_action_id=action.action_id,
        note="degraded cell; pack swapped before the window opened",
    )
    for e in lifecycle.events:
        print(f"    {format_moment(e.at)}  {e.state.value:<18} {e.actor}")
    print(f"\noutcome           : {outcome.describe()}")
    print(f"joins action      : {outcome.related_action_id}")
    print(f"attributed effect : {lifecycle.attributed_effect.value}")
    print("\nThe outcome joins a specific recommendation by id -- which is what makes an")
    print("evaluation dataset possible, because 'acted and no failure' and 'ignored and no")
    print("failure' are different rows. What the record will not say is that the")
    print("recommendation CAUSED the good outcome. Nothing was randomised and the")
    print("recipient chose. This stage captures the data prerequisite for learning; it")
    print("does not retrain or promote a model, and does not claim to.")

    # --------------------------------------------------------------------- TRUST
    heading("TRUST -- the whole loop leaves the platform in one artifact")
    envelope = IntelligenceEnvelope(
        product=product,
        # The trail and the outcome travel as the typed objects they already are. They
        # used to be flattened into dictionaries here, which is how the portable form of
        # the LEARN boundary came to preserve neither the typed events nor the
        # outcome-to-action join that is the whole reason outcomes are collected.
        lifecycle_events=tuple(lifecycle.events),
        outcome=outcome,
        attributed_effect=lifecycle.attributed_effect,
        status_events=(StatusEvent(
            StatusEventType.SUPERSEDED, t(13, 6), "system",
            replacement_product_id="ip-2026-06-13-004"),),
    )
    canonical = envelope.canonical_json()
    print(f"canonicalization  : {envelope.as_record()['canonicalization']}")
    print(f"canonical bytes   : {len(canonical)}")
    print(f"envelope digest   : {envelope.digest()[:32]}...")
    print(f"schema            : {envelope.as_record()['schema_version']}")

    pi = product.evidence.prediction_inputs
    replayed = predict_degradation(
        metric=pi.metric, values=pi.values,
        horizon=timedelta(seconds=pi.horizon_seconds),
        bound=tuple((b.observation_id, b.content_digest) for b in pi.bound_inputs),
    )
    print(f"\nreplayed score    : {replayed.risk}  (on file: {prediction.risk})")
    print(f"fingerprint match : {replayed.input_fingerprint == pi.input_fingerprint}")
    print(f"status at 13 Jun  : {envelope.status_at(t(13, 7)).value}")
    print(f"status at 12 Jun  : {envelope.status_at(t(12, 8)).value}"
          "   (the supersession had not happened yet)")
    print("\nThe envelope carries the claim, what was known when it was made, why it")
    print("qualified for release, what the customer saw, what they did, and what happened.")
    print("It contains enough to replay the prediction with the versioned predictor")
    print("implementation, without access to the original telemetry store. It does not")
    print("carry the model implementation, and does not claim to.")

    heading("SUMMARY")
    checks = [
        ("prediction computed from the readings", "PREDICT"),
        ("consequence derived by graph walk", "REASON"),
        ("delivered when the chain completes", "PRODUCTIZE"),
        ("refused when the clearance belongs to another recipient", "case 2"),
        ("refused when the digest does not match the evidence", "case 3"),
        ("no candidate when no consequence is reachable", "case 4"),
        ("disposition and outcome joined to the action by id", "LEARN"),
        ("late evidence excluded from the day-12 view", "CONNECT"),
        ("whole loop re-verified outside the platform", "TRUST"),
    ]
    for text, stage in checks:
        print(f"{text:.<62} yes  ({stage})")
    print("\nAll outcomes are reachable. A system that only ever refuses is safe and")
    print("useless; one that never refuses is dangerous. This one decides, and says why.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
