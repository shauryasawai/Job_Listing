"""Country filter. Greenhouse/Lever give free-text locations, so India is recognised by country code
(when the platform provides one), the word "India", Indian cities and Indian states."""
import re

from django.conf import settings

_CITIES = (
    "bengaluru|bangalore|mumbai|navi mumbai|new delhi|delhi|gurgaon|gurugram|noida|greater noida|hyderabad|pune|"
    "chennai|kolkata|calcutta|ahmedabad|kochi|cochin|jaipur|chandigarh|mohali|indore|coimbatore|thiruvananthapuram|"
    "trivandrum|bhubaneswar|lucknow|nagpur|vadodara|visakhapatnam|vizag|mysuru|mysore|surat|bhopal|patna|ranchi|"
    "guwahati|dehradun|nashik|vijayawada|madurai|kozhikode|mangalore|mangaluru|thane|faridabad|ghaziabad"
)
_STATES = (
    "karnataka|maharashtra|telangana|tamil nadu|haryana|uttar pradesh|kerala|gujarat|west bengal|rajasthan|"
    "andhra pradesh|madhya pradesh|odisha|punjab"
)
INDIA_RE = re.compile(rf"\b(india|{_CITIES}|{_STATES})\b", re.I)
INDIA_CODES = {"IN", "IND", "INDIA"}


def is_india(country="", locations=()):
    if (country or "").strip().upper() in INDIA_CODES:
        return True
    return any(INDIA_RE.search(loc or "") for loc in locations)


def matches_country_filter(raw):
    """raw is a RawJob. Honour JOB_COUNTRY_FILTER ("IN" or "ALL")."""
    if settings.JOB_COUNTRY_FILTER in ("", "ALL"):
        return True
    return is_india(raw.country, [raw.location, *raw.locations])
