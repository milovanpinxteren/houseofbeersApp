# Untappd integration — diagnosis and fixes

Investigated 2026-07-29 using the account `milovanp`, comparing the working
integration in `houseofbeers_whatsapp` against the broken one in
`Beer_recommender`.

**Summary:** there were three separate problems, not one. Two are fixed and
verified. The third is not a bug and cannot be fixed by changing our requests —
Untappd now requires a login for user beer lists.

---

## Problem 1 — Recommendations were empty for every user (FIXED)

**This was the big one, and it had nothing to do with Untappd blocking us.**

The recommendation engine only considers beers that have an Untappd rating
(`recommendation_engine.py:303`):

```python
queryset = queryset.filter(untappd_rating__isnull=False)
```

Measured on the live catalog: **0 of 2,900 in-stock beers had a rating**, so that
filter emptied the queryset and every user got `recommendations: []`,
`discovery_picks: []`, `tried_beers: []` — regardless of profile source.

### Root cause: a metafield key mismatch

The WhatsApp app's nightly sync writes the rating to Shopify as
`custom.untappd_rating`. Beer_recommender was reading `custom.untappd_score`.

Verified against live Shopify data (25-product sample):

| Metafield key | Present on |
|---|---|
| `custom.untappd_rating` (what the sync **writes**) | **23/25 products** (92%), last synced 2026-07-26 |
| `custom.untappd_score` (what the recommender **read**) | **0/25 products** |

The nightly rating sync has been working correctly the whole time. The
recommender was just reading a key that does not exist.

A second bug sat directly underneath it: `_parse_rating_value` assumed a JSON
object (`{"value": 4.37}`), but the sync writes a plain `number_decimal` string
(`"4.37"`). `json.loads("4.37")` returns a float, and calling `.get()` on it
raises `AttributeError` — which was **not** in the caught exception list, so even
with the right key it would have crashed.

### Fix (`Beer_recommender/recommendations/services/shopify_sync.py`)

- Read `custom.untappd_rating`, falling back to `custom.untappd_score` for
  backwards compatibility.
- `_parse_rating_value` now accepts both the plain decimal string and the legacy
  JSON object, and returns `None` instead of raising on anything unexpected.
- Raised `metafields(first: 20)` to `first: 50`. Products currently carry up to
  18 metafields with the rating sitting at index 13–16 — two more fields on any
  product and ratings would have silently vanished again.

### Verified

Running the recommender's own sync service against live Shopify data:

```
products with untappd_rating after fix: 179/200 (89.5%)
  (before the fix: 0.0%)

examples:
  4.37  (16083 ratings)  Goose Island Bourbon County 2023 Stout - 47.3 CL
  4.5   (8302 ratings)   Goose Island Bourbon County Angel's Envy 2023 Stout
  4.18  (19869 ratings)  Goose Island Bourbon County Backyard Stout 2023
```

**Recommendations will work again for all users once this is deployed and a
product sync has run.**

---

## Problem 2 — The scraper silently parsed nothing (FIXED)

The Beer_recommender scraper sent a full browser impersonation header set
(`Sec-Ch-Ua`, `Sec-Fetch-*`, `Upgrade-Insecure-Requests`, `Cache-Control`, …).
The WhatsApp app's working scraper sends only three headers.

Two things were wrong with the elaborate version:

1. It advertised `Accept-Encoding: gzip, deflate, br` while the `brotli` package
   is not installed, so Untappd's brotli responses came back as undecodable
   bytes. Every page silently parsed to nothing — `title=None`, `stats=[]`.
2. Claiming to be Chrome 137 in headers while presenting Python's TLS
   fingerprint is a mismatch that anti-bot filtering keys on, and it bought
   nothing.

### Fix (`Beer_recommender/recommendations/services/untappd_scraper.py`)

Adopted the WhatsApp app's minimal header set (`Accept`, `Accept-Language`,
`User-Agent`). Leaving `Accept-Encoding` unset lets `requests` advertise only
what it can actually decode, so no `brotli` dependency is needed.

Also: `get_or_create_profile()` no longer caches an empty scrape as
`is_valid=True`. That was what made the failure silent and persistent — a broken
profile was served from cache for the whole TTL with no error anywhere.

