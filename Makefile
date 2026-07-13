.PHONY: install verify-rclone

install:
	pip install -e ".[read,dev]"

# Smoke: rclone binary + config + Drive API (no dataset download).
verify-rclone:
	bash .devcontainer/scripts/verify-rclone.sh
