.PHONY: test test-container image

test:
	python3 -m unittest discover -s tests -v

image:
	docker build --build-arg VERSION=$$(cat VERSION) -t sqlite-backup-sidecar:dev .

test-container:
	BACKUP_TEST_IMAGE=sqlite-backup-sidecar:dev tests/test_container.sh
