#!/bin/sh
# Update the gallery's content from the public GitHub repo (no token). Run on demand from the
# library ("2. Actualizar galería") while the Kindle UI is up, never with the gallery
# running: the gallery stays offline. Downloads only new or changed panels, checks
# each against the catalogue's sha256, and only touches content/ once everything is
# downloaded. A failure leaves the current content as it was.
# Desktop tests: ART_DIR=<dir> sh artsync.sh

DIR=${ART_DIR:-/mnt/us/art}
# GitHub repo to sync from: REPO=owner/name in the gallery's config, or this one
REPO=${ART_REPO:-$(sed -n 's/^REPO=//p' "$DIR/config" 2>/dev/null)}
REPO=${REPO:-ichinaski/kindle-art-gallery}
BRANCH=${ART_BRANCH:-main}
CONTENT=$DIR/content
INCOMING=$DIR/content.incoming   # staging, same filesystem as content/ (renames)
VERSION=$DIR/content-version     # commit the content came from
LOG=$DIR/sync.log
FBINK=/mnt/us/libkh/bin/fbink
API=https://api.github.com/repos/$REPO      # one call: the latest commit
RAW=https://raw.githubusercontent.com/$REPO # files at that commit (no rate limit)

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') $*" >>"$LOG"; }

# one line near the bottom of the screen (and in the log); -m -p centres it and pads
# the rest of the line with blanks, covering the previous one
say() {
  log "$1"
  if [ -x "$FBINK" ]; then $FBINK -q -m -p -y -5 "$1" >/dev/null 2>&1; else echo "$1"; fi
}

has_lipc() { command -v lipc-set-prop >/dev/null 2>&1; }

WIFI_BEFORE=
finish() {
  rm -rf "$INCOMING"
  if has_lipc; then
    [ "$WIFI_BEFORE" = "0" ] && lipc-set-prop com.lab126.cmd wirelessEnable 0 >/dev/null 2>&1
    lipc-set-prop com.lab126.powerd preventScreenSaver 0 >/dev/null 2>&1
  fi
}

fail() {
  say "$1"
  finish
  exit 1
}

get() { # get <repo path> <output file>: one file at the synced commit
  curl -sfL --retry 3 --retry-delay 5 --connect-timeout 20 --max-time 300 \
    -o "$2" "$RAW/$SHA/$1"
}

: >"$LOG"
log "artsync starting ($REPO, $BRANCH)"

if [ -f /tmp/art-gallery.pid ] && kill -0 "$(cat /tmp/art-gallery.pid)" 2>/dev/null; then
  say "La galeria esta en marcha: sal de ella primero"
  exit 1
fi

# keep the Kindle awake and online for the whole sync
if has_lipc; then
  lipc-set-prop com.lab126.powerd preventScreenSaver 1 >/dev/null 2>&1
  WIFI_BEFORE=$(lipc-get-prop com.lab126.cmd wirelessEnable 2>/dev/null)
  if [ "$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)" != "CONNECTED" ]; then
    say "Conectando a la wifi..."
    lipc-set-prop com.lab126.cmd wirelessEnable 1 >/dev/null 2>&1
    n=0
    while [ "$(lipc-get-prop com.lab126.wifid cmState 2>/dev/null)" != "CONNECTED" ]; do
      n=$((n + 1))
      [ $n -gt 60 ] && fail "Sin conexion wifi. No se ha cambiado nada"
      sleep 1
    done
  fi
fi

say "Buscando novedades..."
SHA=$(curl -sf --retry 3 --retry-delay 5 --connect-timeout 20 --max-time 60 \
  -H "Accept: application/vnd.github.sha" \
  -H "X-GitHub-Api-Version: 2022-11-28" "$API/commits/$BRANCH")
case "$SHA" in
  [0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f][0-9a-f]*) ;;
  *) fail "No se puede contactar con GitHub. No se ha cambiado nada" ;;
esac
log "remote commit $SHA"

rm -rf "$INCOMING"
mkdir -p "$INCOMING" "$CONTENT/images" || fail "No se puede escribir en $DIR"
get content/catalog.tsv "$INCOMING/catalog.tsv" &&
  get content/collections.tsv "$INCOMING/collections.tsv" ||
  fail "No se puede descargar el catalogo. No se ha cambiado nada"
grep -q "^# id" "$INCOMING/catalog.tsv" && [ "$(grep -vc '^#' "$INCOMING/catalog.tsv")" -gt 0 ] ||
  fail "Catalogo no valido. No se ha cambiado nada"

# what is missing or different: compare the actual files, so damaged ones get fixed
say "Comprobando las obras..."
TAB=$(printf '\t')
( cd "$CONTENT/images" && for f in */*.png; do [ -f "$f" ] && sha256sum "$f"; done ) \
  >"$INCOMING/have" 2>/dev/null
grep -v '^#' "$INCOMING/catalog.tsv" | cut -f3,4 | while IFS="$TAB" read -r file sum; do
  grep -q "^$sum  $file\$" "$INCOMING/have" || echo "$file $sum"
done >"$INCOMING/need"
total=$(wc -l <"$INCOMING/need" | tr -d ' ')
log "$total panels to download"

i=0
while read -r file sum; do
  i=$((i + 1))
  say "Descargando $i/$total"
  mkdir -p "$INCOMING/images/$(dirname "$file")"
  get "content/panels/$file" "$INCOMING/images/$file" ||
    fail "Error al descargar $file. No se ha cambiado nada"
  got=$(sha256sum "$INCOMING/images/$file" | cut -d' ' -f1)
  [ "$got" = "$sum" ] || fail "Archivo danado: $file. No se ha cambiado nada"
done <"$INCOMING/need"

# every file is here and verified: free space was enough, now move them in (renames)
log "installing"
while read -r file sum; do
  mkdir -p "$CONTENT/images/$(dirname "$file")"
  mv -f "$INCOMING/images/$file" "$CONTENT/images/$file" || fail "Error al instalar $file"
done <"$INCOMING/need"
mv -f "$INCOMING/collections.tsv" "$CONTENT/collections.tsv" &&
  mv -f "$INCOMING/catalog.tsv" "$CONTENT/catalog.tsv" || fail "Error al instalar el catalogo"

# panels no longer in the catalogue
grep -v '^#' "$CONTENT/catalog.tsv" | cut -f3 | sort >"$INCOMING/keep"
removed=0
for f in $(cut -d' ' -f3 "$INCOMING/have" | grep -vxF -f "$INCOMING/keep"); do
  rm -f "$CONTENT/images/$f" && removed=$((removed + 1))
done
for d in "$CONTENT"/images/*/; do rmdir "$d" 2>/dev/null; done
echo "$SHA" >"$VERSION"

works=$(grep -vc '^#' "$CONTENT/catalog.tsv")
log "done: $total downloaded, $removed removed, $works works"
if [ "$total" = 0 ] && [ "$removed" = 0 ]; then
  say "Ya esta al dia ($works obras)"
else
  say "Actualizada: $total nuevas, $removed quitadas ($works obras)"
fi
finish
exit 0
