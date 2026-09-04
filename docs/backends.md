# Storage backends

The sidecar passes repository and credential settings directly to Restic. Its own
validation only requires `RESTIC_REPOSITORY` and either `RESTIC_PASSWORD` or
`RESTIC_PASSWORD_FILE`.

Use a separate repository path and least-privilege storage credential for each
application environment. A Restic password encrypts data, but a storage
credential may still permit repository deletion.

## Local repository

```text
RESTIC_REPOSITORY=/repository
RESTIC_PASSWORD=<secret>
```

Mount durable storage at `/repository`. This is useful for testing and for a local
repository that another system replicates off-host. It is not an off-site backup
by itself.

## S3-compatible storage

```text
RESTIC_REPOSITORY=s3:https://s3.example.com/bucket/application/production
RESTIC_PASSWORD=<secret>
AWS_ACCESS_KEY_ID=<key-id>
AWS_SECRET_ACCESS_KEY=<secret-key>
```

Restic also honors provider-specific S3 settings such as region and path-style
options. Consult the Restic documentation for the chosen provider.

## Backblaze B2

Use either Restic's native B2 backend:

```text
RESTIC_REPOSITORY=b2:bucket-name:application/production
B2_ACCOUNT_ID=<key-id>
B2_ACCOUNT_KEY=<application-key>
```

or Backblaze's S3-compatible endpoint with the S3 variables above.

## Other Restic backends

SFTP, REST server, Azure Blob Storage, Google Cloud Storage, and rclone backends
work without sidecar-specific code. Provide the environment variables or mounted
credential files expected by Restic. Avoid placing credentials in an image or a
Compose file committed to source control.

## Repository initialization

`RESTIC_AUTO_INIT=true` is the default. A backup initializes a repository when it
cannot open one. Set it to `false` when repository creation should be a separate,
controlled operation.

`backup-sidecar doctor` does not initialize a repository. If auto-initialization is
enabled, it reports inaccessible or uninitialized storage as a warning so the
first backup can attempt initialization.
