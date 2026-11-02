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
rerun after a new source only fetches what is new, and a pmid nothing cites
any more is dropped from it. Without `NCBI_API_KEY`,
NCBI allows three requests a second; with it, ten.
"""

import logging
import os
import re
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import batched
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from bpgraph import files
from bpgraph.enums import InteractionKind
from bpgraph.run import HUMAN, HostPaths, Run
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


def fetch(pmids: Iterable[str]) -> Iterator[tuple[list[str], list[Article]]]:
    """Each batch of pmids, with the articles PubMed returns for it."""
    pause = 0.12 if _key() else 0.4
    done = 0
    for batch in batched(pmids, BATCH_SIZE, strict=False):
        root = ET.fromstring(
            _post(EFETCH_URL, {"db": "pubmed", "id": ",".join(batch), "retmode": "xml"})
        )
        articles = [a for a in map(_article, root) if a is not None and a.pmid]
        done += len(batch)
        logger.info("pubmed: %d pmids fetched", done)
        yield list(batch), articles
        time.sleep(pause)


def release() -> str:
    """PubMed's current build, e.g. `Build-2026.09.25.23.10`."""
    root = ET.fromstring(_post(EINFO_URL, {}))
    return _text(root.find("DbInfo/DbBuild"))


def _fields(article: Article) -> list[str]:
    return [
        " ".join(field.split())
        for field in (
            article.pmid,
            article.title,
            str(article.year),
            article.journal,
            AUTHOR_SEPARATOR.join(article.authors),
            article.abstract,
        )
    ]


def write_publications(
    pmids: Iterable[str], path: Path, sources: Path, dataset: str
) -> tuple[int, int, int]:
    """Rewrite a silo's file with exactly these pmids, fetching only those it
    lacks. Returns the pmids written, how many were fetched, and how many
    PubMed did not return.

    The pmids wanted and the file already there are sorted on disk and read
    side by side: a pmid in both keeps its row, one only wanted is fetched.
    """
    from bpgraph.loaders.tsv import rows

    path.parent.mkdir(parents=True, exist_ok=True)
    fetched = absent = 0
    with tempfile.TemporaryDirectory(dir=path.parent) as directory:
        scratch = Path(directory)
        wanted = files.sorted_file(
            scratch / "wanted", ([p] for p in pmids), unique=True
        )
        known = files.sorted_file(
            scratch / "known",
            ([row[c] for c in COLUMNS] for _, row in rows(path))
            if path.exists()
            else (),
        )
        out, missing = scratch / "out", scratch / "missing"
        with out.open("w", encoding="utf-8", newline="\n") as handle:
            with missing.open("w", encoding="utf-8", newline="\n") as lacking:
                for (pmid,), want, have in files.cogroup(
                    files.read(wanted), files.read(known), 1
                ):
                    if want and have:
                        handle.write("\t".join(have[0]) + "\n")
                    elif want:
                        lacking.write(pmid + "\n")
            if missing.stat().st_size:
                for batch, articles in fetch(r[0] for r in files.read(missing)):
                    returned = {article.pmid for article in articles}
                    for article in articles:
                        handle.write("\t".join(_fields(article)) + "\n")
                    for pmid in batch:
                        if pmid not in returned:
                            empty = Article(pmid, "", UNKNOWN_YEAR, "", (), "")
                            handle.write("\t".join(_fields(empty)) + "\n")
                            absent += 1
                    fetched += len(articles)
                record_source(sources, dataset, EFETCH_URL, release())
        written = files.write_table(path, COLUMNS, files.read(files.sort(out)))
    if absent:
        logger.warning(
            "pubmed: %d pmids not returned, kept with their pmid alone", absent
        )
    return written, fetched, absent


def host_pmids(run: Run, host: HostPaths) -> Iterator[str]:
    """Every pmid a host's silo cites: IntAct, our curated rows of its
    interactome, its GO annotations and its function text."""
    from bpgraph.loaders.export import export_pmids
    from bpgraph.loaders.tsv import listed, rows

    yield from (row["pmid"] for _, row in rows(host.intact))
    yield from export_pmids(run.export, InteractionKind.HH)
    yield from (row["pmid"] for _, row in rows(host.go_annotations))
    for cursor, row in rows(host.swissprot):
        yield from listed(cursor, row, "pmids")


def viral_pmids(run: Run) -> Iterator[str]:
    """Every pmid the viral silo cites: our VH rows, and the function text of
    the viral proteins."""
    from bpgraph.loaders.export import export_pmids
    from bpgraph.loaders.tsv import listed, rows

    yield from export_pmids(run.export, InteractionKind.VH)
    for cursor, row in rows(run.viral.functions):
        yield from listed(cursor, row, "pmids")


def main() -> None:
    """Fetch the publications of every silo of one run directory.

    `uv run bpgraph-pubmed data/2026-09-09` needs the silos' other fetches
    first — what a silo cites is what it fetches — and writes each silo's
    `publications.tsv`.
    """
    import sys

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
        print(f"{path}: {written} pmids, {fetched} fetched, {absent} absent")
