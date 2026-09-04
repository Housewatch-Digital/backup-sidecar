.PHONY: test test-container test-container-postgres16 image image-postgres16

test:
	python3 -m unittest discover -s tests -v

image:
	docker build --build-arg VERSION=$$(cat VERSION) -t sqlite-backup-sidecar:dev .

image-postgres16:
	docker build --target postgres --build-arg POSTGRES_MAJOR=16 --build-arg VERSION=$$(cat VERSION) -t sqlite-backup-sidecar:postgres16-dev .

test-container:
	BACKUP_TEST_IMAGE=sqlite-backup-sidecar:dev tests/test_container.sh

test-container-postgres16:
	BACKUP_POSTGRES_TEST_IMAGE=sqlite-backup-sidecar:postgres16-dev tests/test_postgres_container.sh
