# Authentication & Credentials

## Patreon Account

- **Email**: footballstars33@gmail.com
- **Windows Credential Manager entry**: `patreon_02_ai`
  - Stored on the obs-machine (Matt@100.66.194.100)
  - Retrieve via PowerShell: `(Get-StoredCredential -Target patreon_02_ai)`
  - Or via cmdkey: `cmdkey /list:patreon_02_ai`
- **Chrome profile**: Session cookies persist in `C:\Users\Matt\agent-control\chrome-profile\` on the obs-machine
- **No 2FA/SSO** required for this account
- **Purpose**: Subscribing to and recording FIRED Up Wealth Patreon content for personal transcription

## Notes
- If the Chrome session expires, re-login by launching Chrome to https://www.patreon.com/login on the obs-machine
- Credentials should NEVER be hardcoded in scripts — use Windows Credential Manager or the persisted browser session
