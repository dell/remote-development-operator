# Copyright © 2023 Dell Inc. or its subsidiaries. All Rights Reserved.

import os

import kopf
import kubernetes
import yaml

BASE_DIR = os.path.dirname(__file__)


def template_yaml(filename, logger, **kwargs):
    logger.debug(
        "Will attempt to load and interpolate template file %s with kwargs %s",
        filename,
        kwargs,
    )
    with open(os.path.join(BASE_DIR, filename)) as fobj:
        template = fobj.read()
    text = template.format(**kwargs)
    data = yaml.safe_load(text)
    logger.debug("%s data:\n%s", filename, yaml.safe_dump(data))
    return data


@kopf.on.create("dell.com", "v1", "devenvs")
def create_fn(name, spec, namespace, logger, **kwargs):
    del kwargs

    # Parse configuration options.
    image = spec["image"]
    ssh_keys = "\n".join(spec["authorizedKeys"])
    pvc_size = spec["pvcSize"]
    base_domain = spec["baseDomain"]

    # Create PVC
    pvc_data = template_yaml("pvc.yaml", logger, name=name, size=pvc_size)
    kopf.adopt(pvc_data)
    kubernetes.client.CoreV1Api().create_namespaced_persistent_volume_claim(
        namespace=namespace, body=pvc_data
    )
    logger.info("Created PVC.")

    # Create pod
    pod_data = template_yaml(
        "pod.yaml", logger, name=name, image=image, ssh_keys=ssh_keys
    )
    kopf.adopt(pod_data)
    kubernetes.client.CoreV1Api().create_namespaced_pod(
        namespace=namespace, body=pod_data
    )
    logger.info("Created pod.")

    # Create service
    svc_data = template_yaml("svc.yaml", logger, name=name, base_domain=base_domain)
    kopf.adopt(svc_data)
    kubernetes.client.CoreV1Api().create_namespaced_service(
        namespace=namespace, body=svc_data
    )
    logger.info("Created service.")
    return {"ssh": f"docker@{name}.{base_domain}"}
