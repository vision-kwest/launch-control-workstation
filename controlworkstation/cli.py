"""Unified command-line interface for Control Workstation operations."""

from __future__ import annotations

import argparse
import importlib
import sys
from collections.abc import Sequence


COMMANDS = ("launch", "doctor", "status", "ssh", "destroy")


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a workstation subcommand to its existing command module."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(
        prog="workstation",
        description="Provision and manage the Control Workstation.",
    )
    parser.add_argument("command", choices=COMMANDS, help="operation to perform")
    # Parse only the command so subcommand help and options remain owned by the
    # existing command module (for example, ``workstation launch --help``).
    args = parser.parse_args(arguments[:1])
    command_args = arguments[1:]
    command = importlib.import_module(args.command)
    return command.main(command_args)
