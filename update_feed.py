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

    # Conservative fallback. We deliberately do not guess from an employer name.
    return "Not specified in RSS feed"

def clean_feed(xml_bytes):
    root = ET.fromstring(xml_bytes)
    channel = root.find("channel")
    if channel is None:
        raise ValueError("The source is not an RSS 2.0 feed with a channel.")

    new_root = ET.Element("rss", {"version": "2.0"})
    new_channel = ET.SubElement(new_root, "channel")
    ET.SubElement(new_channel, "title").text = "Heller BC Graduway - Simplified Jobs"
    ET.SubElement(new_channel, "link").text = text(channel, "link")
    ET.SubElement(new_channel, "description").text = (
        "Handshake jobs showing job title, employer, location, and expiration date."
    )
    ET.SubElement(new_channel, "language").text = "en-us"

    for old in channel.findall("item"):
        desc = text(old, "description")
        employer = employer_from_description(desc)
        expires = expiration_from_description(desc)
        job_title = remove_employer_from_title(text(old, "title"), employer)

        loc, clean_title = location_from_title(job_title)
        if loc is None:
            loc = location_from_description(desc)

        item = ET.SubElement(new_channel, "item")
        ET.SubElement(item, "title").text = clean_title

        # These are the only visible details in the item body.
        ET.SubElement(item, "description").text = (
            f"Employer: {employer}<br/>"
            f"Location: {loc}<br/>"
            f"Expires: {expires}"
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
