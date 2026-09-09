"""
Build 小鹰 (XiaoYing) 3D mascot - flying pose (展翅).
Reference colours decoded from public/images/小鹰/*.png:
  big white head + dark round eyes + yellow/orange small beak +
  brown feathered body & wings + yellow feet.

Usage (from repo root):
   bash scripts/3d/_env.sh scripts/3d/build_xiaoying.py  [out.blend]
"""
import sys, math
import bpy
from mathutils import Vector

sys.path.insert(0, "scripts/3d")
import xiaoying_utils as U
from xiaoying_utils import make_bsdf, link_object
import xiaoying_feathers as F

OUT = sys.argv[1] if len(sys.argv) > 1 else "小鹰3D模型/小鹰_3D.blend"

U.fresh_scene()
rootcol = U.new_collection("小鹰")
master = U.make_empty("小鹰_XiaoYing_root", coll=rootcol)

# ------------------------------------------------------------------- materials
def mk(name, *a, **k): return make_bsdf(name, *a, **k)
M_white   = mk("脸_白", base="#F6F1E4", rough=0.5, sub=0.4, sub_col="#EDE0C6", sheen=0.5)
M_white2  = mk("绒_白", base="#F0EAD8", rough=0.85, sub=0.5, sub_col="#E4D4B6", sheen=0.7)
M_cream   = mk("绒_米", base="#ECE2C8", rough=0.85, sub=0.5, sub_col="#DDCBA4", sheen=0.7)
M_cream2  = mk("绒_浅米", base="#F3EBD7", rough=0.85, sub=0.5, sub_col="#E5D5B4", sheen=0.7)
M_skin    = mk("肤_白", base="#FBF7EC", rough=0.4, sub=0.3, sub_col="#EADCC2")
M_under   = mk("绒底_深棕", base="#51381F", rough=0.9, sub=0.5, sub_col="#76532E", sheen=0.6)
M_brown_d = mk("羽_深棕", base="#4A331D", rough=0.82, sub=0.3, sub_col="#6a4a2c", sheen=0.6)
M_brown   = mk("羽_棕", base="#6F4E2F", rough=0.78, sub=0.3, sub_col="#8A5F3A", sheen=0.55)
M_brown_l = mk("羽_浅棕", base="#8E6238", rough=0.78, sub=0.3, sub_col="#A57449", sheen=0.5)
M_wing_top  = mk("翼_顶", base="#6C492A", rough=0.7, sub=0.25, sub_col="#8A5F3A", sheen=0.5)
M_wing_under= mk("翼_底", base="#CEC2A6", rough=0.8, sub=0.4, sub_col="#B7A585", sheen=0.5)
M_tail    = mk("尾羽", base="#61431F", rough=0.78, sub=0.25, sub_col="#7A5736", sheen=0.5)
M_tailbar = mk("尾纹", base="#33200D", rough=0.82, sub=0.2, sub_col="#5A3A1E", sheen=0.5)
M_beak    = mk("喙", base="#F0A63A", rough=0.3, sub=0.15, sub_col="#FFB85C", clearcoat=0.5)
M_beak_hi = mk("喙亮", base="#F5B642", rough=0.25, sub=0.12, sub_col="#FFD07A", clearcoat=0.6)
M_mouth   = mk("口", base="#73251B", rough=0.4, sub=0.35, sub_col="#A53A2C")
M_eye     = mk("眼", base="#191611", rough=0.12, sub=0.0, clearcoat=1.0)
M_eye_hi  = mk("眼高光", base="#FFFFFF", rough=0.05, sub=0.0, clearcoat=1.0)
M_leg     = mk("腿", base="#E8A93E", rough=0.4, sub=0.2, sub_col="#F3C063")
M_leg_hi  = mk("腿亮", base="#F0B64E", rough=0.35, sub=0.18, sub_col="#F7CD80")
M_talon   = mk("爪", base="#2B2620", rough=0.3, sub=0.1, sub_col="#54493C")

