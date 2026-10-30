# Dependency and tool provenance

v1.1 adds Tenacity9.1.2 (Apache-2.0), officially downloaded as `tenacity-9.1.2-py3-none-any.whl`, SHA256 `f77bf36710d8b73a50b2dd155c97b870017ad21afe6ab300326b0371b3b05138`. It is used on the payment adapter's safe GET observation path, with explicit stop/backoff policies. The current lock contains26 packages. A new environment installs all26 retained official wheels after checking hashes; no package uninstall or bulk cleanup is used. Detailed receipt: architecture round `tenacity-install.json` / `clean-install-v4.json`. Earlier25-package receipts below remain unchanged.

The source release is MIT, with third-party dependencies retaining their own licenses. Dependencies are installed from the 26 pinned package versions in requirements-lock.txt; no dependency source, model weights or browser binary is bundled in the source ZIP.

- psycopg3.2.12, psycopg-binary3.2.12, psycopg-pool3.2.7: LGPL-3.0-only, verified from each downloaded wheel's METADATA and bundled LICENSE.txt. Wheels and their license texts remain locally available. Binary dependencies retain their upstream notices.
- tzdata2025.2: Apache-2.0, official wheel metadata.
- Prettier3.6.2: MIT, official npm archive, SHA512 integrity verified; development formatter only, not a runtime dependency.
- Shared Qwen3.5-4B model: Apache-2.0 per coordinator-supplied artifact receipt; see MODEL.md. No additional model download by this project.
- ui-ux-pro-max and Impeccable: preinstalled design skills, sources/install receipts maintained by the coordinator. No launcher, hooks, uninstall, recursive cleanup or second browser stack was used.

Exact official download URLs, hashes, all25 wheel license headers/files and retained local artifact paths are in the private delivery records `clean-install-downloads.json`, `wheel-license-evidence.json`, `dependency-license.json` and `formatter-license.json`. Some PyPI JSON license fields were empty; the wheel metadata resolved the Psycopg license to LGPL-3.0-only. The archive contains version pins and this notice, not confidential local runtime configuration.
