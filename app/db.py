import json, os, sqlite3, time, uuid
from contextlib import closing

DB_PATH = os.getenv("DB_PATH", "debt.db")
FIELDS = {"status", "result", "error", "score"}


def _conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init():
    with closing(_conn()) as c, c:
        c.execute(
            "CREATE TABLE IF NOT EXISTS analyses(id TEXT PRIMARY KEY, repo_url TEXT, "
            "status TEXT, created_at REAL, score REAL, result TEXT, error TEXT)"
        )


def create(repo_url: str) -> str:
    aid = uuid.uuid4().hex[:12]
    with closing(_conn()) as c, c:
        c.execute(
            "INSERT INTO analyses(id, repo_url, status, created_at) VALUES (?,?,?,?)",
            (aid, repo_url, "pending", time.time()),
        )
    return aid


def update(aid: str, **fields):
    assert set(fields) <= FIELDS
    sets = ", ".join(f"{k}=?" for k in fields)
    with closing(_conn()) as c, c:
        c.execute(f"UPDATE analyses SET {sets} WHERE id=?", (*fields.values(), aid))


def get(aid: str):
    with closing(_conn()) as c:
        row = c.execute("SELECT * FROM analyses WHERE id=?", (aid,)).fetchone()
    if not row:
        return None
    d = dict(row)
    d["result"] = json.loads(d["result"]) if d["result"] else None
    return d


def list_all(limit: int = 20):
    with closing(_conn()) as c:
        rows = c.execute(
            "SELECT id, repo_url, status, created_at, score FROM analyses "
            "ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def fail_stale():
    """Marca como fallidos los análisis que quedaron a medias tras un reinicio."""
    with closing(_conn()) as c, c:
        c.execute(
            "UPDATE analyses SET status='error', error='Interrumpido por un reinicio del servidor' "
            "WHERE status NOT IN ('done', 'error')"
        )
