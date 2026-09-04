.PHONY: help all generate baseline agent eval risk risk-eval challenge offline-eval razorpay-sync test qa qa-eval api web web-build

help:
	@echo "Available commands:"
	@echo "  make generate  - Generate synthetic dataset"
	@echo "  make all       - Reproduce data, baseline, agent, and metrics"
	@echo "  make agent     - Run deterministic reconciliation pipeline"
	@echo "  make eval      - Evaluate controller output"
	@echo "  make risk      - Scan credit and debit bank-entry risk"
	@echo "  make risk-eval - Score bidirectional risk detection"
	@echo "  make challenge - Run the known-miss GraphShield regression replay"
	@echo "  make offline-eval - Run robustness, known replay, and post-freeze holdout"
	@echo "  make razorpay-sync - Fetch read-only Razorpay Test Mode API snapshot"
	@echo "  make test      - Run fail-closed invariant tests"
	@echo "  make qa-eval   - Measure optional-model tool-call compatibility"
	@echo "  make api       - Start the local LangGraph dashboard API"
	@echo "  make web       - Start the dashboard frontend"
	@echo "  make web-build - Validate the production frontend build"

generate:
	python generator/generate.py

baseline:
	python eval/baseline.py --out results/preds_baseline.json

agent:
	python -m agent.ledger

eval:
	python eval/score.py results/preds_agent.json --outdir results/agent --label deterministic_controller

risk:
	python -c "from agent.risk import scan_bank_risk; scan_bank_risk()"

risk-eval:
	python -c "from eval.risk_score import score_risk; print(score_risk('results/risk_assessments.json','data/risk_truth.json','results/risk')[0])"

challenge:
	python -m eval.challenge

offline-eval:
	python -m eval.suite

razorpay-sync:
	python -m integrations.razorpay_feed

test:
	python -m unittest discover -v

all:
	python run.py

qa:
	python -m agent.qa "Show me the unresolved exceptions"

qa-eval:
	python -m eval.qa_eval

api:
	python -m uvicorn dashboard.api:app --host 127.0.0.1 --port 8000

web:
	cd web && pnpm run dev

web-build:
	cd web && pnpm run build
