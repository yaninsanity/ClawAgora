#!/usr/bin/env python
import os
import sys


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "clawagora_server.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Django is required for the server extra. Install with: pip install clawagora[server]"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
