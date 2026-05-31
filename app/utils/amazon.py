import re
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

def build_affiliate_url(asin: str) -> str:
    return (
        f"https://www.amazon.com/dp/{asin}"
        f"?tag={settings.AMAZON_AFFILIATE_TAG}"
    )

def clean_amazon_url(asin: str) -> str:
    return f"https://www.amazon.com/dp/{asin}"
