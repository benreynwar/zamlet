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
        # For OpenRAM
        git \
        make \
        build-essential \
        ngspice \
        netgen-lvs \
        iverilog \
        libreadline-dev \
        tcl-dev \
        tk-dev \
        # Magic build dependencies (for OpenRAM) \
        m4 \
        csh \
        libx11-dev \
        libcairo2-dev \
        # Development tools \
        vim \
        tmux \
        && rm -rf /var/lib/apt/lists/*

# Build Magic 8.3.363 to match OpenRAM's conda version
RUN git clone git://opencircuitdesign.com/magic /tmp/magic \
    && cd /tmp/magic \
    && git checkout 8.3.363 \
    && ./configure \
    && make \
    && make install \
    && rm -rf /tmp/magic

# Create symlink for netgen binary
RUN ln -s /usr/lib/netgen/bin/netgen /usr/local/bin/netgen

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

# Copy requirements file
COPY requirements.txt /tmp/requirements.txt

# Create Python virtual environment for Bazel using Python 3.13
RUN python3.13 -m venv /opt/python-venv && \
    /opt/python-venv/bin/pip install --upgrade pip && \
    /opt/python-venv/bin/pip install -r /tmp/requirements.txt

# Clone OpenRAM from git repository and install it
WORKDIR /opt
RUN git clone https://github.com/VLSIDA/OpenRAM.git /opt/OpenRAM
RUN cd /opt/OpenRAM && /opt/python-venv/bin/pip install .
# Install Sky130 PDK (for OpenRAM)
RUN . /opt/python-venv/bin/activate && volare enable --pdk sky130 e8294524e5f67c533c5d0c3afa0bcc5b2a5fa066 --pdk-root /opt/pdk
# Install skywater-pdk repository (required by sky130-install) (for OpenRAM)
RUN . /opt/python-venv/bin/activate && cd /opt/OpenRAM && PDK_ROOT=/opt/pdk make sky130-pdk
# Install SRAM libraries (for OpenRAM)
RUN . /opt/python-venv/bin/activate && cd /opt/OpenRAM && PDK_ROOT=/opt/pdk make sky130-install
# Set up OpenRAM environment variables
ENV OPENRAM_HOME=/opt/OpenRAM/compiler
ENV OPENRAM_TECH=/opt/OpenRAM/technology
ENV PDK_ROOT=/opt/pdk
# Disable conda installation in OpenRAM
ENV OPENRAM_DISABLE_CONDA=1

# Set working directory
WORKDIR /workspace

# Configure locale
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
RUN locale-gen en_US.UTF-8

# Auto-activate Python virtual environment for interactive shells
RUN echo 'source /opt/python-venv/bin/activate' >> /root/.bashrc

# Keep container running
CMD ["tail", "-f", "/dev/null"]
