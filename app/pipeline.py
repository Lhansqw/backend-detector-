import json, os, shutil, tempfile, threading
from pathlib import Path

from . import ai, analyzer, db

AI_TOP_N = int(os.getenv("AI_TOP_N", "5"))
# Máximo de análisis simultáneos; el resto espera en estado "pending".
_slots = threading.Semaphore(int(os.getenv("MAX_CONCURRENT", "2")))


def run(aid: str, url: str):
    with _slots:
        tmp = tempfile.mkdtemp(prefix="debt-")
        try:
            db.update(aid, status="cloning")
            analyzer.clone(url, tmp)

            db.update(aid, status="analyzing")
            result = analyzer.build_result(analyzer.analyze_dir(tmp))

            if ai.enabled():
                db.update(aid, status="reviewing")
                for f in result["files"][:AI_TOP_N]:
                    code = (Path(tmp) / f["path"]).read_text(errors="ignore")
                    metrics = {k: f[k] for k in ("nloc", "max_ccn", "avg_ccn", "long_functions", "todos", "commits")}
                    f["ai"] = ai.review_file(f["path"], code, metrics)

            db.update(aid, status="done", result=json.dumps(result), score=result["repo_score"])
        except Exception as e:
            db.update(aid, status="error", error=str(e)[:300] or "Error inesperado")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
