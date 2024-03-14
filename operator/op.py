# Copyright © 2023 Dell Inc. or its subsidiaries. All Rights Reserved.

import base64
import functools
import os
import subprocess
from copy import deepcopy

import kopf
import yaml

BASE_DIR = os.path.dirname(__file__)


@kopf.on.create("dell.com", "v1", "devenvs")
@kopf.on.update("dell.com", "v1", "devenvs", field="spec")
def create_update_dev_env(name, spec, namespace, logger, **kwargs):
    """This handler will idempotently create/update the dev environment.

    It will be called when a DevEnv CRD is created or when its `spec` field is updated.
    To achieve a minimal idempotent implementation, we are just interpolating the
    manifest templates and applying using `kubectl apply -f -`.
    """
    logger.info("Will idempotently create/update the dev environment.")
    del kwargs

    # Parse configuration options.
    image = spec["image"]
    kind = spec.get("kind", "deployment").capitalize()
    ssh_keys = spec["authorizedKeys"]
    pvc_size = spec["pvcSize"]
    base_domain = spec["baseDomain"]
    excluded_paths = spec["excludedPaths"]
    mounts = spec["mounts"]
    reload_signal = spec["reloadSignal"]
    post_mount_pod_cmd = spec["postMountPodCmd"]

    # Interpolate all templates and apply idempotently using kubectl apply -f -
    _t = functools.partial(template_yaml, logger=logger, name=name)
    resources = [
        _t("templates/service-account.yaml"),
        _t("templates/role.yaml"),
        _t("templates/role-binding.yaml"),
        _t(
            "templates/pvc.yaml",
            size=pvc_size,
            access_mode="ReadWriteMany",
            storage_class="efs",
        ),
        _t(
            "templates/resource.yaml",
            image=image,
            ssh_keys="\n".join(ssh_keys),
            mounts=base64.b64encode(yaml.safe_dump(mounts).encode()).decode(),
            reload_signal=reload_signal,
            post_mount_pod_cmd=post_mount_pod_cmd,
            kind=kind,
        ),
        _t("templates/svc.yaml", base_domain=base_domain),
    ]
    kopf.adopt(resources)
    kubectl_apply(namespace=namespace, manifest=resources, logger=logger)

    # Prepare status information to be stored on the DevEnv CRD instance.
    ssh_uri = f"docker@{name}.{base_domain}"
    base_repo_path = ""
    exclude_args = " ".join(f"--exclude={exc}" for exc in excluded_paths)
    cmd = f"echo 'Starting rsync' && rsync -e 'ssh -o StrictHostKeyChecking=no' -rlptzv --progress {exclude_args} `pwd`/{base_repo_path} {ssh_uri}:/home/docker/code && echo Reloading services && ssh {ssh_uri} -- './scripts/reload.sh' && echo Done"  # NOQA: E501
    return {"ssh": ssh_uri, "cmd": cmd}


