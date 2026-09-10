"""从官方 2D 三视图 (public/images/小鹰/*.png) 提取建模用的轮廓数据。

本模块不依赖 bpy，可单独运行做数据体检：
    python3 scripts/3d/xiaoying_refs.py

核心思想：不靠人工估比例，而是把参考图的**逐行轮廓**当成建模输入 ——
正面图给 X 方向半宽，侧面图给 Y 方向半深，两者 loft 成椭圆截面实体，
这样渲染出来的正/侧剪影与参考图**天然对齐**。
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
IMG_DIR = os.path.join(REPO, "public", "images", "小鹰")

# ---------------------------------------------------------------- 采样得到的配色
def srgb_to_linear(hex_str):
    """#RRGGBB(sRGB) → Blender 需要的线性 RGB。

    直接把 sRGB 分量填进 Base Color 会让颜色明显偏亮发灰
    （巧克力棕渲成奶茶色），必须先做这一步反伽马。
    """
    h = hex_str.lstrip("#")
    out = []
    for i in (0, 2, 4):
        c = int(h[i:i + 2], 16) / 255.0
        out.append(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4)
    return tuple(out)


HEX_WHITE, HEX_BROWN, HEX_WING = "#FCF8F2", "#6E4D2E", "#57381F"
HEX_YELLOW, HEX_YELLOW_D = "#F6B32A", "#E09216"
HEX_RED, HEX_DARK = "#E25C48", "#281C0C"

COL_WHITE = srgb_to_linear(HEX_WHITE)      # 头/颈 奶油白
COL_BROWN = srgb_to_linear(HEX_BROWN)      # 身体巧克力棕
COL_WING = srgb_to_linear(HEX_WING)        # 翅膀/尾羽（暗一档）
COL_YELLOW = srgb_to_linear(HEX_YELLOW)    # 喙/爪 金黄
COL_YELLOW_D = srgb_to_linear(HEX_YELLOW_D)
COL_RED = srgb_to_linear(HEX_RED)          # 口腔
COL_DARK = srgb_to_linear(HEX_DARK)        # 眼/描边


def _load(name: str) -> np.ndarray:
    path = os.path.join(IMG_DIR, f"小鹰{name}.png")
    return np.array(Image.open(path).convert("RGBA")).astype(np.int32)


def main_cc(mask: np.ndarray) -> np.ndarray:
    """只保留最大连通域，去掉高光点/描边碎片带来的噪声。"""
    from scipy import ndimage
    lab, n = ndimage.label(mask)
    if n <= 1:
        return mask
    sizes = ndimage.sum(mask, lab, range(1, n + 1))
    return lab == (int(np.argmax(sizes)) + 1)


class ViewMasks:
    def __init__(self, name: str):
        a = _load(name)
        rgb = a[..., :3]
        ok = a[..., 3] > 120
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        self.name = name
        self.h, self.w = a.shape[0], a.shape[1]
        self.sil = ok
        self.white = main_cc(ok & (rgb.min(2) > 195))
        self.brown = main_cc(ok & (r > 60) & (r < 165) & (g < 120) & (b < 95))
        self.yellow = ok & (r > 195) & (g > 125) & (g < 220) & (b < 100)
        self.red = ok & (r > 170) & (g < 120) & (b < 120) & ((r - g) > 70)
        self.dark = ok & (rgb.sum(2) < 230)

    def extent(self, mask, row, lo=None, hi=None):
        if row < 0 or row >= self.h:
            return None
        line = mask[row]
        if lo is not None or hi is not None:
            line = line.copy()
            if lo is not None:
                line[:int(round(lo))] = False
            if hi is not None:
                line[int(round(hi)) + 1:] = False
        xs = np.flatnonzero(line)
        return (int(xs[0]), int(xs[-1])) if xs.size else None

    def bbox(self, mask):
        ys, xs = np.nonzero(mask)
        return int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())


class Refs:
    """三视图 + 统一的像素↔Blender 坐标映射。

    Blender 右手系, Z 朝上：
      X = 左右（正 X = 观众视角右侧）
      Y = 前后，**负 Y = 面朝方向(喙尖)**，正 Y = 尾巴
      Z = 上下，0 = 脚底，全高 = height_units
    """

    def __init__(self, height_units: float = 2.0):
        self.front = ViewMasks("正面")
        self.side = ViewMasks("侧面")
        self.back = ViewMasks("背面")
        self.height_units = height_units

        f = self.front
        _, _, ftop, fbot = f.bbox(f.sil)
        self.f_top, self.f_bot = ftop, fbot
        self.px_h = fbot - ftop
        self.s = height_units / self.px_h

        bx0, bx1, _, _ = f.bbox(f.brown)
        self.cx_front = (bx0 + bx1) / 2.0

        s_ = self.side
        _, _, stop, sbot = s_.bbox(s_.sil)
        self.s_top, self.s_bot = stop, sbot
        # 坑（第6轮校准）：cy_side 原用 brown 掩膜在 y380..440 取中心，
        # 但侧视图这一段**前胸是白羽**（头部白羽垂下盖住胸口），brown 的左边界
        # 因此偏右，整个 Y 基准被系统性后移 —— 实测 Δ左端 98% 为正、均值 +25.6px，
        # 纯平移 -13px 即可把 side IoU 从 0.8595 提到 0.8919。
        # 改用剪影(sil)取躯干中心；并排除尾羽段(y>430)避免把尾巴算进来。
        cols = np.flatnonzero(s_.sil[380:430].any(0))
        self.cy_side = (cols.min() + cols.max()) / 2.0

        b_ = self.back
        _, _, btop, bbot = b_.bbox(b_.sil)
        self.b_top, self.b_bot = btop, bbot
        bbx0, bbx1, _, _ = b_.bbox(b_.brown)
        self.cx_back = (bbx0 + bbx1) / 2.0

    # -------- 行号在三视图之间按比例对齐
    def side_row(self, row_front) -> int:
        t = (row_front - self.f_top) / self.px_h
        return int(round(self.s_top + t * (self.s_bot - self.s_top)))

    def back_row(self, row_front) -> int:
        t = (row_front - self.f_top) / self.px_h
        return int(round(self.b_top + t * (self.b_bot - self.b_top)))

    # -------- 像素 → 世界坐标
    def X(self, x_px):
        return (x_px - self.cx_front) * self.s

    def Xb(self, x_px):
        return -(x_px - self.cx_back) * self.s

    def Y(self, x_side_px):
        return (x_side_px - self.cy_side) * self.s

    def Z(self, row_front):
        return (self.f_bot - row_front) * self.s

    def L(self, px):
        return px * self.s

    def ring(self, row_f, front_mask="sil", side_mask="sil",
             side_lo=None, side_hi=None, front_lo=None, front_hi=None):
        """某一行的截面：X 半宽/中心 + Y 半深/中心。"""
        fm = getattr(self.front, front_mask)
        sm = getattr(self.side, side_mask)
        fe = self.front.extent(fm, int(row_f), front_lo, front_hi)
        se = self.side.extent(sm, self.side_row(row_f), side_lo, side_hi)
        if fe is None or se is None:
            return None
        return dict(
            z=self.Z(row_f),
            ax=self.L((fe[1] - fe[0]) / 2.0), cx=self.X((fe[0] + fe[1]) / 2.0),
            ay=self.L((se[1] - se[0]) / 2.0), cy=self.Y((se[0] + se[1]) / 2.0),
            row=int(row_f), fe=fe, se=se)


def smooth(vals, k=5):
    v = np.asarray(vals, dtype=float)
    if v.size < 3:
        return v
    if k % 2 == 0:
        k += 1
    k = min(k, v.size if v.size % 2 else v.size - 1)
    if k < 3:
        return v
    pad = k // 2
    ext = np.concatenate([np.full(pad, v[0]), v, np.full(pad, v[-1])])
    return np.convolve(ext, np.ones(k) / k, mode="valid")


if __name__ == "__main__":
    r = Refs()
    print(f"scale {r.s:.5f} u/px  front {r.front.w}x{r.front.h} "
          f"cx={r.cx_front:.1f}  side cy={r.cy_side:.1f}  back cx={r.cx_back:.1f}")
    print(f"front rows {r.f_top}..{r.f_bot} (h={r.px_h}px -> {r.height_units}u)")
    for row in range(r.f_top, r.f_bot + 1, 40):
        g = r.ring(row)
        if g:
            print(f"  row {row:3d} z={g['z']:.3f} ax={g['ax']:.3f} ay={g['ay']:.3f} "
                  f"cx={g['cx']:+.3f} cy={g['cy']:+.3f}")
