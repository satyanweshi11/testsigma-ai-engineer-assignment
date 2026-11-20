"""Unit tests for the Code layer symbol extraction (no clone / network)."""
from src.codemap.mapper import _EXPORT_FN, _TOP_FN, _IMPORT, _symbol_kind, _resolve_import

SAMPLE = """\
import { foo } from "./util";
import React from "react";
export const RectangleToolButton = () => <button/>;
export function helperThing() { return 1; }
const InternalWidget = () => null;
"""


def test_export_regex_finds_components_and_functions():
    names = {m.group(1) for m in _EXPORT_FN.finditer(SAMPLE)}
    assert "RectangleToolButton" in names
    assert "helperThing" in names


def test_top_level_regex_finds_internal():
    names = {m.group(1) for m in _TOP_FN.finditer(SAMPLE)}
    assert "InternalWidget" in names


def test_import_regex_only_relative():
    specs = [m.group(1) for m in _IMPORT.finditer(SAMPLE)]
    assert specs == ["./util"]          # "react" is external, excluded


def test_symbol_kind():
    assert _symbol_kind("components/Tools.tsx", "RectangleToolButton") == "component"
    assert _symbol_kind("components/Tools.tsx", "helperThing") == "function"
    assert _symbol_kind("packages/x/actions/actionExport.ts", "actionExport") == "action"


def test_resolve_import(tmp_path):
    (tmp_path / "util.ts").write_text("export const x = 1;")
    src = tmp_path / "Comp.tsx"
    src.write_text("import {x} from './util';")
    assert _resolve_import(src, "./util", tmp_path) == "util.ts"
    assert _resolve_import(src, "./missing", tmp_path) is None
