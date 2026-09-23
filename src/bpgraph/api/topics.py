"""Writing `:Topic` nodes and the proteins they involve."""

from collections.abc import Iterable

from bpgraph.client import GraphWriter, Row
from bpgraph.dedupe import dedupe
from bpgraph.models import Involvement, Topic

INVOLVED_IN = """MATCH (protein:Protein {id: r.protein_id})
MATCH (topic:Topic {name: r.topic})
CREATE (protein)-[involvement:INVOLVED_IN]->(topic)
SET involvement += r.properties"""


def write_topics(writer: GraphWriter, topics: Iterable[Topic]) -> int:
    rows: list[Row] = [
        {"name": topic.name} for topic in dedupe(topics, key=lambda topic: topic.name)
    ]
    return writer.create("Topic", rows)


def write_involvements(writer: GraphWriter, involvements: Iterable[Involvement]) -> int:
    rows: list[Row] = [
        {
            "protein_id": involvement.protein.id,
            "topic": involvement.topic,
            "properties": dict(involvement.properties),
        }
        for involvement in dedupe(involvements, key=lambda i: (i.protein.id, i.topic))
    ]
    return writer.write(INVOLVED_IN, rows)