@kopf.on.field("dell.com", "v1", "devenvs", field="spec.mountsEnabled")
@kopf.on.field("dell.com", "v1", "devenvs", field="spec.mounts")
def update_mounts(name, spec, namespace, logger, **kwargs):
    """This handler will idempotently update the volume mounts."""
    del kwargs
    logger.info("Will idempotently update volume mounts.")
    for (
        manifest,
        mounted,
        mount_path,
        sub_path,
        entrypoints,
    ) in iter_mounts_and_manifests(namespace, spec["mounts"]):
        m_kind, m_name = manifest["kind"], manifest["metadata"]["name"]

        if spec["mountsEnabled"] and mounted:
            if spec.get("mode") == "clone":
                _t = functools.partial(template_yaml, logger=logger, name=name)
                base_domain = spec["baseDomain"]
                port = spec["port"]
                manifest = clone_manifest(manifest=manifest, new_name_postfix=name)
                svc_manifest = _t(
                    "templates/svc-http.yaml",
                    name=manifest["metadata"]["name"],
                    devenv=name,
                    base_domain=base_domain,
                    port=port,
                )
                ing_manifest = _t(
                    "templates/ing.yaml",
                    name=manifest["metadata"]["name"],
                    base_domain=base_domain,
                    port=port,
                    group_name=spec.get("group", "default"),
                )
                logger.info("Idempotently cloning %s:%s", m_kind, m_name)
                kubectl_apply(namespace=namespace, manifest=svc_manifest, logger=logger)
                kubectl_apply(namespace=namespace, manifest=ing_manifest, logger=logger)
            else:
                logger.info("Idempotently mounting volume to %s:%s", m_kind, m_name)
            add_mount(
                manifest=manifest,
                volume_name=name,
                pvc_name=name,
                mount_path=mount_path,
                sub_path=sub_path,
            )
            update_entrypoints(manifest=manifest, entrypoints=entrypoints)
            kubectl_apply(namespace=namespace, manifest=manifest, logger=logger)
        else:
            if spec.get("mode") == "modify":
                remove_mount(manifest=manifest, volume_name=name)
                restore_entrypoints(manifest=manifest, entrypoints=entrypoints)
                logger.info("Idempotently unmounting volume to %s:%s", m_kind, m_name)
                kubectl_apply(namespace=namespace, manifest=manifest, logger=logger)
            elif kubectl_get(namespace=namespace, kind=m_kind, labels={"devenv": name}):
                resource_name = manifest["metadata"]["name"] + "-" + name
                logger.info("Idempotently removing %s %s", m_kind, resource_name)
                kubectl_delete(
                    namespace=namespace, name=resource_name, kind=m_kind, logger=logger
                )
                kubectl_delete(
                    namespace=namespace,
                    name=resource_name,
                    kind="service",
                    logger=logger,
                )
                kubectl_delete(
                    namespace=namespace,
                    name=resource_name,
                    kind="ingress",
                    logger=logger,
                )


@kopf.on.delete("dell.com", "v1", "devenvs")
def cleanup_mounts(name, spec, namespace, logger, **kwargs):
    del kwargs
    logger.info("Clean up all volume mounts because dev env is being deleted.")
    for manifest, _, _, _ in iter_mounts_and_manifests(namespace, spec["mounts"]):
        remove_mount(manifest=manifest, volume_name=name)
        kubectl_apply(namespace=namespace, manifest=manifest, logger=logger)


def template_yaml(filename, logger, **kwargs):
    logger.debug(
        "Will load and interpolate template file %s with kwargs %s", filename, kwargs
    )
    with open(os.path.join(BASE_DIR, filename)) as fobj:
        template = fobj.read()
    text = template.format(**kwargs)
    data = yaml.safe_load(text)
    logger.debug("%s data:\n%s", filename, yaml.safe_dump(data))
    return data


def clone_manifest(manifest, new_name_postfix):
    new_manifest = deepcopy(manifest)
    new_manifest["metadata"]["name"] += "-" + new_name_postfix
    for key in [
        "deployment.kubernetes.io/revision",
        "kubectl.kubernetes.io/last-applied-configuration",
    ]:
        if key in new_manifest["metadata"]["annotations"]:
            del new_manifest["metadata"]["annotations"][key]
    for key in ["creationTimestamp", "generation", "resourceVersion", "uid"]:
        if key in new_manifest["metadata"]:
            del new_manifest["metadata"][key]
    if "release" in new_manifest["metadata"]["labels"]:
        del new_manifest["metadata"]["labels"]["release"]
    new_manifest["spec"]["template"]["metadata"]["labels"] = {
        "devenv": new_name_postfix
    }
    new_manifest["metadata"]["labels"] = {"devenv": new_name_postfix}
    new_manifest["spec"]["selector"]["matchLabels"] = {"devenv": new_name_postfix}
    new_manifest["spec"]["replicas"] = 1
    del new_manifest["status"]
    return new_manifest


def kubectl_delete(namespace: str, name: str, kind: str, logger) -> None:
    logger.debug("Will delete %s:\n%s", kind, name)
    cmd = ["kubectl", "-n", namespace, "delete", kind, name]
    subprocess.run(cmd, check=True, timeout=5)


