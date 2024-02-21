# Remote Development Operator

The Remote Development Operator, is a Kubernetes operator and CRD for deploying remote development environments. It has been developed within Dell ISG Edge, to facilitate the development efforts of __[Dell NativeEdge](https://www.dell.com/en-us/dt/solutions/edge-computing/edge-platform.htm)__, the edge operations platform. The Remote Development Operator can be leveraged to facilitate the development of any software project that can be deployed on Kubernetes.

## Table of Contents

- [Features](#getting-started)
- [Installation](#installation)
- [Create new DevEnv](#create-new-devenv)
- [IDE configuration](#ide-configuration)
- [Contribution](#contribution)
- [License](#license)

# Features
The CRD, defines a new Kubernetes resource named __DevEnv__. Each __DevEnv__ can target one or more k8s deployments or statefulsets using label selectors. For each __DevEnv__, the operator creates a DNS record, a PVC for storing the code or binaries, and starts an SSH server, configured to accept the specified SSH keypairs. Each __DevEnv__, provides a command that can be used to configure the end user's IDE (e.g. VSCode). This configuration will synchronize over SSH the local code that's stored on the developer's device to the PVC that's attached to the __DevEnv__ pod. After the first sync is complete, the __DevEnv__ gets enabled and mounts the code PVC to the target pods.

There are two supported modes of operation.
- In `modify` mode the operator will edit the definition of the target deployments or statefulsets, mounting the code PVC on the target path, which will override the original code that's burned into the image.
- In `clone` mode the operator will launch a new deployment or statefulset, with the PVC mounted on the target path, while leaving the original deployment or statefulset untouched. A new service and ingress is also generated, to expose a port of the cloned deployment over HTTPS.

When working on a large application that consists of numerous microservices, the `clone` mode allows multiple developers to work in parallel, leveraging the same deployed application. There may still be cases were the cloned devenv may affect the original application, e.g. when working on DB schema changes. Developers that leverage the `clone` mode should coordinate with the peers to ensure they're not breaking their development environments. When in doubt, `modify` is the safest option, however it mostly requires a dedicated application deployment for each developer.


## Installation

Apply the Kopf CRD

`kubectl apply -f https://github.com/nolar/kopf/raw/main/peering.yaml`

Apply the DevEnv CRD

`kubectl apply -f operator/crd.yaml`

Install the operator chart

`helm upgrade --install remote-development-operator operator/chart`

## Create new DevEnv

Once the operator is installed, you can start creating DevEnvs. Copy examples/devenv.yaml to my-devenv.yaml and edit my-devenv.yaml, updating the following properties under the `spec` section according to your needs:

| Property      | Description |
| ----------- | ----------- |
| mode | Can be `clone` or `modify`. |
| baseDomain | The base domain name for the devenvs. e.g. dev.nativeedge.dell.com. |
| port | The port of the target resource to be exposed over HTTPS when using the `clone` mode. |
| image | The docker image for the devenv. You can leave the default value here. |
| albGroupName | The ALB group name that will be assigned to the ingress, when using `clone` mode on Amazon EKS. |
| authorizedKeys| A list of public SSH keys authorized to access the SSH server as the `docker` user. |
| mounts | A list of mounts |
| excludedPaths | The repository paths to be excluded from syncing. |
| reloadSignal | The UNIX signal that will force the target resource to reload its code. Can be `TERM` or `HUP`. |
| postMountPodCmd | A command to run on the pod of the target resource after mounting the code PVC. |
||

After you save `my-devenv.yaml` with the appropriate, apply it to create the new __DevEnv__.

`kubectl apply -f my-devenv.yaml`

To see the status of the new __DevEnv__ run the following command, replacing `mydevenv` with the name you specified in `my-devenv.yaml`.

`kubectl get devenv mydevenv`

## IDE configuration

Once the new DevEnv has been created, you can get the command that should run on every file save. The following command uses jq to parse the __DevEnv__ in JSON format and select the command from the status.

`kubectl get devenv mydevenv -o json| jq ".[].status.create_update_dev_env.cmd"`


Once you have the command, then configure the respective setting on your IDE. For VSCode you can install a plugin like [emeraldwalk.runonsave](https://github.com/emeraldwalk/vscode-runonsave).


## Contributing

We appreciate feedback and contribution to this project! Before you get started, please see the [Contributors guidelines](CONTRIBUTING.md).

## License

This repo is covered under [Apache License 2.0](LICENSE).
