.PHONY: validate test check

validate:
	PYTHONPATH=src python3 -m agent_enhance validate .

test:
	PYTHONPATH=src python3 -m unittest discover -s tests -v

check: validate test
