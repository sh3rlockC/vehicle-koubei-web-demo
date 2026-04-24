# systemd Notes

For the MVP, Docker Compose is the primary runtime entrypoint.

This directory is reserved for:

- optional host-level service wrappers
- reboot-time startup integration
- timer units for backups and artifact cleanup

Do not rely on host-level systemd units until the Compose-based stack is validated first.
