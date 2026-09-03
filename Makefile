.PHONY: validate test baseline-check check

validate:
	PYTHONPATH=src python3 -m agent_enhance validate .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

baseline-check:
	python3 scripts/validate_baseline_matrix.py

check: validate test baseline-check
