"""One worker owns the cached models. Threads share its scanner locks."""

import os
import sys
from pathlib import Path

chdir = str(Path(__file__).resolve().parent)
sys.path.insert(0, chdir)
from config import HOST, OPENAI_TIMEOUT, PORT, WARM_MODELS
from scanning import SCREEN_BUDGET

bind = f"{HOST}:{PORT}"
workers = 1
threads = int(os.environ.get("CYBERSYN_THREADS", 8))
timeout = max(180, int(SCREEN_BUDGET + OPENAI_TIMEOUT + 45))
control_socket_disable = True  # do not create an administrative socket in the app directory
access_log_format = '%(t)s "%(m)s %(U)s" %(s)s %(L)s'  # no query, headers or body
accesslog = "-"
errorlog = "-"


def post_worker_init(worker):
    if WARM_MODELS:
        from app import warm_models
        warm_models()
