"""A small stateful fake of the Notion REST API (2022-06-28) for end-to-end tests.

It implements only what Vanguard uses and checks request shapes the way Notion
does, so a contract break shows up as a failing test rather than a failed sync.
"""
from __future__ import annotations

import itertools
import json

import httpx

TITLE_TYPES = {"title", "rich_text", "select", "number"}


class FakeNotion:
    def __init__(self, fail_first_n_with_429: int = 0):
        self.databases: dict[str, dict] = {}
        self.pages: dict[str, dict] = {}
        self.children: dict[str, list] = {}
        self.requests: list[tuple[str, str]] = []
        self._ids = itertools.count(1)
        self._429 = fail_first_n_with_429

    # -- helpers -----------------------------------------------------------
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _err(self, code: int, msg: str) -> httpx.Response:
        return httpx.Response(code, json={"object": "error", "status": code, "message": msg})

    @staticmethod
    def _plain(prop: dict) -> str | float | None:
        if "title" in prop:
            return "".join(t["text"]["content"] for t in prop["title"])
        if "rich_text" in prop:
            return "".join(t["text"]["content"] for t in prop["rich_text"])
        if "select" in prop:
            return prop["select"]["name"] if prop["select"] else None
        if "number" in prop:
            return prop["number"]
        return None

    def rows(self, db_id: str) -> list[dict]:
        return [{k: self._plain(v) for k, v in p["properties"].items()} | {"_id": pid}
                for pid, p in self.pages.items() if p["parent"]["database_id"] == db_id]

    def _check_props(self, db_id: str, props: dict) -> str | None:
        schema = self.databases[db_id]["properties"]
        for name, val in props.items():
            if name not in schema:
                return f"{name} is not a property that exists."
            kind = next(iter(schema[name]))
            if kind not in val:
                return f"{name} is expected to be {kind}."
            if kind in ("title", "rich_text"):
                for t in val[kind]:
                    if len(t["text"]["content"]) > 2000:
                        return f"{name}: text content length should be <= 2000"
            if kind == "select" and val["select"] and "," in val["select"]["name"]:
                return f"{name}: select option names cannot contain commas"
        return None

    # -- router ------------------------------------------------------------
    def handle(self, req: httpx.Request) -> httpx.Response:
        path, method = req.url.path.removeprefix("/v1"), req.method
        self.requests.append((method, path))
        if not req.headers.get("Authorization", "").startswith("Bearer "):
            return self._err(401, "API token is invalid.")
        if req.headers.get("Notion-Version") != "2022-06-28":
            return self._err(400, "Notion-Version header missing or unsupported")
        if self._429 > 0:
            self._429 -= 1
            return httpx.Response(429, headers={"Retry-After": "0"}, json={"message": "rate limited"})
        body = json.loads(req.content or b"{}")

        if method == "POST" and path == "/databases":
            if "title" not in [next(iter(v)) for v in body["properties"].values()]:
                return self._err(400, "database needs exactly one title property")
            db_id = f"db{next(self._ids)}"
            self.databases[db_id] = body
            return httpx.Response(200, json={"id": db_id, "object": "database"})

        if method == "POST" and path.endswith("/query"):
            db_id = path.split("/")[2]
            if db_id not in self.databases:
                return self._err(404, "Could not find database")
            conds = body.get("filter", {}).get("and", [])
            out = []
            for row in self.rows(db_id):
                if all(row.get(c["property"]) == next(iter(c[k] for k in c if k != "property"))["equals"]
                       for c in conds):
                    out.append({"id": row["_id"]})
            return httpx.Response(200, json={"results": out[: body.get("page_size", 100)], "has_more": False})

        if method == "POST" and path == "/pages":
            db_id = body["parent"]["database_id"]
            if db_id not in self.databases:
                return self._err(404, "Could not find database")
            if len(body.get("children", [])) > 100:
                return self._err(400, "body.children.length should be <= 100")
            if (msg := self._check_props(db_id, body["properties"])):
                return self._err(400, msg)
            pid = f"pg{next(self._ids)}"
            self.pages[pid] = {"parent": body["parent"], "properties": body["properties"]}
            self.children[pid] = list(body.get("children", []))
            return httpx.Response(200, json={"id": pid, "object": "page"})

        if method == "PATCH" and path.startswith("/pages/"):
            pid = path.split("/")[2]
            if pid not in self.pages:
                return self._err(404, "Could not find page")
            db_id = self.pages[pid]["parent"]["database_id"]
            if (msg := self._check_props(db_id, body["properties"])):
                return self._err(400, msg)
            self.pages[pid]["properties"].update(body["properties"])
            return httpx.Response(200, json={"id": pid, "object": "page"})

        if method == "PATCH" and path.startswith("/blocks/"):
            pid = path.split("/")[2]
            if len(body["children"]) > 100:
                return self._err(400, "body.children.length should be <= 100")
            self.children.setdefault(pid, []).extend(body["children"])
            return httpx.Response(200, json={"object": "list"})

        return self._err(404, f"unhandled {method} {path}")
