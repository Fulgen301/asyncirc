localtest:
	cd test; python run_all.py

coverage:
	cd test; coverage --source asyncirc run run_all.py; coverage html
	cd test/htmlcov; google-chrome-stable index.html

clean:
	rm -rf test/htmlcov
	rm -f test/.coverage
	rm -rf build dist

install:
	python setup.py install

test: install
	cd test; python run_all.py

dev-deps:
	pip install blinker asyncio
	git clone https://github.com/watchtower/asynctest
	cd asynctest; python setup.py install
