"""景點階層：把計畫裡的地點名稱解析成節點，展開成要查的景點名稱。

階層檔是 TOML（格式寫在 `data/place_hierarchy.toml` 檔頭）。人工成果以階層檔為準，不存進 DB。

`python -m strag_v3.rag.hierarchy [--db DB]` 印出階層樹，並列出 DB `place` 表裡階層檔還沒收的名稱。
"""
import argparse
import sqlite3
import sys
import tomllib
import unicodedata
from dataclasses import dataclass, replace
from pathlib import Path

from ..extract.paths import DATA, DB_PATH
from .embedding import Embedder, cosine

HIERARCHY_PATH = DATA / "place_hierarchy.toml"
KINDS = ("景點", "區域")
_FIELDS = {"name", "kind", "parent", "aliases"}


class HierarchyError(ValueError):
    """階層檔寫錯：欄位、重複名稱、找不到母節點、循環。"""


@dataclass(frozen=True)
class Node:
    name: str
    aliases: tuple[str, ...] = ()
    parent: str | None = None
    kind: str = "景點"


def _normalize_name(name: str) -> str:
    """比對用的正規化：全半形統一、去掉空白、不分大小寫。"""
    return "".join(unicodedata.normalize("NFKC", name).split()).casefold()


class Hierarchy:
    def __init__(self, nodes=()):
        self.nodes: dict[str, Node] = {}
        self._by_key: dict[str, str] = {}
        self._children: dict[str, list[str]] = {}
        for n in nodes:
            if n.kind not in KINDS:
                raise HierarchyError(f"{n.name}：kind 只能是 {'、'.join(KINDS)}，不是 {n.kind}")
            for name in (n.name, *n.aliases):
                owner = self._by_key.setdefault(_normalize_name(name), n.name)
                if owner != n.name:
                    raise HierarchyError(f"名稱「{name}」同時屬於 {owner} 和 {n.name}")
            self.nodes[n.name] = n
            if n.parent:
                self._children.setdefault(n.parent, []).append(n.name)
        for n in self.nodes.values():
            seen = {n.name}
            p = n.parent
            while p:
                if p not in self.nodes:
                    raise HierarchyError(f"{n.name} 的母節點「{p}」不在階層裡（parent 要寫正式名稱）")
                if p in seen:
                    raise HierarchyError(f"母子關係繞成循環：{n.name}")
                seen.add(p)
                p = self.nodes[p].parent

    @classmethod
    def load(cls, path: Path = HIERARCHY_PATH) -> "Hierarchy":
        with open(path, "rb") as f:
            data = tomllib.load(f)
        nodes = []
        for i, d in enumerate(data.get("node", []), 1):
            if "name" not in d:
                raise HierarchyError(f"{path}：第 {i} 個節點沒有 name")
            if extra := d.keys() - _FIELDS:
                raise HierarchyError(f"{path}：{d['name']} 有不認得的欄位 {sorted(extra)}")
            nodes.append(Node(name=d["name"], aliases=tuple(d.get("aliases", ())), parent=d.get("parent"),
                              kind=d.get("kind", "景點")))
        return cls(nodes)

    def with_places(self, names) -> "Hierarchy":
        """對應 DB `place` 表的景點名稱。

        正規化後對得上某個節點、但字面不同的名稱，併成那個節點的別名（片段是用字面比對的）；
        對不上的名稱各自成為沒有母節點的節點。
        """
        nodes = dict(self.nodes)
        owners = dict(self._by_key)
        for name in dict.fromkeys(names):
            owner = owners.setdefault(_normalize_name(name), name)
            if owner == name and name not in nodes:
                nodes[name] = Node(name)
            elif name not in (owner, *nodes[owner].aliases):
                nodes[owner] = replace(nodes[owner], aliases=(*nodes[owner].aliases, name))
        return Hierarchy(nodes.values())

    def lookup(self, name: str) -> Node | None:
        """名稱或別名完全相同（正規化後）的節點。"""
        found = self._by_key.get(_normalize_name(name))
        return self.nodes[found] if found else None

    def nearest(self, name: str, embedder: Embedder, min_sim: float) -> Node | None:
        """名稱 embedding 最接近的節點；節點的正式名稱和每個別名都拿來比，取最像的那個。

        最像的 cosine 低於 min_sim 時回傳 None。
        """
        pairs = [(alias, n.name) for n in self.nodes.values() for alias in (n.name, *n.aliases)]
        if not pairs:
            return None
        qvec, *vecs = embedder.embed([name] + [alias for alias, _ in pairs])
        sim, best = max((cosine(qvec, v), node) for v, (_, node) in zip(vecs, pairs))
        return self.nodes[best] if sim >= min_sim else None

    def canonical(self, name: str) -> str:
        """名稱或別名所屬節點的正式名稱；不在階層裡就原樣傳回。"""
        node = self.lookup(name)
        return node.name if node else name

    def scopes(self, name: str, embedder: Embedder, min_sim: float) -> list[frozenset[str]]:
        """名稱解析成節點後，依序要查的片段景點名稱：先是節點和子孫；退讓時改查母節點和子孫（有母節點才有）。

        先比別名，比不到再用名稱 embedding 找最近的節點；都不夠像時只有一個空集合，什麼都查不到。
        """
        node = self.lookup(name) or self.nearest(name, embedder, min_sim)
        if node is None:
            return [frozenset()]
        parent = self.nodes[node.parent] if node.parent else None
        return [self._names_under(n) for n in (node, parent) if n]

    def children(self, node: Node) -> list[Node]:
        return [self.nodes[c] for c in self._children.get(node.name, ())]

    def _names_under(self, node: Node) -> frozenset[str]:
        """節點和所有子孫節點的名稱（含別名），用來比對片段的景點名稱。"""
        out: set[str] = set()
        stack = [node]
        while stack:
            n = stack.pop()
            out.update((n.name, *n.aliases))
            stack.extend(self.children(n))
        return frozenset(out)


def _tree(h: Hierarchy, n: Node, depth: int = 0):
    kind = f"（{n.kind}）" if n.kind != "景點" else ""
    aliases = f"　別名：{''.join(f'「{a}」' for a in n.aliases)}" if n.aliases else ""
    yield f"{'  ' * depth}- {n.name}{kind}{aliases}"
    for child in h.children(n):
        yield from _tree(h, child, depth + 1)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m strag_v3.rag.hierarchy",
                                 description="印出景點階層，並列出 DB place 表裡階層檔還沒收的名稱")
    ap.add_argument("--db", type=Path, default=DB_PATH, help=f"要對照的 DB（預設 {DB_PATH}）")
    ap.add_argument("--file", type=Path, default=HIERARCHY_PATH, help=f"階層檔（預設 {HIERARCHY_PATH}）")
    a = ap.parse_args(argv)
    try:
        h = Hierarchy.load(a.file)
    except HierarchyError as e:
        print(f"階層檔有錯：{e}", file=sys.stderr)
        return 1
    for root in [n for n in h.nodes.values() if not n.parent]:
        print("\n".join(_tree(h, root)))

    conn = sqlite3.connect(a.db)
    try:
        names = [name for (name,) in conn.execute("SELECT name FROM place ORDER BY id")]
    finally:
        conn.close()
    missing = [n for n in names if h.lookup(n) is None]
    print(f"\nDB place 表有 {len(names)} 個名稱，階層檔沒收的有 {len(missing)} 個")
    for n in missing:
        print(f"- {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
