"""Markdown + YAML frontmatter storage layer."""
import uuid
import frontmatter
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load(path: Path) -> dict:
    post = frontmatter.load(str(path))
    data = dict(post.metadata)
    data["_body"] = post.content
    return data


def _save(path: Path, metadata: dict, body: str = "") -> None:
    post = frontmatter.Post(body, **metadata)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        frontmatter.dump(post, f)


class MarkdownStore:
    def __init__(self, directory: str):
        self.dir = Path(directory)
        self.dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        items = []
        for p in sorted(self.dir.glob("*.md")):
            try:
                items.append(_load(p))
            except Exception:
                pass
        return items

    def get(self, item_id: str) -> Optional[dict]:
        path = self.dir / f"{item_id}.md"
        if not path.exists():
            return None
        return _load(path)

    def create(self, data: dict, body: str = "") -> dict:
        item_id = str(uuid.uuid4())
        now = _now()
        metadata = {**data, "id": item_id, "created_at": now, "updated_at": now}
        _save(self.dir / f"{item_id}.md", metadata, body)
        return {**metadata, "_body": body}

    def update(self, item_id: str, data: dict, body: Optional[str] = None) -> Optional[dict]:
        path = self.dir / f"{item_id}.md"
        if not path.exists():
            return None
        existing = _load(path)
        existing_body = existing.pop("_body", "")
        existing.update({k: v for k, v in data.items() if v is not None})
        existing["updated_at"] = _now()
        new_body = body if body is not None else existing_body
        _save(path, existing, new_body)
        return {**existing, "_body": new_body}

    def delete(self, item_id: str) -> bool:
        path = self.dir / f"{item_id}.md"
        if not path.exists():
            return False
        path.unlink()
        return True


interests_store = MarkdownStore("data/interests")
resources_store = MarkdownStore("data/resources")
summary_reports_store = MarkdownStore("data/summary_reports")
