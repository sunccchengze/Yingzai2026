#!/usr/bin/env python3
"""Build a high-detail Blender model of 小鹰 (XiaoYing), the Yingzai mascot.

Reference: public/images/小鹰/*.png  — cream head, chocolate body, gold beak/feet,
scalloped white ruff, cartoon-chibi proportions, flying pose with spread wings.
Materials aim for downy real-animal fluff (hair systems + sheen + SSS) while
keeping the mascot silhouette, colors and expression.
"""
from __future__ import annotations

import math
import os
import random
import sys

import bpy
import bmesh
from mathutils import Euler, Matrix, Vector, noise


# ---------------------------------------------------------------------------
# Paths / scene constants
# ---------------------------------------------------------------------------
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
OUT_DIR = os.path.join(ROOT, "小鹰3D模型", "高精绒羽版_小鹰")
BLEND_PATH = os.path.join(OUT_DIR, "小鹰.blend")
PREVIEW_DIR = os.path.join(OUT_DIR, "preview")
REF_DIR = os.path.join(ROOT, "public", "images", "小鹰")

RNG = random.Random(2026)


def srgb(r: float, g: float, b: float, a: float = 1.0):
    """8-bit sRGB -> Blender linear RGBA."""

    def c(x):
        x = float(x) / 255.0
        return x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4

    return (c(r), c(g), c(b), a)


# Sampled from 小鹰飞行.png
COL_HEAD = srgb(252, 245, 236)
COL_HEAD_SHADOW = srgb(243, 231, 216)
COL_BODY = srgb(107, 74, 45)
COL_BODY_HI = srgb(120, 84, 53)
COL_WING = srgb(78, 52, 30)
COL_WING_EDGE = srgb(48, 32, 18)
COL_BEAK = srgb(249, 179, 44)
COL_BEAK_SHADOW = srgb(197, 148, 52)
COL_EYE = srgb(18, 10, 4)
COL_TONGUE = srgb(224, 112, 96)
COL_MOUTH = srgb(168, 64, 48)
COL_CLAW = srgb(90, 55, 28)
COL_HIGHLIGHT = srgb(255, 255, 255)


# ---------------------------------------------------------------------------
# Scene helpers
# ---------------------------------------------------------------------------
def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    return scene


def coll(name: str, parent=None):
    c = bpy.data.collections.new(name)
    if parent is None:
        bpy.context.scene.collection.children.link(c)
    else:
        parent.children.link(c)
    return c


def link(obj, collection):
    collection.objects.link(obj)
    return obj


def shade_smooth(obj, auto=True, angle=math.radians(50)):
    mesh = obj.data
    for p in mesh.polygons:
        p.use_smooth = True
    # Blender 4.1+ replaced Mesh.use_auto_smooth with a modifier
    if auto:
        existing = [m for m in obj.modifiers if m.type == "NODES" and "Smooth" in m.name]
        if not existing:
            try:
                m = obj.modifiers.new("SmoothByAngle", "NODES")
                # fallback: if node group isn't auto-assigned, just keep vertex smooth
                if m.node_group is None:
                    obj.modifiers.remove(m)
            except Exception:
                pass


def new_obj(name, bm, collection, smooth=True):
    mesh = bpy.data.meshes.new(name)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    if smooth:
        shade_smooth(obj)
    mesh.update()
    return obj


def ico(name, collection, radius=1.0, subdiv=4, location=(0, 0, 0), scale=None):
    bm = bmesh.new()
    bmesh.ops.create_icosphere(bm, subdivisions=subdiv, radius=radius)
    if scale is not None:
        bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    obj = new_obj(name, bm, collection)
    obj.location = location
    return obj


def uv_sphere(name, collection, radius=1.0, segs=48, rings=24, location=(0, 0, 0), scale=None):
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=segs, v_segments=rings, radius=radius)
    if scale is not None:
        bmesh.ops.scale(bm, vec=scale, verts=bm.verts)
    obj = new_obj(name, bm, collection)
    obj.location = location
    return obj


def apply_world(obj):
    """Bake location/rotation/scale into mesh, keep world origin."""
    obj.data.transform(obj.matrix_world)
    obj.matrix_world = Matrix.Identity(4)


def parent(child, father, keep=True):
    child.parent = father
    if keep:
        child.matrix_parent_inverse = father.matrix_world.inverted()


def subsurf(obj, view=2, render=3):
    m = obj.modifiers.new("Subdivision", "SUBSURF")
    m.levels = view
    m.render_levels = render
    m.quality = 3
    m.uv_smooth = "PRESERVE_CORNERS"
    m.boundary_smooth = "ALL"
    return m


def displace_along_normals(obj, amount, freq=4.5, seed=0.0):
    mesh = obj.data
    for v in mesh.vertices:
        n = v.normal
        t = noise.noise(v.co * freq + Vector((seed, seed * 1.7, seed * 2.3)))
        v.co += n * (t * amount)
    mesh.update()


def push_region(obj, center, radius, amount, falloff=2.0, along=None):
    c = Vector(center)
    mesh = obj.data
    for v in mesh.vertices:
        d = (v.co - c).length
        if d >= radius:
            continue
        f = (1.0 - d / radius) ** falloff
        direction = Vector(along) if along is not None else v.normal
        v.co += direction.normalized() * amount * f
    mesh.update()


def assign_mat(obj, mat, slot=0):
    if obj.data.materials:
        if slot < len(obj.data.materials):
            obj.data.materials[slot] = mat
        else:
            obj.data.materials.append(mat)
    else:
        obj.data.materials.append(mat)


# ---------------------------------------------------------------------------
# Materials
# ---------------------------------------------------------------------------
def _bsdf(mat):
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    out.location = (400, 0)
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    bsdf.location = (0, 0)
    nt.links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    return nt, bsdf, out


def set_in(bsdf, name, value):
    if name in bsdf.inputs:
        bsdf.inputs[name].default_value = value