def place(obj, loc=None, rot=None, scl=None, parent=None):
    if loc: obj.location = Vector(loc)
    if rot: obj.rotation_euler = Vector(rot)
    if scl: obj.scale = Vector(scl)
    if parent: obj.parent = parent
    return obj

def smooth_mesh_from(uv, name, mat, parent, loc=None, scl=None, rot=None):
    verts, faces = uv
    o = U.bmesh_from_objs(name, verts, faces, coll=rootcol, material=mat)
    place(o, loc, rot, scl, parent)
    return o

def ellipsoid(name, mat, center, half, rot=(0, 0, 0), parent=None, nlat=22, nlon=40):
    """axis-aligned then rotated ellipsoid built from unit sphere."""
    uv = U.uvsphere(1.0, nlat=nlat, nlon=nlon)
    o = smooth_mesh_from(uv, name, mat, parent, loc=center, scl=half, rot=rot)
    return o

def ellipsoid_along(name, mat, center, dirvec, half_long, half_b, half_c,
                    up_ref=(0, 0, 1), parent=None):
    """Ellipsoid whose major (scaled by half_long) axis aligns with dirvec."""
    d = Vector(dirvec).normalized()
    u = Vector(up_ref)
    x = d
    z = x.cross(u)
    if z.length < 1e-5:
        z = x.cross(Vector((1, 0, 0)))
    z = z.normalized()
    y = z.cross(x)
    # build a 3x3 rotation matrix (row-major columns)
    R = [[x[0], y[0], z[0]],
         [x[1], y[1], z[1]],
         [x[2], y[2], z[2]]]
    uv = U.uvsphere(1.0, nlat=20, nlon=36)
    verts = []
    # transform unit sphere verts
    for vv in uv[0]:
        v = Vector(vv)
        nv = Vector((R[0][0]*v[0]+R[0][1]*v[1]+R[0][2]*v[2],
                     R[1][0]*v[0]+R[1][1]*v[1]+R[1][2]*v[2],
                     R[2][0]*v[0]+R[2][1]*v[1]+R[2][2]*v[2]))
        # scale: long axis (x local) half_long, y->half_b, z->half_c
        nv = Vector((nv[0]*half_long, nv[1]*half_b, nv[2]*half_c)) + Vector(center)
        verts.append(nv)
    o = U.bmesh_from_objs(name, verts, uv[1], coll=rootcol, material=mat)
    place(o, parent=parent)
    return o

# ============================================================ TORSO (brown)
Tc = Vector((0, -0.02, 0.72))
t_half = Vector((0.52, 0.47, 0.55))
torso = ellipsoid("身体_躯干", M_brown, Tc, t_half)
# belly highlight (soft lighter band front) optional none

# white / cream upper-chest smooth overlay (front, so head white flows into body)
chest_c = Vector((0, 0.28, 1.12))
chest = ellipsoid("身体_前胸", M_cream, chest_c,
                  (0.36, 0.26, 0.30))

# ============================================================ HEAD white
H = Vector((0.0, 0.16, 1.78))
lat, lon = 42, 60
hv, hf = U.uvsphere(1.0, nlat=lat, nlon=lon)
head_verts = []
for vv in hv:
    v = Vector(vv)
    # vertical (z) shaping: slight egg + taper toward neck (bottom, z<0)
    z = v.z
    if z < -0.05:
        t = (-0.05 - z) / 0.95
        # pull bottom inward & shorten so head settles onto shoulders
        v = Vector((v.x*(1-0.1*t), v.y*(1-0.12*t), v.z*(1-0.42*t)))
        # shift down so neck region meets chest not torso center
    head_verts.append(H + v*0.60)
head = U.bmesh_from_objs("头_大圆脸", head_verts, hf, coll=rootcol, material=M_white)
place(head, scl=(1.06, 1.0, 1.05), parent=master)

