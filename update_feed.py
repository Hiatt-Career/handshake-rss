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

OUT_RSS = Path("docs/handshake-feed-cleaned.rss")
OUT_XML = Path("docs/handshake-feed-cleaned.xml")

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

def posting_sentences(desc):
    """Return readable sentences from the unstructured Handshake description."""
    body = re.sub(
        r"^\s*Employer:.*?\s+Expires:\s*\d{1,2}/\d{1,2}/\d{4}\s*",
        "",
        desc,
        count=1,
        flags=re.S | re.I,
    )
    # Handshake sometimes removes spaces between HTML blocks and sentences.
    body = body.replace("**", " ")
    body = re.sub(r"([.!?])(?=[A-Z])", r"\1 ", body)
    body = re.sub(r"(?<=[a-z0-9])(?=(?:This|The|As a|We|Our)\s+[A-Z])", ". ", body)
    body = re.sub(
        r"(?<=[a-z0-9)])(?=(?:SUMMARY|GENERAL DESCRIPTION|JOB SUMMARY|"
        r"RESPONSIBILITIES|IDEAL CANDIDATE|MINIMUM QUALIFICATIONS|"
        r"WHAT [A-Z][A-Z ]+ OFFERS|PHYSICAL WORK ADDRESS):)",
        ". ",
        body,
    )
    body = re.sub(r"(:)(?=[A-Z])", r"\1 ", body)
    sentences = []
    for sentence in re.split(r"(?<=[.!?])\s+", body):
        sentence = normalize(sentence).strip(" -•")
        sentence = re.sub(
            r"^(?:SUMMARY|GENERAL DESCRIPTION|JOB SUMMARY|RESPONSIBILITIES):\s*",
            "",
            sentence,
            flags=re.I,
        )
        if not 45 <= len(sentence) <= 380:
            continue
        if re.search(
            r"https?://|[\w.+-]+@[\w.-]+\.\w+|\bapply (?:today|now|here)\b|"
            r"\bsend (?:your )?resume\b|"
            r"\bequal opportunity\b|\bEOE\b|\bquestions? about the position\b",
            sentence,
            re.I,
        ):
            continue
        sentences.append(sentence)
    return sentences

def select_summary(sentences, score, excluded=None, limit=2):
    excluded = set(excluded or [])
    ranked = []
    for index, sentence in enumerate(sentences):
        if sentence in excluded:
            continue
        value = score(sentence)
        if value > 0:
            ranked.append((value, -index, sentence))
    selected = [entry[2] for entry in sorted(ranked, reverse=True)[:limit]]
    selected.sort(key=sentences.index)
    return selected

def extract_summaries(desc, employer, job_title):
    """Create short extractive employer and role summaries without inventing text."""
    sentences = posting_sentences(desc)
    employer_terms = [
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z&.'-]{2,}", employer)
        if term.lower() not in {"the", "and", "inc", "llc", "corp", "company"}
    ]
    title_terms = [
        term.lower()
        for term in re.findall(r"[A-Za-z][A-Za-z'-]{3,}", job_title)
        if term.lower() not in {"with", "from", "this", "that"}
    ]

    def employer_score(sentence):
        lower = sentence.lower()
        if not re.search(
            r"\b(?:we are|is a|is an|company|organization|firm|our mission|"
            r"founded|specializes|provides|delivers|serves|helps|works with|"
            r"empowers?|unlocks?|offers)\b",
            lower,
        ):
            return 0
        score = 3
        if any(term in lower for term in employer_terms):
            score += 3
        if re.search(r"\b(?:position|role|candidate|responsibilit|you will|you'll)\b", lower):
            score -= 3
        if re.search(
            r"\b(?:required|requirements?|qualifications?|years? of experience|"
            r"applicants?|license|complies?|must have|ideal candidate|"
            r"experience in|skill in|responsibilities?:)\b",
            lower,
        ):
            score -= 6
        return score

    employer_selected = select_summary(sentences, employer_score, limit=2)

    def role_score(sentence):
        lower = sentence.lower()
        score = 0
        if re.search(r"\b(?:job summary|responsible for|responsibilities include)\b", lower):
            score += 6
        elif re.search(
            r"\b(?:position|role|responsibilit|seeking|looking for|"
            r"you will|you'll|will be responsible|opportunity to)\b",
            lower,
        ):
            score += 4
        if any(term in lower for term in title_terms):
            score += 2
        if re.search(r"\b(?:salary|compensation|benefits|insurance|paid time off)\b", lower):
            score -= 3
        if re.search(
            r"\b(?:required|requirements?|qualifications?|years? of experience|"
            r"applicants?|license|must have|ideal candidate|selected for|"
            r"requiring|may require|protective equipment|operational status)\b",
            lower,
        ):
            score -= 6
        return score

    role_selected = select_summary(
        sentences, role_score, excluded=employer_selected, limit=2
    )
    return " ".join(employer_selected), " ".join(role_selected)

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
        employer_summary, role_summary = extract_summaries(
            desc, employer, clean_title
        )

        item = ET.SubElement(new_channel, "item")
        ET.SubElement(item, "title").text = clean_title

        # The job title is already the item heading. Include only body fields
        # that have a value so the published entry has no empty lines.
        fields = [
            ("Employer", employer),
            ("Employer summary", employer_summary),
            ("Role summary", role_summary),
            ("Position type", position_type),
            ("Location type", location_type),
            ("Onsite location", loc),
            ("Expected pay", expected_pay),
            ("Job post date", posted_date),
            ("Application close date", expires),
        ]
        body = "<br/><br/>".join(
            f"{label}: {value}" for label, value in fields if value
        )
        if body:
            body += "<br/><br/>"
        body += "Click the Apply button below to learn more"
        ET.SubElement(item, "description").text = body

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
    OUT_RSS.parent.mkdir(parents=True, exist_ok=True)
    OUT_RSS.write_bytes(cleaned)
    OUT_XML.write_bytes(cleaned)

    # Validate before publishing.
    ET.parse(OUT_RSS)
    ET.parse(OUT_XML)
    print(f"Updated {OUT_RSS} and {OUT_XML}")

if __name__ == "__main__":
    main()
