"""Publication metadata from PubMed, fetched per silo.

Every pmid a silo cites — its interactions, its GO annotations, the evidence
behind its UniProt function text — becomes a `:Publication`, and its title,
abstract, journal, year and authors come from here. Each silo fetches its own
`publications.tsv`, so a pmid two silos cite is fetched twice; the build makes
one node of it.

E-utilities `efetch`, as XML, in batches. The release is PubMed's `DbBuild`,
from `einfo`. A pmid PubMed does not return is written with its pmid alone —
empty text, year `0` — and logged, so the graph still says what cited it.

The file is also the cache: a pmid already in it is not fetched again, so a
rerun after a new source only fetches what is new. Without `NCBI_API_KEY`,
NCBI allows three requests a second; with it, ten.
"""

import csv
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bpgraph.sources import record_source

logger = logging.getLogger(__name__)

EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
EINFO_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/einfo.fcgi?db=pubmed"
BATCH_SIZE = 400
COLUMNS = ("pmid", "title", "year", "journal", "authors", "abstract")
AUTHOR_SEPARATOR = "; "
UNKNOWN_YEAR = 0

TIMEOUT = 120.0
ATTEMPTS = 5
BACKOFF = 5.0
YEAR = re.compile(r"\d{4}")


@dataclass(frozen=True, slots=True)
class Article:
    pmid: str
    title: str
    year: int
    journal: str
    authors: tuple[str, ...]
    abstract: str


def _text(element: ET.Element | None) -> str:
    """All the text under an element, markup dropped, on one line."""
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _year(*elements: ET.Element | None) -> int:
    """The first four-digit year any of these dates holds."""
    for element in elements:
        found = YEAR.search(_text(element))
        if found:
            return int(found.group())
    return UNKNOWN_YEAR


def _authors(authors: Iterable[ET.Element]) -> tuple[str, ...]:
    """`LastName Initials`, or a consortium's name."""
    names: list[str] = []
    for author in authors:
        collective = _text(author.find("CollectiveName"))
        last = _text(author.find("LastName"))
        initials = _text(author.find("Initials"))
        name = collective or " ".join(part for part in (last, initials) if part)
        if name:
            names.append(name)
    return tuple(names)


def _abstract(abstract: ET.Element | None) -> str:
    """The sections of an abstract, each under its label when it has one."""
    if abstract is None:
        return ""
    parts: list[str] = []
    for section in abstract.findall("AbstractText"):
        text = _text(section)
        label = section.get("Label", "")
        if text:
            parts.append(f"{label}: {text}" if label else text)
    return " ".join(parts)


def _article(element: ET.Element) -> Article | None:
    """One `PubmedArticle` or `PubmedBookArticle`."""
    if element.tag == "PubmedArticle":
        citation = element.find("MedlineCitation")
        if citation is None:
            return None
        article = citation.find("Article")
        if article is None:
            return None
        journal = article.find("Journal")
        return Article(
            pmid=_text(citation.find("PMID")),
            title=_text(article.find("ArticleTitle")),
            year=_year(
                journal.find("JournalIssue/PubDate") if journal is not None else None,
                article.find("ArticleDate"),
                citation.find("DateCompleted"),
            ),
            journal=_text(journal.find("Title")) if journal is not None else "",
            authors=_authors(article.findall("AuthorList/Author")),
            abstract=_abstract(article.find("Abstract")),
        )
    if element.tag == "PubmedBookArticle":
        document = element.find("BookDocument")
        if document is None:
            return None
        return Article(
            pmid=_text(document.find("PMID")),
            title=_text(document.find("ArticleTitle"))
            or _text(document.find("Book/BookTitle")),
            year=_year(document.find("Book/PubDate")),
            journal=_text(document.find("Book/Publisher/PublisherName")),
            authors=_authors(document.findall("AuthorList/Author")),
            abstract=_abstract(document.find("Abstract")),
        )
    return None


def _key() -> dict[str, str]:
    key = os.environ.get("NCBI_API_KEY", "")
    return {"api_key": key} if key else {}