def mat_principled(
    name,
    color,
    roughness=0.5,
    specular=0.45,
    sss=0.0,
    sss_radius=(1.0, 0.4, 0.2),
    sss_scale=0.08,
    sheen=0.0,
    sheen_tint=(1, 1, 1, 1),
    coat=0.0,
    coat_rough=0.25,
    transmission=0.0,
    ior=1.45,
    emission=None,
    emission_strength=0.0,
):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt, bsdf, out = _bsdf(mat)
    set_in(bsdf, "Base Color", color)
    set_in(bsdf, "Roughness", roughness)
    set_in(bsdf, "Specular IOR Level", specular)
    set_in(bsdf, "IOR", ior)
    set_in(bsdf, "Subsurface Weight", sss)
    set_in(bsdf, "Subsurface Radius", sss_radius)
    set_in(bsdf, "Subsurface Scale", sss_scale)
    set_in(bsdf, "Sheen Weight", sheen)
    set_in(bsdf, "Sheen Tint", sheen_tint)
    set_in(bsdf, "Sheen Roughness", 0.35)
    set_in(bsdf, "Coat Weight", coat)
    set_in(bsdf, "Coat Roughness", coat_rough)
    set_in(bsdf, "Transmission Weight", transmission)
    if emission is not None:
        set_in(bsdf, "Emission Color", emission)
        set_in(bsdf, "Emission Strength", emission_strength)
    mat.shadow_method = "OPAQUE"
    return mat


def add_noise_bump(mat, strength=0.08, scale=28.0, roughness_extra=True):
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = scale
    tex.inputs["Detail"].default_value = 8.0
    tex.inputs["Roughness"].default_value = 0.55
    tex.location = (-500, -100)
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    bump.inputs["Distance"].default_value = 0.015
    bump.location = (-250, -80)
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    if roughness_extra:
        ramp = nt.nodes.new("ShaderNodeMix")
        ramp.data_type = "FLOAT"
        ramp.inputs["Factor"].default_value = 0.25
        ramp.inputs["A"].default_value = bsdf.inputs["Roughness"].default_value
        ramp.inputs["B"].default_value = min(1.0, bsdf.inputs["Roughness"].default_value + 0.18)
        ramp.location = (-250, 160)
        # Mix roughness with noise
        mathn = nt.nodes.new("ShaderNodeMath")
        mathn.operation = "MULTIPLY_ADD"
        mathn.inputs[1].default_value = 0.12
        mathn.inputs[2].default_value = bsdf.inputs["Roughness"].default_value
        mathn.location = (-250, 280)
        nt.links.new(tex.outputs["Fac"], mathn.inputs[0])
        nt.links.new(mathn.outputs[0], bsdf.inputs["Roughness"])
    return mat


def mat_hair(name, color, roughness=0.28, radial=0.32, coat=0.18, random_color=0.04):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    hair = nt.nodes.new("ShaderNodeBsdfHairPrincipled")
    hair.parametrization = "COLOR"
    hair.inputs["Color"].default_value = color
    if "Roughness" in hair.inputs:
        hair.inputs["Roughness"].default_value = roughness
    if "Radial Roughness" in hair.inputs:
        hair.inputs["Radial Roughness"].default_value = radial
    if "Coat" in hair.inputs:
        hair.inputs["Coat"].default_value = coat
    if "Random Color" in hair.inputs:
        hair.inputs["Random Color"].default_value = random_color
    if "IOR" in hair.inputs:
        hair.inputs["IOR"].default_value = 1.45
    nt.links.new(hair.outputs["BSDF"], out.inputs["Surface"])
    return mat


