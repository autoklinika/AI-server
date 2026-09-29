FROM rocm/pytorch@sha256:96a2fb24dec9896e2f8238178f0c49d0dcc4c7dcc597be09e4564316bd86d191

COPY requirements.txt /tmp/p5-requirements.txt
RUN python3 -m pip install --no-cache-dir --upgrade pip wheel &&     python3 -m pip install --no-cache-dir -r /tmp/p5-requirements.txt

WORKDIR /workspace
