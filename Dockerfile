FROM ubuntu:24.04

# Prevent interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Update and install system dependencies
RUN apt-get update -y && \
    apt-get upgrade -y && \
    apt-get install -y \
        # Basic tools
        curl \
        wget \
        git \
        unzip \
        # Build essentials
        build-essential \
        # Java for Mill and Scala
        openjdk-17-jdk \
        # Python and pip
        python3 \
        python3-pip \
        python3-venv \
        # Dependencies for building Verilator
        autoconf \
        help2man \
        perl \
        python3-dev \
        flex \
        bison \
        ccache \
        libgoogle-perftools-dev \
        numactl \
        perl-doc \
        # Additional tools for cocotb
        make \
        g++ \
        && rm -rf /var/lib/apt/lists/*

# Set Java environment
ENV JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Configure ccache for Verilator compilations
ENV CCACHE_DIR=/workspace/.ccache
ENV CCACHE_UMASK=000
RUN mkdir -p /workspace/.ccache && chmod 777 /workspace/.ccache

# Build and install Verilator from source (for cocotb 2.0 compatibility)
RUN git clone https://github.com/verilator/verilator && \
    cd verilator && \
    git checkout v5.028 && \
    autoconf && \
    ./configure --enable-ccache && \
    make -j$(nproc) && \
    make install && \
    cd .. && \
    rm -rf verilator

# Install Python packages
# Use --break-system-packages since this is a container
RUN pip3 install --no-cache-dir --break-system-packages \
    pytest \
    git+https://github.com/cocotb/cocotb.git@master

# Install Node.js and npm for claude-code
RUN apt-get update -y && \
    apt-get install -y nodejs npm && \
    rm -rf /var/lib/apt/lists/*

# Install claude-code CLI
RUN npm install -g @anthropic-ai/claude-code

# Set working directory
WORKDIR /workspace

# Copy mill build files to pre-download dependencies
COPY mill /workspace/mill
COPY .mill-version /workspace/.mill-version
COPY build.mill /workspace/build.mill
COPY .mill-jvm-opts /workspace/.mill-jvm-opts

# Run mill to download dependencies and cache them in the image
RUN chmod +x /workspace/mill && \
    /workspace/mill --version && \
    /workspace/mill show fmvpu.prepareOffline || true

RUN apt-get update -y && \
    apt-get install -y tmux vim && \
    rm -rf /var/lib/apt/lists/*

ENV LANG=C.UTF-8
  ENV LC_ALL=C.UTF-8
  RUN apt-get update && apt-get install -y locales && locale-gen en_US.UTF-8

# Keep container running
CMD ["tail", "-f", "/dev/null"]
