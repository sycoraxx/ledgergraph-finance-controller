"""Generate and run the interactive deterministic controller on one batch."""

from __future__ import annotations

import argparse
from pathlib import Path

from agent.ledger import run_pipeline
from agent.risk import scan_bank_risk
from eval.suite import score_current_batch
from generator.generate import Generator, self_check


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data")
    parser.add_argument("--results", default="results")
    parser.add_argument("--skip-generate", action="store_true")
    args = parser.parse_args()
    data_dir, results_dir = Path(args.data), Path(args.results)
    results_dir.mkdir(parents=True, exist_ok=True)

    if not args.skip_generate:
        generator = Generator().run()
        truth = generator.write(data_dir)
        errors = self_check(generator, data_dir)
        if errors:
            raise SystemExit("generator self-check failed:\n" + "\n".join(errors))
        print(f"generated          {len(truth)} bank records / {len(generator.orders)} orders")

    predictions, journals = run_pipeline(data_dir, results_dir)
    assessments, findings = scan_bank_risk(data_dir, results_dir, predictions)
    evaluation = score_current_batch(data_dir, results_dir)
    baseline_summary = evaluation["baseline"]
    agent_summary = evaluation["controller"]
    risk_summary = evaluation["risk"]
    ledgergraph = evaluation["ledgergraph"]

    print(f"baseline recall    {baseline_summary['bank_recall_on_resolvable']}")
    print(f"controller recall  {agent_summary['bank_recall_on_resolvable']}")
    print(f"false auto-close   {agent_summary['false_auto_closures']}")
    print(f"exceptions         {agent_summary['component_exceptions']}")
    print(f"journal proposals  {len(journals)} (none posted)")
    print(f"risk precision     {risk_summary['precision']}")
    print(f"risk recall        {risk_summary['recall']}")
    print(f"dubious entries    {len(findings)} / {len(assessments)} bank entries")
    print(f"credit recall      {risk_summary['by_direction']['credit']['recall']}")
    print(f"debit recall       {risk_summary['by_direction']['debit']['recall']}")
    graph_result = next(
        item for item in ledgergraph["comparison"]
        if item["system"] == "ledgergraph_global"
    )
    print(f"LedgerGraph cases  {graph_result['cases_exactly_correct']}/{graph_result['case_count']} exact")
    print(f"Graph false links  {graph_result['false_selections']}")
    print(f"wrote              {results_dir / 'agent' / 'metrics.md'}")
    print(f"wrote              {results_dir / 'risk' / 'risk_metrics.md'}")
    print("offline eval       python -m eval.suite")


if __name__ == "__main__":
    main()
