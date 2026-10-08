"""Análisis estático: complejidad, tamaño, TODOs y hotspots de Git."""
import os, re, subprocess
from collections import Counter
from pathlib import Path

import lizard

GITHUB_RE = re.compile(r"^https://github\.com/([\w.-]+)/([\w.-]+?)(?:\.git)?/?$")
SKIP_DIRS = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__",
             "vendor", "target", ".next", "migrations"}
EXTS = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rb", ".php",
        ".cs", ".c", ".cpp", ".h", ".rs", ".kt", ".swift"}
MARKERS = re.compile(r"\b(TODO|FIXME|HACK|XXX)\b")
MAX_FILE_BYTES = 300_000


def validate_url(url: str) -> str:
    m = GITHUB_RE.match(url.strip())
    if not m:
        raise ValueError("Usa una URL pública con el formato https://github.com/usuario/repositorio")
    return f"https://github.com/{m[1]}/{m[2]}.git"


def clone(url: str, dest: str):
    try:
        subprocess.run(
            ["git", "clone", "--depth", "300", "--quiet", url, dest],
            check=True, timeout=120, capture_output=True,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
        )
    except subprocess.CalledProcessError:
        raise RuntimeError("No se pudo clonar el repositorio. Comprueba que existe y es público.")
    except subprocess.TimeoutExpired:
        raise RuntimeError("La clonación tardó demasiado. Prueba con un repositorio más pequeño.")


def commit_counts(root: Path) -> Counter:
    """Commits por archivo en los últimos 12 meses."""
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "log", "--since=12.months.ago", "--name-only", "--pretty=format:"],
            capture_output=True, text=True, timeout=60,
        ).stdout
    except Exception:
        return Counter()
    return Counter(line for line in out.splitlines() if line.strip())


def score_file(f: dict) -> float:
    cx = min(1, f["max_ccn"] / 30)
    size = min(1, f["nloc"] / 600)
    todo = min(1, f["todos"] / 5)
    long_fn = min(1, f["long_functions"] / 3)
    hot = min(1, f["commits"] / 20) * max(cx, size)
    raw = 0.35 * cx + 0.25 * size + 0.10 * todo + 0.10 * long_fn + 0.20 * hot
    return round(min(100, raw * 140), 1)


def analyze_dir(root: str | Path) -> list[dict]:
    root = Path(root)
    commits = commit_counts(root)
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            path = Path(dirpath) / name
            if path.is_symlink() or path.suffix not in EXTS or path.stat().st_size > MAX_FILE_BYTES:
                continue
            try:
                info = lizard.analyze_file(str(path))
                text = path.read_text(errors="ignore")
            except Exception:
                continue
            if info.nloc == 0:
                continue
            ccns = [fn.cyclomatic_complexity for fn in info.function_list] or [0]
            rel = path.relative_to(root).as_posix()
            f = {
                "path": rel,
                "nloc": info.nloc,
                "functions": len(info.function_list),
                "max_ccn": max(ccns),
                "avg_ccn": round(sum(ccns) / len(ccns), 1),
                "long_functions": sum(1 for fn in info.function_list if fn.nloc > 50),
                "todos": len(MARKERS.findall(text)),
                "commits": commits.get(rel, 0),
            }
            f["score"] = score_file(f)
            files.append(f)
    return sorted(files, key=lambda f: f["score"], reverse=True)


def build_result(files: list[dict]) -> dict:
    total_nloc = sum(f["nloc"] for f in files)
    repo_score = sum(f["score"] * f["nloc"] for f in files) / (total_nloc or 1)
    return {
        "repo_score": round(repo_score, 1),
        "totals": {
            "files": len(files),
            "nloc": total_nloc,
            "todos": sum(f["todos"] for f in files),
            "hotspots": sum(1 for f in files if f["commits"] >= 5 and f["score"] >= 50),
        },
        "files": files[:100],
    }
