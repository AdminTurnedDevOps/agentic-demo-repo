## Setup

Add moat binaries to your PATH so commands work from any directory:

```bash
# Add to ~/.zshrc or ~/.bashrc
export PATH="/Users/michaellevan/gitrepos/moat/target/debug:$PATH"

# Reload your shell
source ~/.zshrc
```

Verify the binaries are accessible:
```bash
which moat moatctl moat-mcp
```

## Run moat

1. Install host prerequisites:
```
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh

source ~/.cargo/env 

which cargo
```

```
brew tap slp/krun
```

```
brew install libkrun libkrunfw zig
```

```
cargo install cargo-zigbuild
```

```
brew install protobuf
```

2. Build moat for macOS and moat-worker for the Linux guest:
```
cd /Users/michaellevan/gitrepos/moat
```

```
make build
```

```
rustup target add aarch64-unknown-linux-musl
make build-worker
```

3. Sign the moat binary with the Hypervisor entitlement:

codesign --sign - --entitlements Formula/entitlements.plist --force target/debug/moat

4. Create the VM Rootfs The libkrun backend needs a Linux root filesystem for the guest VM. This downloads Alpine Linux and installs the moat-worker binary into it.
```
./scripts/build-krun-rootfs.sh ~/.local/state/moat/krun-rootfs
```

## Build Sandbox

5. Run the Server

Default: port 8080, 10 slots
```
# The binary needs to be signed with the Hypervisor entitlement for libkrun.
codesign --sign - --entitlements Formula/entitlements.plist --force ./target/debug/moat && ./target/debug/moat serve --port 8080 --slots 12
```

6. Build the CLI binary to run locally

```
cargo build -p moatctl
```

7. Test It. In another terminal, create a sandbox:
```
echo '{}' | ./target/debug/moatctl sandbox create -
```

![](../images/sandbox.gif)