# EatHalal

**A directory of halal restaurants in Finland.** Search by name or area, filter by
city, see everything on a map, or sort by distance from where you are.

The site is fully static and hosted on GitHub Pages. The whole list lives in one
CSV file, and GitHub Actions rebuilds and republishes the site whenever that file
changes.

## Features

- **One-line listings.** Add a restaurant with just its name and a Google Maps link.
  The build fills in the rest: address, map position, photo, cuisine, Google
  rating, phone number and website.
- **Search** across names, addresses, cuisines and tags. It ignores accents, so
  "aija" finds "Äijä".
- **City filter** built automatically from the addresses.
- **Near me** sorts restaurants by distance using the browser's location.
- **Map view** with OpenStreetMap. On wide screens the list and map sit side by side.
- **Directions, Call and Website** buttons on every card.
- **Dark mode and mobile layout**, keyboard-friendly and screen-reader labelled.
- **Shareable filters.** Searches and city filters are kept in the URL.
- **Open data.** The full list is also published as `restaurants.json`.

## Adding or changing a restaurant

1. Open the restaurant in Google Maps, choose **Share**, then **Copy link**.
2. Add a line to [`restaurants.csv`](restaurants.csv):

   ```csv
   Name,GoogleMapUrl
   Tandoori Villa Kalasatama,https://maps.app.goo.gl/Cx5Qo95PcWZVF6Gi6
   ```

3. Commit to `main`, or open a pull request. The site updates a few minutes after
   the change reaches `main`.

Not comfortable editing files? [Open an issue](../../issues/new?title=Add+restaurant:+)
with the name and link, and a maintainer will add it.

### Fixing wrong details

If the build gets something wrong, add an optional column. Values in the CSV
always win over what is found online.

| Column     | What it does                                                   |
|------------|----------------------------------------------------------------|
| `Address`  | Replaces the address                                           |
| `City`     | Replaces the city used for the filter                          |
| `ImageUrl` | Uses this image instead of the Google photo                    |
| `Tags`     | Extra labels on the card, separated by `;` (e.g. `Buffet;Pizza`) |

Columns can be left empty for restaurants that don't need them.

## How it works

```
restaurants.csv ──► scripts/build.py ──► _site/ ──► GitHub Pages
                     │
                     ├─ follows the maps.app.goo.gl short link
                     ├─ reads coordinates from the resolved Google Maps URL
                     ├─ fetches details: Google Maps place data → OpenStreetMap
                     ├─ downloads and crops the photo to WebP
                     └─ caches everything in .cache/ so only new links are looked up
```

No API keys, accounts or paid services are needed. Details come from:

1. **Google Maps place data**, the same information Google's own side panel shows
   for the link. It is not an official API, so Google could change it; if that
   happens, already-listed restaurants keep their cached details.
2. **OpenStreetMap Nominatim** for the address only, as a last resort.

A failed lookup never fails the build. The restaurant is still listed and the
build log says what's missing. See [PROJECT.md](PROJECT.md) for the full design,
risks and roadmap.

## Setting up the repository

1. **Settings → Pages → Build and deployment → Source:** choose **GitHub Actions**.
2. Push to `main`, or run **Build and deploy site** by hand from the **Actions** tab.

The workflow also runs every Monday to refresh details older than 30 days. A
manual run can re-check every restaurant with the **refresh** option.

## Running it locally

Requires Python 3.10 or newer.

```bash
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q tests            # run the tests
python scripts/build.py              # build into _site/ (needs internet)
python -m http.server -d _site 8000  # then open http://localhost:8000
```

Other build options:

| Option      | Effect                                              |
|-------------|-----------------------------------------------------|
| `--offline` | Build from the cache and CSV only, no network       |
| `--refresh` | Ignore the cache and look every restaurant up again |
| `--csv`     | Use a different CSV file                            |

## Project layout

```
restaurants.csv               the restaurant list
scripts/build.py              build entry point
scripts/places.py             Google Maps and OpenStreetMap lookups
scripts/render.py             writes the site into _site/
site/index.html               page template
site/assets/                  styles, script and icon
tests/                        unit tests
.github/workflows/deploy.yml  build and deploy to GitHub Pages
PROJECT.md                    design notes and task list
```

## Disclaimer

Listings are added by volunteers. Always confirm halal status with the restaurant.
Photos, ratings and addresses come from Google Maps, and each card links back to
the restaurant's Google Maps page. Map data © OpenStreetMap contributors.

## License

See [LICENSE](LICENSE).
