from edrader.monitoring.logging import get_logger, setup_logging


def test_setup_logging() -> None:
    setup_logging("DEBUG")
    logger = get_logger("test")
    assert logger is not None


def test_get_logger_returns_bound_logger() -> None:
    logger = get_logger("test_module")
    assert logger is not None
    assert callable(logger.info)
    assert callable(logger.debug)
    assert callable(logger.error)


def test_logger_with_context() -> None:
    logger = get_logger("context_test")
    assert logger is not None


def test_multiple_loggers() -> None:
    setup_logging("INFO")
    l1 = get_logger("module_a")
    l2 = get_logger("module_b")
    assert l1 is not None
    assert l2 is not None
