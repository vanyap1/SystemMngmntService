"""Shell and filesystem helpers shared by routes."""
import os
import shlex
import subprocess

quote = shlex.quote


def run_command(command, timeout=None):
    """Run a shell command; ``sudo`` never prompts. Returns stdout or an 'Error!' report."""
    if command.startswith('sudo '):
        # Already root (the panel service): sudo is not needed.
        command = command[5:] if os.geteuid() == 0 else command.replace('sudo ', 'sudo -n ', 1)
    try:
        result = subprocess.run(command, shell=True, text=True, capture_output=True, check=True,
                                timeout=timeout)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error!\nSTDOUT: {e.stdout}\nSTDERR: {e.stderr}"
    except subprocess.TimeoutExpired:
        return f"Error!\nTimed out after {timeout} s"


def sh(command, timeout=4):
    """Run a read-only command quietly; returns stripped stdout or '' on any failure."""
    try:
        return subprocess.run(command, shell=True, text=True,
                              capture_output=True, timeout=timeout).stdout.strip()
    except Exception:
        return ''


def resolve_inside(path, root):
    """Return the real path if it lies strictly inside ``root``, else None."""
    if not path:
        return None
    real_path = os.path.realpath(path)
    if real_path.startswith(os.path.realpath(root) + os.sep):
        return real_path
    return None
