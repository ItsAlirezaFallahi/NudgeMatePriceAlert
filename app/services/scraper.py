import asyncio
import random
from decimal import Decimal
from dataclasses import dataclass
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from app.utils.user_agents import get_random_user_agent
from app.utils.amazon import extract_asin, build_affiliate_url, clean_amazon_url
import logging

logger = logging.getLogger(__name__)

@dataclass
class ScrapeResult:
    success: bool
    asin: str | None = None
    product_name: str | None = None
    current_price: Decimal | None = None
    affiliate_url: str | None = None
    error: str | None = None


PRICE_SELECTORS = [
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "span.a-price.aok-align-center span.a-offscreen",
    ".a-price .a-offscreen",
    "#apex_offerDisplay_desktop .a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#corePrice_desktop .a-price .a-offscreen",
    ".priceToPay .a-offscreen",
    "#sns-base-price",
]

TITLE_SELECTORS = [
    "#productTitle",
    "#title span",
    "h1.a-size-large",
]


async def scrape_amazon_product(url: str) -> ScrapeResult:
    asin = extract_asin(url)
    if not asin:
        return ScrapeResult(success=False, error="Could not extract ASIN from URL")

    clean_url = clean_amazon_url(asin)
    affiliate_url = build_affiliate_url(asin)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        context = await browser.new_context(
            user_agent=get_random_user_agent(),
            viewport={"width": 1280, "height": 800},
            locale="en-US",
            timezone_id="America/New_York",
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        page = await context.new_page()

        try:
            await asyncio.sleep(random.uniform(1.0, 3.0))
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=30000)

            content = await page.content()
            if "captcha" in content.lower() or "robot" in content.lower():
                logger.warning(f"CAPTCHA detected for ASIN {asin}")
                return ScrapeResult(
                    success=False,
                    asin=asin,
                    affiliate_url=affiliate_url,
                    error="CAPTCHA detected",
                )

            await asyncio.sleep(random.uniform(1.0, 2.0))

            product_name = None
            for selector in TITLE_SELECTORS:
                try:
                    el = await page.wait_for_selector(selector, timeout=5000)
                    if el:
                        text = await el.inner_text()
                        product_name = text.strip()
                        if product_name:
                            break
                except PlaywrightTimeout:
                    continue

            current_price = None
            for selector in PRICE_SELECTORS:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        text = await el.inner_text()
                        price = parse_price(text)
                        if price:
                            current_price = price
                            break
                except Exception:
                    continue

            if not current_price:
                logger.warning(f"Could not extract price for ASIN {asin}")
                return ScrapeResult(
                    success=False,
                    asin=asin,
                    product_name=product_name,
                    affiliate_url=affiliate_url,
                    error="Price not found — product may be unavailable",
                )

            return ScrapeResult(
                success=True,
                asin=asin,
                product_name=product_name,
                current_price=current_price,
                affiliate_url=affiliate_url,
            )

        except PlaywrightTimeout:
            logger.error(f"Timeout scraping ASIN {asin}")
            return ScrapeResult(
                success=False,
                asin=asin,
                affiliate_url=affiliate_url,
                error="Page load timeout",
            )
        except Exception as e:
            logger.error(f"Unexpected error scraping ASIN {asin}: {e}")
            return ScrapeResult(
                success=False,
                asin=asin,
                affiliate_url=affiliate_url,
                error=str(e),
            )
        finally:
            await browser.close()


def parse_price(text: str) -> Decimal | None:
    import re
    text = text.strip().replace(",", "")
    match = re.search(r"\d+\.\d{2}", text)
    if match:
        try:
            return Decimal(match.group())
        except Exception:
            return None
    return None
