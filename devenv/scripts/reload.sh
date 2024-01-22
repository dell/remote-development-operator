#!/bin/bash
for pod in `kubectl get po -lapp=api-v2 -o name`
do
    kubectl exec -it $pod -- kill -$reload_signal 1
done

kubectl patch devenv $envname --type merge -p '{"spec":{"mountsEnabled":true}}'
