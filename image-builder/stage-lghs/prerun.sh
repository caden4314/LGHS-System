#!/bin/bash -e

# Start this custom stage from the rootfs produced by the previous pi-gen stage.
if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
