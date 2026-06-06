import asyncio
import random
import re
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


# Amazon-specific selectors
AMAZON_PRICE_SELECTORS = [
    "#priceblock_ourprice",
    "#priceblock_dealprice",
    "span.a-price.aok-align-center span.a-offscreen",
    ".a-price .a-offscreen",
    "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
    "#corePrice_desktop .a-price .a-offscreen",
    ".priceToPay .a-offscreen",
]

AMAZON_TITLE_SELECTORS = [
    "#productTitle",
    "#title span",
]

# Generic selectors for other retailers
GENERIC_PRICE_SELECTORS = [
    "[class*='sale-price']",
    "[class*='sale_price']",
    "[class*='current-price']",
    "[class*='current_price']",
    "[class*='product-price']",
    "[class*='product_price']",
    "[data-testid*='price']",
    "[data-automation*='price']",
    "[itemprop='price']",
    ".price",
    "#price",
    "[class*='Price']",
    "[class*='price']",
]

GENERIC_TITLE_SELECTORS = [
    "h1[class*='product']",
    "h1[class*='title']",
    "[class*='product-title']",
    "[class*='product_title']",
    "[class*='product-name']",
    "[itemprop='name']",
    "h1",
]


def is_amazon_url(url: str) -> bool:
    return "amazon.com" in url


def parse_price(text: str) -> Decimal | None:
    text = text.strip().replace(",", "").replace("$", "").replace("USD", "").strip()
    match = re.search(r"\d+\.\d{2}", text)
    if match:
        try:
            return Decimal(match.group())
        except Exception:
            return None
    # Handle prices like "$179" with no cents
    match = re.search(r"\d+", text)
    if match:
        try:
            return Decimal(match.group() + ".00")
        except Exception:
            return None
    return None


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
            await asyncio.sleep(random.uniform(2.0, 5.0))
            await page.goto(clean_url, wait_until="domcontentloaded", timeout=30000)

            content = await page.content()
            if "captcha" in content.lower() and len(content) < 10000:
                logger.warning(f"CAPTCHA detected for ASIN {asin}")
                return ScrapeResult(
                    success=False,
                    asin=asin,
                    affiliate_url=affiliate_url,
                    error="CAPTCHA detected",
                )

            await asyncio.sleep(random.uniform(1.0, 3.0))

            # Extract title
            product_name = None
            for selector in AMAZON_TITLE_SELECTORS:
                try:
                    el = await page.wait_for_selector(selector, timeout=5000)
                    if el:
                        text = await el.inner_text()
                        product_name = text.strip()
                        if product_name:
                            break
                except PlaywrightTimeout:
                    continue

            # Extract price
            current_price = None
            for selector in AMAZON_PRICE_SELECTORS:
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
                    error="Price not found",
                )

            logger.info(f"Scraped Amazon ASIN {asin}: {product_name} @ ${current_price}")
            return ScrapeResult(
                success=True,
                asin=asin,
                product_name=product_name,
                current_price=current_price,
                affiliate_url=affiliate_url,
            )

        except PlaywrightTimeout:
            return ScrapeResult(success=False, asin=asin, affiliate_url=affiliate_url, error="Timeout")
        except Exception as e:
            logger.error(f"Error scraping Amazon ASIN {asin}: {e}")
            return ScrapeResult(success=False, asin=asin, affiliate_url=affiliate_url, error=str(e))
        finally:
            await browser.close()


async def scrape_generic_product(url: str) -> ScrapeResult:
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
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            },
        )

        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        """)

        page = await context.new_page()

        try:
            await asyncio.sleep(random.uniform(1.0, 3.0))
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(random.uniform(1.0, 2.0))

            content = await page.content()

            # Extract title
            product_name = None
            for selector in GENERIC_TITLE_SELECTORS:
                try:
                    el = await page.query_selector(selector)
                    if el:
                        text = await el.inner_text()
                        text = text.strip()
                        if text and len(text) > 3:
                            product_name = text[:200]
                            break
                except Exception:
                    continue

            # Extract price
            current_price = None
            for selector in GENERIC_PRICE_SELECTORS:
                try:
                    elements = await page.query_selector_all(selector)
                    for el in elements:
                        text = await el.inner_text()
                        price = parse_price(text)
                        if price and price > 0:
                            current_price = price
                            break
                    if current_price:
                        break
                except Exception:
                    continue

            # Fallback: search page content for price patterns
            if not current_price:
                prices = re.findall(r'\$(\d{1,4}\.\d{2})', content)
                if prices:
                    try:
                        current_price = Decimal(prices[0])
                    except Exception:
                        pass

            if not current_price:
                return ScrapeResult(
                    success=False,
                    product_name=product_name,
                    error="Price not found",
                )

            logger.info(f"Scraped {url}: {product_name} @ ${current_price}")
            return ScrapeResult(
                success=True,
                product_name=product_name,
                current_price=current_price,
                affiliate_url=url,
            )

        except PlaywrightTimeout:
            return ScrapeResult(success=False, error="Timeout")
        except Exception as e:
            logger.error(f"Error scraping {url}: {e}")
            return ScrapeResult(success=False, error=str(e))
        finally:
            await browser.close()


async def scrape_product(url: str) -> ScrapeResult:
    """Main entry point — routes to Amazon or generic scraper"""
    if is_amazon_url(url):
        return await scrape_amazon_product(url)
    else:
        return await scrape_generic_product(url)