PROJECT = $(CURDIR)

all: build

.PHONY: clean build

clean:
	rm -rf build
	rm -rf site-packages

build:
	$(info ************ Starting Build: $(PROJECT) ************)
	mkdir -p site-packages
	cp *.* ./site-packages
	pip3 install --platform manylinux2014_x86_64 --implementation cp --python-version 3.12 --only-binary=:all: -r requirements.txt -t ./site-packages

