# Brynn Interactive 0.60.12 — Community Edition

Brynn Interactive is a local streaming companion for managing chat overlays,
alerts, goals, rankings, automations and supported platform integrations.

> **Status: community beta.** This build is intended to run locally on Windows.
> Do not expose the administration panel to the public Internet. The project
> still has security hardening work outstanding; see `SECURITY.md`.

## What is included

- Desktop application and local web panel.
- OBS Studio integration through OBS WebSocket.
- Browser overlays for chat, alerts, events, goals and ranking.
- Optional integrations for Twitch, TikTok LIVE/TikFinity, Kick, Streamlabs
  and Social Stream Ninja, depending on provider permissions and availability.
- Community setup guide: `GUIA_COMUNIDAD_Brynn_Interactive_0.60.12.txt`.

## Requirements

- Windows 10/11, 64-bit.
- OBS Studio for overlays and OBS control: <https://obsproject.com/>
- Optional external services: Social Stream Ninja, Streamlabs, TikFinity,
  Kick Developer tools and a secure HTTPS tunnel for inbound webhooks.
- Python 3.11+ only when running from source; see `requirements_desktop.txt`.

## Quick start

1. Download the repository ZIP or a published community release.
2. Extract it into a stable folder, for example `C:\BrynnInteractive`.
3. Read `LEEME_V0612.txt` and
   `GUIA_COMUNIDAD_Brynn_Interactive_0.60.12.txt`.
4. Run `instalar_desktop.bat` if required by your distribution.
5. Start with `iniciar_brynn_desktop.bat`.
6. Configure one integration at a time and test it before going live.

For source execution:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install --upgrade pip
py -m pip install -r requirements_desktop.txt
py desktop.py
```

## Important network safety rule

The local application panel normally listens on `127.0.0.1:8765`. Do **not**
publish or port-forward this port. If a platform needs to send webhooks to
your computer, configure a HTTPS tunnel only to the webhook receiver on
`127.0.0.1:8766`, and only for the routes documented by Brynn. Never tunnel
the admin panel. Keep OBS WebSocket passwords, OAuth secrets, webhook keys
and account tokens private.

## Data and privacy

User-specific data belongs in the user's local application-data directory,
not in this repository. Before publishing changes, verify that no credentials,
account identifiers, chat logs, personal data, backups or private media were
added. Do not commit `%APPDATA%\\BrynnInteractive` or local `.env` files.

## Integrations

Platform integrations depend on third-party APIs, scopes, terms, regional
availability and provider changes. A local simulated event does not prove a
real platform webhook is configured correctly. Consult the community guide
for step-by-step setup and troubleshooting.

## Contributing

Please read `CONTRIBUTING.md` before opening a pull request. Report security
issues privately as described in `SECURITY.md`, rather than posting secrets
or exploit details in a public issue.

## License

No open-source license is included in this community preparation package.
Until the project owner selects and adds a license, all rights remain
reserved; publishing the source on GitHub does not by itself grant permission
to reuse, modify or redistribute it.
