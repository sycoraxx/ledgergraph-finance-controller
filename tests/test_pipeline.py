from __future__ import annotations

import csv
import json
import tempfile
import unittest
from unittest.mock import patch
from datetime import date
from urllib.parse import urlparse
from decimal import Decimal
from pathlib import Path

from agent.ledger import (
    aggregate_settlements,
    load_sources,
    run_pipeline,
    verify_components,
)
from agent.l1_search import parse_date_candidates, reconcile_search
from agent.ledger_graph import build_candidate_graph, solve_candidate_graph
from agent.model_gateway import ExplanationModelClient, LocalQwenClient
from agent.subset_sum import build_subset_sum_index
from agent.qa import answer_question, deterministic_route, validate_call
from agent.risk import scan_bank_risk
from agent.scenario_catalog import scenario_catalog, scenario_context
from agent.workflow import WorkflowRuntime
from eval.risk_score import score_risk
from eval.challenge import run_challenge
from eval.fraud_holdout import FROZEN_GRAPHSHIELD_SHA256, run_fraud_holdout
from eval.score import grade, summarise
from generator.generate import Generator, add_working_days, is_working_day, self_check
from integrations.razorpay_feed import RazorpayFeedError, RazorpayReadOnlyClient, sync_feed


class FinanceControllerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.data = cls.root / "data"
        cls.results = cls.root / "results"
        cls.generator = Generator().run()
        cls.truth = cls.generator.write(cls.data)
        cls.predictions, cls.journals = run_pipeline(cls.data, cls.results)
        cls.risk_assessments, cls.risk_findings = scan_bank_risk(
            cls.data, cls.results, cls.predictions
        )
        cls.risk_metrics, cls.risk_graded = score_risk(
            cls.results / "risk_assessments.json",
            cls.data / "risk_truth.json",
            cls.results / "risk",
        )

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_generator_and_financial_invariants(self):
        self.assertEqual([], self_check(self.generator, self.data))
        self.assertTrue(all(item["balanced"] for item in self.journals))
        self.assertTrue(all(item["posting_status"] == "not_posted" for item in self.journals))
        self.assertEqual(len(self.journals), len({item["proposal_id"] for item in self.journals}))

    def test_controller_closes_resolvable_components_and_refuses_adjustments(self):
        rows = grade(self.truth, self.predictions)
        summary = summarise(rows)
        self.assertEqual("100.0%", summary["bank_match_precision"])
        self.assertEqual("100.0%", summary["component_recall_on_resolvable"])
        self.assertEqual("100.0%", summary["component_unresolvable_recall"])
        self.assertEqual(0, summary["false_auto_closures"])
        self.assertEqual(5, sum(
            item["approval_status"] == "needs_review"
            for item in self.predictions))

    def test_flagship_batch_carries_every_reconciliation_topology_end_to_end(self):
        required = {"1:1", "1:N", "N:1", "N:M"}
        self.assertTrue(required.issubset({item["topology"] for item in self.truth}))
        artifact = json.loads((self.results / "ledgergraph.json").read_text(encoding="utf-8"))
        selected = artifact["solution"]["selected"]
        self.assertTrue(required.issubset({item["topology"] for item in selected}))
        self.assertEqual(
            {"1:1": 13, "1:N": 12, "N:1": 12, "N:M": 13},
            artifact["solution"]["selected_topology_counts"],
        )
        for topology in ("1:N", "N:1", "N:M"):
            self.assertGreater(
                artifact["solution"]["candidate_topology_counts"][topology],
                artifact["solution"]["selected_topology_counts"][topology],
            )
            self.assertGreater(
                artifact["solution"]["hard_gate_rejected_topology_counts"][topology],
                0,
            )
        self.assertGreater(
            sum(artifact["solution"]["global_rejected_topology_counts"].values()),
            0,
        )
        self.assertEqual(75, sum(len(item["bank_ids"]) for item in selected))
        self.assertEqual(75, sum(len(item["settlement_ids"]) for item in selected))
        grouped_journals = {item["topology"]: item for item in self.journals if item["topology"] != "1:1"}
        self.assertEqual({"1:N", "N:1", "N:M"}, set(grouped_journals))
        self.assertTrue(all(item["balanced"] for item in grouped_journals.values()))
        self.assertTrue(all(
            item.get("bank_txn_ids") and item.get("settlement_ids")
            for item in self.predictions if item.get("topology") != "1:1"
        ))

    def test_synthetic_t_plus_policy_skips_weekends_and_preserves_chronology(self):
        self.assertEqual(date(2026, 6, 8), add_working_days(date(2026, 6, 4), 2))
        self.assertFalse(is_working_day(date(2026, 6, 6)))
        with (self.data / "settlement_schedule.csv").open(newline="", encoding="utf-8") as handle:
            schedule = list(csv.DictReader(handle))
        self.assertEqual({"T+1", "T+2"}, {row["settlement_cycle"] for row in schedule})
        self.assertTrue(all(row["chronology_valid"].lower() == "true" for row in schedule))
        thursday_t2 = [
            row for row in schedule
            if row["capture_weekday"] == "Thursday" and row["settlement_cycle"] == "T+2"
        ]
        self.assertTrue(thursday_t2)
        self.assertTrue(all(row["settled_weekday"] == "Monday" for row in thursday_t2))
        self.assertTrue(all("skipped" in row["working_day_path"] for row in thursday_t2))

    def test_missing_cross_source_payment_is_an_exception(self):
        sources = load_sources(self.data)
        settlements = aggregate_settlements(sources)
        settlement = next(item for item in settlements.values() if item["component_payments"])
        missing = settlement["component_payments"][0]
        sources["payments_by_id"].pop(missing)
        result = verify_components(settlement, sources)
        self.assertEqual("exception", result["component_status"])
        self.assertIn("missing_payment", {item["code"] for item in result["component_issues"]})

    def test_bidirectional_risk_detection_is_exact_and_explainable(self):
        self.assertEqual(87, len(self.risk_assessments))
        self.assertEqual(9, len(self.risk_findings))
        self.assertEqual({"credit", "debit"}, {item["direction"] for item in self.risk_findings})
        self.assertEqual("100.0%", self.risk_metrics["precision"])
        self.assertEqual("100.0%", self.risk_metrics["recall"])
        self.assertEqual("100.0%", self.risk_metrics["by_direction"]["credit"]["recall"])
        self.assertEqual("100.0%", self.risk_metrics["by_direction"]["debit"]["recall"])
        self.assertEqual(0, self.risk_metrics["false_positives"])
        self.assertEqual(0, self.risk_metrics["false_negatives"])
        for finding in self.risk_findings:
            self.assertTrue(finding["observed_text"])
            self.assertTrue(finding["expected_text"])
            self.assertTrue(finding["recommended_action"])
            self.assertTrue(finding["transaction_timestamp_utc"])
            self.assertTrue(finding["source_extracted_at_utc"])
            self.assertTrue(finding["citations"])

    def test_synthetic_scenarios_declare_realism_and_required_evidence(self):
        catalog = scenario_catalog()
        self.assertEqual(4, len(catalog["categories"]))
        for finding in self.risk_findings:
            context = scenario_context(finding["anomaly_type"])
            self.assertNotEqual("unclassified", context["id"])
            self.assertTrue(context["required_sources"])
            self.assertTrue(context["realism_basis"])
            self.assertTrue(context["claim_boundary"])
        self.assertEqual(
            "razorpay_native_mechanic",
            scenario_context("topology:1:1")["category"],
        )
        for topology in ("1:N", "N:1", "N:M"):
            self.assertEqual(
                "adversarial_stress_case",
                scenario_context(f"topology:{topology}")["category"],
            )

    def test_risk_detector_does_not_read_benchmark_truth(self):
        truth_path = self.data / "risk_truth.json"
        hidden_path = self.data / "risk_truth.hidden"
        truth_path.replace(hidden_path)
        try:
            assessments, findings = scan_bank_risk(
                self.data, self.results / "truth-blind", self.predictions
            )
            self.assertEqual(len(self.risk_assessments), len(assessments))
            self.assertEqual(len(self.risk_findings), len(findings))
        finally:
            hidden_path.replace(truth_path)

    def test_graph_intelligence_known_miss_replay_remains_a_regression_control(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = run_challenge(Path(directory), seeds=(20260831,))
        self.assertEqual("100.0%", summary["precision"])
        self.assertEqual("100.0%", summary["recall"])
        self.assertEqual(0, summary["false_positives"])
        self.assertEqual(0, summary["false_negatives"])
        self.assertLess(float(summary["baseline_without_graph"]["recall"].rstrip("%")), 100.0)
        self.assertEqual(2, summary["baseline_without_graph"]["false_negatives"])
        self.assertEqual(2, summary["graph_intelligence_delta"]["additional_true_positives"])
        self.assertEqual(0, summary["graph_intelligence_delta"]["false_positives_added"])
        for name in ("counterparty_substitution", "collusive_duplicate"):
            self.assertEqual("0.0%", summary["by_mutation_class"][name]["baseline_recall"])
            self.assertEqual("100.0%", summary["by_mutation_class"][name]["graph_recall"])

    def test_post_freeze_fraud_holdout_reports_new_misses_without_tuning(self):
        with tempfile.TemporaryDirectory() as directory:
            summary = run_fraud_holdout(Path(directory), seeds=(20260911,))
        self.assertEqual(FROZEN_GRAPHSHIELD_SHA256, summary["detector_sha256"])
        self.assertEqual("never used to modify the frozen detector", summary["partition_status"])
        self.assertNotEqual("100.0%", summary["recall"])
        self.assertGreater(summary["false_negatives"], 0)
        self.assertEqual(0, summary["false_positives"])
        self.assertEqual("100.0%", summary["specificity"])

    def test_graph_intelligence_is_explainable_and_non_authoritative(self):
        summary = json.loads((self.results / "graph_ood_summary.json").read_text(encoding="utf-8"))
        assessments = json.loads((self.results / "graph_ood_assessments.json").read_text(encoding="utf-8"))
        self.assertIn("cannot change reconciliation", summary["authority"])
        self.assertEqual(12, summary["operating_paths_scored"])
        self.assertTrue(all("score" in item and "signals" in item for item in assessments))
        self.assertTrue(all(item["evidence_path"][0].startswith("bank:") for item in assessments))

    def test_source_provenance_has_extraction_and_coverage_timestamps(self):
        provenance = json.loads((self.data / "provenance.json").read_text(encoding="utf-8"))
        self.assertTrue(provenance["extracted_at_utc"].endswith("+00:00"))
        self.assertLessEqual(provenance["coverage_start"], provenance["coverage_end"])
        names = {item["name"] for item in provenance["sources"]}
        self.assertTrue({"bank_statement.csv", "cashbook.csv", "risk_truth.json"}.issubset(names))

    def test_read_only_razorpay_test_feed_stages_authentic_api_shapes(self):
        now_epoch = 1787514600
        samples = {
            "/v1/orders": {"id": "order_demo", "amount": 12500, "currency": "INR", "created_at": now_epoch},
            "/v1/payments": {"id": "pay_demo", "order_id": "order_demo", "amount": 12500, "currency": "INR", "created_at": now_epoch},
            "/v1/refunds/": {"id": "rfnd_demo", "payment_id": "pay_demo", "amount": 2500, "currency": "INR", "created_at": now_epoch},
            "/v1/settlements/": {"id": "setl_demo", "amount": 9500, "fees": 100, "tax": 18, "currency": "INR", "created_at": now_epoch},
            "/v1/settlements/recon/combined": {"entity_id": "pay_demo", "type": "payment", "amount": 12500, "credit": 12382, "debit": 0, "fee": 100, "tax": 18, "currency": "INR", "settlement_id": "setl_demo", "settled_at": now_epoch},
        }
        requests = []

        def transport(request, timeout):
            requests.append(request)
            item = samples[urlparse(request.full_url).path]
            return json.dumps({"entity": "collection", "count": 1, "items": [item]}).encode()

        client = RazorpayReadOnlyClient("rzp_test_demo", "never-persist-this", transport=transport)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            summary = sync_feed(
                output_root=root / "api",
                status_path=root / "status.json",
                client=client,
                max_records=100,
            )
            snapshot = Path(summary["snapshot_path"])
            self.assertEqual(5, sum(summary["counts"].values()))
            with (snapshot / "payments.csv").open(newline="", encoding="utf-8") as handle:
                self.assertEqual("125.00", next(csv.DictReader(handle))["amount"])
            with (snapshot / "settlements.csv").open(newline="", encoding="utf-8") as handle:
                self.assertEqual("1.00", next(csv.DictReader(handle))["fees"])
            persisted = (root / "status.json").read_text(encoding="utf-8")
            self.assertNotIn("never-persist-this", persisted)
            self.assertFalse(summary["controller_ready"])
            self.assertFalse(summary["real_money"])
            self.assertEqual("simulated_test_data", summary["data_classification"])
            self.assertEqual(["bank_statement.csv", "cashbook.csv"], summary["missing_independent_sources"])
        self.assertTrue(all(request.get_method() == "GET" for request in requests))
        self.assertTrue(all(request.full_url.startswith("https://api.razorpay.com/v1/") for request in requests))

    def test_razorpay_connector_rejects_live_keys(self):
        with self.assertRaises(RazorpayFeedError):
            RazorpayReadOnlyClient("rzp_live_never", "secret")

    def test_ambiguous_amount_collision_fails_closed(self):
        settlements = {
            "setl_a": {"net": Decimal("10.00"), "utr": "CITIN26010111111111", "settled_dates": {"2026-01-01"}},
            "setl_b": {"net": Decimal("10.00"), "utr": "CITIN26010122222222", "settled_dates": {"2026-01-01"}},
        }
        bank = {"credit": "10.00", "value_date": "01/01/2026", "narration": "NEFT-UNKNOWN"}
        self.assertIsNone(reconcile_search(bank, settlements))

    def test_ledgergraph_resolves_collisions_with_global_evidence(self):
        settlements = {
            "setl_a": {"net": Decimal("100.00"), "utr": "UTRA123456789", "settled_dates": {"2026-01-01"}, "rows": []},
            "setl_b": {"net": Decimal("100.00"), "utr": "UTRB123456789", "settled_dates": {"2026-01-01"}, "rows": []},
        }
        banks = [
            {"bank_txn_id": "bank_a", "credit": "100.00", "debit": "", "value_date": "01/01/2026", "narration": "NEFT UTRA123456789"},
            {"bank_txn_id": "bank_b", "credit": "100.00", "debit": "", "value_date": "01/01/2026", "narration": "NEFT UTRB123456789"},
        ]
        result = solve_candidate_graph(build_candidate_graph(banks, settlements, max_group_size=1))
        selected = {(item["bank_ids"][0], item["settlement_ids"][0]) for item in result["selected"]}
        self.assertEqual({("bank_a", "setl_a"), ("bank_b", "setl_b")}, selected)
        self.assertTrue(all(item["money_conservation"]["residual"] == "0.00" for item in result["certificates"]))

    def test_ledgergraph_tied_optimum_abstains(self):
        settlements = {
            "setl_a": {"net": Decimal("10.00"), "utr": "A", "settled_dates": {"2026-01-01"}, "rows": []},
            "setl_b": {"net": Decimal("10.00"), "utr": "B", "settled_dates": {"2026-01-01"}, "rows": []},
        }
        banks = [{"bank_txn_id": "bank_x", "credit": "10.00", "debit": "", "value_date": "01/01/2026", "narration": "UNKNOWN"}]
        result = solve_candidate_graph(build_candidate_graph(banks, settlements, max_group_size=1))
        self.assertEqual([], result["selected"])
        self.assertEqual(["bank_x"], result["abstained_bank_ids"])
        self.assertTrue(result["components"][0]["tied_optimum"])

    def test_ledgergraph_fuzzy_reference_cannot_override_money(self):
        settlements = {
            "setl_a": {"net": Decimal("90.00"), "utr": "UTRA123456789", "settled_dates": {"2026-01-01"}, "rows": []},
        }
        banks = [{"bank_txn_id": "bank_x", "credit": "100.00", "debit": "", "value_date": "01/01/2026", "narration": "UTRA123456788"}]
        graph = build_candidate_graph(banks, settlements, max_group_size=1)
        self.assertTrue(graph["candidates"])
        self.assertFalse(graph["candidates"][0]["eligible"])
        self.assertEqual([], solve_candidate_graph(graph)["selected"])

    def test_ledgergraph_supports_split_and_merge_reconciliation(self):
        merge_settlements = {
            "setl_40": {"net": Decimal("40.00"), "utr": "A", "settled_dates": {"2026-01-01"}, "rows": []},
            "setl_60": {"net": Decimal("60.00"), "utr": "B", "settled_dates": {"2026-01-01"}, "rows": []},
        }
        merge_banks = [{"bank_txn_id": "bank_100", "credit": "100.00", "debit": "", "value_date": "01/01/2026", "narration": "AGGREGATED CREDIT"}]
        merged = solve_candidate_graph(build_candidate_graph(merge_banks, merge_settlements, max_group_size=2))
        self.assertEqual("many_settlements_to_one_bank", merged["selected"][0]["kind"])

        split_settlements = {
            "setl_100": {"net": Decimal("100.00"), "utr": "C", "settled_dates": {"2026-01-01"}, "rows": []},
        }
        split_banks = [
            {"bank_txn_id": "bank_40", "credit": "40.00", "debit": "", "value_date": "01/01/2026", "narration": "PART 1"},
            {"bank_txn_id": "bank_60", "credit": "60.00", "debit": "", "value_date": "01/01/2026", "narration": "PART 2"},
        ]
        split = solve_candidate_graph(build_candidate_graph(split_banks, split_settlements, max_group_size=2))
        self.assertEqual("one_settlement_to_many_banks", split["selected"][0]["kind"])

        many_to_many_settlements = {
            "setl_50": {"net": Decimal("50.00"), "utr": "D", "settled_dates": {"2026-01-01"}, "rows": []},
            "setl_70": {"net": Decimal("70.00"), "utr": "E", "settled_dates": {"2026-01-01"}, "rows": []},
        }
        many_to_many_banks = [
            {"bank_txn_id": "bank_45", "credit": "45.00", "debit": "", "value_date": "01/01/2026", "narration": "GROUP D E"},
            {"bank_txn_id": "bank_75", "credit": "75.00", "debit": "", "value_date": "01/01/2026", "narration": "GROUP D E"},
        ]
        grouped = solve_candidate_graph(build_candidate_graph(
            many_to_many_banks, many_to_many_settlements, max_group_size=2
        ))
        self.assertEqual("many_banks_to_many_settlements", grouped["selected"][0]["kind"])
        self.assertEqual("N:M", grouped["selected"][0]["topology"])

    def test_dynamic_programming_discovers_and_cp_sat_selects_a_four_item_group(self):
        settlements = {
            f"setl_{amount}": {
                "net": Decimal(f"{amount}.00"),
                "utr": f"UTR{amount}",
                "settled_dates": {"2026-01-01"},
                "rows": [],
            }
            for amount in (10, 20, 30, 40)
        }
        banks = [{
            "bank_txn_id": "bank_100",
            "credit": "100.00",
            "debit": "",
            "value_date": "01/01/2026",
            "narration": "AGGREGATED FOUR-WAY CREDIT",
        }]
        graph = build_candidate_graph(banks, settlements, max_group_size=4)
        result = solve_candidate_graph(graph)
        self.assertEqual("bounded_dynamic_programming_subset_sum", graph["candidate_generation"]["algorithm"])
        self.assertTrue(graph["candidate_generation"]["complete"])
        self.assertEqual("ortools_cp_sat_component_set_packing", result["solver"])
        self.assertEqual(1, len(result["selected"]))
        self.assertEqual("1:N", result["selected"][0]["topology"])
        self.assertEqual(4, len(result["selected"][0]["settlement_ids"]))
        self.assertEqual("OPTIMAL_UNIQUE", result["components"][0]["status"])

    def test_subset_sum_witness_overflow_fails_closed(self):
        settlements = {
            f"setl_{index:02d}": {
                "net": Decimal("1.00"),
                "utr": f"UTR{index:02d}",
                "settled_dates": {"2026-01-01"},
                "rows": [],
            }
            for index in range(12)
        }
        banks = [{
            "bank_txn_id": "bank_ambiguous",
            "credit": "2.00",
            "debit": "",
            "value_date": "01/01/2026",
            "narration": "DENSE SAME-TOTAL COLLISION",
        }]
        graph = build_candidate_graph(banks, settlements, max_group_size=2)
        result = solve_candidate_graph(graph)
        self.assertFalse(graph["candidate_generation"]["complete"])
        self.assertEqual("truncated_fail_closed", graph["candidate_generation"]["status"])
        self.assertIn("B:bank_ambiguous", graph["candidate_generation"]["unsafe_nodes"])
        self.assertEqual([], result["selected"])
        self.assertEqual(["bank_ambiguous"], result["abstained_bank_ids"])

    def test_subset_sum_index_reports_complete_large_group_witness(self):
        index = build_subset_sum_index(
            [("a", Decimal("10")), ("b", Decimal("20")),
             ("c", Decimal("30")), ("d", Decimal("40"))],
            4,
        )
        self.assertIn(("a", "b", "c", "d"), index.matches(Decimal("100")))
        self.assertTrue(index.complete_for(Decimal("100")))
        self.assertGreater(index.transition_count, 0)
        capped = build_subset_sum_index(
            [("a", Decimal("10")), ("b", Decimal("20")), ("c", Decimal("30"))],
            3,
            max_states=2,
        )
        self.assertTrue(capped.globally_truncated)
        self.assertFalse(capped.complete_for(Decimal("60")))

    def test_zero_cp_sat_budget_fails_closed(self):
        settlements = {
            "setl_a": {"net": Decimal("10.00"), "utr": "UTRA", "settled_dates": {"2026-01-01"}, "rows": []},
        }
        banks = [{
            "bank_txn_id": "bank_a", "credit": "10.00", "debit": "",
            "value_date": "01/01/2026", "narration": "UTRA",
        }]
        result = solve_candidate_graph(
            build_candidate_graph(banks, settlements, max_group_size=1),
            component_time_limit_seconds=0,
        )
        self.assertEqual([], result["selected"])
        self.assertEqual("TIME_LIMIT_ZERO", result["components"][0]["status"])
        self.assertTrue(result["components"][0]["exhausted"])

    def test_mixed_date_parser_preserves_ambiguity(self):
        self.assertEqual({"2026-06-03", "2026-03-06"}, parse_date_candidates("2026-03-06 07:00:00"))
        self.assertEqual({"2026-06-03"}, parse_date_candidates("03/06/2026"))

    def test_q_and_a_router_is_read_only_and_schema_guarded(self):
        call = deterministic_route("Why was BNK000004 held?")
        self.assertEqual("get_bank_transaction", call["name"])
        self.assertEqual((True, ""), validate_call(call))
        self.assertFalse(validate_call({"name": "post_journal", "arguments": {}})[0])
        self.assertFalse(validate_call({
            "name": "get_bank_transaction",
            "arguments": {"bank_txn_id": "BNK000004", "amount": 10},
        })[0])

    def test_local_qwen_health_reports_observed_runtime_state(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"status":"ok"}'

        client = LocalQwenClient(base_url="http://127.0.0.1:8001/v1")
        with patch.object(client.opener, "open", return_value=FakeResponse()):
            status = client.health_status()
        self.assertTrue(status["available"])
        self.assertEqual("ok", status["status"])
        self.assertEqual("http://127.0.0.1:8001", status["endpoint"])
        with patch.object(client.opener, "open", side_effect=OSError("offline")):
            status = client.health_status()
        self.assertFalse(status["available"])
        self.assertEqual("unavailable", status["status"])

    def test_hosted_explanation_provider_is_configured_without_network_probe(self):
        client = ExplanationModelClient(provider="groq", api_key="test-secret")
        with patch.object(client.opener, "open", side_effect=AssertionError("no probe")):
            status = client.health_status()
        self.assertTrue(status["available"])
        self.assertEqual("configured", status["status"])
        self.assertEqual("groq", status["provider"])

    def test_q_and_a_never_delegates_routing_to_a_model(self):
        with patch.object(
            ExplanationModelClient,
            "choose_tool",
            side_effect=AssertionError("model routing is forbidden"),
        ):
            answer = answer_question(
                "Please make a financial decision for me",
                self.results,
                use_model=True,
            )
        self.assertIn("cannot route", answer)

    def test_q_and_a_fallback_is_concise_and_grounded(self):
        exception = next(
            item for item in self.predictions
            if item["component_status"] == "exception")
        answer = answer_question(
            f"Why was {exception['bank_txn_id']} held?",
            self.results,
            use_model=False,
        )
        self.assertIn(exception["settlement_id"], answer)
        self.assertIn("No journal was proposed", answer)
        self.assertIn("settlement_recon.csv", answer)
        self.assertNotIn("component_payments", answer)

    def test_langgraph_workflow_gates_and_idempotently_posts_to_sandbox(self):
        runtime = WorkflowRuntime(self.root)
        try:
            state = runtime.start_run("test-workflow")
            self.assertEqual("awaiting_approval", state["status"])
            self.assertEqual("0", str(state["metrics"]["false_auto_closures"]))
            self.assertEqual("100.0%", state["metrics"]["risk_credit_recall"])
            self.assertEqual("100.0%", state["metrics"]["risk_debit_recall"])
            self.assertEqual("current_batch_only", state["metrics"]["evaluation_scope"])
            self.assertEqual("python -m eval.suite", state["metrics"]["offline_eval_command"])
            self.assertNotIn("challenge_recall", state["metrics"])
            self.assertNotIn("robustness_safety_gate_passed", state["metrics"])
            self.assertTrue(state["provenance"]["extracted_at_utc"])
            self.assertTrue(all(item["modified_at_utc"] for item in state["source_manifest"]))
            node_names = set(runtime.pipeline.get_graph().nodes)
            self.assertTrue({
                "inspect_sources", "reconcile_batch", "measure_batch",
                "prepare_review_queue",
            }.issubset(node_names))

            proposal_id = state["pending_approvals"][0]["proposal_id"]
            approved = runtime.decide(
                proposal_id, "approve", "unit-test-reviewer", "verified evidence"
            )
            self.assertEqual("posted_to_sandbox_ledger", approved["status"])
            entry_id = approved["ledger_entry_id"]

            repeated = runtime.decide(
                proposal_id, "approve", "unit-test-reviewer", "verified evidence"
            )
            self.assertEqual(entry_id, repeated["ledger_entry_id"])
            self.assertEqual(
                "posted_to_sandbox_ledger",
                runtime.ledger_state()[proposal_id]["status"],
            )

            rejected_id = state["pending_approvals"][1]["proposal_id"]
            rejected = runtime.decide(
                rejected_id, "reject", "unit-test-reviewer", "evidence not accepted"
            )
            self.assertEqual("rejected", rejected["status"])
            self.assertIsNone(rejected["ledger_entry_id"])
            self.assertNotIn("ledger_entry_id", runtime.ledger_state()[rejected_id])
        finally:
            runtime.connection.close()

    def test_langgraph_source_validation_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "data").mkdir()
            runtime = WorkflowRuntime(root)
            try:
                state = runtime.start_run("missing-sources")
                self.assertEqual("failed", state["status"])
                self.assertEqual("failed", state["current_stage"])
                self.assertIn("missing required source", state["errors"][0])
            finally:
                runtime.connection.close()


if __name__ == "__main__":
    unittest.main()