# ---- eyes (on front face, near top of the round face) ----
def face_dir(dx, dy, dz):
    d = Vector((dx, dy, dz)).normalized()
    return H + d*0.60*1.02
for sgn in (-1, 1):
    c = face_dir(sgn*0.42, 0.86, 0.30)
    eye = ellipsoid("眼睛", M_eye, c, (0.105, 0.135, 0.11), parent=master)
    hi = ellipsoid("眼_高光", M_eye_hi, c + Vector((sgn*0.04, 0.10, 0.05)),
                   (0.035, 0.03, 0.035), parent=master)
    # brow feather tuft
    bc = face_dir(sgn*0.6, 0.5, 0.6)
    r = F.FeatherRegion("x")
    r.feather(Vector(bc), Vector((sgn*0.5, -0.15, 0.75)), Vector((0, 0, 1)),
              0.20, 0.22, down=0.01, u_seg=6, v_seg=3)
    ob = r.to_mesh("眉羽", [M_white2]); place(ob, parent=master)
    # We can't reliably parent region-mesh parent here (created without), so set:
    rootcol.objects.link(ob)

# ---- beak (pointed cone, revolve around forward +Y) ----
def beak_cone(local_pts, base_open=True, nseg=24):
    verts, faces = [], []
    idx = {}
    def pt(y, rad, j):
        ph = 2*math.pi*j/nseg
        return (math.cos(ph)*rad, y, math.sin(ph)*rad)
    nr = len(local_pts)
    for i, (y, rad) in enumerate(local_pts):
        for j in range(nseg):
            verts.append(pt(y, rad, j)); idx[(i, j)] = len(verts)-1
    for i in range(nr-1):
        for j in range(nseg):
            j2 = (j+1) % nseg
            a, b = idx[(i, j)], idx[(i+1, j)]
            c, d = idx[(i+1, j2)], idx[(i, j2)]
            faces.append([a, b, c, d])
    # tip cap
    if local_pts[-1][1] < 1e-5:
        tipv = len(verts); verts.append(pt(local_pts[-1][0], 0, 0))
        for j in range(nseg):
            faces.append([tipv, idx[(nr-1, (j+1) % nseg)], idx[(nr-1, j)]])
    if not base_open and local_pts[0][1] > 1e-5:
        bv = len(verts); verts.append(pt(local_pts[0][0], 0, 0))
        for j in range(nseg):
            faces.append([bv, idx[(0, j)], idx[(0, (j+1) % nseg)]])
    return verts, faces

# upper beak, built pointing +Y then tilted slightly down
up_beak = beak_cone([(0, 0.145), (0.18, 0.135), (0.40, 0.105), (0.60, 0.055),
                     (0.72, 0.008)])
ub = smooth_mesh_from(up_beak, "喙_上", M_beak, master, loc=(0, 0.42, 1.52))
ub.rotation_euler = (math.radians(-30), 0, 0)   # tip dips downward/forward
# glossy ridge
ub_hi = smooth_mesh_from(up_beak, "喙_上亮", M_beak_hi, master,
                         loc=(0, 0.45, 1.55))
ub_hi.rotation_euler = (math.radians(-32), 0, 0)
ub_hi.scale = (0.8, 0.92, 0.86)
# lower beak
lo_beak = beak_cone([(0, 0.08), (0.12, 0.075), (0.28, 0.045), (0.40, 0.006)])
lb = smooth_mesh_from(lo_beak, "喙_下", M_beak, master, loc=(0, 0.36, 1.42))
lb.rotation_euler = (math.radians(-28), 0, 0)
# open-mouth dark slit
mouth = ellipsoid("嘴角_开口", M_mouth, (0, 0.72, 1.40), (0.02, 0.10, 0.045),
                  rot=(math.radians(-30), 0, 0), parent=master)

