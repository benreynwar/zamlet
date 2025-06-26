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
        clang \
        # Java for Bazel and Scala
        openjdk-11-jdk \
        # Python and pip
        python3 \
        python3-pip \
        python3-venv \
        python3-dev \
        # Node.js and npm for Claude Code
        nodejs \
        npm \
        # Dependencies for building Verilator
        autoconf \
        help2man \
        perl \
        flex \
        bison \
        ccache \
        libgoogle-perftools-dev \
        numactl \
        perl-doc \
        # Additional tools
        make \
        g++ \
        tmux \
        vim \
        locales \
        # Docker client for Docker-in-Docker
        ca-certificates \
        gnupg \
        lsb-release \
        time \
        && rm -rf /var/lib/apt/lists/*

# Install Docker CLI
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | tee /etc/apt/sources.list.d/docker.list > /dev/null && \
    apt-get update && \
    apt-get install -y docker-ce-cli && \
    rm -rf /var/lib/apt/lists/*

# Set Java environment
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV PATH="${JAVA_HOME}/bin:${PATH}"

# Install Bazelisk (wrapper that manages Bazel versions)
RUN curl -Lo /usr/local/bin/bazel https://github.com/bazelbuild/bazelisk/releases/latest/download/bazelisk-linux-amd64 && \
    chmod +x /usr/local/bin/bazel

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

# Install Python 3.13 for bazel-orfs compatibility  
RUN apt-get update && \
    apt-get install -y software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y python3.13 python3.13-venv python3.13-dev && \
    rm -rf /var/lib/apt/lists/*

# Create Python virtual environment for Bazel using Python 3.13
RUN python3.13 -m venv /opt/python-venv && \
    /opt/python-venv/bin/pip install --upgrade pip && \
    /opt/python-venv/bin/pip install git+https://github.com/cocotb/cocotb.git
    /opt/python-venv/bin/pip install yaml matplotlib

# Install claude-code CLI
RUN npm install -g @anthropic-ai/claude-code

# Set working directory
WORKDIR /workspace

# Configure locale
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
RUN locale-gen en_US.UTF-8

# Keep container running
CMD ["tail", "-f", "/dev/null"]
