import asyncio
import httpx
import re
from decimal import Decimal
from dataclasses import dataclass
from app.utils.amazon import extract_asin, build_affiliate_url
from app.config import settings
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


PRICE_PATTERNS = [
    r'"priceAmount":([\d.]+)',
    r'"price":\s*"?\$?([\d,]+\.[\d]{2})"?',
    r'class="a-price-whole">(\d+)<',
]

async def scrape_amazon_product(url: str) -> ScrapeResult:
    asin = extract_asin(url)
    if not asin:
        return ScrapeResult(success=False, error="Could not extract ASIN from URL")

    affiliate_url = build_affiliate_url(asin)
    target_url = f"https://www.amazon.com/dp/{asin}"

    scraper_url = (
        f"http://api.scraperapi.com"
        f"?api_key={settings.SCRAPER_API_KEY}"
        f"&url={target_url}"
        f"&country_code=us"
        f"&device_type=desktop"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(scraper_url)

        if response.status_code != 200:
            logger.warning(f"ScraperAPI returned {response.status_code} for ASIN {asin}")
            return ScrapeResult(
                success=False,
                asin=asin,
                affiliate_url=affiliate_url,
                error=f"HTTP {response.status_code}",
            )

        html = response.text

        if "captcha" in html.lower() and len(html) < 5000:
            logger.warning(f"CAPTCHA still detected for ASIN {asin}")
            return ScrapeResult(
                success=False,
                asin=asin,
                affiliate_url=affiliate_url,
                error="CAPTCHA detected",
            )

        # Extract title
        product_name = None
        title_match = re.search(r'id="productTitle"[^>]*>\s*([^<]+)', html)
        if title_match:
            product_name = title_match.group(1).strip()

        # Extract price
        current_price = None

        # Try structured price first
        price_match = re.search(r'"priceAmount":([\d.]+)', html)
        if not price_match:
            price_match = re.search(r'class="a-price-whole">(\d+)', html)
            if price_match:
                whole = price_match.group(1)
                frac_match = re.search(r'class="a-price-fraction">(\d+)', html)
                frac = frac_match.group(1) if frac_match else "00"
                try:
                    current_price = Decimal(f"{whole}.{frac}")
                except Exception:
                    pass

        if not current_price and price_match and '"priceAmount"' in html:
            try:
                current_price = Decimal(price_match.group(1))
            except Exception:
                pass

        # Fallback: look for $XX.XX pattern near price elements
        if not current_price:
            matches = re.findall(r'\$(\d{1,4}\.\d{2})', html)
            if matches:
                try:
                    current_price = Decimal(matches[0])
                except Exception:
                    pass

        if not current_price:
            logger.warning(f"Could not extract price for ASIN {asin}")
            return ScrapeResult(
                success=False,
                asin=asin,
                product_name=product_name,
                affiliate_url=affiliate_url,
                error="Price not found",
            )

        logger.info(f"Scraped ASIN {asin}: {product_name} @ ${current_price}")
        return ScrapeResult(
            success=True,
            asin=asin,
            product_name=product_name,
            current_price=current_price,
            affiliate_url=affiliate_url,
        )

    except httpx.TimeoutException:
        logger.error(f"Timeout scraping ASIN {asin}")
        return ScrapeResult(success=False, asin=asin, affiliate_url=affiliate_url, error="Timeout")
    except Exception as e:
        logger.error(f"Error scraping ASIN {asin}: {e}")
        return ScrapeResult(success=False, asin=asin, affiliate_url=affiliate_url, error=str(e))


def parse_price(text: str) -> Decimal | None:
    text = text.strip().replace(",", "")
    match = re.search(r"\d+\.\d{2}", text)
    if match:
        try:
            return Decimal(match.group())
        except Exception:
            return None
    return None
