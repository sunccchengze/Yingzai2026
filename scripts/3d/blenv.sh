#!/usr/bin/env bash
# 无头 bpy 运行环境（沙箱内 apt 源不可达时的自愈方案）
# 用法: source scripts/3d/blenv.sh && python3 scripts/3d/build_xiaoying_v2.py
# bpy 轮子链接了若干 X11/GL 库，但离屏(Cycles/EEVEE-Next background)渲染不会调用它们，
# 因此用极小的桩库满足动态链接即可。setup_blstub 会在缺失时自动生成。
export BLSTUB_DIR="${BLSTUB_DIR:-$HOME/.blstub}"
export LD_LIBRARY_PATH="$BLSTUB_DIR:$LD_LIBRARY_PATH"
