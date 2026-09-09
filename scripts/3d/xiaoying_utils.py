"""小鹰 3D builder - shared utilities."""
import bpy
import bmesh
import math
import mathutils
from mathutils import Vector

# ----------------------------------------------------------------------------
#  Scene / data helpers
# ----------------------------------------------------------------------------
def fresh_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    # ensure world exists
    if bpy.data.worlds:
        w = bpy.data.worlds[0]
    else:
        w = bpy.data.worlds.new("World")
    bpy.context.scene.world = w


def _active_layer_collection():
    return bpy.context.view_layer.active_layer_collection


def new_collection(name, parent=None):
    c = bpy.data.collections.new(name)
    if parent is None:
        _active_layer_collection().collection.children.link(c)
    else:
        parent.children.link(c)
    return c


def link_object(obj, coll):
    coll.objects.link(obj)
    # remove from scene main collection if it got linked there too
    for sc in bpy.data.scenes:
        mc = sc.collection
        if obj.name in mc.objects:
            mc.objects.unlink(obj)
    return obj


def make_empty(name, loc=(0, 0, 0), parent=None, coll=None, kind='PLAIN_AXES'):
    e = bpy.data.objects.new(name, None)
    e.empty_display_type = kind
    e.location = Vector(loc)
    if coll:
        coll.objects.link(e)
    else:
        bpy.context.scene.collection.objects.link(e)
    if parent:
        e.parent = parent
    return e


# ----------------------------------------------------------------------------
#  Mesh helpers
# ----------------------------------------------------------------------------
def bmesh_from_objs(name, verts, faces, coll=None, material=None):
    """verts: list of (x,y,z) or Vector; faces: list of index lists."""
    me = bpy.data.meshes.new(name)
    mesh = bmesh.new()
    bm_verts = [mesh.verts.new(Vector(v)) for v in verts]
    for f in faces:
        try:
            mesh.faces.new([bm_verts[i] for i in f])
        except Exception:
            pass
    mesh.normal_update()
    bm_to_mesh = mesh
    bm_to_mesh.to_mesh(me)
    mesh.free()
    obj = bpy.data.objects.new(name, me)
    if coll:
        coll.objects.link(obj)
    else:
        bpy.context.scene.collection.objects.link(obj)
    if material is not None:
        me.materials.append(material)
    return obj


def uvsphere(radius=1.0, center=(0, 0, 0), nlat=24, nlon=48, axis='z',
             stretch=(1, 1, 1)):
    """Vertices/faces of a UV sphere. axis selects the polar axis."""
    verts = []
    idx = {}
    cx, cy, cz = center
    for i in range(nlat + 1):
        # theta from 0 (north pole) to pi (south)
        th = math.pi * i / nlat
        for j in range(nlon):
            ph = 2 * math.pi * j / nlon
            # unit sphere local coords with axis
            ux = math.sin(th) * math.cos(ph)
            uy = math.sin(th) * math.sin(ph)
            uz = math.cos(th)
            # remap to global axes based on polar axis
            if axis == 'z':
                v = Vector((ux, uy, uz))
            elif axis == 'y':
                v = Vector((ux, uz, uy))
            else:  # x
                v = Vector((uz, uy, ux))
            x = cx + v.x * radius * stretch[0]
            y = cy + v.y * radius * stretch[1]
            z = cz + v.z * radius * stretch[2]
            idx[(i, j)] = len(verts)
            verts.append((x, y, z))
    faces = []
    for i in range(nlat):
        for j in range(nlon):
            a = (i, j)
            b = (i, (j + 1) % nlon)
            c = (i + 1, (j + 1) % nlon)
            d = (i + 1, j)
            if i == 0:
                faces.append([idx[b], idx[c], idx[d]])
            elif i == nlat - 1:
                faces.append([idx[a], idx[b], idx[c]])
            else:
                faces.append([idx[a], idx[b], idx[c], idx[d]])
    return verts, faces


# ----------------------------------------------------------------------------
#  Materials
# ----------------------------------------------------------------------------
def _srgb(h):
    """Hex '#RRGGBB' or '#RRGGBBAA' -> linear (0..1)."""
    h = h.lstrip('#')
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b)


def srgb_to_linear(c):
    out = []
    for v in c:
        v = max(0.0, min(1.0, v))
        out.append(v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4)
    return tuple(out)


def make_bsdf(name, base='#ffffff', rough=0.45, spec=0.3, sub=0.0,
              sub_col='#ffd5b0', sheen=0.0, sheen_tint=0.0, clearcoat=0.0,
              gloss=0.0):
    """Create Principled BSDF material, return material."""
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    out = nodes.new('ShaderNodeOutputMaterial')
    p = nodes.new('ShaderNodeBsdfPrincipled')
    p.inputs['Base Color'].default_value = (*srgb_to_linear(_srgb(base)), 1.0)
    if 'Roughness' in p.inputs:
        p.inputs['Roughness'].default_value = rough
    if 'Specular IOR Level' in p.inputs:
        p.inputs['Specular IOR Level'].default_value = spec
    elif 'Specular' in p.inputs:
        p.inputs['Specular'].default_value = spec
    if 'Subsurface Weight' in p.inputs:
        p.inputs['Subsurface Weight'].default_value = sub
        if sub_col and 'Subsurface Color' in p.inputs:
            p.inputs['Subsurface Color'].default_value = \
                (*srgb_to_linear(_srgb(sub_col)), 1.0)
        elif sub_col and 'Subsurface Radius' in p.inputs:
            r = _srgb(sub_col)
            p.inputs['Subsurface Radius'].default_value = \
                (r[0]*0.5, r[1]*0.5, r[2]*0.5)
    if 'Sheen Weight' in p.inputs:
        p.inputs['Sheen Weight'].default_value = sheen
    if 'Sheen Tint' in p.inputs and sheen_tint:
        p.inputs['Sheen Tint'].default_value = (sheen_tint, sheen_tint, sheen_tint, 1.0)
    if 'Coat Weight' in p.inputs:
        p.inputs['Coat Weight'].default_value = clearcoat
    links.new(p.outputs['BSDF'], out.inputs['Surface'])
    mat.diffuse_color = (*_srgb(base), 1.0)
    return mat
