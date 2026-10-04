CC      ?= cc
CFLAGS  ?= -std=c17 -O2 -g -Wall -Wextra -Wpedantic -Werror -Wshadow -Wconversion \
           -Wstrict-prototypes -Wmissing-prototypes -Wformat=2 -fstack-protector-strong \
           -D_FORTIFY_SOURCE=2
SANITIZE ?= -fsanitize=address,undefined -fno-omit-frame-pointer
CPPFLAGS += -Iinclude

BUILD   := build
SRCS    := $(wildcard src/*.c)
OBJS    := $(SRCS:src/%.c=$(BUILD)/%.o)
TESTS   := $(wildcard tests/*.c)
TEST_BINS := $(TESTS:tests/%.c=$(BUILD)/tests/%)

.PHONY: all test check clean format

all: $(OBJS)

$(BUILD)/%.o: src/%.c | $(BUILD)
	$(CC) $(CPPFLAGS) $(CFLAGS) -c $< -o $@

$(BUILD)/tests/%: tests/%.c $(SRCS) | $(BUILD)/tests
	$(CC) $(CPPFLAGS) $(CFLAGS) $(SANITIZE) $< $(SRCS) -o $@

$(BUILD) $(BUILD)/tests:
	mkdir -p $@

test: $(TEST_BINS)
	@set -e; for t in $(TEST_BINS); do echo "== $$t"; $$t; done

check: test

format:
	clang-format -i src/*.c include/*.h tests/*.c

clean:
	rm -rf $(BUILD)