### Verified

| | Before | After |
|---|---|---|
| `check_profile_exists('milovanp')` | garbage → wrongly "OK" | `True, 'OK'` |
| `_fetch_profile_stats('milovanp')` | `{0, 0}` | **`{'total_checkins': 1122, 'unique_beers': 1119}`** |
| nonexistent user | unreliable | clean `Profile not found` |

---

## Problem 3 — User beer lists now require a login (NOT fixable by us)

This is the one that actually broke the taste wheel, and it is **not** a bot
block. Untappd made user beer lists authentication-gated:

```
GET https://untappd.com/user/milovanp        -> 200  (public)
GET https://untappd.com/user/milovanp/beers  -> 307  Location: /login?go_to=...
```

The `/beers` pages — the source of every style, ABV, brewery and tried-beer
datapoint — return **307 redirect to `/login`**. The "Just a moment..."
Cloudflare page we first saw was on the *login page* the redirect lands on, which
is what made this look like bot filtering.

This was tested exhaustively before reaching that conclusion: minimal headers,
full browser headers, warmed sessions with cookies and `Referer`, and TLS
fingerprint impersonation as chrome, chrome131, chrome124, safari17_0, edge101
and firefox133. Every single one redirects to login. **No change to how we shape
the request can fix this** — the data is simply no longer public.

Note the asymmetry that explains why the WhatsApp app is unaffected: it scrapes
**beer** pages (`/b/...`), which are still public and work fine. Only **user**
pages are gated.

### Solution: the official API `user/beers` endpoint (IMPLEMENTED, needs a key)

`GET https://api.untappd.com/v4/user/beers/<username>` returns exactly the data
the `/beers` page used to provide. Confirmed against the live API:

```
$ curl 'https://api.untappd.com/v4/user/beers/milovanp'
{"meta":{"code":500,"error_detail":"Your missing the 'client_secret' and/or
 'client_id' parameter","error_type":"invalid_param"}}
```

"Does not need authentication" in the docs means it needs **no per-user OAuth
login** — users still just type their username, exactly as today. It does need
**application** credentials (`client_id` + `client_secret`), which is one key for
the whole service.

**This is now implemented** in `Beer_recommender`:

- `recommendations/services/untappd_api.py` — `UntappdAPIClient`: paginated
  fetch (50/call), maps API items onto the same `CheckIn` shape the profile
  builder already consumes, distinguishes rate limiting from "user not found",
  and treats an unrated beer (`rating_score: 0`) as `None` so it does not drag
  down rating averages.
- `untappd_scraper.py` — `build_taste_profile()` and `check_profile_exists()`
  use the API automatically **when credentials are present**, and fall back to
  the old scraping path when they are not. No code change needed to switch over.
- A rate-limit error never marks a profile invalid (it would otherwise lock the
  user out for the whole cache TTL); stale cached data is served instead.

Verified with a mocked API (9 tests): parsing, pagination stopping at
`total_count`, the `max_beers` cap, unrated-beer handling, rate-limit
propagation, user-not-found, and an end-to-end `build_taste_profile` producing
correct style categories (`"Stout - Imperial"` → `Stout`) and ABV preferences.

**To activate:** register an app at
`https://untappd.com/api/register?register=new`, then set on the recommender:

```bash
UNTAPPD_CLIENT_ID=...
UNTAPPD_CLIENT_SECRET=...
```

### Rate limit — the one thing to plan around

The API allows **100 calls/hour per key**, max 50 beers per call. Budget:

| `UNTAPPD_API_MAX_BEERS` | Calls per profile | Profiles/hour | Profiles/day |
|---|---|---|---|
| 150 | 3 | 33 | 792 |
| **300 (default)** | **6** | **16** | **384** |
| 500 | 10 | 10 | 240 |

Because of this, `CachedUserProfile.is_expired()` now defaults to
`UNTAPPD_PROFILE_CACHE_HOURS` = **168 hours (7 days)** instead of 24. Taste
profiles change slowly, and a 24-hour TTL across a few hundred linked users
would have burned the entire daily quota on refreshes. Profile builds should
stay on the existing Celery path, never inline in a web request.

