import sys, types

try:
    import lizard  # noqa: F401
    HAS_LIZARD = hasattr(lizard, "analyze_file")
except ImportError:
    # Sustituto mínimo para poder probar el resto de la lógica sin lizard instalado.
    # Los tests que dependen de la complejidad real se omiten (HAS_LIZARD = False).
    stub = types.ModuleType("lizard")
    def _analyze(p):
        with open(p, errors="ignore") as fh:
            return types.SimpleNamespace(nloc=sum(1 for l in fh if l.strip()), function_list=[])

    stub.analyze_file = _analyze
    sys.modules["lizard"] = stub
    HAS_LIZARD = False
