# Download Windhover (macOS)

## Direct download (recommended)

Apple Silicon DMG (stable URL — always the latest GitHub Release asset):

**https://github.com/cliclye/Kestrel/releases/latest/download/Windhover-macOS-arm64.dmg**

Browse releases: https://github.com/cliclye/Kestrel/releases/latest

> The GitHub repository is still named `Kestrel`; the product is **Windhover**.

### Install

1. Download `Windhover-macOS-arm64.dmg`
2. Open it and drag **Windhover** into Applications
3. Launch Windhover from Applications / Launchpad

### First launch — Gatekeeper (unsigned builds)

CI ships an **unsigned** DMG until Apple Developer signing + notarization secrets are configured. On first open macOS may say the app “cannot be opened because it is from an unidentified developer.”

Allow it once using any of:

- Right-click **Windhover** → **Open** → **Open**
- **System Settings → Privacy & Security** → **Open Anyway**
- Terminal: `xattr -cr /Applications/Windhover.app`

This is expected for unsigned community builds, not a malware warning from Windhover itself.

### Requirements

- macOS 12+
- Apple Silicon (M1 / M2 / M3 / M4) — primary supported target

Intel Macs: build from source for now (see README).

---

## Cut a release (maintainers)

1. Ensure `desktop/src-tauri/tauri.conf.json` `version` matches the tag you want (e.g. `0.1.0`).
2. Push a tag from `main` (or merge to `main` first):

   ```bash
   git tag v0.1.0
   git push origin v0.1.0
   ```

3. GitHub Actions workflow **Release macOS** builds the DMG and attaches
   `Windhover-macOS-arm64.dmg` to the release for that tag.
4. Confirm the stable latest URL works:

   ```bash
   curl -sI https://github.com/cliclye/Kestrel/releases/latest/download/Windhover-macOS-arm64.dmg | head
   ```

Manual dry-run (artifact only, no Release): **Actions → Release macOS → Run workflow**.

### Optional: signing / notarization

To ship Gatekeeper-clean builds, add Apple Developer secrets (`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_PASSWORD`, `APPLE_TEAM_ID`) and wire them into the workflow (see [Tauri signing docs](https://v2.tauri.app/distribute/sign-macos/)). Until then, keep the Gatekeeper notes above honest and visible.

---

## Build from source

```bash
./windhover build
cd app && npm ci && npm run build && cd ..
cd desktop && cargo tauri build --bundles app,dmg
open src-tauri/target/release/bundle/macos/Windhover.app
```

See [`desktop/README.md`](../desktop/README.md).
