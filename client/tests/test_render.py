from pathlib import Path

import pytest
from pydantic import ValidationError

from bpgraph_client import render
from bpgraph_client.render import Network


def network(**changes: object) -> dict[str, object]:
    """A two-protein network, with `changes` replacing its fields."""
    proteins = [
        {
            "id": "P1",
            "name": "GPX4",
            "kind": "human",
            "description": "</script> in a description",
            "taxon_name": "Homo sapiens",
            "attributes": {"role": "driver"},
        },
        {
            "id": "V1",
            "name": "NS5A",
            "kind": "viral",
            "description": "",
            "taxon_name": "Hepatitis C virus",
        },
    ]
    interactions = [
        {"source": "V1", "target": "P1", "n_publications": 2, "n_methods": 1}
    ]
    fields: dict[str, object] = {
        "title": "Ferroptosis & Flaviviridae",
        "description": "golden",
        "proteins": proteins,
        "interactions": interactions,
    }
    return {**fields, **changes}


def test_render_fills_the_template() -> None:
    page = render.render(
        Network.model_validate(network()), "<title>{{title}}</title>{{network}}"
    )
    assert page.startswith("<title>Ferroptosis &amp; Flaviviridae</title>")
    assert '"name":"NS5A"' in page
    assert "</script>" not in page


def test_main_writes_the_page_beside_the_file(tmp_path: Path) -> None:
    path = tmp_path / "ferroptosis-flaviviridae.json"
    path.write_text(Network.model_validate(network()).model_dump_json())
    render.main([str(path)])
    page = (tmp_path / "ferroptosis-flaviviridae.cytoscape.html").read_text()
    assert '"name":"GPX4"' in page


@pytest.mark.parametrize(
    "changes",
    [
        {
            "interactions": [
                {"source": "V1", "target": "X", "n_publications": 1, "n_methods": 1}
            ]
        },
        {
            "interactions": [
                {"source": "V1", "target": "P1", "n_publications": 1, "n_methods": 1},
                {"source": "P1", "target": "V1", "n_publications": 1, "n_methods": 1},
            ]
        },
    ],
    ids=["unknown protein", "repeated pair"],
)
def test_an_inconsistent_network_is_refused(changes: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Network.model_validate(network(**changes))
