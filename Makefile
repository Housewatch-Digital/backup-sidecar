.PHONY: test test-container test-container-postgres18 image image-postgres18

test:
	python3 -m unittest discover -s tests -v

image:
	docker build --build-arg VERSION=$$(cat VERSION) -t sqlite-backup-sidecar:dev .

image-postgres18:
	docker build --target postgres --build-arg POSTGRES_MAJOR=18 --build-arg VERSION=$$(cat VERSION) -t sqlite-backup-sidecar:postgres18-dev .

test-container:
	BACKUP_TEST_IMAGE=sqlite-backup-sidecar:dev tests/test_container.sh

test-container-postgres18:
	BACKUP_POSTGRES_TEST_IMAGE=sqlite-backup-sidecar:postgres18-dev tests/test_postgres_container.sh