# ---- crown / nape little feather tufts (top of head) ----
tuft_r = F.FeatherRegion("tufts")
for i in range(6):
    ang = -0.5 + i/5.0
    cx = math.sin(ang)*0.16
    cz = 0.95
    org = H + Vector((cx, 0.05, cz))
    tip = H + Vector((cx*1.3, 0.05, cz+0.6)) - Vector((0, 0, 0.5))
    tuft_r.feather(org, tip-org, Vector((0, 0, 1)), 0.16, 0.34, down=0.0,
                   u_seg=7, v_seg=3)
tuft = tuft_r.to_mesh("头顶冠羽", [M_white2]); place(tuft, parent=master)

print("[ok] head, face, beak")

# ============================================================ BODY FEATHERS
def cover_torso():
    reg = F.FeatherRegion("bodyfeathers")
    reg2 = F.FeatherRegion("chestfeathers")
    rows = 26
    matbrown = [0, 0, 1, 0, 0, 1, 2, 2]      # mix deep/brown/light-brown
    for i in range(rows):
        # colatitude: start just below shoulders going to belly
        th0 = math.radians(78) - (i/rows)*math.radians(96)   # ~78deg..-18
        th = th0
        cos_th = math.cos(th); sin_th = math.sin(th)
        # number around varies
        n = 26 + int(6*sin_th)
        for j in range(n):
            ph = 2*math.pi*j/n
            d = Vector((math.cos(ph)*sin_th, math.sin(ph)*sin_th, cos_th))
            # world dir = Tc + d*(half)  -> surface point
            sp = Tc + Vector((d.x*t_half.x, d.y*t_half.y, d.z*t_half.z))
            nrm = Vector((d.x/t_half.x, d.y/t_half.y, d.z/t_half.z)).normalized()
            # skip the smooth neck zone (top) and belly floor? handled by range
            # feather length scale with distance from top pole
            scale = 0.12 + 0.06*(1 - cos_th)
            L = 0.20*scale + 0.06
            W = 0.17*scale + 0.05
            org = sp
            # tip points outward + slightly down
            tip = org + nrm*L
            # decide chest (front centre, upper) cream vs brown sides/back
            front = (ph > -1.1 and ph < 1.1) and cos_th < 0.6 and th > math.radians(15)
            down_val = -0.05
            if front and not (cos_th > 0.15):
                reg2.feather(org, tip, Vector((0, 0, 1)), W, L, down=down_val,
                             u_seg=6, v_seg=3, mat=0 if j % 2 else 1)
            else:
                reg.feather(org, tip, Vector((0, 0, 1)), W, L, down=down_val,
                            u_seg=6, v_seg=3, mat=matbrown[(i + j) % len(matbrown)])
    # lower belly is feathered all round brown; chest cream on front upper part
    b = reg.to_mesh("体羽_背侧", [M_brown_d, M_brown, M_brown_l])
    rootcol.objects.link(b); place(b, parent=master)
    c = reg2.to_mesh("体羽_前胸", [M_cream, M_cream2])
    rootcol.objects.link(c); place(c, parent=master)
cover_torso()
print("[ok] torso feathers")

