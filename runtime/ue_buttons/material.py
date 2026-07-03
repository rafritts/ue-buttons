"""`material` — the Material / Material Instance editors' surface (SPEC-05, born aligned).

NATIVE: drives `MaterialInstanceConstant` authoring (the Material Instance editor's job).
One op today — `op=instance` (moved from asset instance_material) — with `assign`/`params`
and the G40 motion-certificate reads to follow as SPEC-07 lands. Authors ASSETS, not the
level: no transaction, no history, no status block (same class as `asset`).
"""
import unreal

from . import _ue
from . import asset


def handle(p):
    fn = {"instance": _instance}.get(p.get("op", "instance"))
    if fn is None:
        return {"error": f"unknown material op '{p.get('op')}'. known: instance"}
    return fn(p)


def _instance(p):
    """G32(c) — MaterialEditingLibrary + AssetTools.create_asset. Author a
    MaterialInstanceConstant of a master with texture/scalar params —
    on-surface material authoring without raw editor Python. Param names are validated
    against the master BEFORE the asset is created, and every set is verified by READ-BACK
    (5.8's MaterialEditingLibrary setters return False even on success)."""
    parent_q, name = p.get("parent"), p.get("name")
    if not parent_q or not name:
        return {"error": "material op=instance requires parent= (a master material) and "
                         "name= (the new instance's asset name)"}
    ppath, cands = asset._resolve_asset_path(parent_q,
                                       classes=["Material", "MaterialInstanceConstant"])
    if ppath is None:
        if not cands:
            return {"error": f"no material matches '{parent_q}'"}
        return {"error": f"material '{parent_q}' is ambiguous", "candidates": cands[:10]}
    parent = _ue.load_asset(ppath)
    if parent is None:
        return {"error": f"could not load '{ppath}'"}
    mel = unreal.MaterialEditingLibrary
    base = parent.get_base_material()
    known = {"texture": [str(n) for n in mel.get_texture_parameter_names(base)],
             "scalar": [str(n) for n in mel.get_scalar_parameter_names(base)]}
    textures = p.get("textures") or {}
    scalars = p.get("scalars") or {}
    bad = ([k for k in textures if k not in known["texture"]]
           + [k for k in scalars if k not in known["scalar"]])
    if bad:
        return {"error": f"parameter(s) {bad} don't exist on master "
                         f"'{base.get_name()}' — a wrong name silently no-ops",
                "available": known}
    tex_assets = {}
    for k, tq in textures.items():
        tpath, tc = asset._resolve_asset_path(tq, classes=["Texture2D"])
        if tpath is None:
            if not tc:
                return {"error": f"no texture matches '{tq}'"}
            return {"error": f"texture '{tq}' is ambiguous", "candidates": tc[:10]}
        t = _ue.load_asset(tpath)
        if t is None:
            return {"error": f"could not load texture '{tpath}'"}
        tex_assets[k] = t
    folder = (p.get("folder") or "/Game/UEB_Materials").rstrip("/")
    full = f"{folder}/{name}"
    if _ue.load_asset(full) is not None:
        return {"error": f"'{full}' already exists — pick a new name"}
    at = unreal.AssetToolsHelpers.get_asset_tools()
    mi = at.create_asset(name, folder, unreal.MaterialInstanceConstant,
                         unreal.MaterialInstanceConstantFactoryNew())
    if mi is None:
        return {"error": f"asset creation failed for {full}"}
    mel.set_material_instance_parent(mi, parent)
    for k, t in tex_assets.items():
        mel.set_material_instance_texture_parameter_value(mi, k, t)
    for k, v in scalars.items():
        mel.set_material_instance_scalar_parameter_value(mi, k, float(v))
    unreal.EditorAssetLibrary.save_asset(full)
    # read back — the setters' return values lie in 5.8; the stored values don't
    applied_tex = {}
    for tp in mi.get_editor_property("texture_parameter_values"):
        pn = str(tp.get_editor_property("parameter_info").get_editor_property("name"))
        pv = tp.get_editor_property("parameter_value")
        applied_tex[pn] = pv.get_name() if pv else None
    applied_sca = {}
    for sp in mi.get_editor_property("scalar_parameter_values"):
        pn = str(sp.get_editor_property("parameter_info").get_editor_property("name"))
        applied_sca[pn] = sp.get_editor_property("parameter_value")
    missing = ([k for k in tex_assets if applied_tex.get(k) != tex_assets[k].get_name()]
               + [k for k in scalars if k not in applied_sca])
    out = {"created": full, "parent": ppath,
           "applied": {"textures": applied_tex, "scalars": applied_sca}}
    if missing:
        out["warning"] = f"read-back missing/mismatched: {missing} — the set did NOT take"
    vet = asset._describe_material(full, {"asset": name, "path": full,
                                    "class": "MaterialInstanceConstant"})
    if vet.get("warnings"):
        out["warnings"] = vet["warnings"]
    return out
