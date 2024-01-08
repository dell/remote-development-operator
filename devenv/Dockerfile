FROM amaas-eos-mw1.cec.lab.emc.com:5070/python:3-bullseye
ENV USER=docker
RUN useradd -ms /bin/bash $USER
ENV HOME /home/$USER
USER root
# RUN adduser $USER
RUN apt-get update && apt-get install jq curl fuse sudo sed apt-utils vim openssh-server gzip git rsync -y
RUN curl -LO https://storage.googleapis.com/kubernetes-release/release/`curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt`/bin/linux/amd64/kubectl && \
      chmod +x ./kubectl && \
      mv ./kubectl /usr/local/bin/kubectl && \
      curl -LO https://get.helm.sh/helm-v3.13.0-linux-amd64.tar.gz && tar -zxvf helm-v3.13.0-linux-amd64.tar.gz && mv linux-amd64/helm /usr/local/bin/helm && \
      rm -rf helm-v3.13.0-linux-amd64.tar.gz linux-amd

RUN ssh-keygen -A && mkdir -p /run/sshd
RUN usermod -aG sudo $USER && echo '%sudo ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers && touch /home/$USER/.sudo_as_admin_successful
RUN echo "$USER:$USER" |chpasswd
RUN mkdir $HOME/.ssh/ $HOME/scripts
RUN chown -R $USER:$USER $HOME/.ssh
COPY run.sh /
COPY scripts/ $HOME/scripts
RUN chmod 755 /run.sh $HOME/scripts

USER $USER
RUN mkdir -p $HOME/app
WORKDIR $HOME
COPY *.py $HOME/app/
COPY *.txt $HOME/app/
COPY .bashrc $HOME
COPY .vimrc $HOME
RUN echo building as $(whoami)
RUN echo $(which python)
ENV PATH=$HOME/.local/bin:$PATH
COPY requirements.txt $HOME
RUN /usr/local/bin/python -m pip install --disable-pip-version-check --upgrade pip && pip install -r requirements.txt
USER root
RUN sed -i 's/#PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config
EXPOSE 22
ENTRYPOINT ["/run.sh"]
