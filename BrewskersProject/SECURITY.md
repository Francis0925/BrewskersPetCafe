# Security

Brewskers is a student project. Nobody outside our group has audited it, and we would not call it ready for a real shop as it stands. We did try to build it carefully, and this page says honestly what is covered and what is not.

## Reporting a problem

If you find a security problem, please tell us before posting it publicly.

- Best: use the **Report a vulnerability** button on the Security tab of this repository. That sends it to us privately.
- If that button is not available, open an issue titled "Security: please get in touch" and leave the details out. We will reply and sort out a private way to talk.

Tell us what you did, what you expected and what happened instead. A short description is fine. We are students working around classes, so a reply can take a week or two, but we will read everything. Only the latest version on the main branch is looked after.

Please do not test against a database that holds someone else's real data, and do not go after anyone's server just because it runs this code.

## What is in place

- Passwords are stored hashed (Werkzeug), with a salt. Older SHA-256 hashes are accepted once and upgraded at the next login.
- Every database query uses placeholders, so user input is never pasted into SQL.
- Changes made through the API need a CSRF token, and requests from another origin are refused.
- Five wrong passwords lock an account for 10 minutes. Login and password-reset requests are also rate limited per address.
- Sessions last 8 hours, or 30 days if "Keep me signed in" is ticked. Cookies are HttpOnly and SameSite=Lax, and Secure when `APP_ENV=production`.
- Every page and API route checks the user's role on the server. Hiding a button in the page is never the only protection.
- Responses carry a Content-Security-Policy, X-Frame-Options, nosniff and referrer headers. Uploads and request bodies are capped at 2 MB.
- Password reset codes expire after 5 minutes.
- In production mode the app refuses to start with the default secret key.
- The CSV exports leave out password hashes, session tokens and reset codes.

## Known gaps

We would rather you hear these from us.

- **The seeded admin account is `admin` / `12345678`.** Change it the first time you sign in. Anyone who has read this repository knows it.
- The SQL and database downloads (and the backups) are full copies of the database. They include password hashes and any live session tokens. Treat them like passwords and never commit them.
- Session tokens and password reset codes are stored as they are in the SQLite file, not hashed. Whoever can read the database file can use them.
- The SQLite file itself is not encrypted.
- Login rate limiting is kept in memory, so it resets when the app restarts and does not work across several server processes.
- There is no two-factor sign-in.
- Password reset sends the code by Gmail, using an app password you put in `.env`.

## If you run it somewhere real

1. Set `APP_ENV=production` and a long random `SECRET_KEY` in `.env`.
2. Serve it over HTTPS behind a production WSGI server. Do not use `flask run` or `debug=True` on a public machine.
3. Change the admin password and create real staff accounts.
4. Keep `.env`, the database file, `backups/` and `logs/` out of Git. The `.gitignore` already skips them, but check before you push.
5. If `.env` or a database ever gets committed, rotate the secret key and the Gmail app password, and change the staff passwords.
