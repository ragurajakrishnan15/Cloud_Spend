.PHONY: data validate test integration lint typecheck app models seeds report screenshots pipeline bi-export eval-llm

data:
	python -m cloudspend.data_generation.generate_billing --profile demo
validate:
	python -m cloudspend.validation.billing_checks data/generated/cloud_billing_demo.csv --budgets-csv data/generated/budgets_demo.csv
test:
	pytest -m "not integration"
integration:
	pytest -m integration
lint:
	ruff check .
app:
	streamlit run app/Home.py
models:
	python -m cloudspend.analytics.run_models
seeds:
	python -m cloudspend.analytics.evaluate_seeds
report:
	python -m cloudspend.analytics.eval_report
screenshots:
	python scripts/capture_screenshots.py
typecheck:
	mypy
pipeline:
	python -m cloudspend.pipeline --mode local
bi-export:
	python -m cloudspend.reporting.bi_export
eval-llm:
	python scripts/eval_llm_grounding.py --provider anthropic
