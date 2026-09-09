"""Feather islands engine - lets us emit many disconnected feather islands
that share one mesh object per region (efficient + individually smooth)."""
import math
from mathutils import Vector


def ortho_basis(tip, up):
    """Return (x_hat, y_lat, z_up) orthonormal triple given tip dir & approx up."""
    t = tip.normalized()
    n = up.normalized()
    y = t.cross(n)
    if y.length < 1e-6:
        # parallel - pick arbitrary
        ref = Vector((0, 0, 1))
        if abs(t.dot(ref)) > 0.99:
            ref = Vector((1, 0, 0))
        y = t.cross(ref).normalized()
    else:
        y = y.normalized()
    z = t.cross(y)  # re-orthogonalized "up" normal to feather plane
    return t, y, z


class FeatherRegion:
    """Accumulate feather islands; one material slot per face via mat index."""
    def __init__(self, name):
        self.name = name
        self.verts = []
        self.faces = []
        self.face_mat = []   # parallel to faces

    def feather(self, org, tip, up, W, L, down=0.0, u_seg=7, v_seg=3,
                mat=0, tip_split=0.0):
        """Add one feather island.
        org: Vector base. tip: Vector pointing toward tip (its length sets
        direction only; L = total length). up: approx normal (dorsal)."""
        t, y, z = ortho_basis(tip, up)
        # z is dorsal normal; make feathers curve so the tip lifts slightly
        # downward(-ish) = curve along -z is outwards droop; we lift tips:
        base = len(self.verts)
        T = L * t
        rows = u_seg + 1
        cols = v_seg + 1
        grid = [[None] * cols for _ in range(rows)]
        for i in range(rows):
            uu = i / u_seg  # 0 base ..1 tip
            # width taper profile: 0 at base, broad mid, →0 at tip
            prof = math.sin(math.pi * (0.03 + 0.97 * uu))
            if tip_split > 0:
                prof *= (1.0 - tip_split * uu)
            hw = 0.5 * W * prof
            # curvature along length (lift then settle)
            curl = down * math.sin(math.pi * (0.5 * uu)) * 4.0 * uu * (1.0 - 0.5 * uu)
            for j in range(cols):
                vv = j / v_seg
                side = (vv - 0.5) * 2.0
                basepos = Vector(org) + T * uu
                p = basepos + y * (side * hw)
                p = p + z * curl
                grid[i][j] = len(self.verts)
                self.verts.append(p)
        # faces: two triangles per quad, slight tip notch at center handled by
        # tapering profile already giving a clean pointed feather.
        for i in range(u_seg):
            for j in range(v_seg):
                a, b = grid[i][j], grid[i][j + 1]
                c, d = grid[i + 1][j + 1], grid[i + 1][j]
                self.faces.append([a, b, c])
                self.faces.append([a, c, d])
                self.face_mat.append(mat)
                self.face_mat.append(mat)

    def to_mesh(self, name, materials):
        import bpy
        me = bpy.data.meshes.new(name)
        me.from_pydata(self.verts, [], self.faces)
        me.update()
        for mat in materials:
            me.materials.append(mat)
        if self.face_mat and materials:
            nslots = len(materials)
            fml = []
            for m in self.face_mat:
                fml.append(m % nslots if m >= 0 else 0)
            me.polygons.foreach_set("material_index", fml)
        me.validate()
        # smooth shading
        for p in me.polygons:
            p.use_smooth = True
        obj = bpy.data.objects.new(name, me)
        return obj
