#!/usr/bin/env bash
set -euo pipefail

bundle_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
policy_file="${PROTECTED_PATHS_FILE:-${bundle_root}/policies/protected-paths.txt}"
base_ref="${BASE_REF:-origin/main}"

if [[ "${TRUSTED_ALLOW_PROTECTED_PATHS_CHANGE:-0}" == "1" ]]; then
  echo "Protected-path gate bypassed by trusted CI context."
  exit 0
fi

git rev-parse --verify "${base_ref}^{commit}" >/dev/null
mapfile -t changed_paths < <(git diff --name-only --diff-filter=ACMRT "${base_ref}...HEAD")

violations=()
for path in "${changed_paths[@]}"; do
  while IFS= read -r pattern; do
    [[ -z "${pattern}" || "${pattern}" == \#* ]] && continue
    if [[ "${path}" == ${pattern} ]]; then
      violations+=("${path} (matches ${pattern})")
      break
    fi
  done < "${policy_file}"
done

if (( ${#violations[@]} > 0 )); then
  echo "Protected paths changed; this PR requires the separate trusted platform workflow:" >&2
  printf '  - %s\n' "${violations[@]}" >&2
  exit 42
fi

echo "No protected paths changed relative to ${base_ref}."
