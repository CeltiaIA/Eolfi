#!/usr/bin/env python3
import os
import pwd
import sys


def main() -> int:
    # Obtener el UID efectivo del proceso actual (igual que hace el whoami real)
    euid = os.geteuid()

    try:
        # Consultar la base de datos de usuarios del sistema (/etc/passwd / NSS)
        user_info = pwd.getpwuid(euid)
        print(user_info.pw_name)
        return 0
    except KeyError:
        # Comportamiento estándar si el UID efectivo no tiene nombre asociado
        print(f"whoami: cannot find name for user ID {euid}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
