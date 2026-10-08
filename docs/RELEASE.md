# Release checklist

1. Confirm `development` is current and the worktree is clean.
2. Review migrations in both upgrade and downgrade directions on disposable data.
3. Run backend, frontend and Compose validation suites.
4. Review dependency and container image changes for security impact.
5. Verify production secrets exist without printing their values.
6. Back up PostgreSQL and record the restore command before deployment.
7. Deploy the migration job, API, worker, beat, frontend and edge proxy.
8. Check liveness, readiness, worker ping and one safe mock publication.
9. Tag the reviewed commit and retain the previous image for rollback.
