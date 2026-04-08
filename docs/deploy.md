# Deploying ace-web

ace-web is deployed as a tenant service behind the connect-labs ALB on AWS ECS
Fargate, following the same pattern as scout.

Detailed deployment instructions are TBD — see the AWS migration plan at
`docs/plans/2026-04-08-aws-migration.md` (forthcoming) for the implementation
plan, and mirror the reference implementation at
`../connect-labs/.github/workflows/deploy-labs.yml` and scout's
`config/settings/connectlabs.py`.

## Local dev

```bash
docker compose up
```

The app binds to `http://localhost:8000` and uses a local Postgres container.
Auth is bypassed in development via Django's `force_authenticate` test client;
in production, ALB OIDC or CommCare Connect OAuth will handle it.
