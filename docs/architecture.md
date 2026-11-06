# Architecture

## Summary

Two programs that never run at the same time. The gallery (`artd`) stays offline: it
never touches the network, it only reads a local catalogue and images and writes its own
state. A separate sync script (`art/artsync.sh`) is the only thing that goes online. It
runs only on demand, from a library item (**2. Actualizar galería**), with the
gallery stopped and the Kindle UI managing Wi-Fi. It asks GitHub for the catalogue,
downloads what changed, verifies it, and installs it. Only content is synced, never code
(code still goes through `tools/deploy.py`).

```
 GitHub (public repo)                      Kindle
 ---------------------                     ------
 content/catalog.tsv      HTTPS            library item -> artsync.sh -> /mnt/us/art/content
 content/panels/...     ───────────────>   gallery (artd), later, reads content/ offline
```

## Why split them

The gallery is the part that must never fail, and it has no network code at all.
Keeping it that way means a bad connection, a slow download, an expired certificate or
a broken catalogue can never stop the pictures. The sync is allowed to fail: it leaves
the current content untouched and can simply be run again. It also keeps power use
simple, since Wi-Fi is only on during a sync.

## The content repo

This repo, or a fork of it (the device's `REPO=` setting). `content/works/<collection>.json` is the recipe, `content/build.py` turns it
into panels (`content/panels/<collection>/<id>.png`, committed) and
`content/catalog.tsv` (id, collection, file, sha256, title, artist, date), the contract
with the device. Originals are committed too, so rebuilds never depend on a source
still being online. TSV rather than JSON because Lua 5.1 on the Kindle has no JSON
parser. Publishing panels elsewhere (Pages, releases) would keep git history smaller, but
new images are rare.

Collections (`content/collections.tsv`) group works by period or medium, one works file each in
`content/works/`. The repo must be public: the device downloads from it without a
token.

## On the Kindle

```
/mnt/us/art/
  content/            catalog.tsv collections.tsv images/<collection>/<id>.png
  content.incoming/   staging, only during a sync
  content-version     commit the content came from
  sync.log
  config, state       the gallery's settings and place, keyed by collection and work id
```

## artsync

A shell script, started detached by the library item. Steps:

1. Refuse to run if the gallery is running. Keep the Kindle awake; turn Wi-Fi on if it
   is off and wait up to 60 s for a connection.
2. Ask the GitHub API for the latest commit on `main` (one unauthenticated call; the
   limit is 60 an hour), then fetch `catalog.tsv` and `collections.tsv` at that commit
   from `raw.githubusercontent.com` into `content.incoming/`. Pinning the commit means
   a push during a sync cannot mix two versions.
3. Hash the panels on the device and compare with the catalogue, so missing, changed
   and damaged files are all found. Download those, each checked against its sha256.
4. Only when everything is downloaded: move the panels into `content/` (renames on the
   same filesystem), then the catalogue, then delete panels no longer listed.
5. Restore Wi-Fi as it was, show the result at the bottom of the screen, log to
   `sync.log`.

Any failure before step 4 leaves the content exactly as it was. Step 4 takes seconds; if
it is interrupted, the next sync repairs it, since it compares actual files. A full
download of about 320 panels takes a few minutes; a check with nothing to download takes
about 25 seconds on the Kindle, mostly hashing.

## Ideas not built

Quiet hours (no changes at night, which would also let the Kindle hibernate), favourites
and hiding works, and a description page for the current work.

## Not now: code updates

The same channel could update the app itself, but a broken update would break the frame
remotely, with nobody nearby who can repair it. If it is ever wanted: signed bundles, a
kept previous version, and automatic rollback when the new one does not run for a few
minutes. Until then, code changes are installed by hand with `tools/deploy.py`.
