# Copyright © 2023 Dell Inc. or its subsidiaries. All Rights Reserved.

import base64
import functools
import os
import subprocess

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
        _t("service-account.yaml"),
        _t("role.yaml"),
        _t("role-binding.yaml"),
        _t("pvc.yaml", size=pvc_size, access_mode="ReadWriteMany", storage_class="efs"),
        _t(
            "deployment.yaml",
            image=image,
            ssh_keys="\n".join(ssh_keys),
            mounts=base64.b64encode(yaml.safe_dump(mounts).encode()).decode(),
            reload_signal=reload_signal,
            post_mount_pod_cmd=post_mount_pod_cmd,
        ),
        _t("svc.yaml", base_domain=base_domain),
    ]
    kopf.adopt(resources)
    kubectl_apply(namespace=namespace, manifest=resources, logger=logger)

    # Prepare status information to be stored on the DevEnv CRD instance.
    ssh_uri = f"docker@{name}.{base_domain}"
    base_repo_path = ""
    exclude_args = " ".join(f"--exclude={exc}" for exc in excluded_paths)
    cmd = f"echo 'Starting rsync' && rsync -rlptzv --progress {exclude_args} `pwd`/{base_repo_path} {ssh_uri}:/home/docker/code && echo Reloading services && ssh {ssh_uri} -- './scripts/reload.sh' && echo Done"  # NOQA: E501
    return {"ssh": ssh_uri, "cmd": cmd}


@kopf.on.field("dell.com", "v1", "devenvs", field="spec.mountsEnabled")
@kopf.on.field("dell.com", "v1", "devenvs", field="spec.mounts")
def update_mounts(name, spec, namespace, logger, **kwargs):
    del kwargs
    logger.info("Will idempotently update volume mounts.")
    for manifest, mounted, mount_path, sub_path in iter_mounts_and_manifests(
        namespace, spec["mounts"]
    ):
        m_kind, m_name = manifest["kind"], manifest["metadata"]["name"]
        if spec["mountsEnabled"] and mounted:
            add_mount(
                manifest=manifest,
                volume_name=name,
                pvc_name=name,
                mount_path=mount_path,
                sub_path=sub_path,
            )
            logger.info("Idempotently mounting volume to %s:%s", m_kind, m_name)
        else:
            remove_mount(manifest=manifest, volume_name=name)
            logger.info("Idempotently unmounting volume to %s:%s", m_kind, m_name)
        kubectl_apply(namespace=namespace, manifest=manifest, logger=logger)


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
