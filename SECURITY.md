# Security Policy

Brewskers Pet Café handles staff accounts, sales records, and pet owner appointment details. It is a student project that nobody outside our group has audited, and we would not call it ready for a real shop as it stands. We built it carefully, take security reports seriously, and appreciate responsible disclosure.

## Supported versions

Only the latest commit on the `main` branch receives security fixes.

| Version         | Supported |
|-----------------|:---------:|
| `main` (latest) |    ✅     |
| older commits   |    ❌     |

## Reporting a vulnerability

**Please do not report security vulnerabilities through public GitHub issues, discussions, or pull requests.**

Instead, use one of these private channels:

1. **GitHub Private Vulnerability Reporting** (preferred): go to the repository's **Security** tab → **Report a vulnerability**.
2. **If that button is not available:** open an issue titled "Security: please get in touch" and leave the details out. We will reply and arrange a private way to talk.

Please include:

- A description of the vulnerability and its potential impact
- Steps to reproduce, or a proof of concept
- Affected files, routes, or pages
- Any suggested fix, if you have one

A short description is fine.

### What to expect

We are students working around classes, so these are best-effort targets.

| Step                            | Target timeframe                         |
|---------------------------------|------------------------------------------|
| Acknowledgement of your report  | within 14 days                           |
| Fix or mitigation plan          | as soon as we can, depending on severity |
| Public disclosure               | after a fix is available, coordinated with you |

We will credit reporters in the release notes unless you prefer to remain anonymous.

## Scope

**In scope**

- Authentication and session handling (login, lockout, "Keep me signed in", password reset)
- Role-based authorization bypass (reaching a page or API route your role should not allow)
- SQL injection, XSS, CSRF, and other injection flaws
- Exposure of staff accounts, sales, or appointment data, including through CSV, SQL, or database exports and backups
- Insecure defaults in the code or database setup

**Out of scope**

- Vulnerabilities in third-party dependencies with no demonstrable impact on this project (report those upstream)
- Attacks requiring physical access or an already-compromised server
- Denial of service through brute volume
- Social engineering of maintainers or users
- Anyone else's deployment of this code. Please do not attack other people's servers.

## Safe harbor

If you act in good faith, avoid accessing data that isn't yours, avoid degrading the service for others, and give us reasonable time to respond before disclosing, we will not pursue action against you.

> [!IMPORTANT]
> Please do not test against a database that holds someone else's real data.

## Known limitations and hardening checklist

If you deploy this project, **you are responsible for addressing the following** before exposing it to real users or data.

### Must fix before any real deployment

- [ ] **Default admin account.** The seeded account is `admin` / `12345678`, and anyone who has read this repository knows it. Change the password at first sign-in and create real staff accounts.
- [ ] **Production mode and secret key.** Set `APP_ENV=production` and a long random `SECRET_KEY` in `.env`. In production mode the app refuses to start with the default key.
- [ ] **Server.** Do not use `flask run` or `debug=True` on a public machine. Serve over HTTPS behind a production WSGI server.
- [ ] **Keep sensitive files out of Git.** `.env`, the database file, `backups/`, and `logs/` must never be committed. The `.gitignore` already skips them, but check before you push.
- [ ] **If something leaks.** If `.env` or a database ever gets committed, rotate the secret key and the Gmail app password, and change the staff passwords.
- [ ] **Handle exports like passwords.** The SQL and database downloads and the backups are full copies of the database, including password hashes and any live session tokens.

### Recommended improvements

These are known gaps in the current version.

- [ ] Hash session tokens and password reset codes before storing them. They are currently stored as plain values in the SQLite file, so anyone who can read the file can use them.
- [ ] Encrypt the SQLite file, or restrict access to it at the operating system level
- [ ] Move login rate limiting out of memory. It resets when the app restarts and does not work across several server processes.
- [ ] Add two-factor sign-in
- [ ] Password reset currently sends its code through Gmail with an app password kept in `.env`. Protect that file carefully.

### Good practices already in place

| Area              | What the app does |
|-------------------|-------------------|
| Passwords         | Stored hashed with a salt (Werkzeug). Older SHA-256 hashes are accepted once and upgraded at the next login. |
| SQL injection     | Every database query uses placeholders, so user input is never pasted into SQL. |
| CSRF              | Changes made through the API need a CSRF token, and requests from another origin are refused. |
| Brute force       | Five wrong passwords lock an account for 10 minutes. Login and password-reset requests are also rate limited per address. |
| Sessions          | Last 8 hours, or 30 days if "Keep me signed in" is ticked. Cookies are `HttpOnly` and `SameSite=Lax`, and `Secure` when `APP_ENV=production`. |
| Access control    | Every page and API route checks the user's role on the server. Hiding a button in the page is never the only protection. |
| Response headers  | Content-Security-Policy, `X-Frame-Options`, `nosniff`, and referrer headers. |
| Upload limits     | Uploads and request bodies are capped at 2 MB. |
| Password reset    | Reset codes expire after 5 minutes. |
| CSV exports       | Leave out password hashes, session tokens, and reset codes. |

## Data protection note

This system stores staff account details and appointment records that may include pet owners' personal information. Depending on where you operate, laws such as the Philippines' Data Privacy Act of 2012 (RA 10173), GDPR, or similar may apply. Anyone who deploys this software is responsible for compliance, including access controls, retention, and breach notification.