If a large number of users link Untappd at once, lower `UNTAPPD_API_MAX_BEERS`
to 150 — a taste profile converges well before 300 beers.

### What is still public without API access (measured 2026-07-29)

Probed with the working header set, to answer "can we build a profile while we
wait for API access?"

| Path | Result |
|---|---|
| `/user/<name>` | **200 public** |
| `/user/<name>/wishlist` | 200, but renders **0 beers** — no usable signal |
| `/user/<name>/beers` | 307 → login |
| `/user/<name>/badges` | 307 → login |
| `/user/<name>/venues` | 307 → login |
| `/user/<name>/stats` | 307 → login |
| `/user/<name>/lists` | 307 → login |
| `/user/<name>/friends` | 307 → login |
| `/profile/more_feed/<id>/0` (activity pagination) | 307 → homepage |
| `/b/<slug>/<id>` (beer pages) | **200 public** — style, ABV, global rating |

The public profile page yields only:

- headline stats (e.g. 1,122 check-ins, 1,119 unique beers) with **no**
  style/ABV/brewery breakdown, and
- the **5 most recent check-ins** — beer name, brewery and the user's own rating,
  but no inline style (each would need a separate beer-page fetch).

**Five beers is not enough to build a taste profile.** The engine requires at
least 2 rated beers in a style before it counts as preferred
(`get_preferred_styles(min_count=2)`), so 5 beers spread across styles typically
qualifies zero of them, and the radar chart needs several axes. The result would
be an empty or actively misleading taste wheel.

**Conclusion: rely on the Shopify order-history fallback until API access is
granted.** It is already live and produces a genuine profile.

A theoretical alternative — polling each linked user's public profile daily and
accumulating those 5 recent check-ins over weeks — would eventually build real
history, but it only captures *new* drinking (never the existing 1,119 beers),
takes months to become useful, and costs a request per user per day. Not worth
building as a stopgap that API access would immediately obsolete.

### Other options (no longer needed, kept for context)

- **Shopify order history** — already live, and our app falls back to it
  automatically (see below).
- Untappd link for display only — the public profile page still exposes stats
  and ~5 recent check-ins, far too few for a taste profile.

---

## Fix in this app — no more silent empty taste wheel

Our fallback previously only triggered on an HTTP **error**. An Untappd profile
that returned 200 with zero data was treated as success, so the fallback never
fired and the user saw an empty taste wheel.

`backend/recommendations/views.py` now treats a successful-but-empty response as
a failure and falls back to Shopify order history, via
`_is_empty_taste_profile()` / `_is_empty_recommendations()`.

Verified live for `milovanp`: the Untappd profile is detected as empty and the
Shopify profile is served instead — 53 check-ins, 12 unique beers, a 6-axis
radar chart, ABV 3.5–6.8%, top brewery House Of Beers. **The taste wheel works
today, sourced from order history.**

The empty-state message is also now accurate: a user who has a profile but no
matching beers no longer gets told to "start shopping".

---

## Deploy checklist

0. **Untappd API** (restores taste wheels): register at
   `https://untappd.com/api/register?register=new`, then
   `UNTAPPD_CLIENT_ID` / `UNTAPPD_CLIENT_SECRET` on the recommender. The code
   switches to the API automatically once these are set. Until then everything
   below still applies and users get the Shopify-based profile.
1. Deploy `Beer_recommender` (metafield key + parser + header + API fixes).
2. Run a full product sync so ratings populate:
   `python manage.py sync_shopify`
3. Confirm ratings landed:
   `curl 'https://recommendation.houseofbeers.nl/api/beers/?in_stock=true&limit=50'`
   — `untappd_rating` should be non-null on ~90% of results (was 0%).
4. Confirm recommendations return beers:
   `curl -X POST https://recommendation.houseofbeers.nl/api/recommendations/ \
     -H 'Content-Type: application/json' \
     -d '{"email":"<a customer email>","limit":10}'`
5. Deploy this app's backend (empty-profile fallback).
6. Optional: clear `CachedUserProfile` rows so stale empty profiles are not
   served from cache.
