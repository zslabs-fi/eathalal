# EatHalal.fi — project plan

A static website that lists halal restaurants in Finland. The list is maintained as a
CSV file in this repository. Every change to the CSV triggers GitHub Actions, which
looks up each restaurant on Google Maps, downloads a thumbnail, and publishes a fresh
copy of the site to GitHub Pages. There is no server, database or runtime API.

## Goals

- **One file to edit.** Adding a restaurant means adding one line to `restaurants.csv`.
- **Rich listings for free.** Address, coordinates and photo are pulled from the Google
  Maps link automatically, so contributors only supply a name and a link.
- **Fast to use on a phone.** Search, filter by city, sort by distance from you, and
  open directions in one tap.
- **Zero running cost.** Static files on GitHub Pages; build runs on free CI minutes.

## Non-goals (for v1)

- User accounts, reviews or ratings.
- Live opening hours (would need a runtime API key exposed to browsers).
- Verifying halal certification — the site lists what maintainers add.

## Input format

`restaurants.csv` (UTF-8, comma-separated, header row required):

```csv
Name,GoogleMapUrl
Tandoori Villa Kalasatama,https://maps.app.goo.gl/Cx5Qo95PcWZVF6Gi6
```

Header names are matched case-insensitively and surrounding spaces are ignored, so
`Name, GoogleMapUrl` works too. Optional extra columns override what the build finds
online — useful when Google returns something wrong:

| Column     | Effect                                                         |
|------------|----------------------------------------------------------------|
| `Address`  | Replaces the fetched address                                   |
| `City`     | Replaces the city derived from the address                     |
| `ImageUrl` | Uses this image instead of the Google photo                    |
| `Tags`     | Semicolon-separated labels shown on the card, e.g. `Buffet;Pizza` |

## Architecture

```
restaurants.csv ──► scripts/build.py ─────────────────────────► _site/  ──► GitHub Pages
                       │                                          index.html
                       ├─ resolve maps.app.goo.gl short link      restaurants.json
                       ├─ parse name, place id, lat/lng from URL  images/*.webp
                       ├─ get address + photo (see sources)       assets/*
                       ├─ download + resize photo to WebP
                       └─ cache results in .cache/places.json
```

### Where details come from (in priority order)

1. **CSV override columns** — always win.
2. **Google Maps place page** — the build opens the place page the short
   link resolves to, then follows the `/maps/preview/place` data link in its `<head>`.
   That JSON is what Google's own side panel shows: address, categories, rating,
   phone, website and photos. It is undocumented and positional, so each field is
   read defensively; if Google changes it, only the missing fields fall back.
   (The page's own Open Graph tags are also read, but Google currently fills them
   with generic "Google Maps" text.)
3. **OpenStreetMap Nominatim** — reverse-geocodes the coordinates when no address was
   found. Rate-limited to 1 request/second as Nominatim's policy requires.
4. **Placeholder** — if no photo is available, the card shows a generated pattern tile.

Coordinates always come from the resolved Google Maps URL (`!3d<lat>!4d<lng>`), so the
map works even when every other source fails.

Tested on 29 October 2026: all five sample restaurants came back with address,
category, Google rating, phone, website and photo through source 2. OpenStreetMap
alone picked a neighbouring building's address for two of them, which is why it is
only the last resort.

### Caching

`.cache/` holds `places.json` (details per URL) and downloaded images. CI persists it
with `actions/cache`, so a build only hits Google for new or changed links. Entries
older than 30 days are refreshed. Changing a restaurant's URL in the CSV invalidates
its entry.

### Frontend

Plain HTML, CSS and JavaScript — no framework, no bundler. Leaflet with OpenStreetMap
tiles draws the map. Restaurant data is embedded in the page (and also published as
`restaurants.json` for anyone who wants to reuse it).

- Search by name, address or tag (accent-insensitive, so "kalasatama" ≈ "Kalasatama").
- City chips built from the data, with counts.
- "Near me" uses browser geolocation, sorts by distance and shows km on each card.
- List and map views; on wide screens they sit side by side and stay in sync.
- Light and dark themes follow the system setting.

## Repository layout

```
restaurants.csv              data, the only file most contributors touch
scripts/build.py             entry point: fetch details + render site
scripts/places.py            Google Maps / Places / Nominatim lookups
scripts/render.py            writes _site/
site/index.html              page template
site/assets/                 style.css, app.js, favicon.svg
tests/                       unit tests for URL parsing and CSV handling
.github/workflows/deploy.yml CI: build + deploy to Pages
```

## Tasks

### Phase 1 — MVP (this session)

- [x] Write this plan
- [x] CSV reader with flexible headers and override columns
- [x] Short-link resolver and Google Maps URL parser (name, place id, lat/lng)
- [x] Detail lookup chain: Google Maps place data → Nominatim → placeholder
- [x] Image download, resize to 640px WebP, cache
- [x] Page design: search, city filter, near-me sort, list + map
- [x] GitHub Actions workflow: build on push to `main`, deploy to Pages, weekly refresh
- [x] Unit tests for parsing; offline build mode for local preview
- [x] Cards show category, Google rating, phone and website when available
- [ ] Push to `zslabs-fi/eathalal` and enable Pages (Settings → Pages → Source: GitHub Actions)

### Phase 2 — nice to have

- [ ] "Suggest a restaurant" GitHub issue form that maintainers turn into a CSV line
- [ ] CSV validation check on pull requests (duplicate names, bad links)
- [ ] Finnish and Arabic translations of the interface
- [ ] Per-restaurant pages for better search-engine visibility
- [ ] Custom domain (e.g. eathalal.fi) via `CNAME`

## Running locally

```bash
pip install -r requirements.txt
python scripts/build.py            # full build, fetches from the internet
python scripts/build.py --offline  # uses only the cache and CSV, no network
python -m http.server -d _site 8000
```

## Risks

| Risk | Mitigation |
|------|------------|
| Google changes the place page and scraping stops working | Cache keeps old results; CSV overrides; Nominatim fallback for address; build log flags restaurants with missing details |
| Google blocks CI requests | Same as above; build never fails because one lookup fails |
| Photo licensing | Photos come from Google's listing for the business; each card links back to Google Maps. Owners can request removal, and `ImageUrl` can replace any photo |
| Short link points to a search instead of a place | Build logs a warning and uses whatever coordinates are in the URL |
