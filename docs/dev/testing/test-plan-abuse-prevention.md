# Test Plan: Sign-in Abuse Prevention (#158)

The sign-in abuse-prevention machinery (rate limits, verify cooldown, coalesced
alerting, unsubscribe/re-subscribe, `List-Unsubscribe`) is **off in normal local
development** and **off under the automated suite** (the automated behaviour is
covered by unit tests). This document is for exercising it **by hand** in a
running local app, using a settings module that turns it on and makes its
effects observable from the console.

## Prerequisites

- **A real local Redis at `127.0.0.1:6379`.** `runserver` uses the real Redis
  client (only `manage.py test` swaps in fakeredis). Without Redis the limiter
  **fails open** and nothing throttles. Confirm with:

  ```bash
  redis-cli ping        # -> PONG
  ```

- Run the app with the manual-test settings (`ucfp/settings/test_local_abuse.py`,
  which extends `development.py`):

  ```bash
  ./src/manage.py runserver --settings=ucfp.settings.test_local_abuse
  ```

  All email is printed to the terminal running the server (console backend), so
  keep it visible — sign-in codes, admin alerts, unsubscribe links, and email
  headers all appear there.

## Limits configured for manual testing

`test_local_abuse.py` sets deliberately small limits so each is reachable by hand:

| Limit | Value |
|---|---|
| Sign-in per IP (per hour) | **3** |
| Sign-in per email (per hour) | **2** |
| Sign-in per email (per day) | 4 |
| Global sign-in emails (per hour) | 10 |
| Verify: free attempts (no cooldown) | **1** |
| Verify: first cooldown | **3s** (doubling, cap 10s) |
| Verify: hard failure cap | **3** |
| Verify per-IP backstop (per hour) | 8 |

## Resetting between scenarios

- **Rate-limit and alert counters** live in Redis with per-window TTLs. To reset
  immediately instead of waiting out a window:

  ```bash
  redis-cli flushdb
  ```

- **The verify cooldown is per browser session.** Open a fresh
  incognito/private window (or clear cookies) to reset it.
- A **coalesced alert** suppresses repeats for an hour; `redis-cli flushdb` lets
  you re-trigger one immediately.

---

## Scenarios

Local requests come from `127.0.0.1`, so the per-IP limit applies to everything
you send from one browser. Use **distinct emails** when you want to reach the
per-IP limit, and a **single email** when you want to reach the per-email cap.

### 1. Sign-in per-IP throttle

1. `redis-cli flushdb`, then go to `/user/signin`.
2. Submit **three different** emails (`a@x.test`, `b@x.test`, `c@x.test`). Each
   shows the "check your email" page and prints a **sign-in code email** to the
   console.
3. Submit a **fourth** distinct email (`d@x.test`).

**Expected:** the fourth still shows the neutral "check your email" page, but **no
code email is printed** (throttled), and a single **admin alert email**
(`abuse alert: signin-per-ip`) prints to the console.

### 2. Per-email cap

1. `redis-cli flushdb`, then submit the **same** email twice (per-email hourly = 2).
   Both send a code.
2. Submit that same email a **third** time.

**Expected:** neutral page, **no third code email**, and an admin alert
(`signin-per-email-hour`) prints once.

### 3. Verify cooldown + hard cap

1. `redis-cli flushdb`; sign in once and copy the **access code** from the code
   email in the console.
2. On the code page, submit a **wrong** code. → "Invalid sign-in code" (free
   attempt, no wait).
3. Submit a wrong code again. → "Invalid sign-in code", and a **3s cooldown** now
   applies.
4. **Immediately** submit again. → "Too many attempts. Please wait a few seconds
   and try again." (HTTP 429; the code is not even checked).
5. Wait ~3s and submit a wrong code again. → this is the **third failure**: "Too
   many attempts. Please start a new sign-in." The code is now **invalidated** —
   even the *correct* code no longer works; you must restart sign-in.

### 4. Verify per-IP backstop

1. `redis-cli flushdb`; in one session submit wrong codes past the per-IP backstop
   (8/hour). To avoid the per-session cooldown stopping you first, clear
   cookies/use fresh incognito windows between attempts (the backstop is per IP,
   which is shared across your sessions).

**Expected:** once over 8 attempts from `127.0.0.1`, requests are rejected (429)
and an admin alert (`verify-per-ip`) prints once.

### 5. Coalesced admin alerts

1. Re-run scenario 1 but keep submitting past the fourth email.

**Expected:** the admin alert email prints **only once** per limit type within the
hour, regardless of how many times you trip it. Distinct types (`signin-per-ip`,
`signin-per-email-hour`, `verify-per-ip`) each alert once. `redis-cli flushdb`
lets you trigger a fresh one.

### 6. Unsubscribe → graceful sign-in → re-subscribe round-trip

1. `redis-cli flushdb`; sign in with `victim@x.test` and open its code email in
   the console. Note the **Unsubscribe** link in the footer (and the
   `List-Unsubscribe` header — see scenario 8).
2. Open the unsubscribe URL in the browser. → "You have been unsubscribed" page,
   which states it **also stops sign-in codes** and offers **Re-enable emails**.
3. Try to sign in again with `victim@x.test`. → instead of a dead end, the
   **"Emails are turned off for this address"** page appears with a **Re-enable
   emails** button.
4. Click **Re-enable emails**. → "Emails re-enabled" page.
5. Sign in again with `victim@x.test`. → a code email prints again.

### 7. One-click unsubscribe (POST)

Take a code email's unsubscribe URL and POST to it (what a mail client does for
one-click):

```bash
curl -i -X POST 'http://127.0.0.1:8000/notify/email/unsubscribe/<token>/<email>'
```

**Expected:** `HTTP 200`, and the address is now unsubscribed (a subsequent
sign-in shows the graceful re-enable page).

### 8. `List-Unsubscribe` headers

In the console output for a **sign-in code** email, confirm the headers:

```
List-Unsubscribe: <http://127.0.0.1:8000/notify/email/unsubscribe/...>
List-Unsubscribe-Post: List-Unsubscribe=One-Click
```

In an **admin alert** email (a system message), confirm these headers are
**absent**.

### 9. Fail-open when Redis is down

1. Stop Redis (`redis-cli shutdown nosave`, or stop the service).
2. Submit many sign-ins.

**Expected:** everything proceeds normally — **no throttling, no lockout** (the
limiter fails open). Restart Redis afterward.

### 10. Regression: off by default in plain development

Run the app with the normal development settings:

```bash
./src/manage.py runserver
```

**Expected:** no throttling, no cooldown, no admin alerts — the feature is inert
in ordinary local development.

---

## Notes & known gaps

- The graceful "this address is unsubscribed" sign-in page is shown by email, so
  it is a minor way to learn whether a given address has unsubscribed. This is an
  accepted trade-off for giving a real user a way back in; revisit if it matters.
- Update this plan if manual testing surfaces gaps or the limits change.