def build_materials():
    mats = {}
    mats["head"] = mat_principled(
        "Ying_Head_Down",
        COL_HEAD,
        roughness=0.62,
        specular=0.22,
        sss=0.22,
        sss_radius=(1.0, 0.55, 0.35),
        sss_scale=0.12,
        sheen=0.85,
        sheen_tint=srgb(255, 248, 236),
    )
    add_noise_bump(mats["head"], strength=0.045, scale=42)

    mats["body"] = mat_principled(
        "Ying_Body_Down",
        COL_BODY,
        roughness=0.68,
        specular=0.18,
        sss=0.12,
        sss_radius=(1.0, 0.45, 0.2),
        sss_scale=0.1,
        sheen=0.95,
        sheen_tint=srgb(160, 110, 70),
    )
    add_noise_bump(mats["body"], strength=0.06, scale=36)

    mats["belly"] = mat_principled(
        "Ying_Belly",
        COL_BODY_HI,
        roughness=0.66,
        specular=0.18,
        sss=0.14,
        sheen=0.9,
        sheen_tint=srgb(180, 130, 80),
    )
    add_noise_bump(mats["belly"], strength=0.05, scale=32)

    mats["feather"] = mat_principled(
        "Ying_FlightFeather",
        COL_WING,
        roughness=0.42,
        specular=0.35,
        sss=0.04,
        sheen=0.35,
        sheen_tint=srgb(90, 60, 30),
        coat=0.08,
        coat_rough=0.4,
        transmission=0.04,
        ior=1.4,
    )
    add_noise_bump(mats["feather"], strength=0.09, scale=55)

    mats["feather_dark"] = mat_principled(
        "Ying_FlightFeather_Dark",
        COL_WING_EDGE,
        roughness=0.4,
        specular=0.32,
        sheen=0.3,
        coat=0.06,
    )
    add_noise_bump(mats["feather_dark"], strength=0.08, scale=48)

    mats["ruff"] = mat_principled(
        "Ying_Ruff",
        COL_HEAD,
        roughness=0.55,
        specular=0.25,
        sss=0.18,
        sheen=0.8,
        sheen_tint=srgb(255, 250, 240),
    )
    add_noise_bump(mats["ruff"], strength=0.05, scale=40)

    mats["beak"] = mat_principled(
        "Ying_Beak_Keratin",
        COL_BEAK,
        roughness=0.28,
        specular=0.55,
        sss=0.35,
        sss_radius=(1.0, 0.5, 0.15),
        sss_scale=0.04,
        coat=0.22,
        coat_rough=0.18,
        ior=1.52,
    )
    add_noise_bump(mats["beak"], strength=0.025, scale=70, roughness_extra=False)

    mats["beak_inner"] = mat_principled(
        "Ying_MouthInterior",
        COL_MOUTH,
        roughness=0.45,
        specular=0.4,
        sss=0.55,
        sss_scale=0.03,
        coat=0.05,
    )
    mats["tongue"] = mat_principled(
        "Ying_Tongue",
        COL_TONGUE,
        roughness=0.32,
        specular=0.5,
        sss=0.7,
        sss_radius=(1.0, 0.25, 0.2),
        sss_scale=0.025,
        coat=0.15,
        coat_rough=0.22,
    )
    mats["eye"] = mat_principled(
        "Ying_Eye",
        COL_EYE,
        roughness=0.045,
        specular=0.85,
        coat=0.85,
        coat_rough=0.04,
        ior=1.49,
    )
    mats["highlight"] = mat_principled(
        "Ying_EyeHighlight",
        COL_HIGHLIGHT,
        roughness=0.08,
        specular=0.0,
        emission=COL_HIGHLIGHT,
        emission_strength=2.6,
    )
    try:
        mats["highlight"].shadow_method = "NONE"
    except Exception:
        pass
    mats["feet"] = mat_principled(
        "Ying_Feet_Keratin",
        COL_BEAK,
        roughness=0.38,
        specular=0.5,
        sss=0.28,
        sss_scale=0.03,
        coat=0.12,
        coat_rough=0.3,
    )
    add_noise_bump(mats["feet"], strength=0.04, scale=90)
    mats["claw"] = mat_principled(
        "Ying_Claw",
        COL_CLAW,
        roughness=0.3,
        specular=0.55,
        coat=0.2,
        coat_rough=0.22,
    )
    mats["hair_white"] = mat_hair("Ying_Hair_White", COL_HEAD, roughness=0.32, coat=0.22, random_color=0.05)
    mats["hair_brown"] = mat_hair(
        "Ying_Hair_Brown", srgb(118, 78, 46), roughness=0.3, coat=0.16, random_color=0.08
    )
    mats["hair_wing"] = mat_hair(
        "Ying_Hair_Wing", srgb(96, 64, 38), roughness=0.28, coat=0.12, random_color=0.06
    )
    return mats


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------
def leaf_feather(length, width, thick=0.01, bend=0.04, segs=14, camber=0.012):
    """Solid vane + raised rachis. Local +Y = length, +X = width, +Z = up."""
    bm = bmesh.new()
    outline = []
    for i in range(segs + 1):
        u = i / segs
        y = u * length
        # wider at ~28%, taper to a point
        profile = math.sin(math.pi * (u ** 0.72))
        if u < 0.06:
            profile *= u / 0.06
        w = width * profile * (1.0 - 0.12 * u)
        z = bend * (u ** 1.4) + camber * math.sin(u * math.pi)
        outline.append((w, y, z, u))

    # Build a closed solid: top left, top right, bottom right, bottom left
    rows_top = []
    rows_bot = []
    for w, y, z, u in outline:
        t = thick * (1.0 - 0.55 * u) * 0.5
        rachis = 0.55 * t
        # 5 verts across: L, midL, rachis, midR, R
        xs = [-w, -w * 0.45, 0.0, w * 0.45, w]
        z_off = [0.0, camber * 0.35, rachis + camber * 0.5, camber * 0.35, 0.0]
        top = []
        bot = []
        for x, zo in zip(xs, z_off):
            top.append(bm.verts.new((x, y, z + t + zo)))
            bot.append(bm.verts.new((x, y, z - t * 0.55)))
        rows_top.append(top)
        rows_bot.append(bot)
    bm.verts.ensure_lookup_table()

    def faces_strip(a, b):
        for i in range(len(a) - 1):
            try:
                bm.faces.new((a[i], a[i + 1], b[i + 1], b[i]))
            except ValueError:
                pass

    for i in range(len(rows_top) - 1):
        faces_strip(rows_top[i], rows_top[i + 1])
        faces_strip(rows_bot[i + 1], rows_bot[i])  # reverse for normals
        # sides
        try:
            bm.faces.new((rows_top[i][0], rows_top[i + 1][0], rows_bot[i + 1][0], rows_bot[i][0]))
            bm.faces.new((rows_top[i][-1], rows_bot[i][-1], rows_bot[i + 1][-1], rows_top[i + 1][-1]))
        except ValueError:
            pass
    # caps
    try:
        bm.faces.new(list(reversed(rows_top[0])) + rows_bot[0])
    except ValueError:
        # fallback triangles
        for i in range(len(rows_top[0]) - 1):
            try:
                bm.faces.new((rows_top[0][i], rows_bot[0][i], rows_bot[0][i + 1], rows_top[0][i + 1]))
            except ValueError:
                pass
    try:
        last_t = rows_top[-1]
        last_b = rows_bot[-1]
        for i in range(len(last_t) - 1):
            bm.faces.new((last_t[i], last_t[i + 1], last_b[i + 1], last_b[i]))
    except ValueError:
        pass

    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bmesh.ops.smooth_vert(bm, verts=bm.verts, factor=0.35, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    return bm


def place_feather_mesh(bm_src, dest_bm, origin, direction, up, roll=0.0):
    """Copy feather bmesh into dest, oriented so +Y aligns with direction."""
    direction = Vector(direction).normalized()
    up = Vector(up).normalized()
    x_axis = direction.cross(up)
    if x_axis.length < 1e-6:
        up = Vector((0, 0, 1))
        x_axis = direction.cross(up)
    x_axis.normalize()
    z_axis = x_axis.cross(direction).normalized()
    if roll:
        rot = Matrix.Rotation(roll, 3, direction)
        x_axis = rot @ x_axis
        z_axis = rot @ z_axis
    mat3 = Matrix((x_axis, direction, z_axis)).transposed()
    mat = Matrix.Translation(origin) @ mat3.to_4x4()
    copy_bmesh(bm_src, dest_bm, mat)


def copy_bmesh(src, dest, matrix=None):
    """Copy all faces from src into dest (bmesh objects cannot share elements)."""
    vmap = {}
    src.verts.ensure_lookup_table()
    src.faces.ensure_lookup_table()
    for v in src.verts:
        co = matrix @ v.co if matrix is not None else v.co.copy()
        vmap[v.index] = dest.verts.new(co)
    dest.verts.ensure_lookup_table()
    for f in src.faces:
        try:
            dest.faces.new([vmap[v.index] for v in f.verts])
        except ValueError:
            pass


def make_ruff_petal(length=0.16, width=0.11, thick=0.03):
    bm = bmesh.new()
    segs = 10
    rows_t, rows_b = [], []
    for i in range(segs + 1):
        u = i / segs
        y = u * length
        w = width * math.sin(math.pi * (u ** 0.55)) * (0.35 + 0.65 * (1 - u))
        z = 0.02 * math.sin(u * math.pi)
        t = thick * (1 - 0.4 * u) * 0.5
        top = [
            bm.verts.new((-w, y, z + t)),
            bm.verts.new((0.0, y, z + t + 0.006)),
            bm.verts.new((w, y, z + t)),
        ]
        bot = [
            bm.verts.new((-w, y, z - t)),
            bm.verts.new((0.0, y, z - t)),
            bm.verts.new((w, y, z - t)),
        ]
        rows_t.append(top)
        rows_b.append(bot)
    for i in range(segs):
        for k in range(2):
            bm.faces.new((rows_t[i][k], rows_t[i][k + 1], rows_t[i + 1][k + 1], rows_t[i + 1][k]))
            bm.faces.new((rows_b[i][k + 1], rows_b[i][k], rows_b[i + 1][k], rows_b[i + 1][k + 1]))
        bm.faces.new((rows_t[i][0], rows_t[i + 1][0], rows_b[i + 1][0], rows_b[i][0]))
        bm.faces.new((rows_t[i][2], rows_b[i][2], rows_b[i + 1][2], rows_t[i + 1][2]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    return bm


# ---------------------------------------------------------------------------
# Character
# ---------------------------------------------------------------------------
def build_body(col, mats):
    body = ico(
        "Body",
        col,
        radius=0.42,
        subdiv=5,
        location=(0.0, -0.04, 0.10),
        scale=(1.05, 0.92, 0.98),
    )
    # chubby belly forward-down, slightly pear
    push_region(body, (0.0, 0.12, -0.05), 0.38, 0.07, falloff=1.6, along=(0, 0.4, -0.6))
    push_region(body, (0.0, -0.15, 0.05), 0.28, 0.04, falloff=1.8, along=(0, -1, 0.2))
    # shoulder bumps
    push_region(body, (0.28, 0.02, 0.22), 0.18, 0.045, falloff=1.7)
    push_region(body, (-0.28, 0.02, 0.22), 0.18, 0.045, falloff=1.7)
    displace_along_normals(body, 0.0045, freq=7.5, seed=1.2)
    assign_mat(body, mats["body"])
    subsurf(body, 1, 2)
    return body


def build_head(col, mats):
    head = ico(
        "Head",
        col,
        radius=0.46,
        subdiv=5,
        location=(0.0, 0.06, 0.58),
        scale=(1.04, 0.96, 1.02),
    )
    # cheeks
    push_region(head, (0.22, 0.22, 0.50), 0.22, 0.055, falloff=1.7, along=(0.7, 0.4, -0.1))
    push_region(head, (-0.22, 0.22, 0.50), 0.22, 0.055, falloff=1.7, along=(-0.7, 0.4, -0.1))
    # forehead
    push_region(head, (0.0, 0.18, 0.86), 0.2, 0.03, falloff=1.8, along=(0, 0.2, 1))
    # chin / lower face into ruff
    push_region(head, (0.0, 0.22, 0.32), 0.2, 0.03, falloff=1.6, along=(0, 0.5, -0.6))
    displace_along_normals(head, 0.0035, freq=8.0, seed=4.4)
    assign_mat(head, mats["head"])
    subsurf(head, 1, 2)
    return head


def build_ruff(col, mats, parent_obj):
    dest = bmesh.new()
    petal = make_ruff_petal(0.17, 0.125, 0.032)
    n = 16
    for i in range(n):
        ang = (i / n) * math.tau + 0.08
        # ring around the neck, hanging slightly down, facing outward
        r = 0.36
        origin = Vector((math.sin(ang) * r, math.cos(ang) * r * 0.72 + 0.10, 0.34))
        outward = Vector((math.sin(ang), math.cos(ang) * 0.85, -0.55)).normalized()
        up = Vector((0, 0, 1))
        roll = math.sin(i * 1.7) * 0.15
        place_feather_mesh(petal, dest, origin, outward, up, roll=roll)
    # second inner row, offset, slightly smaller
    petal2 = make_ruff_petal(0.13, 0.10, 0.028)
    for i in range(n):
        ang = (i / n) * math.tau + 0.08 + math.pi / n
        r = 0.30
        origin = Vector((math.sin(ang) * r, math.cos(ang) * r * 0.7 + 0.12, 0.38))
        outward = Vector((math.sin(ang), math.cos(ang) * 0.8, -0.35)).normalized()
        place_feather_mesh(petal2, dest, origin, outward, Vector((0, 0, 1)), roll=0.1 * math.sin(i))
    petal.free()
    petal2.free()
    obj = new_obj("NeckRuff", dest, col)
    assign_mat(obj, mats["ruff"])
    subsurf(obj, 1, 2)
    parent(obj, parent_obj)
    return obj


def build_crest(col, mats, parent_obj):
    dest = bmesh.new()
    # 3-4 white tuft feathers on top, swept up-back-right like the 2D cowlick
    specs = [
        (0.04, 0.10, 1.02, 0.22, 0.07, 0.55, 0.02),
        (0.09, 0.06, 1.05, 0.26, 0.065, 0.72, -0.05),
        (0.00, 0.04, 1.04, 0.20, 0.06, 0.48, 0.08),
        (0.13, 0.02, 1.00, 0.18, 0.05, 0.85, 0.12),
    ]
    for x, y, z, length, width, yaw, roll in specs:
        f = leaf_feather(length, width, thick=0.016, bend=0.05, segs=12, camber=0.01)
        direction = Vector((math.sin(yaw) * 0.35, -0.15 + math.cos(yaw) * 0.05, 1.0)).normalized()
        place_feather_mesh(f, dest, Vector((x, y, z)), direction, Vector((0, 1, 0)), roll=roll)
        f.free()
    obj = new_obj("Crest", dest, col)
    assign_mat(obj, mats["ruff"])
    subsurf(obj, 1, 2)
    parent(obj, parent_obj)
    return obj


def build_eyes(col, mats, parent_obj):
    eyes = []
    # Cartoon frontal eyes, slightly embedded, looking at camera (+Y)
    specs = {
        "L": +1,
        "R": -1,
    }
    for name, side in specs.items():
        eye = uv_sphere(
            f"Eye_{name}",
            col,
            radius=0.135,
            segs=48,
            rings=24,
            location=(side * 0.155, 0.455, 0.605),
            scale=(1.08, 0.55, 1.15),
        )
        assign_mat(eye, mats["eye"])
        subsurf(eye, 1, 2)
        parent(eye, parent_obj)
        # Highlights in EYE LOCAL space, sitting on the cornea (front = +Y)
        hi = uv_sphere(f"EyeHighlight_{name}_A", col, radius=0.028, segs=20, rings=10)
        assign_mat(hi, mats["highlight"])
        hi.parent = eye
        hi.matrix_parent_inverse.identity()
        hi.location = (-0.045, 0.072, 0.038)
        hi.scale = (1.15, 0.45, 1.25)
        hi2 = uv_sphere(f"EyeHighlight_{name}_B", col, radius=0.011, segs=12, rings=8)
        assign_mat(hi2, mats["highlight"])
        hi2.parent = eye
        hi2.matrix_parent_inverse.identity()
        hi2.location = (0.038, 0.068, -0.028)
        eyes.extend([eye, hi, hi2])
    return eyes


def beak_half(name, col, mats, upper=True):
    bm = bmesh.new()
    # Parametric hooked cone. +Y forward.
    length = 0.24 if upper else 0.18
    segs_l, segs_c = 10, 16
    rings = []
    for i in range(segs_l + 1):
        u = i / segs_l
        y = 0.02 + u * length
        # taper, slight hook down at the tip
        hook = (u ** 2.4) * (0.055 if upper else 0.03)
        z0 = (0.03 if upper else -0.01) - hook
        rx = (0.105 if upper else 0.09) * (1 - u) ** 0.72 + 0.012
        rz = (0.07 if upper else 0.045) * (1 - u) ** 0.7 + 0.008
        ring = []
        for k in range(segs_c):
            a = k / segs_c * math.tau
            # upper mandible only upper hemisphere-ish
            if upper:
                # full but flattened bottom
                cz = abs(math.sin(a)) * rz
                if math.sin(a) < 0:
                    cz *= 0.25
                cx = math.cos(a) * rx
                ring.append(bm.verts.new((cx, y, z0 + cz * (1 if math.sin(a) >= 0 else -1))))
            else:
                cz = -abs(math.sin(a)) * rz
                if math.sin(a) > 0:
                    cz *= 0.2
                cx = math.cos(a) * rx
                ring.append(bm.verts.new((cx, y, z0 + cz)))
        rings.append(ring)
    for i in range(segs_l):
        for k in range(segs_c):
            k2 = (k + 1) % segs_c
            try:
                if upper:
                    bm.faces.new((rings[i][k], rings[i][k2], rings[i + 1][k2], rings[i + 1][k]))
                else:
                    bm.faces.new((rings[i][k], rings[i + 1][k], rings[i + 1][k2], rings[i][k2]))
            except ValueError:
                pass
    # tip cap
    tip = bm.verts.new((0.0, length + 0.028, (-0.04 if upper else -0.04)))
    for k in range(segs_c):
        k2 = (k + 1) % segs_c
        try:
            if upper:
                bm.faces.new((rings[-1][k], rings[-1][k2], tip))
            else:
                bm.faces.new((rings[-1][k], tip, rings[-1][k2]))
        except ValueError:
            pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    obj = new_obj(name, bm, col)
    obj.location = (0.0, 0.50, 0.50)
    if not upper:
        obj.rotation_euler = Euler((math.radians(38), 0, 0), "XYZ")
    assign_mat(obj, mats["beak"])
    subsurf(obj, 2, 3)
    return obj


def build_mouth(col, mats, parent_obj):
    upper = beak_half("Beak_Upper", col, mats, upper=True)
    lower = beak_half("Beak_Lower", col, mats, upper=False)
    parent(upper, parent_obj)
    parent(lower, parent_obj)

    # mouth cavity
    cavity = uv_sphere(
        "MouthCavity",
        col,
        radius=0.09,
        segs=24,
        rings=16,
        location=(0.0, 0.55, 0.485),
        scale=(0.85, 1.15, 0.55),
    )
    assign_mat(cavity, mats["beak_inner"])
    parent(cavity, parent_obj)

    # tongue
    tongue = ico(
        "Tongue",
        col,
        radius=0.055,
        subdiv=3,
        location=(0.0, 0.60, 0.455),
        scale=(0.7, 1.6, 0.38),
    )
    push_region(tongue, (0.0, 0.12, 0.0), 0.08, 0.02, falloff=1.4, along=(0, 1, 0.2))
    assign_mat(tongue, mats["tongue"])
    subsurf(tongue, 1, 2)
    parent(tongue, parent_obj)

    # nostrils sit on the upper mandible, not the forehead
    for side in (1, -1):
        n = ico(
            f"Nostril_{'L' if side>0 else 'R'}",
            col,
            radius=0.009,
            subdiv=2,
            scale=(1.2, 1.8, 0.65),
        )
        assign_mat(n, mats["beak_inner"])
        n.parent = upper
        n.matrix_parent_inverse.identity()
        n.location = (side * 0.028, 0.10, 0.042)
    return upper, lower


def build_wings(col, mats, parent_obj):
    """Layered cartoon-eagle wings. Feather vanes face the camera."""
    objects = []

    def wing_arm(side, name):
        arm = ico(
            name,
            col,
            radius=0.17,
            subdiv=4,
            location=(side * 0.40, 0.04, 0.26),
            scale=(1.85, 0.78, 0.58),
        )
        assign_mat(arm, mats["body"])
        subsurf(arm, 1, 2)
        parent(arm, parent_obj)
        return arm

    objects.append(wing_arm(+1, "WingArm_L"))
    objects.append(wing_arm(-1, "WingArm_R"))

    def build_one_wing(side, lift=0.0):
        dest = bmesh.new()
        shoulder = Vector((side * 0.32, 0.06, 0.28 + lift * 0.3))
        wrist = Vector((side * 0.88, -0.02, 0.46 + lift))
        tip = Vector((side * 1.38, -0.16, 0.58 + lift))
        # Dorsal surface toward camera (-Y) and up
        normal = Vector((-side * 0.08, 0.62, 0.78)).normalized()

        def along_bone(t):
            if t < 0.55:
                return shoulder.lerp(wrist, t / 0.55)
            return wrist.lerp(tip, (t - 0.55) / 0.45)

        rows = [
            dict(n=7, length=0.50, width=0.11, t0=0.55, t1=1.05, n_off=0.000, thick=0.012, bend=0.07, fan0=-0.05, fan1=0.85),
            dict(n=9, length=0.34, width=0.105, t0=0.18, t1=0.68, n_off=0.014, thick=0.012, bend=0.05, fan0=-0.15, fan1=0.55),
            dict(n=11, length=0.22, width=0.09, t0=0.08, t1=0.62, n_off=0.026, thick=0.011, bend=0.035, fan0=-0.12, fan1=0.48),
            dict(n=10, length=0.15, width=0.072, t0=0.04, t1=0.52, n_off=0.038, thick=0.010, bend=0.025, fan0=-0.08, fan1=0.38),
            dict(n=8, length=0.11, width=0.055, t0=0.00, t1=0.42, n_off=0.048, thick=0.009, bend=0.018, fan0=-0.05, fan1=0.22),
        ]
        span_dir = (tip - shoulder).normalized()
        for row in rows:
            n = row["n"]
            for i in range(n):
                u = i / max(n - 1, 1)
                t = row["t0"] + (row["t1"] - row["t0"]) * u
                origin = along_bone(min(max(t, 0.0), 1.0)) + normal * row["n_off"]
                fan = row["fan0"] + (row["fan1"] - row["fan0"]) * u
                direction = (Matrix.Rotation(-side * fan, 3, normal) @ span_dir).normalized()
                direction = (direction + Vector((0.0, -0.22 - 0.35 * u, 0.05))).normalized()
                length = row["length"] * (0.86 + 0.28 * u) * (0.97 + 0.06 * RNG.random())
                width = row["width"] * (0.96 + 0.08 * RNG.random())
                fbm = leaf_feather(length, width, thick=row["thick"], bend=row["bend"] * (0.75 + 0.5 * u), segs=12, camber=0.014)
                roll = side * (0.04 + 0.06 * u) + (RNG.random() - 0.5) * 0.04
                place_feather_mesh(fbm, dest, origin, direction, normal, roll=roll)
                fbm.free()
        name = "WingFeathers_L" if side > 0 else "WingFeathers_R"
        obj = new_obj(name, dest, col)
        assign_mat(obj, mats["feather"])
        subsurf(obj, 1, 2)
        parent(obj, parent_obj)
        return obj

    objects.append(build_one_wing(+1, lift=0.12))
    objects.append(build_one_wing(-1, lift=0.02))
    return objects


def build_tail(col, mats, parent_obj):
    dest = bmesh.new()
    n = 7
    for i in range(n):
        u = i / (n - 1)
        x = (u - 0.5) * 0.28
        origin = Vector((x, -0.38, 0.02))
        direction = Vector((x * 0.8, -1.0, -0.15)).normalized()
        length = 0.22 + 0.04 * math.sin(u * math.pi)
        fbm = leaf_feather(length, 0.07, thick=0.012, bend=0.03, segs=11)
        place_feather_mesh(fbm, dest, origin, direction, Vector((0, 0, 1)), roll=(u - 0.5) * 0.2)
        fbm.free()
    obj = new_obj("Tail", dest, col)
    assign_mat(obj, mats["feather"])
    subsurf(obj, 1, 2)
    parent(obj, parent_obj)
    return obj


def toe_mesh(length=0.11, radius=0.028, segs=8, rings=6):
    bm = bmesh.new()
    bmesh.ops.create_cone(
        bm,
        cap_ends=True,
        cap_tris=False,
        segments=segs,
        radius1=radius,
        radius2=radius * 0.55,
        depth=length,
    )
    # cone is along +Z; rotate to +Y
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "X"))
    bmesh.ops.translate(bm, verts=bm.verts, vec=(0, length * 0.5, 0))
    return bm


def build_feet(col, mats, parent_obj):
    feet = []
    for side, name in ((+1, "L"), (-1, "R")):
        dest = bmesh.new()
        # ankle / pad
        pad = bmesh.new()
        bmesh.ops.create_icosphere(pad, subdivisions=3, radius=0.055)
        bmesh.ops.scale(pad, vec=(1.15, 1.05, 0.7), verts=pad.verts)
        copy_bmesh(pad, dest)
        pad.free()
        # 3 forward toes + small hallux
        toes = [
            (0.00, 0.00, 0.12, 0.030, 0.0),
            (0.045, -0.15, 0.10, 0.026, 0.0),
            (-0.045, 0.15, 0.10, 0.026, 0.0),
            (0.00, math.pi, 0.07, 0.022, 0.0),  # hallux back
        ]
        for xoff, yaw, length, rad, _ in toes:
            tbm = toe_mesh(length, rad)
            rot = Matrix.Rotation(yaw, 3, "Z")
            for v in tbm.verts:
                v.co = rot @ v.co + Vector((xoff, 0.02, -0.01))
            copy_bmesh(tbm, dest)
            tbm.free()
            # claw
            cbm = bmesh.new()
            bmesh.ops.create_cone(
                cbm, cap_ends=True, segments=6, radius1=0.007, radius2=0.0015, depth=0.028
            )
            bmesh.ops.rotate(cbm, verts=cbm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "X"))
            for v in cbm.verts:
                v.co = rot @ (v.co + Vector((0, 0.01, 0))) + Vector((xoff, 0.02, -0.018)) + Vector((0, length * 0.55, 0))
            copy_bmesh(cbm, dest)
            cbm.free()
        bmesh.ops.remove_doubles(dest, verts=dest.verts, dist=0.002)
        bmesh.ops.recalc_face_normals(dest, faces=dest.faces)
        obj = new_obj(f"Foot_{name}", dest, col)
        obj.location = (side * 0.13, 0.02, -0.22)
        obj.rotation_euler = Euler((math.radians(25), side * math.radians(8), 0), "XYZ")
        assign_mat(obj, mats["feet"])
        subsurf(obj, 1, 2)
        parent(obj, parent_obj)
        feet.append(obj)
    return feet


