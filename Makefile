.PHONY: validate test baseline-check check

validate:
	PYTHONPATH=src python3 -m agent_enhance validate .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

baseline-check:
	python3 scripts/validate_baseline_matrix.py
	python3 scripts/validate_source_results.py
	python3 scripts/validate_baseline_evidence_v2.py
	python3 scripts/validate_baseline_evidence_v3.py
	python3 scripts/validate_foundation_results.py
	python3 scripts/validate_model_retention_policy_v2.py
	python3 scripts/validate_baseline_model_ownership_ledger.py
	python3 scripts/validate_recent_method_reproduction_roadmap_v2.py
	python3 scripts/validate_recent_method_reproduction_roadmap_v3.py
	python3 scripts/validate_wma_table_bundle_v2.py --require-no-admitted-results
	python3 scripts/validate_wma_table_bundle_v3.py --require-no-admitted-results
	python3 scripts/validate_wma_wave3_source_audit.py
	python3 scripts/validate_wma_wave3_adapter_and_models.py
	python3 scripts/validate_wma_wave3_execution_source_audit.py
	python3 scripts/validate_wma_wave3_environment_and_lifecycle.py
	python3 scripts/validate_wma_wave4_tierb_source_readiness.py
	python3 scripts/validate_wma_wave5_structmem_source_readiness.py
	python3 scripts/validate_hf_model_materialization_successors.py
	python3 scripts/validate_wma_postwave_release_sequence.py
	python3 scripts/validate_wma_local_result_admission.py
	python3 scripts/validate_wma_wave1_recovery2.py
	python3 scripts/validate_wma_wave1_recovery2_closure.py
	python3 scripts/validate_wma_wave1_recovery2_result_admission.py

check: validate test baseline-check
