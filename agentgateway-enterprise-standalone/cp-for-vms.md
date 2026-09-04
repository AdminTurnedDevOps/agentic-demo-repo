This guide will show how to install an agw ee standalone control plane on a VM or laptop/desktop

## One VM/laptop

### Install

On the VM, do the following

1. Set the appropriate env vars to set the license key and pull down the latest binary:

```
export ENTERPRISE_INSTALL_URL='https://storage.googleapis.com/enterprise-agentgateway-public-nonprod/install.sh'
export AGENTGATEWAY_VERSION='v2026.9.0-nightly-260904'
export ENTERPRISE_AGENTGATEWAY_LICENSE_KEY='<license-key>'
```

```
curl -fsSL "$ENTERPRISE_INSTALL_URL" | sh
```


2. Check that the binary is downloaded and usable

```
export PATH="$HOME/.agentgateway/bin:$PATH"
agentgateway --version
```

3. Run agentgateway

```
agentgateway
```

By default a config file will be generated for you. For example, the below:

```
loaded config from File("/Users/michaellevan/.config/agentgateway/config.yaml")
```

### Configuration

1. Look in `~/.config/agentgateway`. You'll see that agentgateway, when you run it, creates a config file. You can use that for testing purposes to run agentgateway.

```
agentgateway -f ~/.config/agentgateway/config.yaml
```

## High Availability

Because this section is for HA, doing this on your laptop won't be production-ready
