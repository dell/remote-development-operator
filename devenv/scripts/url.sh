#!/bin/bash
app=$(kubectl get po `hostname` -o json|jq -r ".metadata.labels.app")
uri=docker@$(kubectl get svc $app-nlb -o json | jq -r '.metadata.annotations["external-dns.alpha.kubernetes.io/hostname"]')
echo $uri
