FROM mcr.microsoft.com/devcontainers/python:1-3.12-bookworm

# The image lists Yarn's apt repository, whose signing key has expired, so every `apt-get update`
# fails (and with it the Docker feature's install). Ops Signals uses npm, not Yarn.
RUN rm -f /etc/apt/sources.list.d/yarn.list
