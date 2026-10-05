# Infrastructure: Systemd Unit Definition (Phase 2 - Planned)

> **Status:** NOT IMPLEMENTED (Phase 1 Application Foundation)

This directory is reserved for Linux `systemd` service configuration in Phase 2.

Planned capabilities:
- `ops23-nr.service` systemd unit file
- `Restart=always` and `RestartSec=3s` directives for automatic process crash recovery
- Journald logging configuration directing structured JSON to New Relic Infrastructure agent
- Environment variable loading from secure local paths
