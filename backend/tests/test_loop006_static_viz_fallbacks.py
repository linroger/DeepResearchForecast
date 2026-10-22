"""LOOP-006: static timeline/network fallbacks for report visualizations."""

import hashlib
import json
import math
import os

import pytest

from app.services import report_visualizer as rv
from app.services.report_visualizer import ReportVisualizer


TIMELINE = [
    {"date": "2025-04-01", "event": "TSMC commits $165B to Arizona capacity"},
    {"date": "2026-01-13", "event": "BIS tightens semiconductor export controls"},
    {"date": "2026-06", "event": "Taiwan Strait exercise raises risk premium"},
]

ACTORS = {
    "actors": [
        {"name": "TSMC", "role_class": "principal", "influence": "high"},
        {"name": "Samsung Electronics", "aliases": ["Samsung"],
         "role_class": "principal", "influence": "high"},
        {"name": "BIS", "role_class": "arbiter", "influence": "medium"},
    ],
    "relationships": [
        {"source": "Samsung", "target": "TSMC", "type": "COMPETES_WITH",
         "sign": "rival"},
        {"source": "BIS", "target": "Samsung Electronics", "type": "REGULATES",
         "sign": "neutral"},
        {"source": "TSMC", "target": "BIS", "type": "DEPENDS_ON",
         "sign": "ally"},
    ],
}


def _dense_timeline():
    templates = (
        "BIS policy rule {i} tightens export controls by {value}%",
        "Foundry fab capacity milestone {i} reaches {value} billion",
        "Market funding round {i} reprices the forecast by {value}%",
    )
    return [
        {
            "date": f"2026-{1 + index // 3:02d}-{1 + (index % 3) * 9:02d}",
            "event": templates[index % len(templates)].format(
                i=index, value=index + 10,
            ),
        }
        for index in range(18)
    ]


def _dense_actors():
    names = [f"Actor Organization {index:02d}" for index in range(18)]
    return {
        "actors": [
            {"name": name, "role_class": "principal" if index % 2 else "arbiter"}
            for index, name in enumerate(names)
        ],
        "relationships": [
            {
                "source": name,
                "target": names[(index + 1) % len(names)],
                "type": "INFLUENCES",
                "sign": "supportive" if index % 3 else "adversarial",
            }
            for index, name in enumerate(names)
        ] + [
            {"source": names[index], "target": names[(index + 5) % len(names)],
             "type": "CONSTRAINS", "sign": "neutral"}
            for index in range(0, len(names), 3)
        ],
    }


