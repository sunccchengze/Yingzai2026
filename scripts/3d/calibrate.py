#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三视图对照校准器：把渲染剪影和官方参考图叠在一起算 IoU，并输出对照图。

渲染用 film_transparent，于是 alpha 通道就是精确剪影；把它按参考图的
包围盒归一化后与参考剪影求交并比，就能量化「像不像」，而不是靠嘴说。

用法:
    source scripts/3d/blenv.sh
    python3 scripts/3d/calibrate.py --preview /tmp/build/preview
"""
from __future__ import annotations

import argparse
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaoying_refs import Refs  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BG = (238, 241, 246)


def alpha_mask(path):
    a = np.array(Image.open(path).convert("RGBA"))
    return a[..., 3] > 110, a


def norm_to(mask, target_shape, ref_mask):
    """把 mask 按各自包围盒缩放对齐到参考图坐标系。"""
    ys, xs = np.nonzero(mask)
    if not len(ys):
        return np.zeros(target_shape, bool)
    crop = mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    rys, rxs = np.nonzero(ref_mask)
    rh = rys.max() - rys.min() + 1
    rw = rxs.max() - rxs.min() + 1
    im = Image.fromarray((crop * 255).astype(np.uint8)).resize((rw, rh), Image.BILINEAR)
    out = np.zeros(target_shape, bool)
    out[rys.min():rys.max() + 1, rxs.min():rxs.max() + 1] = np.array(im) > 127
    return out


def iou(a, b):
    u = (a | b).sum()
    return float((a & b).sum() / u) if u else 0.0


def overlay(ref_mask, got_mask, path):
    """红=参考独有(缺肉)  绿=渲染独有(多肉)  灰=重合。"""
    h, w = ref_mask.shape
    img = np.full((h, w, 3), 255, np.uint8)
    both = ref_mask & got_mask
    only_ref = ref_mask & ~got_mask
    only_got = got_mask & ~ref_mask
    img[both] = (110, 118, 130)
    img[only_ref] = (222, 60, 60)
    img[only_got] = (60, 190, 90)
    Image.fromarray(img).save(path)


def flatten(path, out):
    """把透明渲染压到浅底色上，方便肉眼看白色部分。"""
    im = Image.open(path).convert("RGBA")
    bg = Image.new("RGBA", im.size, (*BG, 255))
    Image.alpha_composite(bg, im).convert("RGB").save(out)


def main(preview_dir, report=True):
    r = Refs()
    views = [("front", r.front), ("side", r.side), ("back", r.back)]
    scores = {}
    for name, vm in views:
        p = os.path.join(preview_dir, f"{name}.png")
        if not os.path.exists(p):
            print(f"  [skip] {p}")
            continue
        got, _ = alpha_mask(p)
        ref = vm.sil
        aligned = norm_to(got, ref.shape, ref)
        s = iou(ref, aligned)
        scores[name] = s
        if report:
            overlay(ref, aligned, os.path.join(preview_dir, f"cmp_{name}.png"))
            flatten(p, os.path.join(preview_dir, f"flat_{name}.png"))
            # 逐行宽度差异，指出哪一段太胖/太瘦
            rows = np.linspace(0, ref.shape[0] - 1, 21).astype(int)
            diffs = []
            # 参考图首末行常是抗锯齿残留(如背面 y613 剪影仅 7px 宽)，
            # 拿它做基准会报出 +230px 的假警报，误导迭代方向 —— 剔除。
            ys_ref = np.flatnonzero(ref.any(axis=1))
            edge_lo, edge_hi = ys_ref.min(), ys_ref.max()
            span = edge_hi - edge_lo
            for row in rows:
                rr = np.flatnonzero(ref[row])
                gg = np.flatnonzero(aligned[row])
                if not (len(rr) and len(gg)):
                    continue
                # 上下各 1.5% 高度内、且参考宽度不足全宽 15% 的行视为噪声
                near_edge = (row - edge_lo < span * 0.015) or (edge_hi - row < span * 0.015)
                if near_edge and (rr.max() - rr.min()) < ref.shape[1] * 0.15:
                    continue
                diffs.append((row, (gg.max() - gg.min()) - (rr.max() - rr.min())))
            worst = sorted(diffs, key=lambda t: -abs(t[1]))[:5]
            print(f"  {name}: IoU {s:.4f}   宽度偏差最大行 " +
                  ", ".join(f"y{y}:{d:+d}px" for y, d in worst))
    if scores:
        print(f"  平均 IoU = {np.mean(list(scores.values())):.4f}")
    hero = os.path.join(preview_dir, "hero.png")
    if os.path.exists(hero):
        flatten(hero, os.path.join(preview_dir, "flat_hero.png"))
    return scores


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--preview", default="/tmp/build/preview")
    a = ap.parse_args()
    main(a.preview)
