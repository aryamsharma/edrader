def __getattr__(name: str) -> object:
    import importlib

    if name == "AlertManager":
        module = importlib.import_module("edrader.monitoring.alerts")
        return getattr(module, name)
    if name in ("MetricsCollector", "RuntimeSnapshot"):
        module = importlib.import_module("edrader.monitoring.metrics")
        return getattr(module, name)
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


__all__ = [
    "AlertManager",
    "MetricsCollector",
    "RuntimeSnapshot",
]
