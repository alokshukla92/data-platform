FROM jenkins/jenkins:lts-jdk17

USER root
# Docker CLI so declarative pipelines can build/push images through the mounted
# host Docker socket (Jenkins-as-CI; no DinD daemon inside the container).
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker.io \
    && rm -rf /var/lib/apt/lists/*

# Pre-install the plugins the Jenkinsfile needs so the controller comes up ready.
COPY plugins.txt /usr/share/jenkins/ref/plugins.txt
RUN jenkins-plugin-cli --plugin-file /usr/share/jenkins/ref/plugins.txt

USER jenkins
