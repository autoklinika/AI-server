FROM node@sha256:a6155384446670e9719bdc4fd0ebe4d4b29fb32a8d6aa523da3547a6cfbcf22c
RUN apt-get update && apt-get install -y --no-install-recommends openjdk-21-jdk-headless procps ca-certificates curl unzip gcc libc6-dev python3 && rm -rf /var/lib/apt/lists/*
RUN curl --fail --location --retry 3 -o /tmp/ghidra.zip https://github.com/NationalSecurityAgency/ghidra/releases/download/Ghidra_12.1.4_build/ghidra_12.1.4_PUBLIC_20260921.zip && echo "ddac49f903da9d5bac833e5cc79395098b9c33cfd3279be5f31bd00387d2d4db  /tmp/ghidra.zip" | sha256sum -c - && unzip -q /tmp/ghidra.zip -d /opt && rm /tmp/ghidra.zip
RUN npm install --prefix /opt/rea --save-exact --ignore-scripts --omit=optional rea-agents@6.7.0 && npm cache clean --force
ENV GHIDRA_INSTALL_DIR=/opt/ghidra_12.1.4_PUBLIC JAVA_HOME=/usr/lib/jvm/java-21-openjdk-amd64 HOME=/home/node GHIDRA_HEADLESS_MAXMEM=2G REA_ANALYSIS_PROVIDER=ghidra
ENV PATH=/opt/rea/node_modules/.bin:${PATH}
COPY fixture.c /opt/fixture.c
RUN mkdir /opt/fixtures && gcc -O0 -g -fno-pie -no-pie /opt/fixture.c -o /opt/fixtures/ecu_demo && gcc -O0 -s -fno-pie -no-pie /opt/fixture.c -o /opt/fixtures/ecu_demo_stripped
USER 1000:1000
WORKDIR /work
ENTRYPOINT ["rea"]
