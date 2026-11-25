#!/usr/bin/env bash
set -euo pipefail
cd /tmp/drawing-cad
export PYTHONPATH="$PWD/packages${PYTHONPATH:+:$PYTHONPATH}"
export LD_LIBRARY_PATH="$PWD/gl/usr/lib/$(python3 -c 'import sysconfig; print(sysconfig.get_config_var("MULTIARCH"))')${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
if ! python3 -c 'from OCP.STEPControl import STEPControl_Reader' 2>/dev/null; then
  [[ -d "$PWD/packages/OCP" ]] || python3 -m pip install --no-cache-dir --target "$PWD/packages" 'cadquery-ocp-novtk==7.9.3.1.1'
  if ! python3 -c 'from OCP.STEPControl import STEPControl_Reader' 2>/dev/null; then
    mkdir -p apt/lists/partial apt/cache/archives/partial gl
    opts=(-o "Dir::State::lists=$PWD/apt/lists" -o "Dir::Cache=$PWD/apt/cache")
    apt-get "${opts[@]}" update
    apt-get "${opts[@]}" download libgl1 libglx0 libglvnd0
    for f in ./*.deb; do dpkg-deb -x "$f" gl; done
    rm -rf apt ./*.deb
  fi
fi
python3 -c 'from OCP.STEPControl import STEPControl_Reader'
printf 'export PYTHONPATH=%q\nexport LD_LIBRARY_PATH=%q\n' "$PYTHONPATH" "$LD_LIBRARY_PATH" > env.sh
