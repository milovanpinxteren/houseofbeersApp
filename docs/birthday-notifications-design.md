# Design: notification delivery + birthday rewards

Status: **design, not yet built.**

Two things, deliberately separated:

1. **A reusable notification delivery system** — push first, email fallback.
   This is the foundation, and announcements and personalised
   recommendations will sit on it later.
2. **The birthday reward feature** — the first consumer of that system.

## Decisions already taken

| Decision | Choice |
|---|---|
| Birthdate editing | Freely editable until the first gift is issued, then locked in-app (admin can still correct) |
| Reward | Shopify discount code |
| Delivery | Push, with email fallback when push fails or is unavailable |
| Data stored | Full date, validated 18+ |
| Under-18 | **Rejected outright** — validation fails, and registration is blocked too (not merely excluded from gifts) |
| Email policy | **Per-kind** (see table below) rather than emailing every message |
| Push failure detection | **A separate scheduled run** reads delivery receipts, rather than trusting the send-time response |

---

# Part 1 — Notification delivery system

## One channel: Web Push

The Play Store listing is being retired — every customer uses the PWA at
app.houseofbeers.nl. That removes an entire half of this design:

- **No Expo Push, no FCM credentials, no Firebase project, no
  `google-services.json`, no service account key.** All of that exists only
  to serve a native Android binary we will no longer ship.
- **No `expo-notifications`.** It does not implement web push; the standard
  browser Push API is used directly.
- **No app store release to ship push.** Notifications arrive with an
  ordinary Netlify deploy. This is a significant win: no build, no review, no
  waiting for users to update.

