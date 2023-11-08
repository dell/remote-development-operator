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

    # Create Service Account
    service_account_data = template_yaml("service-account.yaml", logger, name=name)
    kopf.adopt(service_account_data)
    kubernetes.client.CoreV1Api().create_namespaced_service_account(
        namespace=namespace, body=service_account_data
    )
    logger.info("Created Service Account.")

    # Create Role
    role_data = template_yaml("role.yaml", logger, name=name)
    kopf.adopt(role_data)
    kubernetes.client.RbacAuthorizationV1Api().create_namespaced_role(
        namespace=namespace, body=role_data
    )
    logger.info("Created Cluster Role.")

    # Create Role Binding
    role_binding_data = template_yaml("role-binding.yaml", logger, name=name)
    kopf.adopt(role_binding_data)
    kubernetes.client.RbacAuthorizationV1Api().create_namespaced_role_binding(
        namespace=namespace, body=role_binding_data
    )
    logger.info("Created Cluster Role Binding.")

    # Create PVC
    pvc_data = template_yaml("pvc.yaml", logger, name=name, size=pvc_size)
    kopf.adopt(pvc_data)
    kubernetes.client.CoreV1Api().create_namespaced_persistent_volume_claim(
        namespace=namespace, body=pvc_data
    )
    logger.info("Created PVC.")

    # Create deployment
    dpl_data = template_yaml(
        "deployment.yaml", logger, name=name, image=image, ssh_keys=ssh_keys
    )
    kopf.adopt(dpl_data)
    kubernetes.client.AppsV1Api().create_namespaced_deployment(
        namespace=namespace, body=dpl_data
    )
    logger.info("Created deployment.")

    # Create service
    svc_data = template_yaml("svc.yaml", logger, name=name, base_domain=base_domain)
    kopf.adopt(svc_data)
    kubernetes.client.CoreV1Api().create_namespaced_service(
        namespace=namespace, body=svc_data
    )
    logger.info("Created service.")
    return {"ssh": f"docker@{name}.{base_domain}"}
