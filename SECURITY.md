# Security policy

## Current status

Brynn Interactive 0.60.12 Community is a beta intended for local use.
The project has known security-hardening work remaining. In particular,
do not expose the administration panel (`127.0.0.1:8765`) to the Internet
or port-forward it from your router.

## Reporting a vulnerability

Do not publish access tokens, webhook secrets, passwords, personal data,
or exploit instructions in public issues. Until a private security contact
is configured for this repository, contact the project maintainer through
the private channel they provide.

## Credential handling

- Never commit OAuth tokens, client secrets, OBS passwords, webhook keys,
  Social Stream Ninja session credentials or private configuration files.
- Revoke and rotate any credential that has been committed or shared.
- Use HTTPS for externally delivered webhooks.
- Keep webhook tunneling restricted to the documented receiver routes.
