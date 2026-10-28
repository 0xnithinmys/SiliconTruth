# The verification container, as a plain Docker image.
#
# Same recipe as modal_app.py's _image(), minus the Rust half: this one exists
# to run the compile-and-emulate gate on a machine that has Docker and nothing
# else. Modal remains the hosted path; this is the one that needs no account.
#
# Two notes carried over from modal_app.py, both of which cost real time if
# ignored:
#
#  * Renode comes from the portable tarball, not from apt. The packaged build
#    pulls a large Mono dependency tree and has repeatedly been a time sink;
#    the portable tarball is self-contained and pinned by URL here.
#  * Renode must run with --disable-xwt. Without it, it tries to open a GUI,
#    finds no display, and hangs rather than failing, which looks exactly like
#    a slow test until the timeout.
FROM debian:bookworm-slim

ARG RENODE_VERSION=1.15.3

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        xz-utils \
        gcc-arm-none-eabi \
        binutils-arm-none-eabi \
        libnewlib-arm-none-eabi \
        python3 \
        python3-pip \
        # Renode's portable build still needs these present even though it
        # ships its own runtime.
        libicu72 \
        libgtk2.0-0 \
        screen \
        policykit-1 \
        sigrok-cli \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p /opt/renode \
    && curl -fsSL "https://github.com/renode/renode/releases/download/v${RENODE_VERSION}/renode-${RENODE_VERSION}.linux-portable.tar.gz" \
        -o /tmp/renode.tar.gz \
    && tar -xzf /tmp/renode.tar.gz -C /opt/renode --strip-components=1 \
    && rm /tmp/renode.tar.gz \
    && test -x /opt/renode/renode

ENV PATH="/opt/renode:${PATH}"
WORKDIR /work
