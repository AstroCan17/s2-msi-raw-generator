.PHONY: data-sync install devcontainer-setup publish-dataset

install:
	pip install -e ".[read,dev]"

data-sync:
	FORCE_DATA_SYNC=1 bash .devcontainer/scripts/fetch-input-data.sh

devcontainer-setup: install data-sync

# Package a local store root and publish to the private data repo (requires gh auth).
# Example:
#   make publish-dataset STORE_ROOT=/path/to/store-root
publish-dataset:
	@test -n "$(STORE_ROOT)" || (echo "Set STORE_ROOT=/path/to/store-root" && exit 1)
	bash .devcontainer/scripts/publish-dataset.sh "$(STORE_ROOT)"