# ---------------------------------------------------------------------------
# Hair
# ---------------------------------------------------------------------------
def make_vertex_group_all(obj, name="fur"):
    vg = obj.vertex_groups.new(name=name)
    idxs = [v.index for v in obj.data.vertices]
    vg.add(idxs, 1.0, "REPLACE")
    return vg


def paint_head_fur(obj, name="fur"):
    """Keep the cartoon face disk smooth; grow down only on crown, back and sides."""
    vg = obj.vertex_groups.new(name=name)
    for v in obj.data.vertices:
        x, y, z = v.co
        w = 1.0
        # frontal face (eyes + beak area) must stay clean
        if y > 0.06 and z < 0.20 and abs(x) < 0.40:
            w = 0.0
        elif y > 0.18 and z < 0.32:
            w = 0.12
        elif y > 0.10 and z > 0.20:
            w = 0.55  # forehead / tuft zone, thinner
        vg.add([v.index], w, "REPLACE")
    return vg


def bbox_world(objects):
    pts = []
    for obj in objects:
        if obj.type != "MESH":
            continue
        for corner in obj.bound_box:
            pts.append(obj.matrix_world @ Vector(corner))
    if not pts:
        return Vector(), Vector()
    xs, ys, zs = zip(*[(p.x, p.y, p.z) for p in pts])
    return Vector((min(xs), min(ys), min(zs))), Vector((max(xs), max(ys), max(zs)))


