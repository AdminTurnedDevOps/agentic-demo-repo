#!/bin/sh
set -eu

result_dir=/run/gpu-demo
result_file=${result_dir}/probe-result.txt
temporary_result=${result_dir}/probe-result.tmp

mkdir -p "${result_dir}"

if ! /usr/local/bin/cuda-probe >"${temporary_result}" 2>&1; then
  cat "${temporary_result}" >&2
  exit 1
fi

mv "${temporary_result}" "${result_file}"
cat "${result_file}"

# The long-running process must not link to CUDA or retain a CUDA context.
exec /usr/local/bin/status-server "${result_file}"
