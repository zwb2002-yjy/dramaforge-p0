"""Retired executable references fail; harmless descriptions and formatting do not."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location(
    "surface", ROOT / "scripts/check_canonical_surface.py",
)
assert spec and spec.loader
surface = importlib.util.module_from_spec(spec)
spec.loader.exec_module(surface)


@pytest.mark.parametrize("source,suffix,token", [
    ('from app.creation.service import start', '.py', 'app.creation'),
    ('from app import creation', '.py', 'app.creation'),
    ('class CharacterReference: pass', '.py', 'CharacterReference'),
    ('\ufeffclass CharacterReference: pass', '.py', 'CharacterReference'),
    ('data = {"manual_media": True}', '.py', 'manual_media'),
    ('router.post("/creation/start-project")', '.py', '/creation/start-project'),
    ('const path = "/creation/start-project";', '.ts', '/creation/start-project'),
    ('import { CharacterReference } from "./old";', '.tsx', 'CharacterReference'),
    ('Graph: object=ProductionGraph', '.py', 'Graph = ProductionGraph'),
    (
        r'const url = /https?:\/\//; const route = "/creation/start-project";',
        ".ts",
        "/creation/start-project",
    ),
    ('const value = `${(() => { return import("manual_media"); })()}`;', '.ts', 'manual_media'),
    (r'const route = "/creation/\u{73}tart-project";', '.ts', '/creation/start-project'),
    ('const ui = <p>{CharacterReference.name}</p>;', '.tsx', 'CharacterReference'),
    ('const ui = <CharacterReference />;', '.tsx', 'CharacterReference'),
    ('const ui = <p data-kind="manual_media">description</p>;', '.tsx', 'manual_media'),
    ('const value = `${`inner ${CharacterReference.name}`}`;', '.ts', 'CharacterReference'),
    (
        r'if (ready) /https?:\/\//; const route = "/creation/start-project";',
        ".ts",
        "/creation/start-project",
    ),
    (
        'const ui = <Foo<T> href="/creation/start-project"></Foo>;',
        ".tsx",
        "/creation/start-project",
    ),
])
def test_rejects_retired_code_and_contract_references(source, suffix, token):
    assert surface.contains_reference(surface.code_references(source, suffix), token)


@pytest.mark.parametrize("source,suffix", [
    ('# CharacterReference retired\n"""Do not restore manual_media."""', '.py'),
    ('message = "Use exactly 10 seconds; CharacterReference is retired"', '.py'),
    ('// CharacterReference retired\n/* manual_media removed */', '.tsx'),
    ('const message = "CharacterReference was removed; exactly 10 frames";', '.ts'),
    ('{"description": "CharacterReference retired; exactly 10 frames"}', '.json'),
    ('const ui = <p>CharacterReference is a retired design term.</p>;', '.tsx'),
    ('const ui = <><p>manual_media was removed</p><span>CharacterReference</span></>;', '.tsx'),
    (r'const pattern = /CharacterReference\/[a-z/]+/;', '.ts'),
    ('if (ready) /CharacterReference/.test(value);', '.ts'),
])
def test_prose_does_not_restore_a_retired_surface(source, suffix):
    references = surface.code_references(source, suffix)
    assert not any(
        surface.contains_reference(references, token) for token in surface.FORBIDDEN_TEXT
    )