def _post(url: str, fields: dict[str, str]) -> bytes:
    """One request, retried while the failure is NCBI's rather than ours."""
    data = urlencode({**fields, **_key()}).encode()
    attempt = 1
    while True:
        try:
            request = Request(url, data=data, headers={"User-Agent": "bpgraph"})
            with urlopen(request, timeout=TIMEOUT) as response:
                return response.read()
        except (URLError, TimeoutError) as error:
            if isinstance(error, HTTPError) and error.code not in {429, 500, 502, 503}:
                raise
            if attempt == ATTEMPTS:
                raise
            delay = BACKOFF * attempt
            logger.warning("pubmed: %s, retrying in %.0fs", error, delay)
            time.sleep(delay)
            attempt += 1


def fetch(pmids: Iterable[str]) -> Iterator[Article]:
    """The articles PubMed returns for these pmids, batch by batch."""
    wanted = sorted(set(pmids), key=int)
    pause = 0.12 if _key() else 0.4
    for start in range(0, len(wanted), BATCH_SIZE):
        batch = wanted[start : start + BATCH_SIZE]
        root = ET.fromstring(
            _post(EFETCH_URL, {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
        )
        for element in root:
            article = _article(element)
            if article is not None and article.pmid:
                yield article
        logger.info("pubmed: %d/%d pmids", start + len(batch), len(wanted))
        time.sleep(pause)


def release() -> str:
    """PubMed's current build, e.g. `Build-2026.09.25.23.10`."""
    root = ET.fromstring(_post(EINFO_URL, {}))
    return _text(root.find("DbInfo/DbBuild"))


def read_publications(path: Path) -> dict[str, Article]:
    """A silo's file, keyed by pmid. Nothing if it is not fetched yet."""
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t", quoting=csv.QUOTE_NONE)
        return {
            row["pmid"]: Article(
                pmid=row["pmid"],
                title=row["title"],
                year=int(row["year"]),
                journal=row["journal"],
                authors=tuple(
                    a.strip() for a in row["authors"].split(";") if a.strip()
                ),
                abstract=row["abstract"],
            )
            for row in reader
        }


def write_publications(
    pmids: Iterable[str], path: Path, sources: Path, dataset: str
) -> tuple[int, int, list[str]]:
    """Fetch what the file lacks and rewrite it with exactly these pmids.
    Returns the pmids written, how many were fetched, and those PubMed did not
    return."""
    wanted = set(pmids)
    known = read_publications(path)
    missing = wanted - set(known)
    fetched: dict[str, Article] = {}
    if missing:
        fetched = {article.pmid: article for article in fetch(missing)}
        record_source(sources, dataset, EFETCH_URL, release())
    articles = {**known, **fetched}
    absent = sorted(missing - set(fetched), key=int)
    if absent:
        logger.warning(
            "pubmed: %d pmids not returned, kept with their pmid alone: %s",
            len(absent),
            ", ".join(absent[:20]),
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("\t".join(COLUMNS) + "\n")
        for pmid in sorted(wanted, key=int):
            article = articles.get(pmid) or Article(pmid, "", UNKNOWN_YEAR, "", (), "")
            fields = (
                article.pmid,
                article.title,
                str(article.year),
                article.journal,
                AUTHOR_SEPARATOR.join(article.authors),
                article.abstract,
            )
            handle.write("\t".join(" ".join(f.split()) for f in fields) + "\n")
    return len(wanted), len(fetched), absent


def main() -> None:
    """Fetch the publications of every silo of one run directory.

    `uv run bpgraph-pubmed data/2026-09-09` needs the silos' other fetches
    first — what a silo cites is what it fetches — and writes each silo's
    `publications.tsv`.
    """
    import sys

    from bpgraph.loaders.host import host_pmids
    from bpgraph.loaders.viral import viral_pmids
    from bpgraph.run import HUMAN, Run

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if len(sys.argv) != 2:
        sys.exit("usage: bpgraph-pubmed <run directory>")
    run = Run(Path(sys.argv[1]))
    host = run.host(HUMAN)
    for dataset, path, pmids in (
        (f"{HUMAN} pubmed", host.publications, host_pmids(run, host)),
        ("viral pubmed", run.viral.publications, viral_pmids(run)),
    ):
        written, fetched, absent = write_publications(pmids, path, run.sources, dataset)
        print(f"{path}: {written} pmids, {fetched} fetched, {len(absent)} absent")