# ============================================================ WINGS (mirror)
def build_wing(sgn):
    """sgn +1 = bird's right wing (extends toward -Y? choose outward x=sgn)."""
    # Shoulder anchor near upper side of torso
    S = Vector((sgn*0.52, 0.02, 1.28))
    # wing tip (outer & up)
    T = Vector((sgn*2.05, -0.15, 1.75))
    arm = T - S
    armL = arm.length
    mid = (S + T) * 0.5
    # main feathered wing blade
    wing = ellipsoid_along(f"翼{sgn}", M_wing_top, mid, arm,
                           armL*0.55, 0.42, 0.11,
                           up_ref=(0, 0, 1), parent=master)
    # soft pale underwing panel slightly below the blade
    under_c = mid + Vector((0, 0, -0.10))
    under = ellipsoid_along(f"翼下{sgn}", M_wing_under, under_c, arm,
                            armL*0.50, 0.36, 0.10, up_ref=(0, 0, 1), parent=master)
    # coverts: small overlapping feathers on the top surface of the inner wing
    cr = F.FeatherRegion("x")
    d = arm.normalized()
    n_up = Vector((0, 0, 1))
    row_up = n_up.cross(d)
    if row_up.length < 1e-5:
        row_up = d.cross(Vector((1, 0, 0)))
    row_up = row_up.normalized()
    outer = d.cross(row_up).normalized()  # dorsal normal
    for k in range(5):
        tt = 0.08 + k*0.12
        basep = S + d*(armL*tt)
        for ww in range(3):
            side = (ww-1)*0.5
            org = basep + row_up*side
            Lf = (0.45 - 0.07*k)
            Wf = 0.30
            tipd = d - outer*(0.18)
            cr.feather(org + outer*0.02, tipd, outer, Wf, Lf, down=0.05,
                       u_seg=6, v_seg=3, mat=0 if (k+ww) % 2 else 1)
    cb = cr.to_mesh(f"翼羽_覆羽{sgn}", [M_wing_top, M_brown_l, M_brown])
    rootcol.objects.link(cb); place(cb, parent=master)
    # primary feather fan at outer hand, real long feather blades radiating
    pf = F.FeatherRegion("x")
    wrist = S + d*(armL*0.68)
    # wrist slightly inset; primaries radiate around outward+up
    nprim = 9
    for p in range(nprim):
        tt = p/(nprim-1)
        ang = -0.35 + tt*0.7      # spread
        fdir = Vector((sgn*math.cos(ang), 0, math.sin(ang)))
        # feathers all point outward & upward-ish, lying in near vertical fan
        org = wrist
        Lf = 0.95 + 0.0*(1 - abs(tt-0.5)*2)
        pf.feather(org, fdir + Vector((0, -0.05, 0)), Vector((sgn*0.0, 0, 1)),
                   0.30, Lf, down=-0.02, u_seg=9, v_seg=4,
                   mat=0)
    pb = pf.to_mesh(f"翼羽_飞羽{sgn}", [M_wing_top, M_brown_l])
    rootcol.objects.link(pb); place(pb, parent=master)
    return S, T

build_wing(1)
build_wing(-1)
print("[ok] wings")

# ============================================================ TAIL feathers
def build_tail():
    reg = F.FeatherRegion("tailfeathers")
    base = Vector((0, -0.52, 0.30))
    n = 15
    for i in range(n):
        tt = i/(n-1) if n > 1 else 0.5
        # spread across X, all pointing back (-Y) & slightly down/up
        sxa = -0.85 + tt*1.7
        dirv = Vector((math.sin(sxa)*0.9, -1.0, -0.25 + (tt-0.5)*0.4))
        Lf = 0.55 + 0.25*(1-abs(tt-0.5)*2) + 0.3
        org = base + Vector((math.sin(sxa)*0.5, 0, (tt-0.5)*0.1))
        reg.feather(org, dirv, Vector((0, -0.6, 1.0)), 0.34, Lf, down=-0.03,
                    u_seg=8, v_seg=3, mat=0 if i % 3 else 1)
    tb = reg.to_mesh("尾羽_扇", [M_tail, M_brown_l])
    rootcol.objects.link(tb); place(tb, parent=master)
build_tail()
print("[ok] tail")

