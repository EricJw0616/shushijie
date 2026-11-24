#!/bin/sh
set -eu

# Mounts survive image rebuilds. Only fill absent defaults, never overwrite edits.
for directory in /app/app/data /app/platform/out /app/platform/library /app/platform/config /app/lexicon /app/书库分类; do
    mkdir -p "$directory"
    if [ "$(id -u)" = 0 ]; then
        chown 10001:10001 "$directory"
    fi
done
for name in config lexicon; do
    if [ "$name" = config ]; then destination=/app/platform/config; else destination=/app/lexicon; fi
    if [ "$(id -u)" = 0 ]; then
        gosu 10001:10001 cp -Rn "/opt/bookworld-defaults/$name/." "$destination/"
    else
        cp -Rn "/opt/bookworld-defaults/$name/." "$destination/"
    fi
done
if [ "$(id -u)" = 0 ]; then
    exec gosu 10001:10001 "$@"
fi
exec "$@"
