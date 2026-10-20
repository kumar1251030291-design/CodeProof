FROM python:3.12-alpine@sha256:1b668429b3511ab407d8e00648891631b0b1a4d7e15e3ca70f38ab5b91ad4ab4

RUN apk add --no-cache gcc musl-dev \
    && addgroup -S -g 10001 runner \
    && adduser -S -D -H -u 10001 -G runner runner

COPY runner.py /opt/codeproof/runner.py
RUN chmod 0555 /opt/codeproof/runner.py
USER 10001:10001
WORKDIR /workspace
ENTRYPOINT ["python", "/opt/codeproof/runner.py"]