# ============================================================ LEGS / talons
def build_foot(sgn):
    # thigh
    th = ellipsoid(f"腿{sgn}", M_leg, (sgn*0.22, -0.02, 0.30), (0.10, 0.14, 0.16),
                   rot=(math.radians(20), 0, math.radians(sgn*-8)), parent=master)
    # 3 forward toes + hallux, each = small ellipsoid + dark claw cone
    toes = [((0.06, 0.02, -0.16), (0.05, 0.12, 0.035), (0.05, 0.04, 0.05)),
            ((-0.02, 0.03, -0.16), (0.05, 0.12, 0.035), (0.05, 0.04, 0.05)),
            ((0.02, 0.06, -0.16), (0.05, 0.12, 0.035), (0.05, 0.04, 0.05))]
    for (lx, ly, lz), half, cscale in toes:
        center = (sgn*(0.20+lx), ly, 0.30+lz)
        to = ellipsoid(f"趾{sgn}", M_leg, center, half, parent=master)
        to.rotation_euler = (math.radians(-80), 0, math.radians(sgn*8))
build_foot(1)
build_foot(-1)
print("[ok] legs")

# parent everything already linked to rootcol under master but ensure:
for o in list(rootcol.objects):
    if o.parent is None and o != master:
        o.parent = master

print("[model] built")

# ============================================================ SCENE / light
def scene_setup():
    scn = bpy.context.scene
    scn.render.engine = 'CYCLES'
    scn.cycles.device = 'CPU'
    scn.cycles.samples = 96
    # world soft gradient
    world = scn.world
    world.use_nodes = True
    nt = world.node_tree
    for n in list(nt.nodes):
        nt.nodes.remove(n)
    out = nt.nodes.new('ShaderNodeOutputWorld')
    bg = nt.nodes.new('ShaderNodeBackground')
    bg.inputs['Color'].default_value = (0.82, 0.87, 0.94, 1.0)
    bg.inputs['Strength'].default_value = 1.0
    nt.links.new(bg.outputs['Background'], out.inputs['Surface'])
    # lights
    from mathutils import Vector as _V
    li = bpy.data.objects.get('Light')
    if li:
        li.data.energy = 400
        li.location = _V((3.5, -3, 5))
    # extra fill + rim
    def light(name, loc, energy=200, color=(1, 1, 1)):
        la = bpy.data.lights.new(name, 'AREA')
        la.energy = energy
        la.color = color
        ob = bpy.data.objects.new(name, la)
        ob.location = _V(loc)
        rootcol.objects.link(ob)
        ob.rotation_euler = (_V(loc)-_V((0, 0, 0.8))).normalized().to_track_quat('Z','Y').to_euler()
        return ob
    light("主光", (4, 3, 5), 900)
    light("补光", (-4, -2, 3), 500, color=(0.85, 0.9, 1.0))
    light("轮廓", (0, -5, 2.5), 300, color=(1.0, 0.9, 0.8))
    # camera (create - factory reset had no camera)
    cam_data = bpy.data.cameras.new("Camera")
    cam_data.lens = 55
    cam = bpy.data.objects.new("Camera", cam_data)
    rootcol.objects.link(cam)
    cam.location = _V((5.0, -4.3, 2.3))
    look = (_V((0, -0.1, 1.25)) - cam.location).normalized()
    cam.rotation_euler = look.to_track_quat('-Z', 'Y').to_euler()
    scn.camera = cam
    # soft round pedestal ground
    M_floor = make_bsdf("台座", base="#3b414a", rough=0.4, spec=0.0)
    bpy.ops.mesh.primitive_cylinder_add(vertices=64, radius=1.7, depth=0.10,
                                        location=(0, 0.1, -0.14))
    fl = bpy.context.object
    fl.name = "台座"
    if fl.data.materials:
        fl.data.materials[0] = M_floor
    else:
        fl.data.materials.append(M_floor)

scene_setup()
print("[ok] scene")

# --- stats (data only; avoid matrix/bound_box which crashes this bpy build) ---
mobjs = [o for o in bpy.data.objects if o.type == 'MESH']
print("[stats] mesh_objects=%d total_polys=%d"
      % (len(mobjs), sum(len(o.data.polygons) for o in mobjs)))

bpy.ops.wm.save_as_mainfile(filepath=OUT)
print("SAVED:", OUT)
