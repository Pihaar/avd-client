.PHONY: install dev test lint i18n clean

install:
	pip install --user -e .

dev:
	pip install --user -e ".[test,dev]"

test:
	pytest --cov=avd_client --cov-report=term-missing

lint:
	ruff check src/ tests/

i18n:
	xgettext -o src/avd_client/locale/avd-client.pot --language=Python \
		--keyword=_ --from-code=UTF-8 src/avd_client/*.py
	msgmerge --update src/avd_client/locale/de/LC_MESSAGES/avd-client.po \
		src/avd_client/locale/avd-client.pot
	msgfmt -o src/avd_client/locale/de/LC_MESSAGES/avd-client.mo \
		src/avd_client/locale/de/LC_MESSAGES/avd-client.po

i18n-check:
	msgfmt --check -o /dev/null src/avd_client/locale/de/LC_MESSAGES/avd-client.po

clean:
	rm -rf build/ dist/ *.egg-info src/*.egg-info .pytest_cache .coverage htmlcov
