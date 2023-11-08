#!/usr/bin/env python3

import argparse
import os
import subprocess
from typing import Literal

import yaml


def parse_args():
    argparser = argparse.ArgumentParser(
        description="Mount code volume to pods.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    argparser.add_argument(
        "-c",
        "--config",
        required=False,
        default="./config.yaml",
        help="Configuration file with target manifests and mount paths.",
    )
    argparser.add_argument(
        "-n",
        "--namespace",
        default="default",
        required=False,
        help="Kubernetes namespace of all objects that will be modified.",
    )
    argparser.add_argument(
        "-l",
        "--labels",
        default="",
        required=False,
        help=(
            "Labels common to all kubernetes objects that will be manified. "
            "This must be a comma-separated list (no blanks) of key=value pairs. "
            "Main use case is to limit to a particular helm release, for example "
            "with some like `--labels release=test-env-42`."
        ),
    )
    argparser.add_argument(
        "-d",
        "--disable",
        action="store_true",
        help="Disable mounts instead of enabling them.",
    )
    argparser.add_argument("pvc_name", help="Name of PVC to mount.")
    args = argparser.parse_args()
    if args.labels:
        args.labels = dict(lbl.split("=", 1) for lbl in args.labels.split(","))
    else:
        args.labels = {}
    return args


def load_config(path: str) -> dict:
    if not os.path.exists(path):
        raise OSError(f"Can't find configuration file at '{path}'.")
    with open(path) as fobj:
        config = yaml.safe_load(fobj)
    assert "mounts" in config, config
    for mount in config["mounts"]:
        assert isinstance(mount, dict), repr(mount)
        for attr in ("kind", "labels", "mountPath"):
            assert attr in mount, mount
    return config


def get_manifest(
    namespace: str, kind: Literal["deployment", "statefulset"], labels: dict[str, str]
) -> dict:
    labels_str = ",".join("=".join((key, val)) for key, val in labels.items())
    cmd = ["kubectl", "-n", namespace, "get", kind, "-l", labels_str, "-o", "yaml"]
    proc = subprocess.run(cmd, capture_output=True, check=True, timeout=5)
    manifest = yaml.safe_load(proc.stdout)
    assert manifest.get("kind") == "List"
    # TODO: Support multiple matches?
    assert len(manifest["items"]) == 1
    return manifest["items"][0]


def apply_manifest(namespace: str, manifest: dict) -> None:
    cmd = ["kubectl", "-n", namespace, "apply", "-f", "-"]
    print(yaml.safe_dump(manifest))
    subprocess.run(cmd, input=yaml.safe_dump(manifest).encode(), check=True, timeout=5)


def add_mount(
    *,
    manifest: str,
    volume_name: str,
    pvc_name: str,
    mount_path: str,
    sub_path: str = "",
) -> None:
    # Configure volume.
    volumes = manifest["spec"]["template"]["spec"]["volumes"]
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
        mounts = container["volumeMounts"]
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


def remove_mount(*, manifest: str, volume_name: str) -> None:
    # Remove volume.
    volumes = manifest["spec"]["template"]["spec"]["volumes"]
    for i, volume in reversed(list(enumerate(volumes))):
        if volume["name"] == volume_name:
            volumes.pop(i)
    # Remove volume mount.
    for container in manifest["spec"]["template"]["spec"]["containers"]:
        mounts = container["volumeMounts"]
        for i, mount in reversed(list(enumerate(mounts))):
            if mount["name"] == volume_name:
                mounts.pop(i)


def main():
    args = parse_args()
    config = load_config(args.config)
    volume_name = config.get("volume_name", "code")
    assert "mounts" in config, config
    for mount in config["mounts"]:
        assert isinstance(mount, dict), repr(mount)
        for attr in ("kind", "labels", "mountPath"):
            assert attr in mount, mount
        if mount["kind"].lower() != "deployment":
            raise NotImplementedError("Only deployments are supported.")
        manifest = get_manifest(
            namespace=args.namespace,
            kind=mount["kind"],
            labels={**args.labels, **mount["labels"]},
        )
        if args.disable:
            remove_mount(manifest=manifest, volume_name=volume_name)
        else:
            add_mount(
                manifest=manifest,
                volume_name=volume_name,
                pvc_name=args.pvc_name,
                mount_path=mount["mountPath"],
                sub_path=mount.get("subPath", ""),
            )
        apply_manifest(namespace=args.namespace, manifest=manifest)


if __name__ == "__main__":
    main()
