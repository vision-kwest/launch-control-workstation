from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from launch_control_workstation.aws import Instance, ensure_key_pair, tag_spec
from launch_control_workstation.cli import main as cli_main
from launch_control_workstation.config import Config
from launch_control_workstation.health import HealthReport, Check
from launch_control_workstation.ssh import command
from launch_control_workstation.userdata import render


class CoreTests(unittest.TestCase):
    @patch("launch_control_workstation.cli.importlib.import_module")
    def test_cli_dispatches_command_arguments(self, import_module: Mock) -> None:
        """The unified executable forwards options to the selected command."""
        command = Mock()
        command.main.return_value = 7
        import_module.return_value = command

        result = cli_main(["launch", "--login"])

        import_module.assert_called_once_with("launch_control_workstation.commands.launch")
        command.main.assert_called_once_with(["--login"])
        self.assertEqual(result, 7)

    def test_cli_reports_authoritative_version(self) -> None:
        """The version command reads the package's single version source."""
        from launch_control_workstation import __version__

        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            result = cli_main(["version"])
        self.assertEqual(result, 0)
        self.assertEqual(output.getvalue().strip(), __version__)

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

    @patch("launch_control_workstation.aws.run")
    @patch("launch_control_workstation.aws.aws")
    def test_key_pair_accepts_aws_bare_sha256_fingerprint(self, aws_call: Mock, run_call: Mock) -> None:
        """AWS's bare digest and OpenSSH's prefixed digest compare equally."""
        aws_call.return_value = {"KeyPairs": [{"KeyFingerprint": "same-digest="}]}
        run_call.return_value = Mock(returncode=0, stdout="256 SHA256:same-digest= key (ED25519)\n", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            public_key = Path(directory) / "id_ed25519.pub"
            public_key.write_text("ssh-ed25519 test\n")
            public_key.with_suffix("").write_text("private")
            ensure_key_pair(Config(public_key=public_key))

        aws_call.assert_called_once()

    @patch("launch_control_workstation.aws.run")
    @patch("launch_control_workstation.aws.aws")
    def test_replace_key_pair_reimports_mismatched_registration(self, aws_call: Mock, run_call: Mock) -> None:
        """An explicit repair replaces only the stale EC2 registration."""
        aws_call.side_effect = [
            {"KeyPairs": [{"KeyFingerprint": "remote-fingerprint"}]},
            "",
            {"KeyFingerprint": "local-fingerprint"},
        ]
        run_call.return_value = Mock(returncode=0, stdout="256 local-fingerprint key (ED25519)\n", stderr="")

        with tempfile.TemporaryDirectory() as directory:
            public_key = Path(directory) / "id_ed25519.pub"
            public_key.write_text("ssh-ed25519 test\n")
            public_key.with_suffix("").write_text("private")
            config = Config(public_key=public_key, key_name="workstation-test")
            ensure_key_pair(config, replace=True)

        self.assertEqual(aws_call.call_args_list[1].args[0], [
            "ec2", "delete-key-pair", "--key-name", "workstation-test",
        ])
        self.assertEqual(aws_call.call_args_list[2].args[0][:4], [
            "ec2", "import-key-pair", "--key-name", "workstation-test",
        ])

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

    @patch("launch_control_workstation.health.run")
    @patch("launch_control_workstation.health.socket.create_connection")
    def test_remote_health_reports_timeouts_instead_of_raising(self, connection: Mock, ssh_run: Mock) -> None:
        """A dashboard remains comprehensive when a remote probe times out."""
        from launch_control_workstation.health import remote_health

        connection.return_value.__enter__ = Mock()
        connection.return_value.__exit__ = Mock(return_value=False)
        ssh_run.side_effect = [Mock(returncode=0, stdout="AUTHENTICATED", stderr=""),
                               *[TimeoutError("slow")] * 10]
        report = remote_health("192.0.2.1", Config())
        self.assertFalse(report.healthy)
        self.assertIn("cloud-init: slow", report.errors)

    @patch("launch_control_workstation.doctor.shutil.which", return_value=None)
    def test_doctor_reports_every_check_without_aws(self, which: Mock) -> None:
        """Missing AWS CLI does not hide the remaining required diagnostics."""
        from launch_control_workstation.doctor import diagnose

        with tempfile.TemporaryDirectory() as directory:
            checks = diagnose(Config(public_key=Path(directory) / "id_ed25519.pub"))
        names = {item.name for item in checks}
        self.assertTrue({"AWS authentication", "SSH key", "Region", "Default VPC",
                         "Quota sanity", "Existing Control Workstation"}.issubset(names))


if __name__ == "__main__":
    unittest.main()
