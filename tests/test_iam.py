from __future__ import annotations

import json
import unittest
from unittest.mock import Mock, patch

from launch_control_workstation.aws import AwsError
from launch_control_workstation.config import Config
from launch_control_workstation.iam import (
    MANAGED_POLICIES,
    ROLE_NAME,
    SCHEDULER_POLICY_NAME,
    cleanup,
    ensure,
    scheduler_policy,
    validate,
)

ACCOUNT = "123456789012"
ROLE = {
    "Arn": f"arn:aws:iam::{ACCOUNT}:role/{ROLE_NAME}",
    "AssumeRolePolicyDocument": {
        "Statement": [{
            "Effect": "Allow",
            "Principal": {"Service": "ec2.amazonaws.com"},
            "Action": "sts:AssumeRole",
        }],
    },
}


def aws_response(args: list[str], _config: Config) -> dict[str, object]:
    """Return realistic IAM responses for role reconciliation tests."""
    operation = tuple(args[:2])
    if operation == ("iam", "get-role"):
        return {"Role": ROLE}
    if operation == ("iam", "get-instance-profile"):
        return {"InstanceProfile": {"Roles": [{"RoleName": ROLE_NAME}]}}
    if operation == ("iam", "list-attached-role-policies"):
        return {"AttachedPolicies": [{"PolicyArn": arn} for arn in MANAGED_POLICIES]}
    if operation == ("iam", "get-role-policy"):
        return {"PolicyDocument": scheduler_policy(ACCOUNT, "us-east-1")}
    return {}


class IamSchedulerPolicyTests(unittest.TestCase):
    @patch("launch_control_workstation.iam.aws", side_effect=aws_response)
    def test_ensure_reconciles_inline_scheduler_policy(self, aws_call: Mock) -> None:
        ensure(Config(region="us-east-1"))

        put_calls = [
            call.args[0] for call in aws_call.call_args_list
            if call.args[0][:2] == ["iam", "put-role-policy"]
        ]
        self.assertEqual(len(put_calls), 1)
        command = put_calls[0]
        self.assertEqual(command[command.index("--policy-name") + 1], SCHEDULER_POLICY_NAME)
        document = json.loads(command[command.index("--policy-document") + 1])
        self.assertEqual(document, scheduler_policy(ACCOUNT, "us-east-1"))

    @patch("launch_control_workstation.iam.aws", side_effect=aws_response)
    def test_ensure_is_idempotent(self, aws_call: Mock) -> None:
        ensure(Config())
        ensure(Config())

        put_calls = [
            call for call in aws_call.call_args_list
            if call.args[0][:2] == ["iam", "put-role-policy"]
        ]
        self.assertEqual(len(put_calls), 2)
        self.assertEqual(put_calls[0].args[0], put_calls[1].args[0])

    @patch("launch_control_workstation.iam.aws", side_effect=aws_response)
    def test_validate_rejects_stale_scheduler_policy(self, aws_call: Mock) -> None:
        def stale_response(args: list[str], config: Config) -> dict[str, object]:
            response = aws_response(args, config)
            if args[:2] == ["iam", "get-role-policy"]:
                return {"PolicyDocument": {"Version": "2012-10-17", "Statement": []}}
            return response

        aws_call.side_effect = stale_response
        with self.assertRaisesRegex(AwsError, "stale or malformed"):
            validate(Config())

    @patch("launch_control_workstation.iam.aws")
    def test_cleanup_deletes_inline_policy_before_role(self, aws_call: Mock) -> None:
        aws_call.return_value = {"IamInstanceProfileAssociations": []}

        self.assertTrue(cleanup(Config()))

        operations = [call.args[0][:2] for call in aws_call.call_args_list]
        self.assertLess(
            operations.index(["iam", "delete-role-policy"]),
            operations.index(["iam", "delete-role"]),
        )


if __name__ == "__main__":
    unittest.main()
