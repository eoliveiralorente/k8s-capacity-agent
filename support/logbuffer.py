"""Guarda as últimas linhas de log em memória para o pacote de suporte."""
import collections
import logging

_BUFFER = collections.deque(maxlen=800)


class _BufferHandler(logging.Handler):
    def emit(self, record):
        try:
            _BUFFER.append(self.format(record))
        except Exception:
            pass


_installed = False


def install():
    global _installed
    if _installed:
        return
    handler = _BufferHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
    # "uvicorn" não propaga para o root; os loggers da aplicação propagam.
    logging.getLogger("uvicorn").addHandler(handler)
    _installed = True


def recent_lines(limit=500):
    return list(_BUFFER)[-limit:]
