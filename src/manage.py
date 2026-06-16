#!/usr/bin/env python
"""Django's command-line utility for administrative tasks."""
import os
import re
import sys


def main():
    """Run administrative tasks."""
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ucfp.settings")

    # Flag every one-shot management command (i.e. anything but `runserver`) so
    # startup background tasks are skipped for it -- read by
    # background/startup.py's is_management_command(). gunicorn/wsgi never run
    # manage.py, so the server is unaffected and DOES start its tasks.
    if len(sys.argv) > 1 and sys.argv[1] != "runserver":
        os.environ.setdefault("DJANGO_MANAGEMENT_COMMAND", sys.argv[1])

    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc

    set_runserver_defaults_if_needed()
    execute_from_command_line(sys.argv)


def set_runserver_defaults_if_needed():
    """
    Apply default hostname/port to the `runserver` command when the user did not
    specify them:

      - Hostname: 'localhost' -- a stable named host matching ALLOWED_HOSTS and
        any cookie/CORS scope (rather than Django's bare-port 127.0.0.1 default).
      - Port: from the DJANGO_SERVER_PORT env var, if set (else Django's default).

    Explicit args are always respected; only the missing parts are filled in.
    """
    if len(sys.argv) < 2 or sys.argv[1] != "runserver":
        return

    default_hostname = "localhost"
    default_port = os.environ.get("DJANGO_SERVER_PORT")

    if runserver_has_address_specified():
        # User gave an address -- only add a port if they gave a bare hostname.
        if runserver_has_hostname_only_arg() and default_port:
            sys.argv[-1] = f"{sys.argv[-1]}:{default_port}"
    elif default_port:
        sys.argv.append(f"{default_hostname}:{default_port}")
    else:
        sys.argv.append(default_hostname)


def runserver_has_address_specified() -> bool:
    """True if any address (hostname, port, or both) was given to runserver."""
    if len(sys.argv) < 3:
        return False
    for arg in sys.argv[2:]:
        if arg.startswith("--"):
            continue
        return True  # any non-flag argument is an address specification
    return False


def runserver_has_hostname_only_arg() -> bool:
    """True if the last positional arg is a hostname without a port."""
    if len(sys.argv) < 3:
        return False
    last_arg = sys.argv[-1]
    if last_arg.startswith("--"):
        return False
    if re.fullmatch(r"\d+", last_arg):   # port only, e.g. "8000"
        return False
    if ":" in last_arg:                  # already host:port
        return False
    return True                          # bare IP / hostname


if __name__ == "__main__":
    main()
