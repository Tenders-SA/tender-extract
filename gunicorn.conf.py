"""Optimized Gunicorn configuration for Cloud Run.

Addresses worker timeout issues and resource constraints.
"""

import os

# ============= WORKER CONFIGURATION =============

# Worker class - use uvicorn workers for async FastAPI
worker_class = "uvicorn.workers.UvicornWorker"

# Number of workers - Cloud Run 1 vCPU = 2 workers
workers = int(os.environ.get("GUNICORN_WORKERS", "2"))

# Threads per worker
threads = int(os.environ.get("GUNICORN_THREADS", "1"))

# ============= TIMEOUT CONFIGURATION =============

# Worker timeout - CRITICAL for fixing "CRITICAL WORKER TIMEOUT"
# Default is 30s, increase for PDF processing
timeout = int(os.environ.get("GUNICORN_TIMEOUT", "120"))

# Graceful timeout - time to finish requests during shutdown
graceful_timeout = int(os.environ.get("GUNICORN_GRACEFUL_TIMEOUT", "60"))

# Keep-alive timeout
keepalive = 5

# ============= STARTUP & HEALTH =============

# Preload app - False for Cloud Run to avoid memory spikes
preload_app = False

# Max requests per worker before restart (prevents memory leaks)
max_requests = int(os.environ.get("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = 50

# ============= BINDING =============

port = int(os.environ.get("PORT", "8080"))
bind = f"0.0.0.0:{port}"
backlog = 2048

# ============= LOGGING =============

access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'
accesslog = "-"
errorlog = "-"
loglevel = os.environ.get("LOG_LEVEL", "info")
capture_output = True

# ============= WORKER LIFECYCLE HOOKS =============

def on_starting(server):
    """Called before master process starts."""
    server.log.info("Master process starting")
    server.log.info(f"Workers: {workers}, Timeout: {timeout}s, Port: {port}")


def when_ready(server):
    """Called after server is ready."""
    server.log.info("Server ready to accept connections")


def worker_abort(worker):
    """Called when worker receives SIGABRT."""
    worker.log.error(f"Worker {worker.pid} aborted")
    try:
        import psutil
        process = psutil.Process(worker.pid)
        mem = process.memory_info()
        worker.log.error(f"Worker memory: RSS={mem.rss / 1024 / 1024:.2f}MB")
    except Exception:
        pass


def post_fork(server, worker):
    """Called after worker is forked."""
    server.log.info(f"Worker {worker.pid} spawned")


def child_exit(server, worker):
    """Called when worker exits."""
    server.log.info(f"Worker {worker.pid} exited")


def on_exit(server):
    """Called before master exits."""
    server.log.info("Master process shutting down")
