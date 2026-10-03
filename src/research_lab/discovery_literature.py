"""Bounded public metadata discovery. Abstracts are never represented as full texts."""
import json
import re
import time
from html import unescape
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPRedirectHandler
import xml.etree.ElementTree as ET

from .project import identity
from .storage import utc_now, write_json, write_text


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("Literature endpoint redirects are not followed")


def clean(value, limit):
    return unescape(re.sub(r"<[^>]+>", " ", str(value))).strip()[:limit]


def fetch(url, accept):
    request = Request(url, headers={"User-Agent": "BDCI-Research-Lab/0.8 (bounded academic metadata search)", "Accept": accept})
    deadline = time.monotonic() + 35
    with build_opener(NoRedirect()).open(request, timeout=10) as response:
        chunks, size = [], 0
        while True:
            block = response.read(65536)
            size += len(block)
            if size > 4_000_000 or time.monotonic() > deadline:
                raise TimeoutError("Literature response exceeded byte/time allowance")
            if not block:
                break
            chunks.append(block)
    return b"".join(chunks)


class CrossrefSearch:
    identity = {"provider": "Crossref REST", "version": 1}

    def search(self, query, limit, folder):
        url = "https://api.crossref.org/works?" + urlencode({"query.bibliographic": query, "rows": limit})
        data = json.loads(fetch(url, "application/json"))
        write_json(folder / "provider-response.json", data)
        sources = []
        for item in data.get("message", {}).get("items", [])[:limit]:
            doi = item.get("DOI", "")
            title = clean(" ".join(item.get("title", [])), 500)
            if not doi or not title:
                continue
            abstract = clean(item.get("abstract", ""), 3500)
            level = "abstract" if abstract else "metadata_only"
            text = f"Evidence level: {level}. Title: {title}.\n" + abstract
            sources.append({"id": "cr_" + identity(doi.lower())[:20], "title": title,
                "url": "https://doi.org/" + doi, "doi": doi, "text": text,
                "evidence_level": level, "verification": "Publisher-deposited metadata; not verified full text",
                "retrieved_at": utc_now()})
        return {"query": query, "url": url, "sources": sources, "retrieved_at": utc_now(),
                "coverage": "Bounded metadata search; absence is not evidence of novelty"}


class ArxivSearch:
    identity = {"provider": "arXiv Atom API", "version": 1}

    def search(self, query, limit, folder):
        # Generated queries are keywords, never model-supplied URLs or executable expressions.
        tokens = re.findall(r"[A-Za-z0-9-]+", query)[:12]
        if not tokens:
            raise ValueError("arXiv queries require English scientific keywords")
        expression = " AND ".join("all:" + t for t in tokens)
        url = "https://export.arxiv.org/api/query?" + urlencode({"search_query": expression,
               "start": 0, "max_results": limit, "sortBy": "relevance", "sortOrder": "descending"})
        time.sleep(3)  # Single sequential connection; observe the API request-spacing guideline.
        raw = fetch(url, "application/atom+xml")
        write_text(folder / "provider-response.xml", raw.decode("utf-8"))
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("Entity declarations are prohibited in literature feeds")
        try:
            feed = ET.fromstring(raw)
        except ET.ParseError as exc:
            raise ValueError("Invalid arXiv Atom response") from exc
        ns, sources = {"a": "http://www.w3.org/2005/Atom"}, []
        for entry in feed.findall("a:entry", ns)[:limit]:
            url_id = entry.findtext("a:id", "", ns)
            if not re.fullmatch(r"https?://arxiv\.org/abs/[A-Za-z0-9./-]+", url_id):
                continue
            title = clean(entry.findtext("a:title", "", ns), 500)
            abstract = clean(entry.findtext("a:summary", "", ns), 3500)
            if not title or len(abstract) < 20:
                continue
            sources.append({"id": "ax_" + identity(url_id)[:20], "title": title,
                "url": url_id.replace("http://", "https://", 1), "text": "Evidence level: abstract. Title: " + title + ".\n" + abstract,
                "evidence_level": "abstract", "verification": "Author-deposited preprint abstract; not full text or peer-review certification",
                "retrieved_at": utc_now()})
        return {"query": query, "url": url, "sources": sources, "retrieved_at": utc_now(),
                "coverage": "Bounded preprint abstract search; absence is not novelty evidence"}


class FixtureSearch:
    identity = {"provider": "synthetic-literature-fixture", "version": 1}

    def search(self, query, limit, folder):
        return {"query": query, "sources": [{"id": "synthetic_discovery", "title": "Synthetic discovery fixture",
            "url": "https://example.invalid/fixture", "text": "Synthetic classification source for software workflow acceptance only; no scientific evidence.",
            "evidence_level": "synthetic_fixture", "verification": "Scripted fixture"}], "coverage": "Synthetic only"}