def kubectl_apply(namespace: str, manifest: str | dict | list, logger) -> None:
    if isinstance(manifest, list):
        for item in manifest:
            kubectl_apply(namespace, item, logger)
        return
    elif isinstance(manifest, dict):
        manifest = yaml.safe_dump(manifest)
    logger.debug("Will apply manifest:\n%s", manifest)
    cmd = ["kubectl", "-n", namespace, "apply", "-f", "-"]
    subprocess.run(cmd, input=manifest.encode(), check=True, timeout=5)


def kubectl_get(namespace: str, kind: str, labels: dict[str, str]) -> list[dict]:
    labels_str = ",".join(f"{key}={val}" for key, val in labels.items())
    cmd = ["kubectl", "-n", namespace, "get", kind, "-l", labels_str, "-o", "yaml"]
    proc = subprocess.run(cmd, capture_output=True, check=True, timeout=5)
    manifest = yaml.safe_load(proc.stdout)
    assert manifest.get("kind") == "List"
    return manifest["items"]


def iter_mounts_and_manifests(namespace, mounts):
    for mount in mounts:
        assert isinstance(mount, dict), repr(mount)
        for attr in ("kind", "labels", "mountPath", "mounted"):
            assert attr in mount, mount
        if mount["kind"].lower() != "deployment":
            raise NotImplementedError("Only deployments are supported.")
        for manifest in kubectl_get(
            namespace=namespace, kind=mount["kind"], labels=mount["labels"]
        ):
            yield (
                manifest,
                mount["mounted"],
                mount["mountPath"],
                mount.get("subPath", ""),
            )


def add_mount(
    *,
    manifest: dict,
    volume_name: str,
    pvc_name: str,
    mount_path: str,
    sub_path: str = "",
) -> None:
    # Configure volume.
    volumes = manifest["spec"]["template"]["spec"].get("volumes", [])
    for volume in volumes:
        if volume["name"] == volume_name:
            # Update existing volume.
            volume["persistentVolumeClaim"]["claimName"] = pvc_name
            break
    else:
        # Add new volume.
        volumes.append(
            {"name": volume_name, "persistentVolumeClaim": {"claimName": pvc_name}}
        )
    # Configure volume mount.
    for container in manifest["spec"]["template"]["spec"]["containers"]:
        mounts = container.get("volumeMounts", [])
        for mount in mounts:
            if mount["name"] == volume_name:
                # Update existing volume mount.
                mount["mountPath"] = mount_path
                if sub_path:
                    mount["subPath"] = sub_path
                else:
                    mount.pop("subPath", None)
                break
        else:
            # Add new volume mount.
            mount = {"name": volume_name, "mountPath": mount_path}
            if sub_path:
                mount["subPath"] = sub_path
            mounts.append(mount)
            container["volumeMounts"] = mounts


def remove_mount(*, manifest: dict, volume_name: str) -> None:
    # Remove volume.
    volumes = manifest["spec"]["template"]["spec"]["volumes"]
    for i, volume in reversed(list(enumerate(volumes))):
        if volume["name"] == volume_name:
            volumes.pop(i)
    # Remove volume mount.
    for container in manifest["spec"]["template"]["spec"]["containers"]:
        mounts = container.get("volumeMounts", [])
        for i, mount in reversed(list(enumerate(mounts))):
            if mount["name"] == volume_name:
                mounts.pop(i)


def update_entrypoints(*, manifest: dict, entrypoints: dict) -> None:
    for container in manifest["spec"]["template"]["spec"]["containers"]:
        entrypoint = entrypoints.get(container["name"])
        if entrypoint is None:
            continue
        container["command"] = entrypoint


def restore_entrypoints(*, manifest: dict, entrypoints: dict) -> None:
    for container in manifest["spec"]["template"]["spec"]["containers"]:
        entrypoint = entrypoints.get(container["name"])
        if entrypoint is None:
            continue
        if container.get("command"):
            del container["command"]
