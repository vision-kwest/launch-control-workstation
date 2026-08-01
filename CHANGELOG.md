# Changelog

All notable changes to this project are documented here.

## Unreleased

## 1.0.1 - 2026-08-01

### Changed

- Made PyPI and pipx the official distribution and installation path.
- Added tag-gated Trusted Publishing, GitHub Release artifacts, and post-publish
  installation validation to the automated release workflow.
- Made workstation bootstrap installation idempotently install or upgrade the
  published package and verify its CLI diagnostics.
- Removed the duplicated configuration version literal so package metadata, the
  CLI, and AWS resource tags all use the authoritative package version module.
- Added release-contract tests for version sourcing, tag-triggered releases,
  PyPI Trusted Publishing, and generated installation notes.

## 1.0.0 - 2026-07-30

### Added

- A unified health framework covering EC2, SSH, provisioning, developer tools,
  disk, memory, uptime, and reboot state.
- A read-only `doctor.py` preflight for local tools, AWS access, networking,
  quota, keys, and existing workstation discovery.
- End-to-end readiness verification with automatic reconnection across reboots.

### Changed

- Automated safe ED25519 key creation and EC2 fingerprint verification.
- Expanded `status.py` into a complete workstation health dashboard.
- Added phase timings, a multi-workflow completion screen, and optional login.
- Declared the project production-ready and feature complete; future releases
  are limited to bug fixes and maintenance.
