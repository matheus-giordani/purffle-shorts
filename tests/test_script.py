import json
from pathlib import Path

import pytest

from purffle_shorts.config import Settings
from purffle_shorts.llm import extract_json
from purffle_shorts.script import SCRIPT_SCHEMA, _clean_hook_text, build_prompt, load_script, normalize, offline_script


@pytest.mark.parametrize("text", [
    '{"a": 1}',
    '```json\n{"a": 1}\n```',
    'Sure! Here it is:\n{"a": 1}\nHope that helps.',
    '{"a": 1,}',
])
def test_extract_json_variants(text):
    assert extract_json(text) == {"a": 1}


def test_normalize_cleans_everything():
    data = {
        "topic": "Octopus", "title": '"Octopus Secrets" #shorts 🐙', "hook_text": "3 HEARTS?!",
        "scenes": [
            {"narration": "[Hook] Narrator: Octopuses have three hearts! 🐙 #facts", "search_query": "octopus",
             "image_prompt": "an octopus"},
            {"narration": "", "search_query": "x", "image_prompt": "x"},
            "Plain string scene works too.",
        ],
        "description": "Wow. #octopus", "hashtags": ["octopus", "#Ocean Life", "#shorts", "#octopus"],
        "tags": ["a" * 70] + [f"tag{i}" for i in range(200)], "category": "nonsense",
    }
    s = normalize(data, "octopus", "facts", "en")
    assert s.scenes[0].narration == "Octopuses have three hearts!"
    assert len(s.scenes) == 2
    assert s.title == "Octopus Secrets"
    assert s.hashtags[0] == "#shorts" and "#OceanLife" in s.hashtags
    assert len([h for h in s.hashtags if h.lower() == "#octopus"]) == 1
    assert sum(len(t) + 1 for t in s.tags) <= 500
    assert s.category == "education" and s.category_id == "27"
    assert "#" not in s.description


def test_normalize_merges_too_many_scenes():
    data = {"scenes": [{"narration": f"Sentence {i}.", "search_query": "q", "image_prompt": "p"} for i in range(20)]}
    s = normalize(data, "x", "facts", "en")
    assert len(s.scenes) == 12
    assert s.narration.count("Sentence") == 20


def test_offline_script_is_complete():
    s = offline_script("", Settings())
    assert s.title and len(s.scenes) >= 4 and s.hashtags[0] == "#shorts"


def test_prompt_mentions_language_and_length():
    system, user = build_prompt("space", "facts", Settings(language="es", target_seconds=30), ["Old title"])
    assert "Spanish" in user and "78 words" in user and "Old title" in user
    assert "JSON" in system
    assert set(SCRIPT_SCHEMA["required"]) >= {"title", "scenes", "hashtags"}


def test_hook_text_does_not_end_with_dangling_word():
    hook = "Um clique. Vários serviços. Como não perder o rastro?"
    assert _clean_hook_text(hook, "Título") == hook
    assert not _clean_hook_text("Um clique. Vários serviços. Como não perder o", "Título").lower().endswith(" o")


@pytest.mark.parametrize("x,y,expected", [(1.8, -0.2, (1.0, 0.0)),
                                         ("invalid", None, (0.5, 0.5)),
                                         (float("nan"), float("inf"), (0.5, 0.5))])
def test_product_focus_is_safe_for_rendering(x, y, expected):
    script = normalize({"scenes": [{"narration": "Look at the product.", "focus_x": x, "focus_y": y}]},
                       "product", "product", "en")
    assert (script.scenes[0].focus_x, script.scenes[0].focus_y) == expected


def test_load_script_cleans_like_an_ai_script(tmp_path):
    f = tmp_path / "mine.json"
    f.write_text(json.dumps({"title": "My Own Script #viral", "style": "not-a-style", "hashtags": ["cats"],
                             "scenes": [{"narration": "Cats sleep a lot.", "search_query": "sleeping cat"}]}))
    sc = load_script(f, Settings())
    assert sc.title == "My Own Script" and sc.style == "facts"
    assert sc.hashtags[:2] == ["#shorts", "#cats"] and sc.topic == "My Own Script #viral"
    assert sc.scenes[0].image_prompt == "sleeping cat"


def test_load_script_rejects_non_objects(tmp_path):
    f = tmp_path / "bad.json"
    f.write_text("[1, 2]")
    with pytest.raises(ValueError):
        load_script(f, Settings())


@pytest.mark.parametrize("path", sorted((Path(__file__).parent.parent / "examples").glob("*.json")))
def test_shipped_examples_load(path):
    sc = load_script(path, Settings())
    assert len(sc.scenes) >= 4 and sc.hook_text and all(s.image_prompt for s in sc.scenes)