def _assert_collision_free(boxes):
    for index, left in enumerate(boxes):
        for right in boxes[index + 1:]:
            assert not rv._boxes_overlap(left, right)


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_plotly_disabled_emits_static_timeline_and_actor_network_manifest_items(
        tmp_path, monkeypatch):
    """Both formerly interactive-only figures remain publishable without Plotly.

    actor_network is now opt-in (relationship structure, not forecast data), so the
    static fallback only emits it when REPORT_META_CHARTS is on — set it here to keep
    exercising the matplotlib fallback path for that figure.
    """
    monkeypatch.setattr(rv, "PLOTLY_AVAILABLE", False)
    monkeypatch.setenv("REPORT_META_CHARTS", "1")

    items = ReportVisualizer().build_all(
        "loop006-static",
        str(tmp_path),
        {
            "timeline": TIMELINE,
            "actors": ACTORS,
            "graph_priors": {"TSMC": 0.95, "Samsung Electronics": 0.75, "BIS": 0.6},
        },
    )

    by_id = {item["id"]: item for item in items}
    assert by_id["timeline_lanes"]["type"] == "png"
    assert by_id["timeline_lanes"]["placement_hint"] == "timeline"
    assert by_id["actor_network"]["type"] == "png"
    assert by_id["actor_network"]["placement_hint"] == "actors"

    for item_id in ("timeline_lanes", "actor_network"):
        item = by_id[item_id]
        assert item["path"] == os.path.join("charts", f"{item_id}.png")
        with open(tmp_path / item["path"], "rb") as image:
            assert image.read(8) == b"\x89PNG\r\n\x1a\n"

    manifest = json.loads((tmp_path / "viz_manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 2
    assert {item["id"] for item in manifest["items"]} >= {
        "timeline_lanes", "actor_network",
    }


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_static_timeline_and_actor_network_builders_are_input_safe(tmp_path):
    viz = ReportVisualizer()
    charts = str(tmp_path / "charts")

    assert viz.build_timeline_lanes({}, charts) is None
    assert viz.build_actor_network({"relationships": []}, charts) is None


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
@pytest.mark.parametrize("builder_name,payload", [
    ("build_timeline_lanes", TIMELINE),
    ("build_actor_network", ACTORS),
])
def test_static_builders_close_figures_when_drawing_raises(
        tmp_path, monkeypatch, builder_name, payload):
    """A degrade-safe render failure must not leak hidden Agg figures into the worker."""
    before = set(rv.plt.get_fignums())

    def _raise_after_subplots(*_args, **_kwargs):
        raise RuntimeError("forced drawing failure")

    monkeypatch.setattr(rv.plt.Axes, "scatter", _raise_after_subplots)
    result = getattr(ReportVisualizer(), builder_name)(payload, str(tmp_path / "charts"))

    assert result is None
    assert set(rv.plt.get_fignums()) == before


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_cjk_labels_are_preserved_or_explicitly_degraded(tmp_path, monkeypatch):
    """CJK labels remain their real names; no synthetic Event/Actor labels are permitted."""
    cjk_timeline = [{"date": "2026-03-01", "event": "台积电扩大先进制程产能"}]
    cjk_actors = {
        "actors": [
            {"name": "台积电", "role_class": "主要参与者"},
            {"name": "三星电子", "role_class": "主要参与者"},
        ],
        "relationships": [
            {"source": "台积电", "target": "三星电子", "type": "COMPETES",
             "sign": "rival"},
        ],
    }
    timeline_labels = "台积电扩大先进制程产能"
    actor_labels = "台积电 三星电子 主要参与者"
    assert rv._mpl_text("台积电", fallback="Actor 1") == "台积电"

    viz = ReportVisualizer()
    captured = []

    def _capture(fig, _charts_dir, filename):
        captured.extend(text.get_text() for axis in fig.axes for text in axis.texts)
        rv.plt.close(fig)
        return os.path.join("charts", filename)

    monkeypatch.setattr(viz, "_save", _capture)
    timeline_result = viz.build_timeline_lanes(cjk_timeline, str(tmp_path / "timeline"))
    actor_result = viz.build_actor_network(cjk_actors, str(tmp_path / "actors"))

    if rv._mpl_font_for_text(timeline_labels) is None:
        assert timeline_result is None
    else:
        assert timeline_result
        assert any(timeline_labels in text for text in captured)
    if rv._mpl_font_for_text(actor_labels) is None:
        assert actor_result is None
    else:
        assert actor_result
        assert "台积电" in captured
        assert "三星电子" in captured
    assert not any(text.startswith("Actor ") or text == "Event" for text in captured)


def test_extended_cjk_ranges_require_verified_font_coverage(monkeypatch):
    extended = "𠀀ㄅＡ"  # Extension B ideograph, Bopomofo, full-width Latin.
    assert {ord(char) for char in extended} <= rv._cjk_codepoints(extended)
    monkeypatch.setattr(rv, "_MPL_CJK_FONT_CACHE", [])
    assert not rv._mpl_labels_supported(extended)


def test_dense_label_plans_are_deterministic_and_collision_free():
    timeline_events = rv._prepare_timeline_events(_dense_timeline())
    lanes = [category for category, _ in rv._TL_CATEGORIES] + ["Other"]
    lane_order = {category: index for index, category in enumerate(lanes)}
    used = sorted({event["cat"] for event in timeline_events}, key=lane_order.get)
    used_index = {category: index for index, category in enumerate(used)}
    first_timeline = rv._timeline_label_plan(timeline_events, used_index)
    second_timeline = rv._timeline_label_plan(timeline_events, used_index)
    assert first_timeline == second_timeline
    assert len(first_timeline) == 12
    _assert_collision_free([entry["bbox"] for entry in first_timeline.values()])

    nodes = [f"Actor Organization {index:02d}" for index in range(18)]
    positions = {
        node: (math.cos(2 * math.pi * index / len(nodes)),
               math.sin(2 * math.pi * index / len(nodes)))
        for index, node in enumerate(nodes)
    }
    weights = {node: float(len(nodes) - index) for index, node in enumerate(nodes)}
    first_actor = rv._actor_label_plan(nodes, positions, weights)
    second_actor = rv._actor_label_plan(nodes, positions, weights)
    assert first_actor == second_actor
    assert len(first_actor) >= 16
    _assert_collision_free([entry["bbox"] for entry in first_actor.values()])


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_dense_static_outputs_are_byte_deterministic(tmp_path):
    viz = ReportVisualizer()
    paths = []
    for run in ("first", "second"):
        charts = tmp_path / run / "charts"
        timeline = viz.build_timeline_lanes(_dense_timeline(), str(charts))
        network = viz.build_actor_network(_dense_actors(), str(charts))
        assert timeline and network
        paths.append((tmp_path / run / timeline, tmp_path / run / network))

    for first, second in zip(paths[0], paths[1], strict=True):
        assert hashlib.sha256(first.read_bytes()).digest() == hashlib.sha256(
            second.read_bytes()).digest()


@pytest.mark.skipif(
    not (rv.MATPLOTLIB_AVAILABLE and rv.PLOTLY_AVAILABLE),
    reason="matplotlib/plotly not installed",
)
def test_kaleido_missing_attaches_static_timeline_and_actor_pngs(tmp_path, monkeypatch):
    """Interactive cards keep HTML while the new static equivalents supply PDF-safe PNGs.

    actor_network is opt-in now, so enable REPORT_META_CHARTS to keep it in the manifest.
    """
    monkeypatch.setattr(ReportVisualizer, "_png_export_ok", lambda self: False)
    monkeypatch.setenv("REPORT_META_CHARTS", "1")
    items = ReportVisualizer().build_all(
        "loop006-no-kaleido",
        str(tmp_path),
        {"timeline": TIMELINE, "actors": ACTORS},
    )
    by_id = {item["id"]: item for item in items}
    for item_id in ("timeline_lanes", "actor_network"):
        assert by_id[item_id]["type"] == "html"
        assert by_id[item_id]["png_path"] == os.path.join("charts", f"{item_id}.png")
        assert (tmp_path / by_id[item_id]["png_path"]).is_file()


@pytest.mark.skipif(not rv.MATPLOTLIB_AVAILABLE, reason="matplotlib not installed")
def test_worldstate_visual_is_titled_simulated_and_placed_with_simulation(tmp_path, monkeypatch):
    # ADR 0003 / S0.2: a chart drawn from simulation artifacts is never titled
    # "Forecast" and never files under the evidence-based scenario slot.
    from app.services import sim_provenance as sp
    monkeypatch.setattr(rv, "PLOTLY_AVAILABLE", False)
    items = ReportVisualizer().build_all(
        "loop006-outcome-first",
        str(tmp_path),
        {"world_state_trajectory": {"trajectory": [
            {"round": 0, "shares": {"Base case": 0.6, "Tail case": 0.4}},
            {"round": 1, "shares": {"Base case": 0.7, "Tail case": 0.3}},
        ]}},
    )
    item = {entry["id"]: entry for entry in items}["worldstate_trajectory"]
    assert item["title"] == sp.CHART_OUTCOME_SHARES_EN
    assert item["title"].lower().startswith("simulated")
    assert item["placement_hint"] == sp.CHART_PLACEMENT_HINT == "simulation"


@pytest.mark.skipif(not rv.PLOTLY_AVAILABLE, reason="plotly not installed")
def test_worldstate_html_has_no_simulation_mechanics_copy(tmp_path):
    rel = ReportVisualizer().build_worldstate_area_html(
        {"trajectory": [
            {"round": 0, "shares": {"Base case": 0.6, "Tail case": 0.4}},
            {"round": 1, "shares": {"Base case": 0.7, "Tail case": 0.3}},
        ]},
        str(tmp_path / "charts"),
    )
    assert rel
    html = (tmp_path / rel).read_text(encoding="utf-8")
    assert "Forecast update step %{x}" in html
    assert "round %{x}" not in html
