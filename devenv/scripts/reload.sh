#!/bin/bash

# Send reload signal to target pods.
for pod in `kubectl get po -lapp=api-v2 -o name`
do
    kubectl exec -it $pod -- kill -$reload_signal 1
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
        for pod in `kubectl get po -lapp=api-v2 -o name`
        do
            echo kubectl exec -it $pod -- $post_mount_pod_cmd
            kubectl exec -it $pod -- $post_mount_pod_cmd
        done
    fi
fi