def add_hair(
    obj,
    name,
    mat,
    count=4000,
    length=0.055,
    children=8,
    rendered_children=18,
    clump=0.28,
    roughness=0.22,
    brownian=0.012,
    vgroup="fur",
    seed=1,
):
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    if mat.name not in [m.name for m in obj.data.materials if m]:
        obj.data.materials.append(mat)
    mat_index = list(obj.data.materials).index(mat) + 1  # particle material is 1-based

    mod = obj.modifiers.new(name, "PARTICLE_SYSTEM")
    psys = obj.particle_systems[-1]
    psys.name = name
    s = psys.settings
    s.name = f"{name}_settings"
    s.type = "HAIR"
    s.use_advanced_hair = True
    s.count = count
    s.hair_length = length
    s.hair_step = 5
    s.display_step = 3
    s.emit_from = "FACE"
    s.use_emit_random = True
    s.use_even_distribution = True
    s.distribution = "JIT"
    try:
        s.material = mat_index
    except Exception:
        pass
    s.child_type = "INTERPOLATED"
    s.child_percent = children
    s.rendered_child_count = rendered_children
    s.child_length = 0.92
    s.child_length_threshold = 0.1
    s.clump_factor = clump
    s.clump_shape = 0.12
    s.roughness_2 = roughness
    s.roughness_2_size = 0.85
    s.roughness_endpoint = 0.08
    s.roughness_end_shape = 0.0
    try:
        s.brownian_factor = brownian
    except Exception:
        pass
    s.use_strand_primitive = True
    s.radius_scale = 0.012
    s.root_radius = 1.0
    s.tip_radius = 0.12
    s.shape = 0.15
    s.use_close_tip = True
    s.kink = "WAVE"
    s.kink_amplitude = 0.008
    s.kink_frequency = 2.2
    s.kink_shape = 0.0
    s.kink_flat = 0.4
    try:
        psys.seed = seed
    except Exception:
        s.seed = seed
    if vgroup in obj.vertex_groups:
        psys.vertex_group_density = vgroup
    # cycles hair
    s.render_type = "PATH"
    obj.select_set(False)
    return psys


