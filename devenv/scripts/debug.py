#!/usr/bin/env python3

import os
import argparse
import subprocess
from typing import Dict, Literal
from time import sleep

import yaml


def parse_args():
    argparser = argparse.ArgumentParser(
        description="Debug pod interactively.",
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
        default="hzp",
        required=False,
        help="Kubernetes namespace of all objects that will be modified.",
    )
    argparser.add_argument(
        "-l",
        "--labels",
        default='',
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
        help="Disable debugging instead of enabling it.",
    )
    args = argparser.parse_args()
    if args.labels:
        args.labels = dict(l.split("=", 1) for l in args.labels.split(","))
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
    namespace: str, kind: Literal["deployment", "statefulset"], labels: Dict[str, str]
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
                mount["readWrjteMany"] = True
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


def set_sleep_cmd(
    *,
    manifest: str,
) -> None:
    #import ipdb;ipdb.set_trace()
    old_cmd = manifest['spec']['template']['spec']['containers'][0]['args']
    manifest['spec']['template']['spec']['containers'][0]['args'] = ['/bin/sleep', '47000']
    return ' '.join(old_cmd)


def unset_sleep_cmd(*, manifest: str, old_cmd: str) -> None:
    manifest['spec']['template']['spec']['containers'][0]['args'] = old_cmd.split(' ')
#    manifest['spec']['template']['spec']['containers'][0]['args'] = ['/usr/local/bin/uwsgi', '--ini=uwsgi.ini', '--plugins=python3', '--http=0.0.0.0:8080', '--wsgi-file=v2/mist_api_v2/__main__.py', '--callable=application', '--master', '--processes=8', '--max-requests=100', '--honour-stdin', '--enable-threads']


def scale_to_zero(*, manifest: str) -> None:
    manifest['spec']['replicas'] = 0


def scale_to_one(*, manifest: str) -> None:
    manifest['spec']['replicas'] = 1


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
        labels={**args.labels, **mount["labels"]}
        labels_str = ",".join("=".join((key, val)) for key, val in labels.items())
        manifest = get_manifest(
            namespace=args.namespace,
            kind=mount["kind"],
            labels=labels,
        )
        if args.disable:
            unset_sleep_cmd(manifest=manifest, old_cmd=old_cmd)
        else:
            old_cmd = set_sleep_cmd(
                manifest=manifest,
            )
        scale_to_zero(manifest=manifest)
        apply_manifest(namespace=args.namespace, manifest=manifest)
        cmd = f'kubectl delete po --force -n {args.namespace} -l{labels_str}'
        print('Running command: ', cmd)
        os.system(cmd)
        manifest = get_manifest(
            namespace=args.namespace,
            kind=mount["kind"],
            labels=labels,
        )
        scale_to_one(manifest=manifest)
        apply_manifest(namespace=args.namespace, manifest=manifest)
        sleep(3)
        cmd = f'kubectl exec -it $(kubectl get po -o name -l{labels_str}) -- {old_cmd} --no-threads-wait --threads 0 --reload-mercy 1 --worker-reload-mercy 2'
        print('Running command on fg: ', cmd)
        os.system(cmd)
        manifest = get_manifest(
            namespace=args.namespace,
            kind=mount["kind"],
            labels=labels,
        )
        scale_to_zero(manifest=manifest)
        apply_manifest(namespace=args.namespace, manifest=manifest)
        manifest = get_manifest(
            namespace=args.namespace,
            kind=mount["kind"],
            labels=labels,
        )
        unset_sleep_cmd(manifest=manifest, old_cmd=old_cmd)
        apply_manifest(namespace=args.namespace, manifest=manifest)
        manifest = get_manifest(
            namespace=args.namespace,
            kind=mount["kind"],
            labels=labels,
        )
        scale_to_one(manifest=manifest)
        apply_manifest(namespace=args.namespace, manifest=manifest)


if __name__ == "__main__":
    main()
