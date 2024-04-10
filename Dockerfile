FROM isgedge.artifactory.cec.lab.emc.com/isgedge-docker-virtual/python:3.11-slim-bookworm

# Install kubectl.
RUN set -x && \
    apt-get update && \
    apt-get install -y curl && \
    release="$(curl -s https://storage.googleapis.com/kubernetes-release/release/stable.txt)" && \
    echo "Will download kubectl $release." && \
    curl -LO https://storage.googleapis.com/kubernetes-release/release/$release/bin/linux/amd64/kubectl && \
    chmod +x kubectl && \
    mv kubectl /usr/local/bin && \
    apt-get remove -y curl && \
    apt-get autoremove -y && \
    apt-get clean

# Install python requirements.
COPY ./requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt

# Add and configure operator.
COPY ./operator /opt/operator
ENTRYPOINT [ "kopf", "run", "/opt/operator/op.py" ]
