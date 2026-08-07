.PHONY: test regression

test:
	python -m pytest tests/ -q

regression: test
