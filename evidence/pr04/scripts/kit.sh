#!/usr/bin/env bash
# Закрепить ревизию course kit для ПР04: узнать текущую ревизию через /api/course-kit, скачать её
# неизменяемый архив, сверить SHA-256, распаковать в .course-kit/, проверить манифест pr04.json и
# прописать ту же ревизию в .github/workflows/ci.yml и evidence/pr04/report.json.
# Запуск из корня репозитория до коммита реализации:  bash evidence/pr04/scripts/kit.sh
# Повторный запуск безопасен: архив скачивается заново, файлы перезаписываются той же ревизией.
set -euo pipefail

BASE=${KIT_BASE:-https://ros.lms.ci.nsu.ru}   # KIT_BASE — только для проверки скрипта
CI=.github/workflows/ci.yml
REPORT=evidence/pr04/report.json
[ -f "$CI" ] && [ -f "$REPORT" ] || { echo "запускать из корня репозитория" >&2; exit 2; }

echo "запрос $BASE/api/course-kit (сайт бывает медленным, ждать до минуты)"
INFO=$(curl -fsS --retry 3 --retry-delay 5 --max-time 60 "$BASE/api/course-kit")
read -r VERSION ARCHIVE SHA < <(python3 -c '
import json, sys
info = json.loads(sys.argv[1])
print(info["version"], info["archive"], info["sha256"])' "$INFO")
case "$ARCHIVE" in
    http*) URL=$ARCHIVE ;;
    /*) URL=$BASE$ARCHIVE ;;
    *) URL=$BASE/$ARCHIVE ;;
esac
echo "ревизия $VERSION, архив $URL"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
curl -fL --retry 3 --retry-delay 5 --max-time 300 -o "$TMP/kit.tar.gz" "$URL"
printf '%s  %s\n' "$SHA" "$TMP/kit.tar.gz" | sha256sum -c -

rm -rf .course-kit
mkdir -p .course-kit
tar -xzf "$TMP/kit.tar.gz" -C .course-kit
[ "$(cat .course-kit/v1/VERSION)" = "$VERSION" ] || { echo "VERSION в архиве не $VERSION" >&2; exit 1; }
echo "манифест ПР04:"
cat .course-kit/v1/practices/manifests/pr04.json

python3 - "$URL" "$SHA" "$VERSION" <<'PYCODE'
import json
import re
import sys
from pathlib import Path

url, sha, version = sys.argv[1:]
ci = Path('.github/workflows/ci.yml')
text = ci.read_text(encoding='utf-8')
text, n_url = re.subn(r'(COURSE_KIT_URL: ).*', lambda m: m.group(1) + url, text)
text, n_sha = re.subn(r'(COURSE_KIT_SHA256: ).*', lambda m: m.group(1) + sha, text)
assert n_url == 1 and n_sha == 1, 'в ci.yml не найдены COURSE_KIT_URL / COURSE_KIT_SHA256'
ci.write_text(text, encoding='utf-8')

path = Path('evidence/pr04/report.json')
report = json.loads(path.read_text(encoding='utf-8'))
report['course_kit'] = {'version': version, 'archive_sha256': sha}
path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'ci.yml и report.json: {version}, {sha}')
PYCODE
