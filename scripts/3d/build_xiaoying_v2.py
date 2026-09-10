#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小鹰 3D 模型 v2 —— 由官方三视图**数据驱动**生成。

与旧版最大的区别：头/身/冠羽/喙/脚 的每一圈截面尺寸不是手填的魔法数字，
而是从 `public/images/小鹰/{正面,侧面,背面}.png` 里逐行量出来的
（正面给 X 半宽、侧面给 Y 半深），因此渲染出的正/侧剪影与参考图天然对齐。

运行（沙箱内）:
    source scripts/3d/blenv.sh
    python3 scripts/3d/build_xiaoying_v2.py --out 小鹰3D模型/官方三视图版_小鹰/小鹰.blend

在 Blender 里运行:
    Scripting 标签页打开本文件 → Run Script
"""
from __future__ import annotations

import argparse
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from xiaoying_refs import (Refs, smooth, COL_WHITE, COL_BROWN, COL_WING,  # noqa: E402
                           COL_YELLOW, COL_YELLOW_D, COL_RED, COL_DARK,
                           srgb_to_linear)

import bpy  # noqa: E402
import bmesh  # noqa: E402
from mathutils import Vector  # noqa: E402

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ════════════════════════════════════════════════════════════ 基础工具
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    sc = bpy.context.scene
    sc.unit_settings.system = 'METRIC'
    for blk in (bpy.data.meshes, bpy.data.materials, bpy.data.objects):
        for it in list(blk):
            blk.remove(it)


def mat(name, color, rough=0.55, sheen=0.0, sss=0.0, spec=0.4, emit=None,
        flat=0.50):
    """半平涂材质。

    官方 2D 是平涂矢量风，纯 PBR 打光会让奶油白被压成灰色、棕色发糊。
    这里把 `flat` 比例的自发光(=纯本色)和 Principled 漫反射混合，
    既保留 3D 体积感，又让主色稳定落在参考图取样值附近。
    """
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*color, 1.0)
    b.inputs["Roughness"].default_value = rough
    if "Specular IOR Level" in b.inputs:
        b.inputs["Specular IOR Level"].default_value = spec
    if sheen and "Sheen Weight" in b.inputs:
        b.inputs["Sheen Weight"].default_value = sheen
        b.inputs["Sheen Roughness"].default_value = 0.35
        b.inputs["Sheen Tint"].default_value = (1, 1, 1, 1)
    if sss and "Subsurface Weight" in b.inputs:
        b.inputs["Subsurface Weight"].default_value = sss
        b.inputs["Subsurface Radius"].default_value = (0.09, 0.05, 0.03)
    if emit and "Emission Color" in b.inputs:
        b.inputs["Emission Color"].default_value = (*emit, 1)
        b.inputs["Emission Strength"].default_value = 1.0
    m.diffuse_color = (*color, 1.0)

    if flat > 0.0:
        nt = m.node_tree
        out = next(n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL')
        emit_n = nt.nodes.new("ShaderNodeEmission")
        emit_n.inputs["Color"].default_value = (*color, 1.0)
        emit_n.inputs["Strength"].default_value = 1.0
        mix = nt.nodes.new("ShaderNodeMixShader")
        mix.inputs["Fac"].default_value = flat
        nt.links.new(b.outputs[0], mix.inputs[1])
        nt.links.new(emit_n.outputs[0], mix.inputs[2])
        nt.links.new(mix.outputs[0], out.inputs["Surface"])
    return m


def new_obj(name, bm, material=None, coll=None, shade_smooth=True):
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    if shade_smooth:
        for p in me.polygons:
            p.use_smooth = True
    ob = bpy.data.objects.new(name, me)
    (coll or bpy.context.scene.collection).objects.link(ob)
    if material:
        ob.data.materials.append(material)
    return ob


def loft(rings, close_bottom=True, close_top=True, segments=48):
    """rings: [(z, ax, ay, cx, cy)] 由下往上；生成椭圆截面放样体。"""
    bm = bmesh.new()
    layers = []
    for (z, ax, ay, cx, cy) in rings:
        ring = []
        for i in range(segments):
            t = 2 * math.pi * i / segments
            ring.append(bm.verts.new((cx + ax * math.cos(t),
                                      cy + ay * math.sin(t), z)))
        layers.append(ring)
    bm.verts.ensure_lookup_table()
    for a, b in zip(layers, layers[1:]):
        for i in range(segments):
            j = (i + 1) % segments
            bm.faces.new((a[i], a[j], b[j], b[i]))
    if close_bottom:
        bm.faces.new(list(reversed(layers[0])))
    if close_top:
        bm.faces.new(layers[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


def add_subsurf(ob, levels=2, render=3):
    m = ob.modifiers.new("Subdivision", 'SUBSURF')
    m.levels = levels
    m.render_levels = render
    return m



# ════════════════════════════════════════════════════════════ 由参考图取轮廓
def sample_profile(r: Refs, row_lo, row_hi, front_mask, side_mask,
                   step=4, smooth_k=7, side_lo=None, side_hi=None,
                   front_lo=None, front_hi=None):
    """在 [row_lo,row_hi] 每 step 像素取一圈，返回平滑后的 rings。"""
    rows, ax, ay, cx, cy = [], [], [], [], []
    for row in range(int(row_lo), int(row_hi) + 1, step):
        g = r.ring(row, front_mask, side_mask, side_lo, side_hi, front_lo, front_hi)
        if g is None:
            continue
        rows.append(g['z'])
        ax.append(g['ax'])
        ay.append(g['ay'])
        cx.append(g['cx'])
        cy.append(g['cy'])
    if len(rows) < 3:
        raise RuntimeError("轮廓采样点太少")
    ax = smooth(ax, smooth_k)
    ay = smooth(ay, smooth_k)
    cx = smooth(cx, smooth_k)
    cy = smooth(cy, smooth_k)
    rings = list(zip(rows, ax, ay, cx, cy))
    rings.reverse()  # 由下往上
    return rings


def taper_ends(rings, top_frac=0.0, bot_frac=0.0):
    """把首/尾圈收成尖点，避免放样体出现硬边圆盘。"""
    out = list(rings)
    if bot_frac:
        z, ax, ay, cx, cy = out[0]
        z2 = z - (out[1][0] - z) * 0.6
        out.insert(0, (z2, ax * bot_frac, ay * bot_frac, cx, cy))
    if top_frac:
        z, ax, ay, cx, cy = out[-1]
        z2 = z + (z - out[-2][0]) * 0.6
        out.append((z2, ax * top_frac, ay * top_frac, cx, cy))
    return out


# ════════════════════════════════════════════════════════════ 各部件
def build_head(r: Refs, m_white, coll):
    """头：正面 y 55..300 的白色区域（不含下缘绒毛裙边）。"""
    # 坑（第10轮，肉眼复核）：IoU 涨到 0.93 但渲染图里**头顶是个尖角**，
    # 参考图却是圆润的大弧顶 —— 剪影分数对「顶部 20px 的尖/圆」几乎不敏感，
    # 纯看数字会漏掉这种气质问题。
    # 实测参考图 y70 头宽已 110px、y100 达 207px，是快速展开的圆顶；
    # 采样从 y58 起 + top_frac=0.22 把顶端掐成了尖点。
    # 改为从 y68 起采样（避开冠羽根部那段窄区），top_frac 提到 0.72 留住圆顶。
    # 坑（第14轮）：三视图在 y85 同时缺 23~30px、且全高持续缺 6~20px ——
    # 头是系统性偏窄。原因有二：
    #   ① 采样从 y68 起 + top_frac=0.72 补的那一圈仍不够宽，头顶被削；
    #   ② white 掩膜不含黑色描边，逐行半宽天生比剪影窄 ~6px（每侧 3px）。
    # 对策：采样上移到 y62 让顶部由实测数据接管，top_frac 提到 0.86，
    # 并对整条剖面施加 +3.2px 的描边补偿（bloat）。
    rings = sample_profile(r, 62, 300, "white", "white", step=4, smooth_k=9,
                           side_lo=55)
    pad = r.L(3.2)
    # 第16轮分区统计「参考宽/模型宽」中位比值：
    #   头  正面 1.0228 / 侧面 1.0221 / 背面 1.0498  → 仍偏窄，X 更缺（背面看的也是 X）
    # X 取正/背折中偏大(1.033)，Y 取 1.022。
    # 第19轮：侧面头部 y190..262 的 Δ左 稳定 +8~+19px（该段缺肉 42~66px/行，
    # 是 side 最大失分源）。不是头窄，而是**头整体在 Y 向偏后** ——
    # 把头的 cy 前移 7px（负 Y = 朝喙方向），不改变尺寸故不撑包围盒。
    dy = r.L(7.0)
    rings = [(z, (ax + pad) * 1.028, (ay + pad) * 1.032, cx, cy - dy)
             for (z, ax, ay, cx, cy) in rings]
    rings = taper_ends(rings, top_frac=0.86, bot_frac=0.55)
    ob = new_obj("头", loft(rings, segments=64), m_white, coll)
    add_subsurf(ob, 2, 3)
    return ob


def build_head_fringe(r: Refs, m_white, coll):
    """颈羽裙边：头部下缘那一圈波浪状白绒毛（正面 y 290..355）。

    参考图里这是「一圈扇贝状的白色羽尖盖在棕色身体上」，
    所以用一圈**扁而尖**的水滴贴着头下缘排布，而不是一圈圆球（否则像牙齿）。
    """
    g = r.ring(300, "white", "white", side_lo=55)
    n = 17
    objs = []
    for i in range(n):
        t = 2 * math.pi * i / n
        # 半径取 0.84：**藏在头部剪影之内**，只在下方露出扇贝边，
        # 否则会在头两侧支棱出去，看着像一圈牙齿。
        # 坑：颈羽原本沿椭圆均匀铺（0.84 圈），最前那颗球表面伸到 y≈-0.50，
        # 比头部前表面(-0.44)还靠前，把整张嘴挡在后面。
        # 参考图里这圈扇贝其实是**从下巴兜到两颊**、并不越过脸的最前沿，
        # 所以前后方向压到 0.66 并整体下沉。
        px = g['cx'] + g['ax'] * 0.86 * math.cos(t)
        py = g['cy'] + g['ay'] * 0.66 * math.sin(t)
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=16, v_segments=12, radius=1.0)
        rr = r.L(31) * (1.0 + 0.10 * math.sin(i * 2.3))
        drop = r.L(16) * (1.0 + 0.18 * math.cos(i * 1.7))
        # 扁圆扇贝：横向宽、纵向略长，不做成尖牙
        bmesh.ops.scale(bm, vec=(rr, rr, rr * 0.95), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(px, py, g['z'] - drop), verts=bm.verts)
        ob = new_obj(f"颈羽_{i:02d}", bm, m_white, coll)
        add_subsurf(ob, 1, 2)
        objs.append(ob)
    return objs


def build_crest(r: Refs, m_white, coll):
    """头顶那撮翘起的呆毛：参考图 y 0..70，明显偏观众右+前。"""
    # 坑（第10轮）：头部采样起点从 y58 提到 y68 修圆头顶后，冠羽只画到 y66，
    # 两者之间**裂开一条缝**。让冠羽向下多延伸 20px（到 y86）插进头里，
    # 靠体积相交自然融合 —— 多出来的部分被头包住，不影响剪影。
    pts = []
    for row in range(2, 86, 6):
        fe = r.front.extent(r.front.sil, row)
        se = r.side.extent(r.side.sil, r.side_row(row))
        if not fe or not se:
            continue
        pts.append((r.Z(row),
                    r.L((fe[1] - fe[0]) / 2.0), r.L((se[1] - se[0]) / 2.0),
                    r.X((fe[0] + fe[1]) / 2.0), r.Y((se[0] + se[1]) / 2.0)))
    pts.reverse()
    rings = taper_ends(pts, top_frac=0.15)
    ob = new_obj("冠羽", loft(rings, close_bottom=True, segments=32),
                 m_white, coll)
    add_subsurf(ob, 2, 3)
    return ob


def build_body(r: Refs, m_brown, coll):
    """身体：正面 y 325..568 的棕色区域；侧面需把尾羽从躯干上剪掉。

    坑：尾羽在侧视图里与躯干**同色且连通**，若用固定的 side_hi=352 去裁，
    y450..530 这一段会连续 8 行都卡在 x=352，躯干后缘被削成一堵垂直的墙，
    渲出来就是个方盒子。改用**随高度收敛的裁剪线**：尾羽只长在 y440..535，
    在这一段按上下位置插值出后缘允许的最大 x，其余高度不裁，
    这样后背轮廓仍是连续的蛋形圆弧。
    """
    def tail_cut(row_side):
        # 尾羽出现的高度区间之外不做裁剪
        if row_side < 436 or row_side > 538:
            return None
        # 躯干真实后缘（由 436/538 两端的未污染值线性插值）
        t = (row_side - 436) / (538 - 436)
        return 337 + (349 - 337) * (1.0 - abs(2 * t - 1)) ** 0.6

    # 坑（第 2 轮校准发现）：侧面深度原先用 brown 掩膜取，但参考图侧视里
    # **胸前那块是白色**（头部白羽垂下盖住前胸），brown 掩膜把它整片漏掉，
    # 于是躯干在 Y 向系统性后缩 —— 逐行对比显示 Δ左 全线 +15~+86px，
    # 侧面 IoU 卡在 0.83。深度应当取**剪影**(sil)，颜色分界交给材质/描边。
    rows, ax, ay, cx, cy = [], [], [], [], []
    for row in range(330, 579, 4):
        rs = r.side_row(row)
        g = r.ring(row, "brown", "sil", side_hi=tail_cut(rs))
        if g is None:
            continue
        rows.append(g['z']); ax.append(g['ax']); ay.append(g['ay'])
        cx.append(g['cx']); cy.append(g['cy'])
    # 坑（第3/4轮校准）：ax 原先用 smooth(...,9)，步长 4px → 窗口跨 36 行。
    # 参考图正面 y505..530 身体在 25 行内收窄 89px（屁股收口），
    # 36 行的窗口正好把这个急转弯抹平，导致该段持续 +82px 过肥，
    # 且改 taper_ends 完全无效（那只影响端点补圈）。
    # 解法：对半宽用**自适应平滑** —— 逐点比较宽窗与窄窗，
    # 局部曲率大（|宽窗-窄窗| 显著）的地方采用窄窗保住转折，平缓段仍用宽窗去锯齿。
    ax_w, ax_n = smooth(ax, 9), smooth(ax, 3)
    ax_adapt = []
    tol = r.L(6)          # 6px 以内的差异视为噪声，仍走宽窗
    for vw, vn in zip(ax_w, ax_n):
        ax_adapt.append(vn if abs(vw - vn) > tol else vw)
    # 同头部：brown 掩膜不含黑描边，逐行半宽比剪影窄，统一补偿 +3.2px。
    pad = r.L(3.2)
    # 坑（第15轮）：把 blend 求值后按高度带筛顶点，定位到**身体**（不是脚/尾）
    # 在侧面 y563..575 那段 Ymax 超出参考 17px（Δ右 +22）。
    # 身体最底部几圈的 Y 向半深要额外收，否则屁股在侧视里拖出一块。
    ay_s = list(smooth(ay, 11))
    n_ay = len(ay_s)
    ay_fix = []
    for i, v in enumerate(ay_s):
        # rows 是从上往下采样后 reverse 前的顺序：i 越大越靠下
        f = i / max(1, n_ay - 1)
        shrink = 1.0 - 0.14 * max(0.0, (f - 0.78) / 0.22) ** 1.2
        ay_fix.append(v * shrink)
    # 坑（第16轮）：描边补偿 +3.2px 对正面(X)是必要的，但对侧面(Y)过量 ——
    # 逐行实测「参考宽/模型宽」中位数只有 0.967，即 Y 向整体胖 3.3%。
    # 因此 Y 向改用较小的补偿(1.2px)再乘 0.968 的整体收缩。
    pad_y = r.L(1.2)
    rings = list(zip(rows, [v + pad for v in ax_adapt],
                     [(v + pad_y) * 0.985 for v in ay_fix],
                     smooth(cx, 9), smooth(cy, 11)))
    rings.reverse()
    # 底部：0.55 会压出平底盘，0.30 又收太尖导致身体吊在脚上方露缝。
    # 0.46 兼顾「圆润」与「盖住脚背」。
    # 注：bot_frac 是「额外补一圈的缩放系数」，不是收敛速度；调它治不了腰身。
    # y505..530 的急收靠上面的自适应平滑保住（见 smooth 段注释）。
    # 第10轮肉眼复核：bot_frac=0.62 让底部收成**倒三角尖屁股**，
    # 参考图是圆润的收口。提到 0.86 把底部补圆（IoU 几乎不变，但形对了）。
    rings = taper_ends(rings, top_frac=0.62, bot_frac=0.96)
    ob = new_obj("身体", loft(rings, segments=64), m_brown, coll)
    add_subsurf(ob, 2, 3)
    return ob


def build_wings(r: Refs, m_wing, coll):
    """收拢的翅膀：正面身体两侧那两片、侧面 y 340..520 的分层羽。

    参考图里翅膀是贴身收拢的（不是展翅），所以用扁平的水滴片贴在体侧。
    """
    objs = []
    # 坑（第5轮校准）：翅膀下缘原锚在 y520，但参考图 y505..530 身体已急剧收窄
    # (348→259px)，翅膀仍按体侧最宽处贴着 → 正面 y517 支棱出 +82px，
    # 且该偏差不随 body 采样/平滑/taper 改变而变（因为它根本不是身体造成的）。
    # 侧面图实测翅膀棕色区到 y500 之后明显内收，故下缘锚点上提到 500。
    top = r.ring(360, "brown", "brown", side_hi=337)
    bot = r.ring(500, "brown", "brown", side_hi=349)
    zc = (top['z'] + bot['z']) / 2.0
    h = (top['z'] - bot['z']) / 2.0 * 1.02
    # 坑：Y 半径原为 115px，翅膀前后比躯干还长，侧视变成一道横扫的深色
    # 「回旋镖」。参考图的收拢翅只是贴在体侧的一小片，前后长度约躯干的 6 成。
    for sign, side in ((+1, "右"), (-1, "左")):
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=28, v_segments=18, radius=1.0)
        bmesh.ops.scale(bm, vec=(r.L(46), r.L(78), h * 0.94), verts=bm.verts)
        bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0),
                         matrix=__import__("mathutils").Matrix.Rotation(
                             math.radians(-6 * sign), 3, 'Y'))
        # 贴合体侧：略微下沉 + 稍稍靠后，露出的是「翅尖收在屁股上方」的形态
        bmesh.ops.translate(bm, vec=(sign * (top['ax'] * 0.82),
                                     top['cy'] + r.L(20), zc - h * 0.06),
                            verts=bm.verts)
        ob = new_obj(f"翅膀_{side}", bm, m_wing, coll)
        add_subsurf(ob, 2, 3)
        objs.append(ob)
    return objs


def build_beak(r: Refs, m_beak, m_beak_d, m_mouth, m_tongue, coll):
    """喙：上喙是带钩的三角(鹰喙)，下喙略小，中间张口露出红色口腔。

    正面 y217..333（黄），侧面 x 6..107 向前伸出。
    """
    S, F = r.side, r.front
    # 侧面：喙尖 x≈6，喙根 x≈107；正面最宽 y≈271 (138..269)
    # 头前表面（喙生长点）：用眼高度那圈头椭球的最前点
    head = r.ring(240, "white", "white", side_lo=55)
    # 侧面剪影里喙尖抵到 x=0；留一点余量确保剪影覆盖到位
    # 侧面剪影里喙尖抵到 x=0（甚至被画布裁掉），校准报告显示 y209 一带
    # 仍缺 65px，说明喙不够长/不够高 —— 这里把喙尖再往前送一截。
    tip_y = r.Y(-26)
    root_y = head['cy'] - head['ay'] * 0.42   # 埋进头里，保证无缝
    z_top = r.Z(217)
    z_mid = r.Z(262)
    z_bot = r.Z(333)
    half_w = r.L((269 - 138) / 2.0)

    objs = []
    # ---- 上喙：**正面是上窄下宽的菱形**（实测 row218 宽 17px → row268 宽 132px）
    # 坑：早先做成「根部宽 → 前端窄」的倒三角回转体，正面看恰好和参考图反了，
    # 导致下喙怎么摆都对不上。现在改成「按正面剪影逐行取半宽，再沿 -Y 挤出并
    # 向喙尖收拢下勾」，正面轮廓因此天然等于参考图。
    bm = bmesh.new()
    # 正面菱形的逐行半宽（取自 F.yellow 实测，rows 214..272）
    rows_up = [(214, 9), (222, 20), (230, 26), (238, 33), (246, 45),
               (254, 60), (262, 64), (268, 66), (272, 64)]
    face_pts = [(r.X(204.5 - hw), r.Z(row)) for (row, hw) in rows_up]
    face_pts += [(r.X(204.5 + hw), r.Z(row)) for (row, hw) in reversed(rows_up)]
    # 侧面：喙从脸部 y=root_y 一路伸到 tip_y，且末端下勾
    # 侧视实测：喙黄色占 y193..265，喙尖(x≈6)在 y217..257 —— 也就是说
    # **喙尖落在正面菱形(y214..272)的内部**，不会往下盖住嘴。
    # 因此放样方式是「从脸部的完整菱形，向前收敛到喙尖那一小点」，
    # 而不是整片菱形平移下沉（那会把下面的碗全遮住）。
    # 实测(侧面图)：剪影左端 x=0 出现在 y≈258–262，喙黄最左 x=6 也在 y260，
    # 即**喙尖比原先假设的 y246 更低**。喙尖抬太高会让 y209/y269 两行同时缺肉
    # （首轮校准 Δw≈-57）。这里对齐实测值。
    # ── 第9轮重写：改用**侧视实测脊线**放样，取代原先的「单点 tip_pt 收敛」。
    #
    # 原实现把整个喙朝一个点收敛，做不出鹰喙那条「上缘先高后钩下」的脊线，
    # 侧面 y209/y239 长期缺 68px/37px（side IoU 卡在 0.859）。
    #
    # 侧视图 yellow 掩膜逐列分离出的**上喙**上下缘实测（x 越小越靠前/喙尖）：
    #   x= 8: y241..261   x=24: y221..251   x=40: y202..251
    #   x=56: y192..256   x=72: y223..259   x=88: y241..254   x=104: y249..261
    # 即：上缘最高点在 x≈56（贴脸处 y192），向喙尖方向一路下降到 y241+，
    # 喙尖(x≈6)收拢到 y249..263 的一小段 —— 这就是要复刻的钩状轮廓。
    #
    # 侧视 x 与世界 Y 的关系由 r.Y() 给出；下面按 x 采样，逐段建环。
    beak_profile = [
        # (侧视x, 上缘y, 下缘y)  —— 从喙根(大x) 到 喙尖(小x)
        (104, 249, 261),
        (92, 240, 256),
        (80, 228, 259),
        (68, 196, 259),
        (56, 186, 256),
        (44, 192, 253),
        (32, 213, 258),
        (20, 220, 263),
        (12, 236, 274),
        (6, 244, 277),
        (1, 250, 277),   # 补一段更靠前的小截面，抵消 subsurf 对末端的收缩
    ]
    # 坑（第13轮，实测 evaluated mesh 后定位）：把 blend 里的上喙连同 subsurf
    # 一起求值，量到它最低只到 Z=1.150，而参考图 y269 的剪影需要 Z=1.117
    # ——**差 10px**，正是侧面 y260..269 那 10 行 -103px 断崖的成因。
    # 之前只下探 y_dn 无效：zc 取上下缘中点、half_z 取半差，
    # 单独压低下缘会同时把中点抬起来，末端反而更短。
    # 正确做法是上下缘**一起下移**（如 (6,249,263) -> (6,244,277)）。
    # 坑（第12轮）：喙尖原下缘取黄色像素的实际下界(263)，但参考图 y264..269
    # 剪影左端仍在 x=1..4 —— 那几行是喙的**黑色描边**，yellow 掩膜量不到。
    # 只按黄色建模会让喙在 y257 处戛然而止，侧面出现连续 4 行 -103px 的断崖。
    # 让末端 4 段一起下探覆盖描边区。
    # 正面菱形的半宽随「离喙根的距离」收窄；喙根处满宽，喙尖处收成小尖。
    n_prof = len(beak_profile)
    rings = []
    for k, (sx, y_up, y_dn) in enumerate(beak_profile):
        t = k / (n_prof - 1)          # 0=喙根, 1=喙尖
        y = r.Y(sx)
        z_up, z_dn = r.Z(y_up), r.Z(y_dn)
        zc = (z_up + z_dn) / 2.0
        half_z = (z_up - z_dn) / 2.0
        # 横向收窄：根部保持菱形满宽，越靠喙尖越窄。
        # 坑（第13轮）：尖端原留 12%，配合 subsurf(levels=2/render=3) 会被
        # **抹圆收缩**——渲染出的喙在 y259 处直接断掉，比设计短了整整 10 行
        # （侧面 y260..269 连续 -103px，占 side IoU 缺口的绝大部分）。
        # Catmull-Clark 对细长尖端收缩明显，尖端保留 26% 才能撑住剪影。
        wf = (1.0 - t) ** 0.85 * 0.74 + 0.26
        ring = []
        for (px, pz) in face_pts:
            # px 保持正面菱形的左右形状，按 wf 收窄
            nx = px * wf
            # pz 原本是正面菱形的高度，这里**重映射到侧视实测的上下缘之间**，
            # 使侧面轮廓严格等于参考图，而正面轮廓仍由 face_pts 决定。
            span = max(1e-6, z_top - z_bot)
            u = (pz - z_bot) / span            # 0..1 在原菱形里的相对高度
            nz = zc + (u - 0.5) * 2.0 * half_z
            # 鹰钩下垂：越靠喙尖整圈越往下压。
            # 坑（第13轮）：只改 beak_profile 的 y_dn 不够 —— face_pts 的 u 分布
            # 集中在中部，末端几圈的顶点仍挤在 zc 附近，求值后 Zmin 只到 1.143，
            # 而参考图 y269 需要 1.117。这里对末端额外施加一个下垂偏置，
            # 让喙尖真正勾到位（t=1 时下压 ~24px）。
            nz -= r.L(14.0) * (t ** 1.6)
            ring.append(bm.verts.new((nx, y, nz)))
        rings.append(ring)
    m = len(face_pts)
    for A, B in zip(rings, rings[1:]):
        for i in range(m):
            j = (i + 1) % m
            bm.faces.new((A[i], A[j], B[j], B[i]))
    bm.faces.new(list(reversed(rings[0])))
    bm.faces.new(rings[-1])
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = new_obj("喙_上", bm, m_beak, coll)
    add_subsurf(ob, 2, 3)
    objs.append(ob)

    # ---- 下喙 + 口腔 + 爱心舌
    # 坑：早先想用「上开口半椭球壳」一次成型，结果渲成一个向下的黄色倒三角，
    # 红口腔完全被糊住。改成**分层叠片**：由外到内、由后到前依次是
    # 下颌(黄) → 唇圈(黄，略前) → 口腔(红) → 爱心舌(红亮)，
    # 每层沿 -Y 前移一点点，靠遮挡关系自然形成「张开的嘴」，
    # 不依赖脆弱的壳体拓扑。
    # 实测：碗上沿 y274（宽 103px）→ 逐行收窄 → 碗底 y334（宽 ~20px）。
    # 上沿必须紧贴上喙下缘（y272 宽 128px），中间不能露出白脸。
    z_lip = r.Z(272)      # 唇线：与上喙下沿同高，接住它
    z_chin = r.Z(336)     # 下颌最低
    mouth_w = r.L((256 - 153) / 2.0)     # 下喙外缘半宽
    # 坑：嘴片原先放在 t=0.30（y≈-0.39），但颈羽白球表面已经伸到 y≈-0.50，
    # 整张嘴被白绒毛挡在后面，渲出来只剩一个黄色倒三角。
    # 嘴必须落在颈羽**之前**，故 t 提到 0.66（y≈-0.61）。
    # 颈羽已后收，嘴不必再前推躲它。t=0.50 换算到侧视 x≈68px，
    # 与参考图下喙所在的 x46..108 吻合；t=0.66 会飘到 x≈38，明显戳出脸外。
    y_face = root_y + (tip_y - root_y) * 0.50   # 嘴所在的"脸平面"

    def disc(name, matr, hw, hh, zc, y, thick, squash_top=None, subs=2):
        """一枚朝前的扁椭圆片（Y 方向薄）。squash_top<1 时把上半压扁成 D 形。"""
        bm = bmesh.new()
        seg = 40
        f_ring, b_ring = [], []
        for i in range(seg):
            a = 2 * math.pi * i / seg
            cx_, cz_ = math.cos(a), math.sin(a)
            if squash_top is not None and cz_ > 0:
                cz_ *= squash_top
            f_ring.append(bm.verts.new((hw * cx_, y - thick, zc + hh * cz_)))
            b_ring.append(bm.verts.new((hw * cx_ * 0.94, y + thick,
                                        zc + hh * cz_ * 0.94)))
        for i in range(seg):
            j = (i + 1) % seg
            bm.faces.new((f_ring[i], f_ring[j], b_ring[j], b_ring[i]))
        bm.faces.new(list(reversed(f_ring)))
        bm.faces.new(b_ring)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = new_obj(name, bm, matr, coll)
        add_subsurf(ob, subs, subs + 1)
        return ob

    # 坑：早先把椭圆的**上半**用 squash_top 压扁，可参考图的碗恰恰是
    # 「上沿最宽、向下收成圆底」——最宽处就在唇线上。压错了半边，
    # 碗顶被削掉 17px，整张嘴看起来比参考图低了一大截、还和上喙断开。
    # 正确做法：椭圆中心**放在唇线上**，上半几乎压平（squash_top≈0.06），
    # 下半保留完整，自然形成上宽下圆的碗。
    zc_mouth = z_lip                      # 中心 = 唇线（碗的最宽处）
    hh_mouth = (z_lip - z_chin)           # 向下的深度

    # ① 下颌（黄）：最外层，把整个嘴兜住
    objs.append(disc("喙_下颌", m_beak_d, mouth_w, hh_mouth,
                     zc_mouth, y_face + r.L(10), r.L(15), squash_top=0.06))
    # ② 口腔（红）：内缩一圈，露出四周一道黄色厚唇
    objs.append(disc("口腔", m_mouth, mouth_w * 0.80, hh_mouth * 0.80,
                     zc_mouth - r.L(4), y_face + r.L(2), r.L(9),
                     squash_top=0.06))
    # ③ 爱心舌：参考图口腔里那颗心（正面 x179..230, y287..320）
    bm = bmesh.new()
    seg = 30
    hw_h, hh_h = r.L(28), r.L(21)
    zc_h = r.Z(304)
    y_h = y_face - r.L(6)
    f_ring, b_ring = [], []
    for i in range(seg):
        t = 2 * math.pi * i / seg
        # 经典心形参数方程（归一化到 ±1）
        hx = (16 * math.sin(t) ** 3) / 17.0
        hz = (13 * math.cos(t) - 5 * math.cos(2 * t)
              - 2 * math.cos(3 * t) - math.cos(4 * t)) / 17.0
        f_ring.append(bm.verts.new((hw_h * hx, y_h - r.L(5), zc_h + hh_h * hz)))
        b_ring.append(bm.verts.new((hw_h * hx * 0.9, y_h + r.L(6),
                                    zc_h + hh_h * hz * 0.9)))
    for i in range(seg):
        j = (i + 1) % seg
        bm.faces.new((f_ring[i], f_ring[j], b_ring[j], b_ring[i]))
    bm.faces.new(list(reversed(f_ring)))
    bm.faces.new(b_ring)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    ob = new_obj("舌_爱心", bm, m_tongue, coll)
    add_subsurf(ob, 1, 2)
    objs.append(ob)
    return objs


def build_eyes(r: Refs, m_dark, m_white, coll):
    """眼：从参考图 dark 连通域量出的位置/半径，并**贴到头部椭球表面**。

    正面（y≈210 行）左眼 x109-162、右眼 x255-303，眼半径 ≈27px。
    关键：眼球中心必须落在头表面附近，否则会整颗埋进头里（v1 的坑）。
    """
    objs = []
    head = r.ring(210, "white", "white", side_lo=55)
    cz = r.Z(212)
    for (x0, x1, side) in ((109, 162, "左"), (255, 303, "右")):
        cx = r.X((x0 + x1) / 2.0)
        rad = r.L((x1 - x0) / 2.0)
        # 头部截面椭圆在该 x 处的前表面 y
        t = min(abs((cx - head['cx']) / head['ax']), 0.985)
        y_surf = head['cy'] - head['ay'] * math.sqrt(1.0 - t * t)
        # 眼球中心略微内嵌 40% 半径，其余凸出于表面
        cy = y_surf + rad * 0.40
        bm = bmesh.new()
        bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=22, radius=rad)
        bmesh.ops.scale(bm, vec=(1.0, 0.95, 1.05), verts=bm.verts)
        bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=bm.verts)
        objs.append(new_obj(f"眼_{side}", bm, m_dark, coll))
        # 两点高光（参考图是卡通高光）
        for k, (ox, oz, sc) in enumerate(((-0.34, 0.40, 0.30), (0.22, -0.30, 0.15))):
            bm = bmesh.new()
            bmesh.ops.create_uvsphere(bm, u_segments=14, v_segments=10,
                                      radius=rad * sc)
            bmesh.ops.translate(bm, vec=(cx + ox * rad,
                                         cy - rad * 0.80,
                                         cz + oz * rad), verts=bm.verts)
            objs.append(new_obj(f"眼高光_{side}{k}", bm, m_white, coll))
    return objs


def build_feet(r: Refs, m_foot, coll):
    """脚爪：正面两团黄色 (x91-182 / x228-319, y551-604)，每只三根圆头趾。

    坑：侧视黄色团 x99..255 是「三根趾错开排布」的**总包络**，
    不是单根趾的长度。早先按 168px 当单趾深度做，渲出来是一张前伸的黄煎饼。
    真实单趾长约 96px，三根趾再沿 Y 各自错开，合起来才凑成那个包络。
    """
    objs = []
    # 参考图里三趾是**紧贴身体底部并被身体压住**的（有重叠），
    # 早先趾心压得太低，渲出来脚和身体之间露出一条缝，像掉在地上的独立物件。
    # 坑（第12轮）：z0 原取 y606（参考剪影最底行），但那是趾底描边的最后几像素。
    # 参考图脚趾 y551 就出现、y565..580 已达全宽 283px，而模型那几行只有 89px
    # （Δ=-194，当时全图最大缺口）—— 趾心被压太低且半径过小，上半段没肉。
    # 第18轮：模型脚底停在 y608，参考到 y609（Z=0.0066），最后一行空出
    # -194px（正面唯一的大缺口）。z0 从 Z(604) 降到 Z(609) 补齐。
    z0 = r.Z(604)          # 脚底（贴地）
    ztop = r.Z(540)        # 脚背顶（抬高，塞进身体下缘）
    h = ztop - z0
    toe_len = r.L(100)     # 单根趾长度（三趾错开后凑成 157px 的侧视包络）
    # 第16轮：脚区中位比值 正面1.038/侧面1.078/背面1.056 → 仍偏小，半径×1.055
    toe_r = r.L(26.6)      # 单根趾半径（第17轮：脚区仍偏小 3.4~7.1%）
    # 侧视包络中心：趾整体略微偏前（负 Y = 朝喙的方向）
    cy_mid = r.Y((98 + 255) / 2.0) - r.L(2)

    # 实测正面 y580 行黄色分段：左脚 67-86 / 91-128 / 132-182，
    # 右脚 228-278 / 282-319 / 324-343 —— 即每只脚三根趾，
    # 左脚整体 x67..182、右脚 x228..343（比早先用的 91..319 更宽）。
    for (x0, x1, side) in ((67, 182, "左"), (228, 343, "右")):
        cx = r.X((x0 + x1) / 2.0)
        w = r.L(x1 - x0)
        # 三根趾：外/中/内，横向错开 + 前后错开（中趾最长最靠前）
        # 坑（第3轮校准）：xo=±0.30 时三趾挤在脚宽中段，正面 y555..560
        # 渲染宽仅 164px 而参考是 273px（Δ=-109）。趾半径 toe_r 只占脚宽约
        # 1/3，要铺满 x0..x1 必须让趾心分布到 ±0.34*w 之外——这里按
        # 「趾心间距 = (脚宽 - 单趾直径) / 2」精确排布，使外侧趾缘正好落在 x0/x1。
        xo_out = max(0.0, 0.5 - toe_r / max(w, 1e-6))
        for k, (xo, yo, lf) in enumerate(((-xo_out, +0.14, 0.90),
                                          (0.00, -0.08, 1.00),
                                          (+xo_out, +0.14, 0.90))):
            L = toe_len * lf
            bm = bmesh.new()
            n = 18
            rings = []
            # 沿趾长方向放样：根部略粗 → 前端圆头收尖
            prof = ((-0.50, 0.72), (-0.18, 1.00), (0.18, 0.98),
                    (0.42, 0.86), (0.50, 0.52))
            for (t, rf) in prof:
                y = cy_mid + yo * toe_len + t * L
                ring = []
                for i in range(n):
                    a = 2 * math.pi * i / n
                    # 趾断面：略扁（贴地），顶部圆
                    # 趾心抬到「半径高度」，使趾腹正好切到 z0 平面（贴地不悬空），
                    # 同时整体再上抬 34%，让趾背插进身体下缘、被身体压住，
                    # 消除「脚像掉在地上的独立物件」那条缝。
                    ring.append(bm.verts.new((
                        cx + xo * w + toe_r * rf * math.cos(a),
                        y,
                        z0 + toe_r * 1.30 + toe_r * rf * 1.05 * math.sin(a))))
                rings.append(ring)
            for A, B in zip(rings, rings[1:]):
                for i in range(n):
                    j = (i + 1) % n
                    bm.faces.new((A[i], A[j], B[j], B[i]))
            bm.faces.new(list(reversed(rings[0])))
            bm.faces.new(rings[-1])
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
            ob = new_obj(f"趾_{side}{k}", bm, m_foot, coll)
            add_subsurf(ob, 2, 3)
            objs.append(ob)

        # 掌垫：把三根趾的根部连成一只脚。
        # 坑（第10轮肉眼复核）：三趾各自独立放样后，渲染出来是**六颗孤立的黄球**，
        # 参考图里三趾根部是连在一起的一只脚掌。剪影 IoU 看不出这个问题
        # （孤立球和连体脚的外轮廓几乎一样），必须靠看图发现。
        bm = bmesh.new()
        n = 20
        rings = []
        # 掌垫沿 Y 从趾根略后 → 趾根略前，横向覆盖整只脚宽
        pad_prof = ((-0.42, 0.62), (-0.10, 1.00), (0.24, 0.92), (0.46, 0.58))
        for (t, rf) in pad_prof:
            y = cy_mid + t * toe_len
            ring = []
            for i in range(n):
                a = 2 * math.pi * i / n
                ring.append(bm.verts.new((
                    cx + (w * 0.5 * rf) * math.cos(a),
                    y,
                    z0 + toe_r * 1.30 + toe_r * rf * 0.95 * math.sin(a))))
            rings.append(ring)
        for A, B in zip(rings, rings[1:]):
            for i in range(n):
                j = (i + 1) % n
                bm.faces.new((A[i], A[j], B[j], B[i]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = new_obj(f"掌_{side}", bm, m_foot, coll)
        add_subsurf(ob, 2, 3)
        objs.append(ob)
    return objs


def build_tail(r: Refs, m_wing, coll):
    """尾羽：侧视 x340..394 / y436..538，是 **3 片向后上翘的尖羽**。

    坑：早先做成回转体楔形（每圈都是完整圆），侧面看只是个鼓包小球。
    参考图里尾羽是**扁平的叶片**：横向薄、纵向有宽度、末端收成尖，
    三片沿 X 错开并各自旋转不同角度，才有那种「羽毛张开」的层次。
    """
    objs = []
    # 尾根贴在躯干后缘，尾尖伸到侧视 x≈394 且上翘
    # 坑：尾尖原设 x=398 超出了参考剪影最远处(x=395)，再叠加 subsurf 外扩，
    # 侧面宽高比被撑大 +7%，归一化后整圈缺肉(首轮 side IoU 仅 0.839)。
    # 参考剪影 x=395 已含黑描边，实体应更收一点。
    y_root = r.Y(330)
    y_tip = r.Y(388)
    z_root = r.Z(r.f_top + (505 - r.s_top) / (r.s_bot - r.s_top) * r.px_h)
    z_tip = r.Z(r.f_top + (446 - r.s_top) / (r.s_bot - r.s_top) * r.px_h)

    n = 16
    # 坑：三片若只沿 X（左右）错开，从侧面看会完全重叠成一根「大拇指」。
    # 参考图的扇形张开发生在**侧平面内**（上下俯仰不同），所以主要错开量是
    # lift（末端抬升高度），X 只留很小的错位来避免 Z-fighting。
    for k, (xoff, lift, wide, extend) in enumerate((
            (-0.34, 0.24, 0.74, 0.82),    # 下片：几乎不翘、最短
            (0.00, 0.80, 0.92, 1.00),     # 中片
            (+0.30, 1.42, 0.80, 0.92))):  # 上片：翘得最高，拉开扇形
        bm = bmesh.new()
        rings = []
        # 沿羽长放样：根部窄 → 中段最宽 → 羽尖收成尖
        prof = ((0.00, 0.40, 0.34), (0.30, 0.88, 0.44),
                (0.62, 1.00, 0.42), (0.86, 0.72, 0.30), (1.00, 0.08, 0.10))
        half_h = r.L(27)     # 羽片纵向半宽
        thick = r.L(5.5)     # 羽片厚度（更薄，避免三片糊成一根拇指）
        for (t, wf, tf) in prof:
            y = y_root + (y_tip - y_root) * extend * t
            # 上翘：末端抬到 z_tip * lift
            zc = z_root + (z_tip - z_root) * lift * (t ** 0.85)
            ring = []
            for i in range(n):
                a = 2 * math.pi * i / n
                # 扁椭圆断面：X 方向薄，Z 方向宽 → 形成叶片
                px = thick * tf / 0.42 * math.cos(a)
                pz = half_h * wide * wf * math.sin(a)
                ring.append(bm.verts.new((
                    xoff * r.L(20) + px, y, zc + pz)))
            rings.append(ring)
        for A, B in zip(rings, rings[1:]):
            for i in range(n):
                j = (i + 1) % n
                bm.faces.new((A[i], A[j], B[j], B[i]))
        bm.faces.new(list(reversed(rings[0])))
        bm.faces.new(rings[-1])
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
        ob = new_obj(f"尾羽_{k}", bm, m_wing, coll)
        add_subsurf(ob, 2, 3)
        objs.append(ob)
    return objs


# ════════════════════════════════════════════════════════════ 场景 / 相机 / 灯
def setup_render(r: Refs, samples=64, res=(900, 1200)):
    sc = bpy.context.scene
    sc.render.engine = 'CYCLES'
    sc.cycles.device = 'CPU'
    sc.cycles.samples = samples
    sc.cycles.use_denoising = True
    sc.render.resolution_x, sc.render.resolution_y = res
    sc.render.film_transparent = True
    sc.view_settings.view_transform = 'Standard'
    # 曝光由标定得到：让渲染出的棕/白/黄与参考图取样值最接近（见 calibrate.py）
    sc.view_settings.exposure = 0.4
    sc.view_settings.look = 'None'
    return sc


def setup_freestyle(sc, thickness=2.6):
    """Freestyle 描边：还原官方 2D 的墨线贴纸风。

    Cycles 里做不了反向外壳（没有背面剔除），Freestyle 才是 Blender
    内置的正确工具：只在轮廓/折边处画线，不会把模型整个包住。
    不想要描边就在输出属性里关掉 Freestyle，或加 --no-outline 重跑。
    """
    sc.render.use_freestyle = True
    vl = sc.view_layers[0]
    vl.use_freestyle = True
    fs = vl.freestyle_settings
    fs.mode = 'EDITOR'
    fs.crease_angle = math.radians(140)
    fs.use_smoothness = True
    ls = fs.linesets.new("LineSet") if not fs.linesets else fs.linesets[0]
    if ls.linestyle is None:
        ls.linestyle = bpy.data.linestyles.new("墨线")
    ls.select_silhouette = True
    ls.select_border = True
    ls.select_crease = True
    ls.select_edge_mark = False
    lst = ls.linestyle
    lst.color = COL_DARK
    lst.thickness = thickness
    lst.thickness_position = 'INSIDE'
    lst.caps = 'ROUND'
    return fs


def add_cameras(r: Refs, center, size):
    """正/侧/背/三分之四 四台正交相机，视野按模型包围盒自动匹配。"""
    cams = {}
    specs = {
        "Camera_Front": (Vector((0, -6, 0)), (math.radians(90), 0, 0)),
        "Camera_Side": (Vector((6, 0, 0)), (math.radians(90), 0, math.radians(90))),
        "Camera_Back": (Vector((0, 6, 0)), (math.radians(90), 0, math.radians(180))),
        "Camera_ThreeQuarter": (Vector((-4.2, -4.6, 1.6)), None),
    }
    for name, (loc, rot) in specs.items():
        cd = bpy.data.cameras.new(name)
        cd.type = 'ORTHO'
        cd.ortho_scale = size * 1.12
        ob = bpy.data.objects.new(name, cd)
        bpy.context.scene.collection.objects.link(ob)
        ob.location = Vector((center[0], center[1], center[2])) + loc
        if rot:
            ob.rotation_euler = rot
        else:
            cd.type = 'PERSP'
            cd.lens = 70
            d = (ob.location - Vector(center))
            ob.rotation_euler = d.to_track_quat('Z', 'Y').to_euler()
        cams[name] = ob
    bpy.context.scene.camera = cams["Camera_Front"]
    return cams


def add_lights(center, size):
    def L(name, kind, loc, energy, **kw):
        d = bpy.data.lights.new(name, kind)
        d.energy = energy
        for k, v in kw.items():
            setattr(d, k, v)
        o = bpy.data.objects.new(name, d)
        bpy.context.scene.collection.objects.link(o)
        o.location = loc
        o.rotation_euler = (Vector(loc) - Vector(center)).to_track_quat('Z', 'Y').to_euler()
        return o
    # 三点柔光；强度按包围盒尺寸归一，避免换比例后过曝
    k = max(size, 0.5) ** 2
    L("Key", 'AREA', (-2.2, -3.0, 2.6), 14 * k, size=2.4)
    L("Fill", 'AREA', (2.8, -2.0, 1.2), 5.5 * k, size=3.0)
    L("Rim", 'AREA', (0.6, 3.2, 2.4), 8 * k, size=2.4)
    w = bpy.context.scene.world or bpy.data.worlds.new("World")
    bpy.context.scene.world = w
    w.use_nodes = True
    w.node_tree.nodes["Background"].inputs[0].default_value = (0.90, 0.93, 0.99, 1)
    w.node_tree.nodes["Background"].inputs[1].default_value = 0.22


def bounds(objs):
    mn = Vector((1e9, 1e9, 1e9))
    mx = Vector((-1e9, -1e9, -1e9))
    dg = bpy.context.evaluated_depsgraph_get()
    for ob in objs:
        if ob.type != 'MESH':
            continue
        for c in ob.bound_box:
            w = ob.matrix_world @ Vector(c)
            mn = Vector((min(mn[i], w[i]) for i in range(3)))
            mx = Vector((max(mx[i], w[i]) for i in range(3)))
    return mn, mx


# ════════════════════════════════════════════════════════════ 主流程
def build(out_path, samples=64, do_render=True, preview_dir=None, outline=True):
    r = Refs(height_units=2.0)
    reset_scene()
    sc = bpy.context.scene

    coll = bpy.data.collections.new("小鹰")
    sc.collection.children.link(coll)

    m_white = mat("羽_奶油白", COL_WHITE, rough=0.62, sheen=0.55, sss=0.16)
    m_brown = mat("羽_巧克力棕", COL_BROWN, rough=0.68, sheen=0.45, sss=0.10)
    # 坑：早先给翅/尾单独用了明显更深的 COL_WING，正面渲出来体侧多了两块
    # 参考图没有的深色斑。实测参考图身体/翅膀/尾羽**全是同一个棕 (110,77,46)**，
    # 深色像素只是黑描边——这是 2D 平涂 + 线稿的风格本质。
    # 因此这里与身体同色，只留极轻微的压暗保住体积感，分界交给 Freestyle 描边。
    m_wing = mat("羽_翅尾棕", tuple(c * 0.93 for c in COL_BROWN),
                 rough=0.66, sheen=0.40)
    m_beak = mat("喙_金黄", COL_YELLOW, rough=0.30, spec=0.6)
    m_beakd = mat("喙下_金黄暗", COL_YELLOW_D, rough=0.32, spec=0.6)
    # 口腔用较暗的红（处在阴影里），舌头用参考图取样的亮红，两者拉开层次
    m_mouth = mat("口腔_暗红", tuple(c * 0.55 for c in COL_RED), rough=0.5)
    m_tongue = mat("舌_爱心红", COL_RED, rough=0.42)
    m_dark = mat("眼_近黑", COL_DARK, rough=0.12, spec=0.9, flat=0.30)
    m_hl = mat("眼_高光白", (1, 1, 1), rough=0.05, spec=1.0, flat=0.85)
    m_foot = mat("爪_金黄", COL_YELLOW, rough=0.38, spec=0.5)

    parts = []
    parts.append(build_body(r, m_brown, coll))
    parts += build_wings(r, m_wing, coll)
    parts += build_tail(r, m_wing, coll)
    parts.append(build_head(r, m_white, coll))
    parts += build_head_fringe(r, m_white, coll)
    parts.append(build_crest(r, m_white, coll))
    parts += build_beak(r, m_beak, m_beakd, m_mouth, m_tongue, coll)
    parts += build_eyes(r, m_dark, m_hl, coll)
    parts += build_feet(r, m_foot, coll)

    # 角色根：便于整体旋转/摆姿
    root = bpy.data.objects.new("XiaoYing_Root", None)
    root.empty_display_type = 'PLAIN_AXES'
    root.empty_display_size = 0.6
    coll.objects.link(root)
    for ob in parts:
        if ob.parent is None:
            ob.parent = root

    mn, mx = bounds(parts)
    center = ((mn.x + mx.x) / 2, (mn.y + mx.y) / 2, (mn.z + mx.z) / 2)
    size = max(mx.x - mn.x, mx.z - mn.z)
    print(f"[bounds] x {mn.x:.3f}..{mx.x:.3f}  y {mn.y:.3f}..{mx.y:.3f}  z {mn.z:.3f}..{mx.z:.3f}")

    setup_render(r, samples=samples)
    if outline:
        setup_freestyle(bpy.context.scene)
    add_cameras(r, center, size)
    add_lights(center, size)

    out_path = os.path.abspath(out_path)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=out_path)
    print("[saved]", out_path)

    if do_render:
        pd = preview_dir or os.path.join(os.path.dirname(out_path), "preview")
        os.makedirs(pd, exist_ok=True)
        for cam, fn in (("Camera_Front", "front"), ("Camera_Side", "side"),
                        ("Camera_Back", "back"), ("Camera_ThreeQuarter", "hero")):
            sc.camera = bpy.data.objects[cam]
            sc.render.filepath = os.path.join(pd, f"{fn}.png")
            bpy.ops.render.render(write_still=True)
            print("[render]", sc.render.filepath)
    return out_path


if __name__ == "__main__":
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(
        REPO, "小鹰3D模型", "官方三视图版_小鹰", "小鹰.blend"))
    ap.add_argument("--samples", type=int, default=64)
    ap.add_argument("--no-render", action="store_true")
    ap.add_argument("--no-outline", action="store_true")
    a = ap.parse_args(argv)
    build(a.out, samples=a.samples, do_render=not a.no_render,
          outline=not a.no_outline)
