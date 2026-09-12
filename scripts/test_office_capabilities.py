#!/usr/bin/env python3
"""Small checks for Python dependency capability reporting."""

from __future__ import annotations

from unittest.mock import patch

import office_capabilities


def main() -> None:
    with (
        patch.object(office_capabilities.importlib.metadata, "version", return_value="1.2.3"),
        patch.object(office_capabilities.importlib, "import_module", return_value=object()),
    ):
        assert office_capabilities.package_status("demo", "demo") == {
            "status": "available",
            "version": "1.2.3",
        }

    with (
        patch.object(office_capabilities.importlib.metadata, "version", return_value="1.2.3"),
        patch.object(office_capabilities.importlib, "import_module", side_effect=ImportError("broken")),
    ):
        assert office_capabilities.package_status("demo", "demo") == {
            "status": "failed",
            "version": "1.2.3",
        }

    with patch.object(
        office_capabilities.importlib.metadata,
        "version",
        side_effect=office_capabilities.importlib.metadata.PackageNotFoundError,
    ):
        assert office_capabilities.package_status("demo", "demo") == {
            "status": "unavailable",
            "version": "",
        }

    print("Python dependency capability imports: PASS")


if __name__ == "__main__":
    main()
