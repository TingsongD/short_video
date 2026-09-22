"""Bounded private service diagnostics, separate from launcher console logs.

Only explicit identifiers and codes are logged: no payloads, raw exception
messages, tracebacks, URLs with query strings, or credential dictionaries.
"""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import fcntl
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from pathlib import Path

from .events.redact import redact, redact_log
from .store.uow import utcnow

logger = logging.getLogger("factory.diagnostics")
FIELDS = {"job_id", "run_id", "stage", "status", "code", "error_type", "route"}


def event(name, **fields):
    logger.info(name, extra={"diagnostic_fields": redact({
        k: str(v)[:250] for k, v in fields.items() if k in FIELDS})})


class PrivateRotatingFileHandler(RotatingFileHandler):
    def _open(self):
        fd = os.open(self.baseFilename, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
        os.fchmod(fd, 0o600)
        return os.fdopen(fd, "a", encoding="utf-8")


class DiagnosticFormatter(logging.Formatter):
    def __init__(self, service):
        super().__init__()
        self.service = service

    def format(self, record):
        return json.dumps({"at": utcnow(), "pid": os.getpid(),
            "service": self.service, "event": record.getMessage(),
            **getattr(record, "diagnostic_fields", {})}, sort_keys=True)


class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Redact the final rendering too: exception messages and request-line
        # arguments may otherwise bypass a filter on record.msg.
        return redact_log(super().format(record))[:16000]


class LogStream:
    def __init__(self, target, level):
        self.target, self.level, self.buffer = target, level, ''

    def write(self, text):
        self.buffer += text
        while '\n' in self.buffer:
            line, self.buffer = self.buffer.split('\n', 1)
            if line.strip(): self.target.log(self.level, line)
        return len(text)

    def flush(self):
        if self.buffer.strip(): self.target.log(self.level, self.buffer)
        self.buffer = ''

    def isatty(self): return False


@contextmanager
def console_logging(folder, service):
    lock_fd = os.open(folder / f'{service}.log.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        os.fchmod(lock_fd, 0o600)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BaseException:
        os.close(lock_fd)
        raise RuntimeError('Another service owns this log; do not start a second writer')
    try:
        handler = PrivateRotatingFileHandler(folder / f'{service}.log',
            maxBytes=4 * 1024 * 1024, backupCount=3)
    except BaseException:
        os.close(lock_fd)
        raise
    handler.setFormatter(SafeFormatter('%(asctime)s %(levelname)s %(name)s %(message)s'))
    loggers = [logging.getLogger(n) for n in ('', 'uvicorn', 'uvicorn.error', 'uvicorn.access')]
    saved = [(l, l.handlers[:], l.level, l.propagate) for l in loggers]
    for l in loggers:
        l.handlers = [handler] if l.name == 'root' else []
        l.setLevel(logging.INFO); l.propagate = l.name != 'root'
    streams = [LogStream(logging.getLogger('factory.console'), level) for level in (logging.INFO, logging.ERROR)]
    try:
        with redirect_stdout(streams[0]), redirect_stderr(streams[1]):
            yield
    except BaseException:
        logging.getLogger('factory.console').exception('Service stopped')
        raise
    finally:
        for stream in streams: stream.flush()
        for l, handlers, level, propagate in saved:
            l.handlers, l.level, l.propagate = handlers, level, propagate
        handler.close()
        os.close(lock_fd)


@contextmanager
def service_logging(root, service):
    folder = Path(root) / ".run"
    folder.mkdir(parents=True, exist_ok=True)
    # Acquire ownership before either log is opened or written.
    with console_logging(folder, service):
        for pattern in (f'{service}.log*', f'factory-{service}.jsonl*'):
            for path in folder.glob(pattern):
                if path.is_file() and not path.is_symlink(): path.chmod(0o600)
        handler = PrivateRotatingFileHandler(folder / f"factory-{service}.jsonl",
                                             maxBytes=4 * 1024 * 1024, backupCount=3)
        handler.setFormatter(DiagnosticFormatter(service))
        previous = logger.level, logger.propagate
        logger.setLevel(logging.INFO)
        logger.propagate = False
        logger.addHandler(handler)
        try:
            event("service_started")
            yield
        except BaseException as error:
            if not isinstance(error, (KeyboardInterrupt, SystemExit)):
                event("service_failed", error_type=type(error).__name__)
            raise
        finally:
            event("service_stopped")
            logger.removeHandler(handler)
            handler.close()
            logger.setLevel(previous[0])
            logger.propagate = previous[1]
