# Draft email — Untappd API access request

Send to: **api.requests@untappd.com**

Before sending, fill in the placeholders marked `[...]` — see the checklist at
the bottom.

---

**Subject:** API access request — House of Beers (existing Untappd for Business customer)

Dear Untappd team,

I'm writing to request access to the Untappd API for House of Beers
(houseofbeers.nl), a specialist craft beer retailer in the Netherlands. We
understand API access now requires a commercial agreement, and we are happy to
enter into one.

**Our existing relationship with Untappd**

We are already an Untappd for Business customer and use the UTFB v1 API in
production to manage our menus and taplists (account: `info@gerijptebieren.nl`,
currently maintaining menus including "Taplijst 2e Paasdag Bier & BBQ House of
Beers"). That integration has been running reliably for [TIME PERIOD, e.g. "the
past two years"].

We also surface Untappd ratings across our webshop: roughly 2,900 of our
in-stock products display their Untappd rating and rating count, which we keep
current with a nightly sync. Untappd data is already a visible, valued part of
how our customers choose beer with us.

**What we would like to build**

We have launched a loyalty app for our existing customers ([Android on Google
Play, and an iOS web app at app.houseofbeers.nl]). We would like to let a
customer optionally connect their Untappd account so we can recommend beers
from our own inventory that match their taste — their preferred styles, ABV
range and breweries — rather than showing everyone the same generic list.

Concretely, we are requesting read access to:

    GET /v4/user/beers/{username}

This is the only endpoint we need. We do not need write access, check-in
posting, or any social/friend data.

**How we would use it, and why it is low-volume**

- **User-initiated and opt-in.** We only ever call the API for a user who has
  personally entered their own Untappd username in our app. Customers can
  unlink at any time.
- **Cached aggressively.** A taste profile is built once and cached for seven
  days. Taste changes slowly, so there is no need to re-read frequently.
- **Capped per profile.** We read at most 300 beers per user (6 calls at the
  50-per-call limit), which is more than enough for a reliable style and ABV
  profile.
- **Expected volume.** Our app serves a few hundred existing customers, of whom
  we expect a minority to link Untappd. We estimate on the order of
  [N] profile builds per week — comfortably inside the documented
  100 calls/hour limit, and we have rate-limit handling and backoff built in.
- **No redistribution.** The data is used solely to rank our own product
  catalogue for that individual user. We do not store or expose other users'
  check-in data, resell it, or make it available to third parties.

**Why we think this is a good fit for Untappd**

Our recommendations point customers toward beers they are likely to check in and
rate, and connecting an Untappd account becomes a visible benefit of having one.
We already drive attention to Untappd ratings across our webshop and in our
venue menus, and this would extend that into the app our most engaged customers
use.

We would be glad to discuss commercial terms, expected volumes, or any technical
or compliance detail that would help. If it is easier to handle this as an
extension of our existing Untappd for Business agreement, that works well for us
too.

Thank you for your time — we would very much like to keep building on Untappd.

Kind regards,

[YOUR NAME]
[ROLE], House of Beers
[EMAIL] | [PHONE]
houseofbeers.nl
UTFB account: info@gerijptebieren.nl

---

## Before you send — fill these in

| Placeholder | Notes |
|---|---|
| `[TIME PERIOD]` | How long the UTFB integration has been running. |
| Android / PWA line | Confirm the app is publicly live; if it is still in testing, say "launching shortly" instead — don't overstate it. |
| `[N] profile builds per week` | Your own estimate. Be honest and conservative; a small number *helps* here, since their stated concern is abuse. |
| Name, role, email, phone | — |

## Tips

- **Lead with the existing commercial relationship.** You are already a paying
  customer with a live integration, not a new unknown applicant. That is the
  single strongest point in this email.
- **Keep the "one endpoint, read-only, opt-in, cached" framing.** Their stated
  reason for restricting access is abuse; every one of those words is the
  opposite of abuse.
- **Do not send the API key** or any credential in the email.
- If you have figures for webshop traffic or app installs, adding one concrete
  number strengthens the case — but only real ones.
- If you get no reply in ~2 weeks, a short polite follow-up on the same thread
  is reasonable, and it is worth also asking your UTFB account contact, since
  an existing commercial channel often moves faster than a general inbox.
