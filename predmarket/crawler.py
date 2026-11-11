import asyncio
from pathlib import Path
from crawl4ai import AsyncWebCrawler

BASE_URL = "https://dexbuilder.mintlify.site/en"
OUTPUT_DIR = Path("scraped")
CONCURRENCY = 5  # parallel requests

# Content tree for each section
CONTENT_TREE = {
    "event-markets": [
        "overview",
        "event-markets",
        "place-first-order",
        "markets-events",
        "negative-risk",
        "prices-order-book",
        "positions-tokens",
        "order-lifecycle",
        "resolution",
        "trading-overview",
        "how-positions-work",
        "fees",
        "market-data-overview",
        "discover-markets",
        "market-details",
        "market-prices-orderbooks",
        "realtime-data",
        "place-orders",
        "manage-orders",
        "realtime-order-updates",
        "wallet-activity",
    ],
    "event-contracts": [
        "overview",
        "event-contracts",
        "place-first-order",
        "market-events",
        "negative-risk",
        "prices-orderbook",
        "positions-tokens",
        "resolution",
        "order-lifecycle",
        "trading-overview",
        "how-positions-work",
        "fees",
        "market-data-overview",
        "discover-markets",
        "market-details",
        "market-prices-orderbooks",
        "realtime-data",
        "place-orders",
        "manage-orders",
        "realtime-order-updates",
        "wallet-activity",
    ],
}


def build_url(section: str, page: str) -> str:
    """
    Build the URL for a given page.

    - If the page name matches the section name, it points to the section root
      (e.g. `/en/event-markets` for page `event-markets` under section `event-markets`).
    - Otherwise it becomes `/en/<section>/<page>`.
    """
    if page == section:
        return f"{BASE_URL}/{section}"
    return f"{BASE_URL}/{section}/{page}"


def safe_filename(name: str) -> str:
    return name.replace("/", "_").replace(" ", "_").strip()


async def scrape_page(crawler: AsyncWebCrawler, url: str, output_path: Path, semaphore: asyncio.Semaphore):
    async with semaphore:
        try:
            result = await crawler.arun(url=url)
            markdown = (result.markdown or "").strip()

            if not markdown:
                print(f"[EMPTY] {url}")
                return url, False, "empty markdown"

            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(markdown, encoding="utf-8")
            print(f"[OK]    {url}  ->  {output_path}  ({len(markdown)} chars)")
            return url, True, None

        except Exception as e:
            print(f"[FAIL]  {url}  ({type(e).__name__}: {e})")
            return url, False, str(e)


async def main():
    # Build the full list of (url, output_path) targets
    targets = []
    for section, pages in CONTENT_TREE.items():
        for page in pages:
            url = build_url(section, page)
            out = OUTPUT_DIR / section / f"{safe_filename(page)}.md"
            targets.append((section, page, url, out))

    semaphore = asyncio.Semaphore(CONCURRENCY)
    results = []

    async with AsyncWebCrawler() as crawler:
        results = await asyncio.gather(
            *(scrape_page(crawler, url, out, semaphore) for _, _, url, out in targets)
        )

    # Summary
    total = len(results)
    successes = sum(1 for _, ok, _ in results if ok)
    failures = [(url, err) for url, ok, err in results if not ok]

    print("\n" + "=" * 60)
    print(f"Completed: {successes}/{total} pages saved to '{OUTPUT_DIR}/'")
    if failures:
        print(f"\n{len(failures)} failure(s):")
        for url, err in failures:
            print(f"  - {url}  ({err})")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())