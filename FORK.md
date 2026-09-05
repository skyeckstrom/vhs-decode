# Fork notes — skyeckstrom/vhs-decode

A maintained automation fork of [oyvindln/vhs-decode](https://github.com/oyvindln/vhs-decode) that
carries a small stack of not-yet-upstreamed fixes for a private NAS decode pipeline, via an
overlay/delta CI. See [README.md](README.md) for the visitor-facing summary; this file is the
mechanics.

## One fork, two upstreams

[happycube/ld-decode](https://github.com/happycube/ld-decode) is the **root** of this fork
network; oyvindln/vhs-decode is itself a fork of it, adding `vhsdecode/`, `cvbsdecode/` etc.
while carrying ld-decode's `lddecode/` directory as **inherited code — not a vendored copy**.
So a bug belongs to whichever upstream owns the file it lives in:

| Code | Owned by | We PR against | Branch rooted on | Manifest |
|---|---|---|---|---|
| `vhsdecode/`, `cvbsdecode/`, … | oyvindln/vhs-decode | oyvindln/vhs-decode | `upstream/vhs_decode` | [`.github/develop-deltas.txt`](.github/develop-deltas.txt) |
| `lddecode/` | happycube/ld-decode | happycube/ld-decode | `upstream_ld/main` | [`.github/lddecode-deltas.txt`](.github/lddecode-deltas.txt) |

**Why one repo serves both:** GitHub allows only **one fork per network per account**, and this
network's root is happycube/ld-decode — so `skyeckstrom/ld-decode` cannot be created. It also
isn't needed: this fork can open PRs directly against happycube/ld-decode (its `source`) from a
branch rooted on `happycube:main`.

**Why `lddecode-deltas.txt` is separate (and deliberately droppable):** oyvindln resyncs from
happycube periodically, so a fix landed at happycube reaches our decodes only after his next
merge. These entries emulate that resync early — carrying the fix into `develop` in the
meantime. Once oyvindln's merge brings it in, deleting the manifest line drops the delta with
no other change. Paths align across the lineages (`lddecode/core.py` is the same path, and the
regions we touch are byte-identical), so the cherry-picks apply cleanly.

## Branches

The names are deliberately explicit. We do **not** use `main`: this network's root
(happycube/ld-decode) uses `main` as *its* default, and our parent oyvindln uses `vhs_decode`, so
a `main` here would be ambiguous — it belonged to neither and confused readers. The default is the
overlay we interface with most.

- **`vhs_decode-overlay`** — *default branch.* Upstream `vhs_decode` + exactly one overlay commit
  carrying **only** our control plane: the sync CI, the two delta manifests, this file, and the
  public `README.md`. It is **reconstructed, never rebased** — each sync lays that fixed fileset
  onto a fresh upstream checkout, and a guard refuses to push if the tree differs from upstream in
  any *other* path. (Rebasing a persisted overlay commit instead can silently carry a stale source
  snapshot forward on every sync; reconstruct-then-guard makes that impossible.) Because the overlay
  is derived, you don't hand-amend it: edit a control-plane file on this branch and the next sync
  re-lays it cleanly.
- **develop** — the deploy branch consumed downstream: upstream `vhs_decode` + each delta in
  `develop-deltas.txt`, then each in `lddecode-deltas.txt`, replayed in order. Pinned by SHA in
  the `vhs-decode-pipeline` Docker build (`docker/Dockerfile` `VHS_DECODE_REF`).
- **`fix/vhs_decode/<slug>`** / **`fix/ld_decode/<slug>`** (+ `feature/<upstream>/<slug>`) — one
  short-lived branch per in-flight upstream PR, deleted once it merges. The `<upstream>` segment
  names the target so lineage is explicit: `vhs_decode/` PRs go to oyvindln (rooted on `vhs_decode`),
  `ld_decode/` PRs go to happycube (rooted on its `main`). `fix/` vs `feature/` follows happycube's
  [CONTRIBUTING.md](CONTRIBUTING.md).

**Only the branches above are kept.** Forking copies *all* of upstream's branches; those inherited
branches are not retained here, so every branch in this repo is unambiguously ours. The two delta
manifests ([`develop-deltas.txt`](.github/develop-deltas.txt),
[`lddecode-deltas.txt`](.github/lddecode-deltas.txt)) are the source of truth for what `develop`
carries. The upstreams themselves are the reference for their code — browse them at
[oyvindln/vhs-decode](https://github.com/oyvindln/vhs-decode) and
[happycube/ld-decode](https://github.com/happycube/ld-decode).

[`.github/workflows/sync-and-rebuild-develop.yml`](.github/workflows/sync-and-rebuild-develop.yml)
rebuilds all of this weekly (and on manual dispatch) and files a tracking issue on any replay conflict.

**What `develop` currently carries is defined entirely by the two manifests** — read them, not this
file. This file is the mechanism; it holds no snapshot of current state (which would only go stale).
