"""Tests for get_topn.py - Top N plugin selection script."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from get_topn import (
    filter_excluded,
    generate_output,
    get_topn_plugins,
    merge_and_rank,
    _url_to_id,
)


# --- test_merges_stats_and_list ---
def test_merges_stats_and_list():
    """Correctly merge stats and list, using repository URL as key."""
    stats = {
        "https://github.com/foo/plugin-a": {"stars": 100},
        "https://github.com/foo/plugin-b": {"stars": 200},
    }
    node_list = {
        "custom_nodes": [
            {
                "id": "plugin-a",
                "title": "Plugin A",
                "reference": "https://github.com/foo/plugin-a",
                "description": "Desc A",
            },
            {
                "id": "plugin-b",
                "title": "Plugin B",
                "reference": "https://github.com/foo/plugin-b",
                "description": "Desc B",
            },
        ]
    }
    result = merge_and_rank(stats, node_list)
    assert len(result) == 2
    urls = [r["repository"] for r in result]
    assert "https://github.com/foo/plugin-a" in urls
    assert "https://github.com/foo/plugin-b" in urls
    # Should have stars merged
    plugin_a = next(r for r in result if r["repository"] == "https://github.com/foo/plugin-a")
    plugin_b = next(r for r in result if r["repository"] == "https://github.com/foo/plugin-b")
    assert plugin_a["stars"] == 100
    assert plugin_b["stars"] == 200


# --- test_sorts_by_stars_desc ---
def test_sorts_by_stars_desc():
    """Sort by star count descending."""
    stats = {
        "https://github.com/foo/plugin-a": {"stars": 50},
        "https://github.com/foo/plugin-b": {"stars": 300},
        "https://github.com/foo/plugin-c": {"stars": 150},
    }
    node_list = {
        "custom_nodes": [
            {"id": "plugin-a", "title": "A", "reference": "https://github.com/foo/plugin-a", "description": ""},
            {"id": "plugin-b", "title": "B", "reference": "https://github.com/foo/plugin-b", "description": ""},
            {"id": "plugin-c", "title": "C", "reference": "https://github.com/foo/plugin-c", "description": ""},
        ]
    }
    result = merge_and_rank(stats, node_list)
    assert [r["stars"] for r in result] == [300, 150, 50]
    assert result[0]["id"] == "plugin-b"


# --- test_excludes_by_repository_url ---
def test_excludes_by_repository_url():
    """Exclude plugins in excluded_custom_nodes.json (URL match)."""
    ranked = [
        {"id": "plugin-a", "repository": "https://github.com/foo/plugin-a", "stars": 100},
        {"id": "plugin-b", "repository": "https://github.com/foo/plugin-b", "stars": 200},
        {"id": "excluded-one", "repository": "https://github.com/foo/excluded-one", "stars": 500},
    ]
    excluded = {
        "custom_nodes": [
            {"repository": "https://github.com/foo/excluded-one"},
        ]
    }
    result = filter_excluded(ranked, excluded)
    assert len(result) == 2
    urls = [r["repository"] for r in result]
    assert "https://github.com/foo/excluded-one" not in urls
    assert "https://github.com/foo/plugin-a" in urls
    assert "https://github.com/foo/plugin-b" in urls


# --- test_takes_top_n ---
def test_takes_top_n():
    """Take only first N items."""
    ranked = [
        {"id": f"p{i}", "repository": f"https://github.com/foo/p{i}", "stars": 100 - i, "name": f"P{i}", "enabled": True, "description": ""}
        for i in range(10)
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_output(ranked, top_n=3, output_dir=tmpdir)
        with open(path) as f:
            data = json.load(f)
        assert len(data["custom_nodes"]) == 3
        assert data["metadata"]["top_n"] == 3
        assert data["metadata"]["total"] == 3


# --- test_output_filename_includes_date ---
def test_output_filename_includes_date():
    """Output filename includes execution date."""
    ranked = [{"id": "p1", "repository": "https://github.com/f/p1", "stars": 1, "name": "P1", "enabled": True, "description": ""}]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_output(ranked, top_n=1, output_dir=tmpdir)
        name = Path(path).name
        assert name.startswith("custom_nodes_topn_")
        assert name.endswith(".json")
        # Format YYYY-MM-DD
        date_part = name.replace("custom_nodes_topn_", "").replace(".json", "")
        parts = date_part.split("-")
        assert len(parts) == 3
        assert len(parts[0]) == 4  # year
        assert len(parts[1]) == 2  # month
        assert len(parts[2]) == 2  # day


# --- test_output_metadata ---
def test_output_metadata():
    """Output file contains full metadata fields."""
    ranked = [
        {"id": "p1", "name": "P1", "repository": "https://github.com/f/p1", "stars": 10, "enabled": True, "description": "D1"},
    ]
    with tempfile.TemporaryDirectory() as tmpdir:
        path = generate_output(ranked, top_n=1, output_dir=tmpdir, excluded_count=2)
        with open(path) as f:
            data = json.load(f)
        m = data["metadata"]
        assert "generated_at" in m
        assert m["top_n"] == 1
        assert m["total"] == 1
        assert "source_stats_url" in m
        assert "source_list_url" in m
        assert m["excluded_count"] == 2
        nodes = data["custom_nodes"]
        assert len(nodes) == 1
        n = nodes[0]
        assert n["id"] == "p1"
        assert n["name"] == "P1"
        assert n["repository"] == "https://github.com/f/p1"
        assert n["stars"] == 10
        assert n["enabled"] is True
        assert n["description"] == "D1"


# --- test_invalid_top_n_raises_error ---
def test_invalid_top_n_raises_error():
    """top_n <= 0 raises ValueError."""
    with pytest.raises(ValueError, match="top_n must be a positive integer, got 0"):
        get_topn_plugins(top_n=0)
    with pytest.raises(ValueError, match="top_n must be a positive integer, got -1"):
        get_topn_plugins(top_n=-1)


# --- test_stars_none_treated_as_zero ---
def test_stars_none_treated_as_zero():
    """When stars is None in stats, treat as 0 and sort without crash."""
    stats = {
        "https://github.com/foo/plugin-a": {"stars": 100},
        "https://github.com/foo/plugin-b": {"stars": None},
        "https://github.com/foo/plugin-c": {"stars": 50},
    }
    node_list = {
        "custom_nodes": [
            {"id": "plugin-a", "title": "A", "reference": "https://github.com/foo/plugin-a", "description": ""},
            {"id": "plugin-b", "title": "B", "reference": "https://github.com/foo/plugin-b", "description": ""},
            {"id": "plugin-c", "title": "C", "reference": "https://github.com/foo/plugin-c", "description": ""},
        ]
    }
    result = merge_and_rank(stats, node_list)
    # Sort: 100, 50, 0 (None treated as 0)
    assert [r["stars"] for r in result] == [100, 50, 0]
    assert result[0]["repository"] == "https://github.com/foo/plugin-a"
    assert result[2]["repository"] == "https://github.com/foo/plugin-b"
    assert result[2]["stars"] == 0


# --- test_missing_star_data ---
def test_missing_star_data():
    """When plugin has no data in stats, stars default to 0."""
    stats = {
        "https://github.com/foo/plugin-a": {"stars": 100},
        # plugin-b missing from stats
    }
    node_list = {
        "custom_nodes": [
            {"id": "plugin-a", "title": "A", "reference": "https://github.com/foo/plugin-a", "description": ""},
            {"id": "plugin-b", "title": "B", "reference": "https://github.com/foo/plugin-b", "description": ""},
        ]
    }
    result = merge_and_rank(stats, node_list)
    plugin_a = next(r for r in result if r["repository"] == "https://github.com/foo/plugin-a")
    plugin_b = next(r for r in result if r["repository"] == "https://github.com/foo/plugin-b")
    assert plugin_a["stars"] == 100
    assert plugin_b["stars"] == 0


# --- Integration test with mocked fetch ---
def test_get_topn_plugins_integration():
    """Full flow with mocked fetch_json - no real network."""
    stats = {
        "https://github.com/foo/p1": {"stars": 100},
        "https://github.com/foo/p2": {"stars": 50},
    }
    node_list = {
        "custom_nodes": [
            {"id": "p1", "title": "P1", "reference": "https://github.com/foo/p1", "description": "D1"},
            {"id": "p2", "title": "P2", "reference": "https://github.com/foo/p2", "description": "D2"},
        ]
    }
    excluded_content = {"custom_nodes": [], "metadata": {}}

    def mock_fetch(url):
        if "stats" in url or "github-stats" in url:
            return stats
        if "list" in url or "custom-node-list" in url:
            return node_list
        raise ValueError(f"Unexpected URL: {url}")

    with tempfile.TemporaryDirectory() as tmpdir:
        excluded_file = Path(tmpdir) / "excluded_custom_nodes.json"
        excluded_file.write_text(json.dumps(excluded_content))

        with patch("get_topn.fetch_json", side_effect=mock_fetch), \
             patch("get_topn.EXCLUDED_FILE", str(excluded_file)):
            path = get_topn_plugins(top_n=2, output_dir=tmpdir)
            with open(path) as f:
                data = json.load(f)
            assert len(data["custom_nodes"]) == 2
            assert data["metadata"]["top_n"] == 2


# --- _url_to_id helper ---
def test_url_to_id():
    """Convert repository URL to id (owner/repo repo part)."""
    assert _url_to_id("https://github.com/aigc-apps/EasyAnimate") == "easyanimate"
    assert _url_to_id("https://github.com/ltdrdata/ComfyUI-Manager") == "comfyui-manager"
