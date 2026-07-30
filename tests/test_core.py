from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from controlworkstation.aws import tag_spec
from controlworkstation.config import Config
from controlworkstation.ssh import command
from controlworkstation.userdata import render


class CoreTests(unittest.TestCase):
    def test_config_reads_environment_at_creation(self) -> None:
        """Prove default factories read overrides when each Config is created.

        The environment patch is scoped around construction, after which both a
        string setting and an integer-parsed setting are checked independently.
        """
        with patch.dict(os.environ, {"LCW_REGION": "eu-west-1", "LCW_DISK_SIZE": "150"}):
            config = Config()
        self.assertEqual(config.region, "eu-west-1")
        self.assertEqual(config.disk_size, 150)

    def test_tag_spec_is_valid_json_and_preserves_spaces(self) -> None:
        """Ensure AWS tag JSON remains parseable without corrupting whitespace.

        Decoding the helper's result validates its serialization, and comparing
        the exact tag structure proves a human-readable value survives intact.
        """
        value = json.loads(tag_spec("instance", {"Owner": "Studio Ops"}))
        self.assertEqual(value["Tags"], [{"Key": "Owner", "Value": "Studio Ops"}])

    def test_cloud_init_embeds_bootstrap(self) -> None:
        """Verify rendering inserts an indented script and removes its marker.

        Assertions cover the cloud-config header, YAML indentation of the shell
        shebang, and full replacement of the template placeholder.
        """
        user_data = render()
        self.assertTrue(user_data.startswith("#cloud-config"))
        self.assertIn("      #!/usr/bin/env bash", user_data)
        self.assertNotIn("__BOOTSTRAP_SCRIPT__", user_data)

    def test_ssh_command_uses_matching_private_key(self) -> None:
        """Confirm SSH derives the private path from the configured public key.

        The complete vector is compared so the identity flag, destination user,
        argument ordering, and removal of ``.pub`` are all protected behavior.
        """
        config = Config(public_key=Path("/tmp/studio.pub"))
        self.assertEqual(command("192.0.2.1", config), ["ssh", "-i", "/tmp/studio", "-o", "IdentitiesOnly=yes", "ubuntu@192.0.2.1"])


if __name__ == "__main__":
    unittest.main()
