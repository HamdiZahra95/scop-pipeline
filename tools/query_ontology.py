"""
s13_manual_query.py — Stage 13: manual query & visual inspection of the ontology.

NOT part of the S01–S12 trunk (it produces no versioned artifact and is not
registered in run.py). It is a hands-on inspection tool that loads the latest
exported OWL (artifacts/s11_export_owl/*.owl) and lets you:

  * print the full subtree of any concept, with a count of each DIRECT child's
    own children, e.g.  `Machine_Learning (10 children)`; and
  * dump the WHOLE taxonomy as an indented tree (concept names only) to a file
    for visual inspection (Markdown by default; JSON or plain text on request).

The subClassOf hierarchy is read straight from the OWL graph via rdflib, so what
you inspect is exactly what S11 serialized and S12 validated.

USAGE (run from pipeline_v2/):
    # print the subtree of a concept (name, label, or slug — case-insensitive)
    python stages/s13_manual_query.py --children "Machine Learning"
    python stages/s13_manual_query.py --children ml_model --max-depth 3

    # list the direct children only (one level)
    python stages/s13_manual_query.py --children "Computer Science" --direct

    # dump the whole ontology tree to reports/ontology_tree.md (Markdown)
    python stages/s13_manual_query.py --tree
    python stages/s13_manual_query.py --tree --format json   # or: txt

    # search for a concept when you don't know its exact name
    python stages/s13_manual_query.py --find embedding

    # point at a specific OWL file instead of the latest
    python stages/s13_manual_query.py --tree --owl /path/to/ontology.owl
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import common as C

from rdflib import Graph, RDFS, URIRef
from rdflib.namespace import OWL


# ── Loading the OWL into a light graph model ─────────────────────────────────
class OntologyView:
    """parent→children / child→parent maps + labels, built from an OWL file."""

    def __init__(self, owl_path: Path):
        self.owl_path = Path(owl_path)
        self.g = Graph()
        self.g.parse(str(self.owl_path), format="xml")

        self.children: dict[str, list] = {}
        self.parents: dict[str, list] = {}
        self.labels: dict[str, str] = {}

        # subClassOf edges (skip blank nodes / restrictions — named classes only).
        for child, _, parent in self.g.triples((None, RDFS.subClassOf, None)):
            if not isinstance(child, URIRef) or not isinstance(parent, URIRef):
                continue
            c, p = str(child), str(parent)
            self.children.setdefault(p, []).append(c)
            self.parents.setdefault(c, []).append(p)

        # labels for pretty printing.
        for s, _, o in self.g.triples((None, RDFS.label, None)):
            if isinstance(s, URIRef):
                self.labels[str(s)] = str(o)

        # every named owl:Class URI (so roots with no edges still appear).
        self.classes = set()
        for s, _, o in self.g.triples((None, None, OWL.Class)):
            if isinstance(s, URIRef):
                self.classes.add(str(s))
        self.classes |= set(self.children) | set(self.parents)

    # -- naming helpers -----------------------------------------------------
    def label_of(self, uri: str) -> str:
        return self.labels.get(uri) or uri.split("#")[-1].replace("_", " ").title()

    def local(self, uri: str) -> str:
        return uri.split("#")[-1]

    def resolve(self, query: str) -> str | None:
        """Resolve a user string (label, slug, or full URI) to a class URI."""
        if query.startswith("http"):
            return query if query in self.classes else None
        target_slug = C.get_uri_name(query)
        # exact slug match on the local name.
        for uri in self.classes:
            if C.get_uri_name(self.local(uri)) == target_slug:
                return uri
        # fall back to label match.
        for uri in self.classes:
            if C.get_uri_name(self.label_of(uri)) == target_slug:
                return uri
        return None

    def find(self, needle: str) -> list:
        """Substring search over labels/slugs; returns matching URIs."""
        n = needle.lower()
        hits = [u for u in self.classes
                if n in self.local(u).lower() or n in self.label_of(u).lower()]
        return sorted(hits, key=self.label_of)

    def direct_children(self, uri: str) -> list:
        return sorted(self.children.get(uri, []), key=self.label_of)

    def roots(self) -> list:
        """Named classes with no named parent (the top of the forest)."""
        return sorted((u for u in self.classes if not self.parents.get(u)),
                      key=self.label_of)

    def count_descendants(self, uri: str) -> int:
        """Total number of descendants under `uri` (cycle-safe)."""
        seen = set()
        stack = list(self.children.get(uri, []))
        while stack:
            n = stack.pop()
            if n in seen:
                continue
            seen.add(n)
            stack.extend(self.children.get(n, []))
        return len(seen)


# ── Query: children of a concept (printed to console) ────────────────────────
def print_children(view: OntologyView, query: str, *, direct: bool,
                   max_depth: int) -> None:
    uri = view.resolve(query)
    if uri is None:
        print(f"❌ Concept not found: {query!r}")
        matches = view.find(query)
        if matches:
            print("   Did you mean:")
            for m in matches[:10]:
                print(f"     - {view.label_of(m)}")
        return

    total = view.count_descendants(uri)
    direct_kids = view.direct_children(uri)
    print(f"\n📂 {view.label_of(uri)}")
    print(f"   ({len(direct_kids)} direct child(ren), {total} total descendant(s))\n")

    if not direct_kids:
        print("   (leaf — no children)")
        return

    if direct:
        # One level only, each with its own direct-child count.
        for kid in direct_kids:
            n = len(view.direct_children(kid))
            note = f"  [{n} child{'ren' if n != 1 else ''}]" if n else "  [leaf]"
            print(f"   • {view.label_of(kid)}{note}")
        return

    # Full subtree, indented; every node annotated with its direct-child count.
    def walk(node: str, depth: int, prefix: str):
        kids = view.direct_children(node)
        for i, kid in enumerate(kids):
            last = (i == len(kids) - 1)
            branch = "└── " if last else "├── "
            n = len(view.direct_children(kid))
            note = f"  [{n} child{'ren' if n != 1 else ''}]" if n else ""
            print(f"{prefix}{branch}{view.label_of(kid)}{note}")
            if n and depth + 1 < max_depth:
                walk(kid, depth + 1, prefix + ("    " if last else "│   "))
            elif n and depth + 1 >= max_depth:
                print(f"{prefix}{'    ' if last else '│   '}… ({n} more, "
                      f"depth limit {max_depth})")

    walk(uri, 0, "   ")


# ── Whole-ontology tree dump (Markdown / JSON / text) ────────────────────────
def build_tree_markdown(view: OntologyView) -> str:
    lines = ["# Ontology Tree", "",
             f"Source: `{view.owl_path.name}`  ",
             f"Total named classes: **{len(view.classes)}**", ""]

    def walk(node: str, depth: int, seen: set):
        indent = "  " * depth
        kids = view.direct_children(node)
        suffix = f"  _({len(kids)})_" if kids else ""
        lines.append(f"{indent}- {view.label_of(node)}{suffix}")
        if node in seen:
            return
        seen.add(node)
        for kid in kids:
            walk(kid, depth + 1, seen)

    seen: set = set()
    for root in view.roots():
        walk(root, 0, seen)
    return "\n".join(lines) + "\n"


def build_tree_text(view: OntologyView) -> str:
    lines = []

    def walk(node: str, prefix: str, last: bool, seen: set):
        branch = "" if not prefix and node in view.roots() else \
                 ("└── " if last else "├── ")
        lines.append(f"{prefix}{branch}{view.label_of(node)}")
        if node in seen:
            return
        seen.add(node)
        kids = view.direct_children(node)
        child_prefix = prefix + ("" if not branch else ("    " if last else "│   "))
        for i, kid in enumerate(kids):
            walk(kid, child_prefix, i == len(kids) - 1, seen)

    seen: set = set()
    for root in view.roots():
        lines.append(view.label_of(root))
        kids = view.direct_children(root)
        for i, kid in enumerate(kids):
            walk(kid, "", i == len(kids) - 1, seen)
    return "\n".join(lines) + "\n"


def build_tree_json(view: OntologyView) -> str:
    def node(uri: str, seen: set) -> dict:
        entry = {"name": view.label_of(uri),
                 "slug": C.get_uri_name(view.local(uri)),
                 "child_count": len(view.direct_children(uri))}
        if uri not in seen:
            seen.add(uri)
            kids = [node(k, seen) for k in view.direct_children(uri)]
            if kids:
                entry["children"] = kids
        return entry

    seen: set = set()
    forest = [node(r, seen) for r in view.roots()]
    return json.dumps({"source": view.owl_path.name,
                       "class_count": len(view.classes),
                       "roots": forest}, ensure_ascii=False, indent=2)


def dump_tree(view: OntologyView, fmt: str) -> Path:
    ext = {"md": "md", "json": "json", "txt": "txt"}[fmt]
    builder = {"md": build_tree_markdown, "json": build_tree_json,
               "txt": build_tree_text}[fmt]
    out = C.REPORTS / f"ontology_tree.{ext}"
    out.write_text(builder(view), encoding="utf-8")
    return out


# ── CLI ──────────────────────────────────────────────────────────────────────
def _latest_owl() -> Path:
    return C.require_latest("s11_export_owl", ext="owl")


def main() -> None:
    ap = argparse.ArgumentParser(description="Manual ontology query & inspection.")
    ap.add_argument("--owl", help="OWL file to load (default: latest s11 export).")
    ap.add_argument("--children", metavar="CONCEPT",
                    help="Print the subtree of a concept (name/label/slug).")
    ap.add_argument("--direct", action="store_true",
                    help="With --children: list only the direct children.")
    ap.add_argument("--max-depth", type=int, default=6,
                    help="With --children: max subtree depth to print (default 6).")
    ap.add_argument("--tree", action="store_true",
                    help="Dump the whole ontology tree to reports/ontology_tree.*")
    ap.add_argument("--format", choices=["md", "json", "txt"], default="md",
                    help="With --tree: output format (default md).")
    ap.add_argument("--find", metavar="TEXT",
                    help="Search concepts by substring and print matches.")
    args = ap.parse_args()

    if not (args.children or args.tree or args.find):
        ap.error("nothing to do — use --children, --tree, or --find.")

    owl_path = Path(args.owl) if args.owl else _latest_owl()
    print(f"📂 Loading {owl_path} ...")
    view = OntologyView(owl_path)
    print(f"   {len(view.classes)} classes, {len(view.roots())} root(s).")

    if args.find:
        hits = view.find(args.find)
        print(f"\n🔎 {len(hits)} match(es) for {args.find!r}:")
        for h in hits:
            n = len(view.direct_children(h))
            print(f"   • {view.label_of(h)}  [{n} child(ren)]")

    if args.children:
        print_children(view, args.children, direct=args.direct,
                       max_depth=args.max_depth)

    if args.tree:
        out = dump_tree(view, args.format)
        print(f"\n🌳 Wrote whole-ontology tree -> {out}")


if __name__ == "__main__":
    main()
