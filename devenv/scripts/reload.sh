#!/bin/bash

# Send reload signal to target pods.
export pods=$(python -d <<EOF
import os
import yaml
import base64
import subprocess

mounts = base64.b64decode(os.getenv('mounts'))
mounts_yaml = f"""mounts:
{mounts.decode()}"""
mounts_obj = yaml.safe_load(mounts)

for mount in mounts_obj:
    labels = mount['labels']
    labels_str = ",".join(f"{key}={val}" for key, val in labels.items())
    print(subprocess.check_output(['kubectl','get','po',f"-l{labels_str}",'-o','name']).decode('utf-8'))
EOF
)

for pod in $pods
do
    echo $pod
    kubectl exec -it $pod -- kill -$reload_signal 1
    if [ -z "$reload_cmd" ]; then
        # No reload command to be executed inside the pod.
        echo
    else
        echo "Executing reload command inside $pod: $reload_cmd"
        kubectl exec -it $pod -- $reload_cmd
    fi
    echo "Reloading $pod"
done

# Enable mounts if needed
if [[ $(kubectl patch devenv $envname --type merge -p '{"spec":{"mountsEnabled":true}}') == *"(no change)"* ]]; then
    echo "No changing mounts"
else
    echo "Mounts enabled"
    # Run post mount command
    if [[ -z "$post_mount_pod_cmd" ]]; then
        echo "No post mount command to be executed inside the pods"
    else
        echo "Executing post mount command inside each pod"
        for pod in $pods
        do
            echo kubectl exec -it $pod -- $post_mount_pod_cmd
            kubectl exec -it $pod -- $post_mount_pod_cmd
        done
    fi
fi
