.PHONY: clean
clean:
	@rm -rf `hg status -nu .`
	@find . -type d -empty -delete
