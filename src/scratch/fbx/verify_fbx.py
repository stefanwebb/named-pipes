"""Re-import cskel27.fbx and check rig + skin against skin_standard.npz.
Also poses the re-imported rig (rotate RightArm 60deg about the bone) and compares
Blender's skinning result to a numpy LBS using Ardy's bind data."""
import json, sys, bpy
import numpy as np
from mathutils import Vector, Matrix
argv = sys.argv[sys.argv.index("--") + 1:]
data = json.load(open(argv[0])); skin = np.load(argv[1])
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=argv[2])
arm = [o for o in bpy.data.objects if o.type == "ARMATURE"][0]
mesh_obj = [o for o in bpy.data.objects if o.type == "MESH"][0]
names = [j["name"] for j in data["joints"]]
def to_ardy(v): return np.array([v.x, v.z, -v.y])

# 1. bones
bind_pos = skin["bind_rig_transform"][:, :3, 3]
err = max(np.linalg.norm(to_ardy(arm.matrix_world @ arm.data.bones[n].head_local) - bind_pos[i]) for i, n in enumerate(names))
parents_ok = all((arm.data.bones[j["name"]].parent.name if arm.data.bones[j["name"]].parent else None) == j["parent"] for j in data["joints"])
print(f"bones: {len(arm.data.bones)}  max head err {err:.2e} m  parents ok: {parents_ok}")

# 2. mesh + weights
me = mesh_obj.data
mw = mesh_obj.matrix_world
verr = max(np.linalg.norm(to_ardy(mw @ v.co) - skin["bind_vertices"][v.index]) for v in me.vertices)
gi = {g.index: g.name for g in mesh_obj.vertex_groups}
W = np.zeros((len(me.vertices), 27))
for v in me.vertices:
    for g in v.groups:
        W[v.index, names.index(gi[g.group])] += g.weight
Wref = np.zeros_like(W)
for k in range(skin["lbs_indices"].shape[1]):
    np.add.at(Wref, (np.arange(len(W)), skin["lbs_indices"][:, k]), skin["lbs_weights"][:, k])
print(f"mesh: {len(me.vertices)} verts {len(me.polygons)} faces  max bind-vertex err {verr:.2e} m  max weight err {np.abs(W-Wref).max():.2e}")

# 3. pose test: rotate RightArm by 60deg about its local Y, compare skinning
bpy.context.view_layer.objects.active = arm
pb = arm.pose.bones["RightArm"]
pb.rotation_mode = "XYZ"; pb.rotation_euler = (0.0, 1.0472, 0.0)
bpy.context.view_layer.update()
dg = bpy.context.evaluated_depsgraph_get()
posed = np.array([to_ardy(mw @ v.co) for v in mesh_obj.evaluated_get(dg).data.vertices])

# reference LBS in Ardy space: M_j = world transform of joint j now, B_j = bind
B = skin["bind_rig_transform"]
# Blender world matrices for bones -> Ardy space via change of basis C (blender->ardy)
C = np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]], float)   # (x,y,z)_b -> (x, z, -y)
Ci = np.linalg.inv(C)
M = []
for i, n in enumerate(names):
    rest = np.array(arm.matrix_world @ arm.data.bones[n].matrix_local)
    now = np.array(arm.matrix_world @ arm.pose.bones[n].matrix)
    delta_b = now @ np.linalg.inv(rest)          # world-space delta in blender coords
    M.append(C @ delta_b @ Ci @ B[i])             # apply the same delta to ardy bind frame
M = np.array(M)
A = M @ np.linalg.inv(B)                         # [27,4,4] skinning matrices
V = np.c_[skin["bind_vertices"], np.ones(len(skin["bind_vertices"]))]
ref = np.zeros((len(V), 3))
for k in range(skin["lbs_indices"].shape[1]):
    idx, w = skin["lbs_indices"][:, k], skin["lbs_weights"][:, k]
    ref += w[:, None] * np.einsum("vij,vj->vi", A[idx][:, :3, :], V)
moved = np.linalg.norm(ref - skin["bind_vertices"], axis=1).max()
print(f"pose test: max vertex displacement {moved:.3f} m, max blender-vs-ardy LBS err {np.abs(posed-ref).max():.2e} m")
