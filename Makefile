.PHONY: test install run

test:
	python3 -m unittest discover -s tests -v

install:
	./install.sh

run:
	./mypomodoro &
