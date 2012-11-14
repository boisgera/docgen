.PHONY: all
all: pdf

.PHONY: clean
clean:
	@rm -rf `git ls-files --other --exclude-standard`
	@find . -type d -empty -delete

.PHONY: pdf
pdf: docgen.pdf

docgen.pdf: docgen.py
	@./docgen -o docgen.pdf -i docgen.py docgen

.PHONY: install
install: docgen.py
	@sudo python setup.py install

