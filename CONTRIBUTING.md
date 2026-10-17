# Contributing

The project aims for transparent, low-dependency, Linux-native model management. Avoid adding database installations, Docker, Node build chains or shell-command subprocess interpolation without a clear justification.

1. Create a Python 3.10+ virtual environment and install `pip install -e '.[test]'`.
2. Run `pytest -q` and `bash -n deploy/install.sh cert/generate_cert.sh`.
3. Add tests for process lifecycle, port conflicts, nginx configuration generation/rollback, or hardware estimation changes.
4. Check API changes for auth/CSRF regressions and backend port isolation.
5. For nginx changes, verify a long-lived streamed response survives an actual graceful reload.
6. Document any llama.cpp-version-dependent behavior, and avoid presenting estimated memory or performance numbers as guarantees.

For now, open a GitHub issue describing the feature or bug, proposed behavior and hardware/build details before a large refactor. Never put model secrets, private certificates or client data into test fixtures.
