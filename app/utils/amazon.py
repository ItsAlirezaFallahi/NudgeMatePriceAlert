import re
import httpx
from app.config import settings

ASIN_PATTERNS = [
    r"/dp/([A-Z0-9]{10})",
    r"/gp/product/([A-Z0-9]{10})",
    r"/product/([A-Z0-9]{10})",
    r"asin=([A-Z0-9]{10})",
]

def extract_asin(url: str) -> str | None:
    for pattern in ASIN_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None

async def resolve_and_extract_asin(url: str) -> str | None:
    """Handle regular URLs and short amzn.to links"""
    # Try extracting directly first
    asin = extract_asin(url)
    if asin:
        return asin

    # If no ASIN found, try following redirects (for amzn.to short links)
    if "amzn.to" in url or "amzn.com" in url:
        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=10,
                headers={"User-Agent": "Mozilla/5.0"}
            ) as client:
                response = await client.get(url)
                final_url = str(response.url)
                return extract_asin(final_url)
        except Exception:
            return None

    return None

def build_affiliate_url(asin: str) -> str:
    return (
        f"https://www.amazon.com/dp/{asin}"
        f"?tag={settings.AMAZON_AFFILIATE_TAG}"
    )

def clean_amazon_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}"