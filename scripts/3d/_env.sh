#!/bin/bash
# Run Blender-python (headless, via bpy) without triggering bpy's glog double-init
# that happens when running a .py *file* directly. We exec the file's source
# through `python -c` instead (validated to work reliably).
BPYLIB=$(find /home/user/venv -type d -path '*site-packages/bpy/lib' | head -1)
export LD_LIBRARY_PATH="/home/user/blender_stubs:$BPYLIB"
SCRIPT="$1"
shift
exec /home/user/venv/bin/python -c "
import sys
src = open('$SCRIPT', encoding='utf-8').read()
sys.argv = ['bpy'] + sys.argv[1:]     # argv[1:] = args after the script path
exec(compile(src, '$SCRIPT', 'exec'), {'__name__': '__main__', '__file__': '$SCRIPT'})
" "$@"
