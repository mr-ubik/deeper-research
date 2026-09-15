#!/usr/bin/env python3
"""Cache archived or fetched source text for M1 judging."""

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import urllib.request
from email.message import Message
from html.parser import HTMLParser
from pathlib import Path


class TextHTMLParser(HTMLParser):
    DROP = {"script", "style", "nav", "noscript"}
    BLOCK = {"address", "article", "aside", "blockquote", "br", "dd", "div", "dl", "dt",
             "fieldset", "figcaption", "figure", "footer", "form", "h1", "h2", "h3", "h4",
             "h5", "h6", "header", "hr", "li", "main", "ol", "p", "pre", "section",
             "table", "td", "th", "tr", "ul"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.DROP:
            self.hidden.append(tag)
        if not self.hidden and tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.hidden:
            self.hidden = self.hidden[:len(self.hidden) - 1 - self.hidden[::-1].index(tag)]
            if not self.hidden:
                self.parts.append("\n")
        elif not self.hidden and tag in self.BLOCK:
            self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def html_to_text(text):
    parser = TextHTMLParser()
    parser.feed(text)
    parser.close()
    lines = [re.sub(r"\s+", " ", line).strip() for line in "".join(parser.parts).splitlines()]
    return "\n".join(line for line in lines if line)


def fetch_url(url):
    """The only network boundary: return (HTTP status, raw bytes, Content-Type)."""
    request = urllib.request.Request(url, headers={"User-Agent": "deeper-research-bench/0.1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.status, response.read(), response.headers.get("Content-Type", "")


def archive_mapping(run_dir):
    if run_dir is None:
        return {}
    run_dir = Path(run_dir)
    results_file = run_dir / "results.json"
    if not results_file.exists():
        return {}
    data = json.loads(results_file.read_text(encoding="utf-8"))
    mapping = {}
    for source, result in zip(data.get("ledger", {}).get("sources", []), data.get("results", [])):
        url, filename = source.get("source"), result.get("page_file")
        if not url or not filename:
            continue
        path = Path(filename)
        if not path.is_file():
            path = run_dir / "pages" / path.name
        if path.is_file():
            mapping[url] = path
    return mapping


def decode_source(data, content_type):
    """Convert supported response bodies; unsupported formats raise ValueError."""
    header = Message()
    header["content-type"] = content_type
    mime = content_type.split(";", 1)[0].strip().lower()
    if mime == "application/pdf":
        executable = shutil.which("pdftotext")
        if executable is None:
            raise ValueError("pdf-no-pdftotext")
        result = subprocess.run([executable, "-layout", "-", "-"], input=data,
                                capture_output=True, check=True, timeout=30)
        return result.stdout.decode("utf-8", errors="replace")
    if not (mime.startswith("text/") or mime == "application/xhtml+xml"):
        raise ValueError("non-text-content-type: " + (mime or "missing"))
    text = data.decode(header.get_content_charset() or "utf-8", errors="replace")
    return html_to_text(text) if mime in {"text/html", "application/xhtml+xml"} else text


def fetch_sources(items, out, run_dir=None):
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    index_path = out / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    archives = archive_mapping(run_dir)
    urls = dict.fromkeys(url for item in items for url in item["urls"])
    for url in urls:
        if url in index:
            continue
        status, reason, text = "dead", "", ""
        try:
            if url in archives:
                text = archives[url].read_bytes().decode("utf-8", errors="replace")
                status = "archived"
            else:
                if not url:
                    raise ValueError("empty-url")
                code, data, content_type = fetch_url(url)
                if code >= 400:
                    raise ValueError(f"http-{code}")
                text = decode_source(data, content_type)
                status = "fetched"
        except Exception as error:
            reason = str(error) or type(error).__name__
        path = (out / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".txt")).resolve()
        encoded = text.encode("utf-8")
        path.write_bytes(encoded)
        index[url] = {"path": str(path), "status": status, "bytes": len(encoded), "reason": reason}
        # Checkpoint each completed source so an interrupted run retains its cache.
        index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")
    if not index_path.exists():
        index_path.write_text("{}\n", encoding="utf-8")
    return index


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--items", required=True)
    parser.add_argument("--run-dir")
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    items = json.loads(Path(args.items).read_text(encoding="utf-8"))
    fetch_sources(items, args.out, args.run_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
