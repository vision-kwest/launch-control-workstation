from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from controlworkstation.aws import Instance, tag_spec
from controlworkstation.cli import main as cli_main
from controlworkstation.config import Config
from controlworkstation.health import HealthReport, Check
from controlworkstation.ssh import command
from controlworkstation.userdata import render


class CoreTests(unittest.TestCase):
    @patch("controlworkstation.cli.importlib.import_module")
    def test_cli_dispatches_command_arguments(self, import_module: Mock) -> None:
        """The unified executable forwards options to the selected command."""
        command = Mock()
        command.main.return_value = 7
        import_module.return_value = command

        result = cli_main(["launch", "--login"])

        import_module.assert_called_once_with("launch")
        command.main.assert_called_once_with(["--login"])
        self.assertEqual(result, 7)

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
        self.assertIn("condition: test -f /var/run/reboot-required", user_data)

    def test_ssh_command_uses_matching_private_key(self) -> None:
        """Confirm SSH derives the private path from the configured public key.

        The complete vector is compared so the identity flag, destination user,
        argument ordering, and removal of ``.pub`` are all protected behavior.
        """
        config = Config(public_key=Path("/tmp/studio.pub"))
        self.assertEqual(command("192.0.2.1", config), ["ssh", "-i", "/tmp/studio", "-o", "IdentitiesOnly=yes", "ubuntu@192.0.2.1"])

    def test_health_report_aggregates_all_categories(self) -> None:
        """Overall health requires every category to pass."""
        passed = Check("one", True, "ok")
        failed = Check("two", False, "broken")
        report = HealthReport(infrastructure=(passed,), system=(failed,))
        self.assertFalse(report.healthy)
        self.assertEqual(report.errors, ("two: broken",))

    def test_instance_defaults_are_diagnostic_safe(self) -> None:
        """An instance model can represent incomplete AWS addressing."""
        instance = Instance("i-test", "pending")
        self.assertEqual(instance.public_ip, "")

    @patch("controlworkstation.health.run")
    @patch("controlworkstation.health.socket.create_connection")
    def test_remote_health_reports_timeouts_instead_of_raising(self, connection: Mock, ssh_run: Mock) -> None:
        """A dashboard remains comprehensive when a remote probe times out."""
        from controlworkstation.health import remote_health

        connection.return_value.__enter__ = Mock()
        connection.return_value.__exit__ = Mock(return_value=False)
        ssh_run.side_effect = [Mock(returncode=0, stdout="AUTHENTICATED", stderr=""),
                               *[TimeoutError("slow")] * 10]
        report = remote_health("192.0.2.1", Config())
        self.assertFalse(report.healthy)
        self.assertIn("cloud-init: slow", report.errors)

    @patch("controlworkstation.doctor.shutil.which", return_value=None)
    def test_doctor_reports_every_check_without_aws(self, which: Mock) -> None:
        """Missing AWS CLI does not hide the remaining required diagnostics."""
        from controlworkstation.doctor import diagnose

        with tempfile.TemporaryDirectory() as directory:
            checks = diagnose(Config(public_key=Path(directory) / "id_ed25519.pub"))
        names = {item.name for item in checks}
        self.assertTrue({"AWS authentication", "SSH key", "Region", "Default VPC",
                         "Quota sanity", "Existing Control Workstation"}.issubset(names))


if __name__ == "__main__":
    unittest.main()