# ---------------------------------------------------------------------------
# Lighting / camera / render
# ---------------------------------------------------------------------------
def setup_stage(scene, root):
    lights = coll("Lighting")
    cams = coll("Cameras")

    def lamp(name, type_, loc, energy, color, rot=None, size=0.4):
        data = bpy.data.lights.new(name, type_)
        data.energy = energy
        data.color = color[:3] if len(color) > 3 else color
        if hasattr(data, "shadow_soft_size"):
            data.shadow_soft_size = size
        if type_ == "AREA":
            data.size = 2.2
            data.size_y = 1.6
        obj = bpy.data.objects.new(name, data)
        obj.location = loc
        if rot:
            obj.rotation_euler = Euler(rot, "XYZ")
        lights.objects.link(obj)
        return obj

    # cinematic three-point + rim, warm key matching the mascot
    lamp("KeyLight", "AREA", (2.2, 3.4, 3.0), 480, (1.0, 0.95, 0.88), rot=(math.radians(55), 0, math.radians(210)), size=1.8)
    lamp("FillLight", "AREA", (-3.0, 2.2, 2.0), 160, (0.75, 0.82, 1.0), rot=(math.radians(65), 0, math.radians(-30)), size=2.4)
    lamp("RimLight", "AREA", (0.3, -3.2, 2.4), 280, (1.0, 0.9, 0.75), rot=(math.radians(70), 0, 0), size=1.4)
    lamp("GroundBounce", "AREA", (0.0, 0.6, -1.6), 70, (0.55, 0.4, 0.28), rot=(math.radians(-90), 0, 0), size=3.0)
    sun = lamp("Sun", "SUN", (3.5, 5.5, 7.5), 2.6, (1.0, 0.97, 0.92), rot=(math.radians(50), math.radians(-10), math.radians(200)))
    sun.data.angle = math.radians(12)

    world = bpy.data.worlds.new("StudioWorld")
    world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()
    bg = nt.nodes.new("ShaderNodeBackground")
    bg.inputs["Color"].default_value = (0.03, 0.028, 0.026, 1)
    bg.inputs["Strength"].default_value = 0.35
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    scene.world = world

    # cameras
    def cam(name, loc, look_at, lens=50, collection=cams):
        data = bpy.data.cameras.new(name)
        data.lens = lens
        data.sensor_width = 36
        data.clip_start = 0.01
        data.clip_end = 100
        data.dof.use_dof = False
        obj = bpy.data.objects.new(name, data)
        obj.location = loc
        collection.objects.link(obj)
        # aim
        direction = Vector(look_at) - Vector(loc)
        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
        # focus
        data.dof.focus_object = root
        return obj

    look = Vector((0.0, 0.30, 0.48))
    hero = cam("Camera_Hero", (0.55, 3.45, 0.95), look, lens=48)
    front = cam("Camera_Front", (0.0, 3.60, 0.72), look, lens=42)
    side = cam("Camera_Side", (3.4, 0.35, 0.70), look, lens=45)
    threeq = cam("Camera_ThreeQuarter", (1.90, 2.90, 1.10), look, lens=46)
    scene.camera = hero
    return hero, front, side, threeq


