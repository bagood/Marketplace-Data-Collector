# Facebook Marketplace link scraper

This program opens the Jakarta Marketplace search for `iphone`, collects the
`/marketplace/item/` links that appear in the initial results without scrolling,
removes tracking parameters and duplicates, and saves them to
`links/facebook_marketplace_links.txt`.

The program does not wait for authentication. It opens the search immediately
and collects whatever initial results Facebook makes available. Existing links
are loaded from the file, so only newly discovered listings are added across
separate runs.

After collecting the initial links, the scraper opens each ad not already in
`data/facebook_marketplace_ads.csv` and saves its details using the same
pipe-delimited layout as the OLX export:

```text
link|title|price|description
```

Rows are deduplicated by canonical listing URL and written only by the parent
process to keep the CSV safe from concurrent writes. Use `--csv-output` to
choose a different CSV file.

Ad detail pages are processed in parallel using four Chrome worker processes by
default. Adjust this based on available memory and CPU:

```bash
python scrapperScripts/facebook_marketplace_scraper.py --detail-workers 2
```

## Setup

Python 3.10+ and Google Chrome are required. Selenium 4 uses Selenium Manager,
so a compatible ChromeDriver is normally installed automatically.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python scrapperScripts/facebook_marketplace_scraper.py
```

The scraper always opens a visible temporary Chrome session. Browser session
data is not persisted by this script.

Useful options:

```bash
python scrapperScripts/facebook_marketplace_scraper.py --output links/custom.txt --pause 3
```

The scraper now selects Marketplace item URLs directly instead of relying on
Facebook's frequently changing generated class names. Use it in accordance
with Facebook's terms and applicable rate limits.

## OLX scraper

`olx_scraper.py` opens the configured Jakarta iPhone search, scrolls to the
bottom, repeatedly clicks **Muat Lainnya**, and stores unique `/item/` links in
`links/olx_item_links.txt`. It merges only newly discovered ads into the file across
separate runs. Every run performs exactly
five successful **Muat Lainnya** clicks by default before extraction starts. The configured
number is exact, so the scraper stops clicking immediately after reaching it. The button is
located using its `data-aut-id="btnLoadMore"` attribute. Link collection happens
only after result expansion is complete.

After URL collection, the scraper opens every ad that is not already present
in `data/olx_ads.csv` and stores its details using these columns:

```text
link|title|price|description
```

Rows are written only by the parent process after parallel collection, avoiding
concurrent CSV writes. Existing comma-delimited output is automatically migrated
to the pipe format. Use `--csv-output` to choose another CSV path.

OLX detail pages also use four worker processes by default:

```bash
python scrapperScripts/olx_scraper.py --detail-workers 2
```

```bash
python scrapperScripts/olx_scraper.py
```

The minimum can be increased when needed:

```bash
python scrapperScripts/olx_scraper.py --min-load-more-clicks 10
```
