# Kubernetes deployment

Run the image as a CronJob when the application and backup pod can mount the same
persistent volume. The example below assumes `ReadWriteMany` storage. A
`ReadWriteOnce` volume may not be attachable to both pods at once, depending on
the storage driver and node placement.

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: application-sqlite-backup
spec:
  schedule: "0 * * * *"
  concurrencyPolicy: Forbid
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: backup
              image: ghcr.io/housewatch-digital/backup-sidecar:0.1.1
              args: ["run"]
              env:
                - name: BACKUP_NAME
                  value: application-production
                - name: SQLITE_DATABASES
                  value: /source/application.db
                - name: RESTIC_REPOSITORY
                  valueFrom:
                    secretKeyRef:
                      name: application-backup
                      key: repository
                - name: RESTIC_PASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: application-backup
                      key: password
              volumeMounts:
                - name: application-data
                  mountPath: /source
                  readOnly: true
                - name: state
                  mountPath: /state
                - name: stage
                  mountPath: /stage
                - name: cache
                  mountPath: /cache
          volumes:
            - name: application-data
              persistentVolumeClaim:
                claimName: application-data
            - name: state
              persistentVolumeClaim:
                claimName: application-backup-state
            - name: stage
              emptyDir: {}
            - name: cache
              emptyDir: {}
```

Add storage-provider credentials from Kubernetes Secrets. Keep `/state`
persistent when health and last-run records must survive Job replacement. The
staging directory only needs enough temporary space for one complete backup.

Use a separate Job with an empty restore volume for rehearsals. Never point
`RESTORE_ROOT` at the live claim.