(Android Chrome does route web push through FCM internally, but that is the
browser's business — it needs VAPID keys, not Firebase credentials.)

### Where push actually works

| Platform | In a browser tab | Installed to home screen |
|---|---|---|
| Android Chrome | yes | yes |
| **iOS / iPadOS Safari 16.4+** | **no** | yes |
| Desktop Chrome / Edge / Firefox | yes | yes |

**iOS is the only platform that requires installation**, and it requires it
absolutely — in a Safari tab there is no permission prompt at all. Android
users get push whether or not they install. So driving PWA installs is
really an iOS-reach problem, and email covers whoever never installs.

### Client foundation is already built

`public/service-worker.js` already implements `push` and `notificationclick`
(handling `{title, body, url}`), it is registered from `public/index.html`,
and `icons/badge-72.png` exists. What remains client-side is only:
request permission → `pushManager.subscribe()` → POST the subscription.

### Three browser constraints that shape the UX

1. **Permission must come from a user gesture** on iOS — a tap on an
   "Enable notifications" button, never an automatic prompt on load.
2. **A denial is permanent.** Once refused, the prompt cannot be shown
   again programmatically; the user has to change it in system settings. So
   ask at a moment of obvious value — for example straight after they save
   their birthdate ("want a reminder when your gift arrives?") — rather than
   on first launch, where it is usually dismissed.
3. **Subscriptions are lost** when a user removes and re-adds the PWA, and
   can expire on their own. The client should re-subscribe on every launch
   and upsert by `endpoint`, so a stale record is replaced rather than
   duplicated.

## Models

```
PushSubscription
  user            FK
  endpoint        TEXT   UNIQUE      # identifies the browser+device install
  p256dh, auth    subscription keys
  device_label    e.g. "iPhone Safari", "Chrome on Android"
  is_active       deactivated on 404/410 from the push service
  failure_count
  last_success_at, last_seen_at, created_at

NotificationPreference          # one per user
  push_enabled, email_enabled
  birthday, announcements, recommendations     # per-category opt-out

NotificationDelivery            # the outbox — one row per message per user
  user            FK
  kind            'birthday_gift' | 'announcement' | ...
  title, body
  data            JSON: deep link, discount code, ...
  dedupe_key      UNIQUE
  push_status     pending | sent | failed | skipped
  email_status    pending | sent | failed | skipped
  push_error, email_error
  created_at, sent_at
```

`dedupe_key` is the reliability primitive. Every send is idempotent on it
(e.g. `birthday:42:2026`), so a retried task, an overlapping beat run, or a
worker restart mid-send cannot produce a duplicate message.

## Send flow

```
send(user, kind, title, body, data, dedupe_key)
  1. get_or_create NotificationDelivery on dedupe_key  → already sent? stop.
  2. respect NotificationPreference for `kind`         → opted out? skip.
  3. push to every active PushSubscription for that user
  4. apply the per-kind email policy (below)
  5. record per-channel outcome on the delivery row
```

### Verifying delivery in a separate run

Web push is queued, not delivered, at send time. A `202 Accepted` from the
push service means it took the message — not that a phone showed it. Two
stages, as agreed:

- **At send time:** no active subscription, or an immediate hard error →
  fall back to email now.
- **In a separate scheduled run:** re-check subscriptions and retire dead
  ones. `404`/`410` from the push service means the subscription is gone for
  good (PWA deleted, permission revoked) → deactivate it. Repeated `5xx`
  increments `failure_count` and deactivates past a threshold.

Without that second stage, dead subscriptions accumulate and quietly swallow
messages while every send still looks successful. Anyone whose subscription
died then falls into the email path on the next send, which is the correct
outcome.

### Email policy per kind

Fallback should not mean "email everything" — that is how people learn to
ignore you.

| Kind | Push | Email |
|---|---|---|
| `birthday_gift` | yes | **always** — a discount code belongs in an inbox where it can be found later |
| `announcement` | yes | only when the user has no working push channel |
| `recommendations` | yes | never |
| transactional (order/reward) | yes | always |

Birthday deliberately sends both. The push is the moment; the email is the
receipt.

### Quiet hours

Sends are scheduled for a civil local hour (default 09:00 Europe/Amsterdam),
never "whenever the cron fired". Celery already runs on that timezone.

---

# Part 2 — Birthday rewards

## Data

```
User (or a profile model)
  birthdate           DATE     null=True       # optional
  birthdate_set_at    DATETIME null=True       # when it was last set

BirthdayReward
  user            FK
  year            INT
  discount_code   CHAR
  expires_at      DATETIME
  issued_at       DATETIME
  delivery        FK NotificationDelivery null=True
  unique_together (user, year)
```

`unique_together (user, year)` is the hard guarantee that nobody receives two
gifts in one year, regardless of task retries or races.

## Anti-abuse: three rules working together

| Attack | Rule that stops it |
|---|---|
| Set birthday to today, claim immediately | **Lead time** — the gift only issues if `birthdate_set_at` is at least 30 days before the birthday |
| Claim, change the date, claim again | **One reward per calendar year** (DB constraint) |
| Shift the date every year to suit | **Locked once the first gift is issued** |

Net effect: an honest customer sets it once and forgets. The worst outcome
for someone gaming it is their one normal yearly gift, slightly early — after
which they are locked to a date they invented.

The birthdate stays editable while
`BirthdayReward.objects.filter(user=user).exists()` is false. That forgives
the fat-fingered date picker without ever letting an edit produce a gift
sooner.

## Validation when setting the date

- A real, parseable date.
- **Age ≥ 18 — hard rejection.** We sell alcohol, so an under-18 date is not
  merely ineligible for a gift: the validation fails. Applied in the
  serializer so it holds for every caller, not just the profile screen.
- Age ≤ 120 (plausibility).
- Rejected with a clear reason, never silently ignored.

**Under-18 is also blocked at registration.** Once the app knows a date of
birth, quietly continuing to sell alcohol to a self-declared minor is worse
than not asking at all. Two consequences to handle deliberately:

- If birthdate is collected at registration, it stops being optional there —
  decide whether it is a required signup field or an optional profile field
  that rejects under-18 values when supplied.
- Existing accounts have no birthdate. They stay usable; the check only
  applies when a date is set. No retroactive lockout.

## Being honest in the UI

Two states must be explained or the feature reads as broken:

- **Set inside the 30-day window:** say so — "your first gift arrives next
  year." Silently skipping them generates support tickets.
- **The lock:** "You can set this once. It unlocks a gift every year —
  contact us if it needs correcting." Stated up front, this reads as fair
  rather than sneaky.

## Daily job

```
birthday_scan                       # beat, hourly; acts at configured send hour
  users whose (day, month) == today
    OR whose birthday fell in the last 3 days with nothing issued   # catch-up
  skip if a BirthdayReward exists for this year
  skip if birthdate_set_at > birthday − lead_time_days
  create a Shopify discount code (single use, expiring)
  create BirthdayReward                       # unique constraint = idempotent
  enqueue NotificationDelivery(dedupe_key=f"birthday:{user_id}:{year}")
```

The **catch-up window** matters: without it, anyone whose birthday lands
during an outage silently receives nothing, and nobody ever finds out.

**29 February:** celebrate on 28 February in non-leap years.

## Admin-tunable config

So the business can tune the offer without a deploy:

```
BirthdayRewardConfig
  is_active
  discount_type        fixed_amount | percentage
  discount_value
  validity_days        how long the code lives      (default 30)
  lead_time_days       anti-abuse window            (default 30)
  minimum_age                                       (default 18)
  send_hour            local hour to send           (default 9)
```

## Required change to the Shopify service

No existing discount path sets an expiry. `create_discount_code` /
`create_basic_discount` need an `ends_at` parameter (Shopify GraphQL
`endsAt`). A birthday code that never expires cheapens the gift and lingers
as an open liability.

## Customers with no linked Shopify account

Such a code cannot be locked to a customer. It can still be issued with
`usage_limit=1`, which bounds the exposure precisely: even if shared, exactly
one discount is redeemed — the same cost as the gift we intended. So a linked
Shopify customer is a nice-to-have here, not a blocker.

---

# Build order

Web push is no longer a later phase — it is the only channel, so it comes
first. Nothing here needs an app store release.

1. **Delivery core** — `PushSubscription`, `NotificationPreference`,
   `NotificationDelivery` outbox, VAPID + `pywebpush` sender, subscription
   registration endpoint, per-kind email policy, and the separate
   subscription-health run.
2. **Client subscribe flow** — permission request behind a user gesture,
   `pushManager.subscribe()`, POST to the backend, re-subscribe and upsert on
   every launch. The service worker already handles receipt and clicks.
3. **Birthday feature** — birthdate field, 18+ validation, the lock, config
   model, Shopify `ends_at`, daily job with catch-up.
4. **Retrofit** announcements and recommendations onto the same system.

Steps 1–3 ship together via an ordinary Netlify + Dokku deploy.

# Prerequisites outside the code

## VAPID keys — the only credential needed

With the PWA as the sole client, there is **no Firebase project, no FCM
credential and no Apple push certificate**. Web push authenticates with a
single VAPID keypair that we generate ourselves.

```bash
# generated once, e.g. via the py-vapid CLI that ships with pywebpush
vapid --gen
```

| Key | Where it lives | Secret? |
|---|---|---|
| Private | Dokku config on the backend (`VAPID_PRIVATE_KEY`) | **Yes** |
| Public | shipped to the browser as `EXPO_PUBLIC_VAPID_PUBLIC_KEY` | No — public by design |

Plus a `VAPID_SUBJECT` (a `mailto:` contact, required by the spec so push
providers can reach us).

Server dependency: **`pywebpush`**.

Do not regenerate the keypair casually — changing it invalidates every
existing subscription, and every user would have to re-grant permission.

## Retiring the Play Store listing

Existing Android app users will not migrate automatically. Before delisting,
they need telling to open app.houseofbeers.nl and install the PWA — the
in-app notification system already in the app is the natural way to reach
them while it still works.

Worth confirming Google Play's rules on removing a published app, and
whether existing installs keep working (they generally do, but stop
receiving updates).

## Other prerequisites

- A decision on the **discount value and expiry** — though defaults in
  `BirthdayRewardConfig` mean this does not block the build.

# Remaining question

Is the birthdate a **required field at registration**, or an optional profile
field that rejects under-18 values whenever it is supplied?

Requiring it enforces the age rule for everyone but adds friction to signup
and makes the data mandatory rather than optional. Keeping it optional means
customers who never fill it in are never age-checked — the rule only bites
when a date is given. This is a business/compliance call rather than a
technical one; the validation logic is identical either way.
