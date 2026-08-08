# Marketplace Phone Data Scraper

This repository collects phone advertisements from multiple online marketplaces
for comparison and analysis. It currently supports Facebook Marketplace and
OLX, with searches configured for iPhone listings in Jakarta.

Each scraper discovers advertisement links, avoids duplicates across runs, and
collects structured details including the listing title, offered price,
description, and collection timestamp. The analysis pipeline combines data from
all supported marketplaces, records the source of each listing, and uses Codex
CLI to estimate phone condition from the advertisement description.

## Project structure

```text
scrapperScripts/  Marketplace scraping programs
links/            Deduplicated advertisement URLs
data/             Marketplace CSV data and combined analysis output
analyzeData/      Data concatenation, rating logic, schema, and guidelines
uploadToGoogleSheets/  Standalone Google Sheets upload service and Docker image
```

Use these tools responsibly and in accordance with each marketplace's terms,
robots policies, and applicable rate limits.

## Facebook Marketplace scraper

The Facebook scraper opens the Jakarta Marketplace search for `iphone`, collects the
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
link|title|price|description|timestamp
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
link|title|price|description|timestamp
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

## Data analysis

`analyzeData/analyze_data.py` scans every source CSV in `data/`, adds a `source`
column containing the source filename, and rates each new phone from its
description using the rules in `analyzeData/condition_guidelines.md`. It also
extracts a canonical `phone_type` from each ad title (for example, `iPhone 12`
or `iPhone 12 Pro Max`). Every assigned label is recorded in
`analyzeData/phone_type_labels.json`; matching is case-insensitive, so title
variants such as `IPhone 11` reuse the documented `iPhone 11` label. An ad is
considered already processed when its `link` is present in
`data/combined_rated_ads.csv`. Existing ads are not rated again; newly rated ads
are appended to the pipe-delimited combined output after each successful batch.
The combined output is excluded from input scans.

The combined output columns are:

```text
link|title|price|description|timestamp|source|phone_type|condition_rating|condition_reason
```

```bash
python analyzeData/analyze_data.py
```

On the next run, combined rows created by an older version are backfilled with
phone types from their titles without invoking Codex or changing their existing
condition ratings. Titles without a recognizable iPhone model receive the
documented `Unknown` label.

### Google Sheets upload

The analyzer can replace a Google Sheets worksheet with the complete combined
CSV after analysis. Enable the Google Sheets API, create a service account, and
share the destination spreadsheet with that service account as an editor.

Encode the downloaded service-account JSON as a single Base64 line. This avoids
multiline private-key parsing problems in `.env`:

```bash
python -c 'import base64, pathlib; print(base64.b64encode(pathlib.Path("/absolute/path/to/service-account.json").read_bytes()).decode())'
```

Copy the output into `.env` together with the destination settings:

```dotenv
GOOGLE_SHEETS_SPREADSHEET_ID=your_spreadsheet_id
GOOGLE_SHEETS_WORKSHEET=Ads
GOOGLE_SERVICE_ACCOUNT_JSON_BASE64=paste_the_generated_base64_value_here
```

The spreadsheet ID is the value between `/d/` and `/edit` in its URL. The
worksheet is created when it does not exist. Existing worksheet values are
cleared before the complete CSV is uploaded using raw values, while cell
formatting is preserved. If `GOOGLE_SHEETS_SPREADSHEET_ID` is unset, analysis
continues without an upload.

The uploader is a standalone package under `uploadToGoogleSheets/`. It uses the
repository's root `Dockerfile` and shared dependencies. To upload the current
combined CSV without scraping or analysis:

```bash
python -m uploadToGoogleSheets.upload_to_google_sheets \
  --spreadsheet-id your_spreadsheet_id \
  --worksheet "Ads"
```

The dedicated Compose service shares the CSV read-only and automatically reads
all Google configuration and credentials from `.env`:

```bash
docker compose run --rm upload-to-google-sheets
```

`GOOGLE_SERVICE_ACCOUNT_JSON_BASE64` is decoded only in memory. File-based
Application Default Credentials remain supported as a fallback when this value
is empty. Although `.env` is ignored by Git, it contains a private key and must
not be copied, logged, or committed.

The default `gpt-5.6-luna` model is the lightweight classification model. The
model and batch size can be overridden:

```bash
python analyzeData/analyze_data.py --model gpt-5.6-luna --batch-size 10
```

## MCP and FastAPI server

The read-only server exposes `data/combined_rated_ads.csv` through both a REST
API and MCP Streamable HTTP. Its implementation is separated into controller,
service, and repository layers under `mcp_server/`.

```bash
pip install -r requirements.txt
uvicorn mcp_server.main:app --host 127.0.0.1 --port 8000 --reload
```

Connect an MCP client to `http://127.0.0.1:8000/mcp`. The MCP tools are
`fetch_ads`, `get_ad_by_link`, and `get_dataset_metadata`. Matching REST routes
start at `/api/v1/ads`, and interactive API documentation is at `/docs`.

`fetch_ads` supports `limit`, `offset`, `source`, `condition_rating`, and a
case-insensitive `query` filter. Page size is capped at 500 rows. To select a
different file, set `COMBINED_ADS_CSV` to its absolute path.

```bash
python -m unittest discover -s tests -v
```

## Docker Compose

The Compose stack uses Python 3.10 and starts the MCP server alongside the
`collect_analyze_data.py` pipeline. The pipeline launches both scrapers concurrently,
waits for them to finish successfully, and then runs incremental analysis.
Chromium, ChromeDriver, and Codex CLI are installed in the image.
The container explicitly uses `/usr/bin/chromium` and
`/usr/bin/chromedriver`, avoiding Selenium Manager architecture detection on
ARM64 Docker hosts.

```bash
cp .env.example .env
docker compose run --rm codex-login
# Open the displayed URL and enter its one-time code using your ChatGPT account.
docker compose up --build
```

If device login is unavailable, enable device-code authorization in your
ChatGPT account's **Settings → Security** and run the login command again.

The MCP endpoint is available at `http://localhost:8000/mcp`. Scraped CSV and
link files persist in the host's `data/` and `links/` directories. The
collection container exits after completing one scrape-and-analysis run while
the MCP service remains active. Codex authentication is stored in the private
`codex-auth` Docker volume. Run the full pipeline again without restarting MCP
with:

```bash
docker compose run --rm collect-data
```

The host port and detail worker counts can be configured through environment
variables:

```bash
OPENAI_API_KEY=... MCP_PORT=8080 FACEBOOK_DETAIL_WORKERS=1 OLX_DETAIL_WORKERS=1 docker compose up --build
```

To check the cached ChatGPT login:

```bash
docker compose run --rm codex-login codex login status
```

Do not put a ChatGPT password, browser cookie, or access token in `.env`.
`docker compose down` preserves the login volume; `docker compose down -v`
deletes it and requires signing in again. API-platform authentication remains
available by setting `OPENAI_API_KEY` in `.env`, but API usage is billed
separately from the ChatGPT subscription.

The same pipeline can be run locally:

```bash
python collect_analyze_data.py --headless
```
