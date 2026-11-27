PYTHON ?= uv run --locked python
export PYTHONPATH := $(CURDIR)/backend:$(PYTHONPATH)

.PHONY: run test check
run:
	$(PYTHON) -m mrp_app --mode demo

test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v

check:
	bash check.sh
