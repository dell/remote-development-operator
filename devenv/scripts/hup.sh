#!/bin/bash
for pod in `kubectl get po -lapp=api-v2 -o name`
do
    kubectl exec -it $pod -- kill -HUP 1
done