def setup_render(scene, filepath, res=(1600, 1200), samples=48, transparent=True):
    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = samples
    scene.cycles.use_adaptive_sampling = True
    scene.cycles.adaptive_threshold = 0.04
    scene.cycles.max_bounces = 8
    scene.cycles.transparent_max_bounces = 8
    scene.cycles.transmission_bounces = 6
    scene.cycles.transparent_min_bounces = 4
    scene.cycles.use_denoising = True
    try:
        scene.cycles.denoiser = "OPENIMAGEDENOISE"
    except Exception:
        pass
    scene.render.resolution_x = res[0]
    scene.render.resolution_y = res[1]
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.film_transparent = transparent
    scene.render.filepath = filepath
    scene.render.threads_mode = "AUTO"
    scene.cycles.use_preview_denoising = False
    # hair
    if hasattr(scene.cycles, "hair_type"):
        scene.cycles.hair_type = "THICK"
    if hasattr(scene.cycles, "hair_subdivisions"):
        scene.cycles.hair_subdivisions = 2
    scene.view_settings.view_transform = "Filmic"
    scene.view_settings.look = "Medium High Contrast"
    scene.view_settings.exposure = 0.35
    scene.view_settings.gamma = 1.0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(do_render=True):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(PREVIEW_DIR, exist_ok=True)
    scene = reset_scene()
    mats = build_materials()

    col_char = coll("XiaoYing")
    col_body = coll("BodyParts", col_char)
    col_wing = coll("Wings", col_char)
    col_face = coll("Face", col_char)
    col_fur = coll("Groom", col_char)

    root = bpy.data.objects.new("XiaoYing_Root", None)
    root.empty_display_type = "ARROWS"
    root.empty_display_size = 0.4
    col_char.objects.link(root)
    # Gentle flying tilt — face stays readable from the hero camera
    root.rotation_euler = Euler((math.radians(-8), math.radians(4), math.radians(-6)), "XYZ")
    root.location = (0.0, 0.0, 0.15)

    body = build_body(col_body, mats)
    head = build_head(col_body, mats)
    parent(body, root)
    parent(head, root)

    ruff = build_ruff(col_body, mats, root)
    crest = build_crest(col_face, mats, root)
    eyes = build_eyes(col_face, mats, root)
    build_mouth(col_face, mats, root)
    wings = build_wings(col_wing, mats, root)
    tail = build_tail(col_wing, mats, root)
    feet = build_feet(col_body, mats, root)

    # vertex groups + hair (moderate density so 4GB RAM can render a preview)
    paint_head_fur(head, "fur")
    make_vertex_group_all(body, "fur")
    make_vertex_group_all(wings[0], "fur")  # arm L
    make_vertex_group_all(wings[1], "fur")
    make_vertex_group_all(ruff, "fur")
    make_vertex_group_all(crest, "fur")

    add_hair(
        head,
        "HeadDown",
        mats["hair_white"],
        count=3500,
        length=0.048,
        children=6,
        rendered_children=14,
        clump=0.22,
        roughness=0.18,
        seed=7,
    )
    add_hair(
        body,
        "BodyDown",
        mats["hair_brown"],
        count=4200,
        length=0.058,
        children=6,
        rendered_children=14,
        clump=0.32,
        roughness=0.24,
        seed=11,
    )
    add_hair(
        ruff,
        "RuffDown",
        mats["hair_white"],
        count=1800,
        length=0.04,
        children=5,
        rendered_children=12,
        clump=0.4,
        roughness=0.16,
        seed=3,
    )
    add_hair(
        crest,
        "CrestDown",
        mats["hair_white"],
        count=600,
        length=0.035,
        children=4,
        rendered_children=10,
        clump=0.45,
        seed=5,
    )
    add_hair(
        wings[0],
        "WingArmDown_L",
        mats["hair_wing"],
        count=700,
        length=0.04,
        children=4,
        rendered_children=10,
        clump=0.3,
        seed=13,
    )
    add_hair(
        wings[1],
        "WingArmDown_R",
        mats["hair_wing"],
        count=700,
        length=0.04,
        children=4,
        rendered_children=10,
        clump=0.3,
        seed=17,
    )

    hero, front, side, threeq = setup_stage(scene, root)

    # metadata
    scene["xiaoying_character"] = "小鹰 / XiaoYing — Yingzai Love Society mascot"
    scene["xiaoying_notes"] = (
        "Stylized-chibi proportions from official 2D sheets, "
        "downy hair grooms + layered flight feathers, "
        "colors sampled from public/images/小鹰/小鹰飞行.png"
    )

    # save blend first
    bpy.ops.wm.save_as_mainfile(filepath=BLEND_PATH)
    print("SAVED", BLEND_PATH, "size", os.path.getsize(BLEND_PATH))

    if do_render:
        shots = [
            ("hero", hero, 48),
            ("front", front, 32),
            ("side", side, 32),
            ("threequarter", threeq, 36),
        ]
        for label, cam, samples in shots:
            scene.camera = cam
            fp = os.path.join(PREVIEW_DIR, f"xiaoying_{label}.png")
            setup_render(scene, fp, res=(1280, 960), samples=samples, transparent=True)
            print("RENDER", label, "->", fp)
            bpy.ops.render.render(write_still=True)
            print("  wrote", os.path.getsize(fp) if os.path.exists(fp) else 0)

        bpy.ops.wm.save_mainfile()
        print("SAVED again", BLEND_PATH)


if __name__ == "__main__":
    do_render = "--no-render" not in sys.argv
    main(do_render=do_render)
