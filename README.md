# skyeckstrom/vhs-decode — automation fork (not the upstream project)

This is a **private-infrastructure automation fork**. It exists only to carry a small stack of
not-yet-merged fixes for an unattended NAS decode pipeline, and to keep a reproducible build branch
current with upstream. **It is not the VHS-Decode project, and it is not where you want to be as a user.**

## Go here instead

- **VHS-Decode — the actual project:** <https://github.com/oyvindln/vhs-decode> (downloads, docs, wiki, issues)
- **LD-Decode — the network root, source of the `lddecode/` code:** <https://github.com/happycube/ld-decode>
- Support & discussion: the VHS-Decode Discord, linked from oyvindln's README.

Please file issues and pull requests against those upstreams, **not here**. Our own fixes are submitted
there too — this fork just carries them locally until they merge.

## What this fork actually is

GitHub allows only one fork per network per account, and this network's root is happycube/ld-decode —
so a single repo serves **both** upstreams (oyvindln/vhs-decode is itself a fork of happycube/ld-decode
and carries its `lddecode/` directory as inherited code). We keep **only** the two branches below; every
inherited upstream branch has been deleted to keep the fork legible.

| Branch | What it is |
|---|---|
| **`vhs_decode-overlay`** *(default)* | upstream `oyvindln:vhs_decode` + our control plane **only**: the [sync CI](.github/workflows/sync-and-rebuild-develop.yml), the two delta manifests ([`develop-deltas.txt`](.github/develop-deltas.txt), [`lddecode-deltas.txt`](.github/lddecode-deltas.txt)), [`FORK.md`](FORK.md), and this README. Reconstructed on top of fresh upstream every sync — it never hand-carries source, so it stays exactly one commit of *config* ahead of upstream. |
| [`develop`](../../tree/develop) | the branch our pipeline builds from: upstream `vhs_decode` + the deltas listed in the two manifests, rebuilt by CI and pinned by SHA downstream. |

In-flight fixes live on short-lived `fix/vhs_decode/<slug>` branches (PR'd to oyvindln, rooted on
`vhs_decode`) and `fix/ld_decode/<slug>` branches (PR'd to happycube, rooted on its `main`); each is
deleted once its PR merges.

The full mechanics — how the two delta manifests drive the `develop` rebuild, and why an ld-decode fix
lingers until oyvindln's next resync — are in **[FORK.md](FORK.md)**. The upstream project's own README
lives at [oyvindln/vhs-decode](https://github.com/oyvindln/vhs-decode).
