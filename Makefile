# Original bootstrap skeleton is retained in docs/legacy-Makefile.txt.
# Normal entrypoints now reach the enforced CMake safety gates.
.PHONY: all test check selftest clean format
all:
	./tools/safety check-fast
test check:
	./tools/safety check-full
selftest:
	./tools/safety selftest
format:
	./tools/safety check-fast
clean:
	rm -rf build
