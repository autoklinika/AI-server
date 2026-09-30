FROM ai-platform-p5-train:rocm7.2.1-v1
RUN pip install --no-cache-dir "flash-linear-attention[rocm]==0.5.2"
ENV HIP_ARCHITECTURES=gfx1150
RUN pip install --no-cache-dir --no-build-isolation "causal-conv1d==1.7.0"
RUN python3 -c "import torch, fla, causal_conv1d; print('P5_5_KERNELS_READY', torch.__version__, fla.__version__, causal_conv1d.__version__)"
