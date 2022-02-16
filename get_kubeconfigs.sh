#!/bin/bash -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ssh master.admin.31337.ooo "sudo cat /root/.kube/config" > kubeconfig-admin
ssh master.game.31337.ooo "sudo cat /root/.kube/config" > kubeconfig-game

echo "# For game network:"
echo "export KUBECONFIG=$SCRIPT_DIR/kubeconfig-game"
echo "# For admin network:"
echo "export KUBECONFIG=$SCRIPT_DIR/kubeconfig-admin"
