#!/usr/bin/env python3
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from pathlib import Path
from xml.dom import minidom

FEED_URL = os.environ.get("HANDSHAKE_FEED_URL")
if not FEED_URL:
    raise SystemExit("Missing HANDSHAKE_FEED_URL secret.")

OUT = Path("docs/handshake-feed-cleaned.rss")

def text(el, tag):
    return (el.findtext(tag) or "").strip()

def normalize(s):
    return " ".join((s or "").split())

def employer_from_description(desc):
    m = re.search(r"Employer:\s*(.*?)\s+Expires:", desc, re.S | re.I)
    return normalize(m.group(1)) if m else ""

def expiration_from_description(desc):
    m = re.search(r"Expires:\s*(\d{1,2}/\d{1,2}/\d{4})", desc, re.I)
    return m.group(1) if m else ""

def posted_date_from_item(item):
    value = text(item, "pubDate")
    if not value:
        return ""
    try:
        return parsedate_to_datetime(value).strftime("%m/%d/%Y")
    except (TypeError, ValueError, OverflowError):
        return ""

def position_type_from_text(title, desc):
    """Return a position type only when the posting states one clearly."""
    haystack = f"{title} {desc}"
    patterns = [
        (r"\b(?:full[- ]time|fulltime)\b", "Full-time"),
        (r"\b(?:part[- ]time|parttime)\b", "Part-time"),
        (r"\bintern(?:ship)?\b", "Internship"),
        (r"\bfellow(?:ship)?\b", "Fellowship"),
        (r"\bapprentice(?:ship)?\b", "Apprenticeship"),
        (r"\btemporary\b|\bseasonal\b", "Temporary/seasonal"),
        (r"\bcontract(?:or)?\s+(?:role|position|job)\b", "Contract"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, haystack, re.I):
            return label
    return ""

def location_type_from_description(desc):
    d = normalize(desc)
    if re.search(r"\bhybrid\b", d, re.I):
        return "Hybrid"
    if re.search(r"\bfully remote\b|\b100% remote\b|\bremote position\b|\bwork remotely\b", d, re.I):
        return "Remote"
    if re.search(r"\bon[- ]site\b|\bin[- ]person\b|\bin the office\b", d, re.I):
        return "On-site"
    return ""

def onsite_location_from_description(desc):
    d = normalize(desc)
    state = (
        r"(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
        r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|"
        r"Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|"
        r"Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|"
        r"North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
        r"South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|"
        r"Wisconsin|Wyoming|District of Columbia|A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|"
        r"I[ADLN]|K[SY]|LA|M[ADEHINOPST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|"
        r"UT|V[AIT]|W[AIVY])\b"
    )
    city = r"[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,4}"
    city_state = rf"{city},\s*{state}"
    patterns = [
        rf"Location\(s\):\s*({city_state}(?:\s+and\s+{city_state})*)",
        rf"(?:This position|The position|This role|The job)\s+(?:will be\s+)?(?:is\s+)?based in\s+({city_state})",
        rf"(?:our|the)\s+({city_state})\s+office",
        rf"(?:located|location)\s+in\s+({city_state})",
    ]
    for pattern in patterns:
        m = re.search(pattern, d, re.I)
        if m:
            return normalize(m.group(1)).rstrip(" ,")
    return ""

def expected_pay_from_description(desc):
    d = normalize(desc)
    money = r"\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?![\d,])"
    amount = rf"{money}(?:\s*(?:-|–|to)\s*{money})?(?:\s*(?:per|/|a)\s*(?:hour|year|annum))?"
    patterns = [
        rf"(?:salary|pay|compensation)(?:\s+range)?(?:\s+is|\s+of)?\s*[:：]?\s*({amount})",
        rf"({money}\s*(?:-|–|to)\s*{money}(?:\s*(?:per|/|a)\s*(?:hour|year|annum))?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, d, re.I)
        if m:
            return normalize(m.group(1)).rstrip(" ,")
    return ""

def remove_employer_from_title(title, employer):
    title = normalize(title)
    if employer:
        suffix = f" at {employer}"
        if title.lower().endswith(suffix.lower()):
            return title[:-len(suffix)].strip()
    return title

def location_from_title(job_title):
    # Handshake sometimes appends locations like:
    # "Software Developer Intern - San Diego, California"
    m = re.search(
        r"\s+-\s+([A-Za-z][A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))$",
        job_title,
    )
    if not m:
        return None, job_title
    location = normalize(m.group(1))
    clean_title = job_title[:m.start()].strip()
    return location, clean_title

def location_from_description(desc):
    d = normalize(desc)

    # Explicit remote geography.
    m = re.search(
        r"This is a remote position that may be based in\s+([^.]+)\.",
        d, re.I
    )
    if m:
        return "Remote; " + normalize(m.group(1))

    # Explicit "position is based in City, State".
    m = re.search(
        r"(?:This position is based in|position is based in)\s+"
        r"([A-Za-z][A-Za-z .'-]+,\s*(?:D\.?C\.?|[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))"
        r"(?:\s*\([^)]*\))?",
        d, re.I
    )
    if m:
        loc = normalize(m.group(1)).rstrip(".,")
        return loc

    # Explicit headquarters/office location, often under a LOCATION heading.
    m = re.search(
        r"headquarters(?:\s+is)?(?:\s+located)?\s+in\s+"
        r"([A-Za-z][A-Za-z .'-]+,\s*(?:D\.?C\.?|[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))",
        d, re.I
    )
    if m:
        loc = normalize(m.group(1)).rstrip(".,")
        return loc

    return ""

def clean_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("The source is not an RSS 2.0 feed with a channel.")

    new_root = ET.Element("rss", {"version": "2.0"})
    new_channel = ET.SubElement(new_root, "channel")
    ET.SubElement(new_channel, "title").text = "Brandeis Handshake Jobs"
    ET.SubElement(new_channel, "link").text = text(channel, "link")
    ET.SubElement(new_channel, "description").text = (
        "Simplified Handshake job listings."
    )
    ET.SubElement(new_channel, "language").text = "en-us"

    for old in channel.findall("item"):
        desc = text(old, "description")
        employer = employer_from_description(desc)
        expires = expiration_from_description(desc)
        posted_date = posted_date_from_item(old)
        job_title = remove_employer_from_title(text(old, "title"), employer)

        clean_title = job_title
        loc = onsite_location_from_description(desc)
        position_type = position_type_from_text(clean_title, desc)
        location_type = location_type_from_description(desc)
        expected_pay = expected_pay_from_description(desc)

        item = ET.SubElement(new_channel, "item")
        ET.SubElement(item, "title").text = clean_title

        # The job title is already the item heading. Include only body fields
        # that have a value so the published entry has no empty lines.
        fields = [
            ("Employer", employer),
            ("Position type", position_type),
            ("Location type", location_type),
            ("Onsite location", loc),
            ("Expected pay", expected_pay),
            ("Posted date", posted_date),
            ("Application close date", expires),
        ]
        ET.SubElement(item, "description").text = "<br/>".join(
            f"{label}: {value}" for label, value in fields if value
        )

        # Preserve click-through without exposing the private source-feed token.
        link = text(old, "link")
        if link:
            ET.SubElement(item, "link").text = link

        guid_text = text(old, "guid")
        if guid_text:
            guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
            guid.text = guid_text

    raw = ET.tostring(new_root, encoding="utf-8")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")

def main():
    req = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "Brandeis-Career-Network-RSS-Updater/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        xml_bytes = response.read()

    cleaned = clean_feed(xml_bytes)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(cleaned)

    # Validate before publishing.
    ET.parse(OUT)
    print(f"Updated {OUT}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

FEED_URL = os.environ.get("HANDSHAKE_FEED_URL")
if not FEED_URL:
    raise SystemExit("Missing HANDSHAKE_FEED_URL secret.")

OUT = Path("docs/handshake-feed-cleaned.rss")

def text(el, tag):
    return (el.findtext(tag) or "").strip()

def normalize(s):
    return " ".join((s or "").split())

def employer_from_description(desc):
    m = re.search(r"Employer:\s*(.*?)\s+Expires:", desc, re.S | re.I)
    return normalize(m.group(1)) if m else ""

def expiration_from_description(desc):
    m = re.search(r"Expires:\s*(\d{1,2}/\d{1,2}/\d{4})", desc, re.I)
    return m.group(1) if m else ""

def position_type_from_text(title, desc):
    """Return a position type only when the posting states one clearly."""
    haystack = f"{title} {desc}"
    patterns = [
        (r"\b(?:full[- ]time|fulltime)\b", "Full-time"),
        (r"\b(?:part[- ]time|parttime)\b", "Part-time"),
        (r"\bintern(?:ship)?\b", "Internship"),
        (r"\bfellow(?:ship)?\b", "Fellowship"),
        (r"\bapprentice(?:ship)?\b", "Apprenticeship"),
        (r"\btemporary\b|\bseasonal\b", "Temporary/seasonal"),
        (r"\bcontract(?:or)?\s+(?:role|position|job)\b", "Contract"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, haystack, re.I):
            return label
    return ""

def location_type_from_description(desc):
    d = normalize(desc)
    if re.search(r"\bhybrid\b", d, re.I):
        return "Hybrid"
    if re.search(r"\bfully remote\b|\b100% remote\b|\bremote position\b|\bwork remotely\b", d, re.I):
        return "Remote"
    if re.search(r"\bon[- ]site\b|\bin[- ]person\b|\bin the office\b", d, re.I):
        return "On-site"
    return ""

def onsite_location_from_description(desc):
    d = normalize(desc)
    state = (
        r"(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
        r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|"
        r"Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|"
        r"Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|"
        r"North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
        r"South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|"
        r"Wisconsin|Wyoming|District of Columbia|A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|"
        r"I[ADLN]|K[SY]|LA|M[ADEHINOPST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|"
        r"UT|V[AIT]|W[AIVY])\b"
    )
    city = r"[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,4}"
    city_state = rf"{city},\s*{state}"
    patterns = [
        rf"Location\(s\):\s*({city_state}(?:\s+and\s+{city_state})*)",
        rf"(?:This position|The position|This role|The job)\s+(?:will be\s+)?(?:is\s+)?based in\s+({city_state})",
        rf"(?:our|the)\s+({city_state})\s+office",
        rf"(?:located|location)\s+in\s+({city_state})",
    ]
    for pattern in patterns:
        m = re.search(pattern, d, re.I)
        if m:
            return normalize(m.group(1)).rstrip(" ,")
    return ""

def expected_pay_from_description(desc):
    d = normalize(desc)
    money = r"\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?![\d,])"
    amount = rf"{money}(?:\s*(?:-|–|to)\s*{money})?(?:\s*(?:per|/|a)\s*(?:hour|year|annum))?"
    patterns = [
        rf"(?:salary|pay|compensation)(?:\s+range)?(?:\s+is|\s+of)?\s*[:：]?\s*({amount})",
        rf"({money}\s*(?:-|–|to)\s*{money}(?:\s*(?:per|/|a)\s*(?:hour|year|annum))?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, d, re.I)
        if m:
            return normalize(m.group(1)).rstrip(" ,")
    return ""

def remove_employer_from_title(title, employer):
    title = normalize(title)
    if employer:
        suffix = f" at {employer}"
        if title.lower().endswith(suffix.lower()):
            return title[:-len(suffix)].strip()
    return title

def location_from_title(job_title):
    # Handshake sometimes appends locations like:
    # "Software Developer Intern - San Diego, California"
    m = re.search(
        r"\s+-\s+([A-Za-z][A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))$",
        job_title,
    )
    if not m:
        return None, job_title
    location = normalize(m.group(1))
    clean_title = job_title[:m.start()].strip()
    return location, clean_title

def location_from_description(desc):
    d = normalize(desc)

    # Explicit remote geography.
    m = re.search(
        r"This is a remote position that may be based in\s+([^.]+)\.",
        d, re.I
    )
    if m:
        return "Remote; " + normalize(m.group(1))

    # Explicit "position is based in City, State".
    m = re.search(
        r"(?:This position is based in|position is based in)\s+"
        r"([A-Za-z][A-Za-z .'-]+,\s*(?:D\.?C\.?|[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))"
        r"(?:\s*\([^)]*\))?",
        d, re.I
    )
    if m:
        loc = normalize(m.group(1)).rstrip(".,")
        return loc

    # Explicit headquarters/office location, often under a LOCATION heading.
    m = re.search(
        r"headquarters(?:\s+is)?(?:\s+located)?\s+in\s+"
        r"([A-Za-z][A-Za-z .'-]+,\s*(?:D\.?C\.?|[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))",
        d, re.I
    )
    if m:
        loc = normalize(m.group(1)).rstrip(".,")
        return loc

    return ""

def clean_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("The source is not an RSS 2.0 feed with a channel.")

    new_root = ET.Element("rss", {"version": "2.0"})
    new_channel = ET.SubElement(new_root, "channel")
    ET.SubElement(new_channel, "title").text = "Brandeis Handshake Jobs"
    ET.SubElement(new_channel, "link").text = text(channel, "link")
    ET.SubElement(new_channel, "description").text = (
        "Simplified Handshake job listings."
    )
    ET.SubElement(new_channel, "language").text = "en-us"

    for old in channel.findall("item"):
        desc = text(old, "description")
        employer = employer_from_description(desc)
        expires = expiration_from_description(desc)
        job_title = remove_employer_from_title(text(old, "title"), employer)

        clean_title = job_title
        loc = onsite_location_from_description(desc)
        position_type = position_type_from_text(clean_title, desc)
        location_type = location_type_from_description(desc)
        expected_pay = expected_pay_from_description(desc)

        item = ET.SubElement(new_channel, "item")
        ET.SubElement(item, "title").text = clean_title

        # Keep every requested field present, using a blank value when the
        # source posting does not provide enough information.
        ET.SubElement(item, "description").text = (
            f"Employer: {employer}<br/>"
            f"Job title: {clean_title}<br/>"
            f"Position type: {position_type}<br/>"
            f"Location type: {location_type}<br/>"
            f"Onsite location: {loc}<br/>"
            f"Expected pay: {expected_pay}<br/>"
            f"Application close date: {expires}"
        )

        # Preserve click-through without exposing the private source-feed token.
        link = text(old, "link")
        if link:
            ET.SubElement(item, "link").text = link

        guid_text = text(old, "guid")
        if guid_text:
            guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
            guid.text = guid_text

    raw = ET.tostring(new_root, encoding="utf-8")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")

def main():
    req = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "Brandeis-Career-Network-RSS-Updater/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        xml_bytes = response.read()

    cleaned = clean_feed(xml_bytes)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(cleaned)

    # Validate before publishing.
    ET.parse(OUT)
    print(f"Updated {OUT}")

if __name__ == "__main__":
    main()
#!/usr/bin/env python3
import os
import re
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from xml.dom import minidom

FEED_URL = os.environ.get("HANDSHAKE_FEED_URL")
if not FEED_URL:
    raise SystemExit("Missing HANDSHAKE_FEED_URL secret.")

OUT = Path("docs/handshake-feed-cleaned.rss")

def text(el, tag):
    return (el.findtext(tag) or "").strip()

def normalize(s):
    return " ".join((s or "").split())

def employer_from_description(desc):
    m = re.search(r"Employer:\s*(.*?)\s+Expires:", desc, re.S | re.I)
    return normalize(m.group(1)) if m else ""

def expiration_from_description(desc):
    m = re.search(r"Expires:\s*(\d{1,2}/\d{1,2}/\d{4})", desc, re.I)
    return m.group(1) if m else ""

def position_type_from_text(title, desc):
    """Return a position type only when the posting states one clearly."""
    haystack = f"{title} {desc}"
    patterns = [
        (r"\b(?:full[- ]time|fulltime)\b", "Full-time"),
        (r"\b(?:part[- ]time|parttime)\b", "Part-time"),
        (r"\bintern(?:ship)?\b", "Internship"),
        (r"\bfellow(?:ship)?\b", "Fellowship"),
        (r"\bapprentice(?:ship)?\b", "Apprenticeship"),
        (r"\btemporary\b|\bseasonal\b", "Temporary/seasonal"),
        (r"\bcontract(?:or)?\s+(?:role|position|job)\b", "Contract"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, haystack, re.I):
            return label
    return ""

def location_type_from_description(desc):
    d = normalize(desc)
    if re.search(r"\bhybrid\b", d, re.I):
        return "Hybrid"
    if re.search(r"\bfully remote\b|\b100% remote\b|\bremote position\b|\bwork remotely\b", d, re.I):
        return "Remote"
    if re.search(r"\bon[- ]site\b|\bin[- ]person\b|\bin the office\b", d, re.I):
        return "On-site"
    return ""

def onsite_location_from_description(desc):
    d = normalize(desc)
    state = (
        r"(?:Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|"
        r"Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|"
        r"Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|"
        r"Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|"
        r"North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|"
        r"South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|"
        r"Wisconsin|Wyoming|District of Columbia|A[LKZR]|C[AOT]|D[EC]|FL|GA|HI|"
        r"I[ADLN]|K[SY]|LA|M[ADEHINOPST]|N[CDEHJMVY]|O[HKR]|PA|RI|S[CD]|T[NX]|"
        r"UT|V[AIT]|W[AIVY])\b"
    )
    city = r"[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z][A-Za-z.'-]*){0,4}"
    city_state = rf"{city},\s*{state}"
    patterns = [
        rf"Location\(s\):\s*({city_state}(?:\s+and\s+{city_state})*)",
        rf"(?:This position|The position|This role|The job)\s+(?:will be\s+)?(?:is\s+)?based in\s+({city_state})",
        rf"(?:our|the)\s+({city_state})\s+office",
        rf"(?:located|location)\s+in\s+({city_state})",
    ]
    for pattern in patterns:
        m = re.search(pattern, d, re.I)
        if m:
            return normalize(m.group(1)).rstrip(" ,")
    return ""

def expected_pay_from_description(desc):
    d = normalize(desc)
    money = r"\$(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?(?![\d,])"
    amount = rf"{money}(?:\s*(?:-|–|to)\s*{money})?(?:\s*(?:per|/|a)\s*(?:hour|year|annum))?"
    patterns = [
        rf"(?:salary|pay|compensation)(?:\s+range)?(?:\s+is|\s+of)?\s*[:：]?\s*({amount})",
        rf"({money}\s*(?:-|–|to)\s*{money}(?:\s*(?:per|/|a)\s*(?:hour|year|annum))?)",
    ]
    for pattern in patterns:
        m = re.search(pattern, d, re.I)
        if m:
            return normalize(m.group(1)).rstrip(" ,")
    return ""

def remove_employer_from_title(title, employer):
    title = normalize(title)
    if employer:
        suffix = f" at {employer}"
        if title.lower().endswith(suffix.lower()):
            return title[:-len(suffix)].strip()
    return title

def location_from_title(job_title):
    # Handshake sometimes appends locations like:
    # "Software Developer Intern - San Diego, California"
    m = re.search(
        r"\s+-\s+([A-Za-z][A-Za-z .'-]+,\s*(?:[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))$",
        job_title,
    )
    if not m:
        return None, job_title
    location = normalize(m.group(1))
    clean_title = job_title[:m.start()].strip()
    return location, clean_title

def location_from_description(desc):
    d = normalize(desc)

    # Explicit remote geography.
    m = re.search(
        r"This is a remote position that may be based in\s+([^.]+)\.",
        d, re.I
    )
    if m:
        return "Remote; " + normalize(m.group(1))

    # Explicit "position is based in City, State".
    m = re.search(
        r"(?:This position is based in|position is based in)\s+"
        r"([A-Za-z][A-Za-z .'-]+,\s*(?:D\.?C\.?|[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))"
        r"(?:\s*\([^)]*\))?",
        d, re.I
    )
    if m:
        loc = normalize(m.group(1)).rstrip(".,")
        return loc

    # Explicit headquarters/office location, often under a LOCATION heading.
    m = re.search(
        r"headquarters(?:\s+is)?(?:\s+located)?\s+in\s+"
        r"([A-Za-z][A-Za-z .'-]+,\s*(?:D\.?C\.?|[A-Z]{2}|[A-Za-z][A-Za-z .'-]+))",
        d, re.I
    )
    if m:
        loc = normalize(m.group(1)).rstrip(".,")
        return loc

    return ""

def clean_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("The source is not an RSS 2.0 feed with a channel.")

    new_root = ET.Element("rss", {"version": "2.0"})
    new_channel = ET.SubElement(new_root, "channel")
    ET.SubElement(new_channel, "title").text = "Brandeis Handshake Jobs"
    ET.SubElement(new_channel, "link").text = text(channel, "link")
    ET.SubElement(new_channel, "description").text = (
        "Simplified Handshake job listings."
    )
    ET.SubElement(new_channel, "language").text = "en-us"

    for old in channel.findall("item"):
        desc = text(old, "description")
        employer = employer_from_description(desc)
        expires = expiration_from_description(desc)
        job_title = remove_employer_from_title(text(old, "title"), employer)

        clean_title = job_title
        loc = onsite_location_from_description(desc)
        position_type = position_type_from_text(clean_title, desc)
        location_type = location_type_from_description(desc)
        expected_pay = expected_pay_from_description(desc)

        item = ET.SubElement(new_channel, "item")
        ET.SubElement(item, "title").text = clean_title

        # The job title is already the item heading. Include only body fields
        # that have a value so the published entry has no empty lines.
        fields = [
            ("Employer", employer),
            ("Position type", position_type),
            ("Location type", location_type),
            ("Onsite location", loc),
            ("Expected pay", expected_pay),
            ("Application close date", expires),
        ]
        ET.SubElement(item, "description").text = "<br/>".join(
            f"{label}: {value}" for label, value in fields if value
        )

        # Preserve click-through without exposing the private source-feed token.
        link = text(old, "link")
        if link:
            ET.SubElement(item, "link").text = link

        guid_text = text(old, "guid")
        if guid_text:
            guid = ET.SubElement(item, "guid", {"isPermaLink": "false"})
            guid.text = guid_text

    raw = ET.tostring(new_root, encoding="utf-8")
    return minidom.parseString(raw).toprettyxml(indent="  ", encoding="UTF-8")

def main():
    req = urllib.request.Request(
        FEED_URL,
        headers={"User-Agent": "Brandeis-Career-Network-RSS-Updater/1.0"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        xml_bytes = response.read()

    cleaned = clean_feed(xml_bytes)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(cleaned)

    # Validate before publishing.
    ET.parse(OUT)
    print(f"Updated {OUT}")

if __name__ == "__main__":
    main()
