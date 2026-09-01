# Chronify — a macOS menu bar work tracker.
# Copyright (C) 2026 Zepuff
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "chronify"
APP_SOURCES = ("main.py", "main_setup.py")
INHERITED = {
    "menu", "title", "icon", "template", "name", "quit_button",
    "clicked", "run", "_menu",
}


def _tree(name):
    return ast.parse((PACKAGE / name).read_text(encoding="utf-8"))


def _defined_names(tree):
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            if isinstance(node.value, ast.Name) and node.value.id == "self":
                names.add(node.attr)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    names.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _referenced_names(tree):
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Load)
    }


def test_no_dangling_self_references():
    trees = [_tree(name) for name in APP_SOURCES]

    defined = set(INHERITED)
    for tree in trees:
        defined |= _defined_names(tree)

    referenced = set()
    for tree in trees:
        referenced |= _referenced_names(tree)

    missing = sorted(referenced - defined)
    assert not missing, (
        "these are used as self.<name> but defined nowhere in "
        f"{' or '.join(APP_SOURCES)}: {missing}"
    )


def test_mixin_is_first_in_mro():
    tree = _tree("main.py")
    app = next(
        node for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef) and node.name == "WorkTrackerApp"
    )
    bases = [b.id if isinstance(b, ast.Name) else b.attr for b in app.bases]
    assert bases[0] == "SetupMixin", (
        f"SetupMixin must come first or its methods are shadowed; bases are {bases}"
    )


def test_mixin_methods_are_not_shadowed():
    def methods(name, cls_name):
        cls = next(
            node for node in ast.walk(_tree(name))
            if isinstance(node, ast.ClassDef) and node.name == cls_name
        )
        return {m.name for m in cls.body if isinstance(m, ast.FunctionDef)}

    clash = methods("main.py", "WorkTrackerApp") & methods("main_setup.py", "SetupMixin")
    assert not clash, f"WorkTrackerApp redefines mixin methods, silently disabling them: {sorted(clash)}"


def test_objc_subclass_methods_have_selector_safe_signatures():
    """PyObjC turns every method of an ObjC subclass into a selector.

    A name ending in '_' maps each underscore to a colon and must take that
    many arguments; any other name becomes a zero-argument selector, so it
    must take none. Getting this wrong raises BadPrototypeError at import
    time and takes the whole app down with it.
    """
    objc_bases = {"NSObject", "NSView", "NSPanel", "NSWindow", "NSTextField"}
    offenders = []

    for source in ("forms.py", "ui_windows.py"):
        tree = _tree(source)
        for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
            bases = {b.id if isinstance(b, ast.Name) else getattr(b, "attr", "")
                     for b in cls.bases}
            if not bases & objc_bases:
                continue

            for method in [m for m in cls.body if isinstance(m, ast.FunctionDef)]:
                decorators = {
                    d.id if isinstance(d, ast.Name) else getattr(d, "attr", "")
                    for d in method.decorator_list
                }
                if decorators & {"staticmethod", "classmethod", "property"}:
                    continue

                name = method.name
                taken = len(method.args.args) - 1
                expected = name.lstrip("_").count("_") if name.endswith("_") else 0
                if taken != expected:
                    offenders.append(
                        f"{source}:{cls.name}.{name} takes {taken} arg(s) but its "
                        f"selector allows {expected}"
                    )

    assert not offenders, "\n".join(offenders)


def test_helpers_used_by_forms_are_public():
    exported = _defined_names(_tree("ui_windows.py"))
    for helper in ("make_button", "make_panel", "top_right_origin"):
        assert helper in exported, (
            f"forms.py imports {helper} from ui_windows; renaming it back to "
            f"_{helper} breaks the whole app at import time"
        )


def test_every_section_field_has_a_path_and_label():
    import re

    source = (PACKAGE / "main_setup.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    sections = next(
        node.value for node in module.body
        if isinstance(node, ast.Assign)
        and getattr(node.targets[0], "id", "") == "SETTINGS_SECTIONS"
    )
    data = ast.literal_eval(sections)

    keys = [s["key"] for s in data]
    assert len(keys) == len(set(keys))

    for section in data:
        assert section["fields"], section["key"]
        for field in section["fields"]:
            assert field["path"] and field["label"]
            assert field.get("kind", "text") in ("text", "secret", "int", "float")
        for path in section["required"]:
            assert list(path) in [f["path"] for f in section["fields"]], (
                f"{section['key']}: required path {path} is not one of its fields"
            )
        assert re.search(r"\S", section["title"])


def _bound_names(tree):
    """Everything a module makes available to its own code."""
    bound = set(dir(__builtins__)) | set(vars(__import__("builtins")))
    bound |= {"__file__", "__name__", "__doc__", "self", "cls"}

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                bound.add((alias.asname or alias.name).split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            bound.update(node.names)

    return bound


def test_no_module_uses_a_name_it_never_defines():
    """A missing import only shows up when the menu item is clicked."""
    offenders = []

    for source in sorted(PACKAGE.glob("*.py")):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        bound = _bound_names(tree)
        used = {
            node.id for node in ast.walk(tree)
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
        }
        for name in sorted(used - bound):
            offenders.append(f"{source.name}: {name}")

    assert not offenders, (
        "used but never imported or defined — this raises NameError only when "
        f"that code path runs: {offenders}"
    )
