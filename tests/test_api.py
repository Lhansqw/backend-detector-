import shutil, tempfile, unittest
from pathlib import Path
from unittest import mock

try:
    from fastapi.testclient import TestClient
    from app.main import app
    HAS_API = True
except ImportError:
    HAS_API = False

from app import db, pipeline


@unittest.skipUnless(HAS_API, "fastapi/httpx no instalados")
class Api(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp()); self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        for p in (mock.patch.object(db, "DB_PATH", str(tmp / "t.db")),
                  mock.patch.object(pipeline, "run")):   # no clona nada en estos tests
            p.start(); self.addCleanup(p.stop)
        self.client = TestClient(app)
        self.client.__enter__(); self.addCleanup(self.client.__exit__, None, None, None)

    def test_create_then_get(self):
        r = self.client.post("/api/analyses", json={"repo_url": "https://github.com/a/b"})
        self.assertEqual(r.status_code, 202)
        got = self.client.get(f"/api/analyses/{r.json()['id']}")
        self.assertEqual((got.status_code, got.json()["status"]), (200, "pending"))
        self.assertEqual(got.json()["repo_url"], "https://github.com/a/b.git")

    def test_invalid_url_is_422(self):
        r = self.client.post("/api/analyses", json={"repo_url": "https://example.com/a/b"})
        self.assertEqual(r.status_code, 422)

    def test_unknown_id_is_404(self):
        self.assertEqual(self.client.get("/api/analyses/nope").status_code, 404)

    def test_history_lists_created(self):
        self.client.post("/api/analyses", json={"repo_url": "https://github.com/a/b"})
        self.assertEqual(len(self.client.get("/api/analyses").json()), 1)
