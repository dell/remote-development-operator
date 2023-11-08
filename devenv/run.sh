#!/bin/bash
export > $HOME/.bashrc
echo 'source <(kubectl completion bash)
alias k=kubectl
complete -F __start_kubectl k
' >> $HOME/.bashrc
echo -e $authorized_keys > $HOME/.ssh/authorized_keys
chown -R docker /home/docker
/usr/sbin/sshd -D
