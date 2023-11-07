FROM python:3.11-slim-bookworm
COPY ./requirements.txt /opt/requirements.txt
RUN pip install --no-cache-dir -r /opt/requirements.txt
COPY ./operator /opt/operator
ENTRYPOINT [ "kopf", "run", "/opt/operator/op.py", "--verbose", "--debug" ]
