"""增量：互动影视图补强（类型化结局 / WorldAnchor / 节点坐标 / 选项 weight）测试。"""
import pytest
from pydantic import ValidationError

from app.schemas.story_graph import (
    Choice,
    StoryEnding,
    StoryGraph,
    StoryNode,
    WorldAnchor,
    sync_node_positions,
)


def _graph() -> StoryGraph:
    return StoryGraph(
        graph_id="g1",
        nodes=[
            StoryNode(node_id="start", kind="scene", title="开头"),
            StoryNode(node_id="end_good", kind="ending", title="好结局"),
        ],
        entry_node_id="start",
    )


def test_typed_endings_valid():
    graph = _graph().model_copy(update={
        "endings": [StoryEnding(ending_id="e1", node_id="end_good", title="圆满", type="good")],
    })
    assert graph.endings[0].type == "good"
    assert graph.endings[0].node_id == "end_good"


def test_typed_endings_dangling_node_rejected():
    with pytest.raises(ValidationError):
        StoryGraph(
            graph_id="g1",
            nodes=[StoryNode(node_id="start", kind="scene")],
            entry_node_id="start",
            endings=[StoryEnding(ending_id="e1", node_id="nope", type="bad")],
        )


def test_choice_weight_and_node_position():
    node = StoryNode(
        node_id="mid", kind="choice", position={"x": 12.5, "y": 42.0},
        choices=[Choice(choice_id="c1", text="追问", weight="critical")],
    )
    assert node.position == {"x": 12.5, "y": 42.0}
    assert node.choices[0].weight == "critical"


def test_sync_node_positions():
    graph = _graph()
    moved = sync_node_positions(graph, {"start": {"x": 3, "y": 9}})
    assert moved.nodes[0].position == {"x": 3, "y": 9}
    assert moved.nodes[1].position is None
    assert graph.nodes[0].position is None  # 原 graph 不变


def test_world_anchor_default_and_set():
    g = _graph()
    assert g.world_anchor is None
    anchored = g.model_copy(update={"world_anchor": WorldAnchor(story_core="雨夜追凶", genre="悬疑")})
    assert anchored.world_anchor.story_core == "雨夜追凶"
    assert anchored.world_anchor.duration_minutes == 30