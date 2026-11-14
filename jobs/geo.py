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


# Canonical city names for the location filter (aliases map to one name).
CITY_CANON = [
    ("Bengaluru", r"bengaluru|bangalore"), ("Hyderabad", r"hyderabad|secunderabad"), ("Pune", r"pune"),
    ("Chennai", r"chennai|madras"), ("Mumbai", r"mumbai|navi mumbai|thane|bombay"), ("Delhi", r"new delhi|delhi"),
    ("Gurugram", r"gurugram|gurgaon"), ("Noida", r"noida|greater noida"), ("Kolkata", r"kolkata|calcutta"),
    ("Ahmedabad", r"ahmedabad|gandhinagar"), ("Kochi", r"kochi|cochin"), ("Jaipur", r"jaipur"),
    ("Chandigarh", r"chandigarh|mohali|panchkula"), ("Indore", r"indore"), ("Coimbatore", r"coimbatore"),
    ("Thiruvananthapuram", r"thiruvananthapuram|trivandrum"), ("Bhubaneswar", r"bhubaneswar"),
    ("Lucknow", r"lucknow"), ("Nagpur", r"nagpur"), ("Vadodara", r"vadodara|baroda"),
    ("Visakhapatnam", r"visakhapatnam|vizag"), ("Mysuru", r"mysuru|mysore"), ("Ghaziabad", r"ghaziabad"),
    ("Faridabad", r"faridabad"), ("Surat", r"surat"), ("Bhopal", r"bhopal"), ("Mangaluru", r"mangaluru|mangalore"),
]
_CITY_RES = [(name, re.compile(rf"\b({pat})\b", re.I)) for name, pat in CITY_CANON]
REMOTE = "Remote"


def cities_for(locations, workplace_type=""):
    """['Bengaluru', 'Remote'] from free-text locations; ordered, de-duplicated."""
    text = " | ".join(l for l in locations if l)
    found = [name for name, rx in _CITY_RES if rx.search(text)]
    if (workplace_type or "").lower() == "remote" or re.search(r"\b(remote|work from home|wfh)\b", text, re.I):
        found.append(REMOTE)
    return found


def encode_cities(cities):
    """Stored as ',Bengaluru,Remote,' so a single city can be matched with icontains(',Pune,')."""
    return f",{','.join(cities)}," if cities else ""
