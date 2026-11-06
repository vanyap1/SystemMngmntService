"""Start child processes that die with the panel (PR_SET_PDEATHSIG) — from one long-lived thread.

Linux sends the parent-death signal when the *thread* that forked the child exits, not the process. Flask serves
every request in its own short-lived thread, so a child started directly from a request handler with PDEATHSIG
would be killed (SIGTERM, exit code 143) as soon as the response is sent. ``popen()`` therefore forks from a
dedicated daemon thread that lives as long as the panel.
"""
import ctypes
import queue
import signal
import subprocess
import threading

_jobs = queue.Queue()
_started = threading.Lock()
_thread = None


def die_with_parent():
    """preexec_fn: the child gets SIGTERM when the panel exits (only valid when forked by popen())."""
    try:
        ctypes.CDLL('libc.so.6', use_errno=True).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except OSError:
        pass


def _worker():
    while True:
        args, kwargs, box, done = _jobs.get()
        try:
            box['proc'] = subprocess.Popen(*args, **kwargs)
        except BaseException as e:      # handed back to the caller
            box['error'] = e
        done.set()


def popen(*args, setup=None, **kwargs):
    """subprocess.Popen(*args, **kwargs) with PDEATHSIG; ``setup`` is an extra preexec function run before it."""
    global _thread
    with _started:
        if _thread is None or not _thread.is_alive():
            _thread = threading.Thread(target=_worker, name='spawner', daemon=True)
            _thread.start()

    def pre():
        if setup:
            setup()
        die_with_parent()
    kwargs['preexec_fn'] = pre
    box, done = {}, threading.Event()
    _jobs.put((args, kwargs, box, done))
    done.wait()
    if 'error' in box:
        raise box['error']
    return box['proc']
