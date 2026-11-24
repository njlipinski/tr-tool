"""Read the installed game's Unity files. Read-only: nothing here writes to the install.

This package is the only code that knows game-file names and field names.
UnityPy (and TypeTreeGeneratorAPI, because the game's type trees are stripped)
are imported only inside the functions that need them.
"""
import collections
import csv
import os

INSTALL_HINT = ("This command needs UnityPy and TypeTreeGeneratorAPI:\n"
                "  python -m pip install --user UnityPy TypeTreeGeneratorAPI")


class GameDirError(Exception):
    pass


def _unitypy():
    try:
        import UnityPy  # noqa: F401
        from UnityPy.helpers.TypeTreeGenerator import TypeTreeGenerator  # noqa: F401
        import TypeTreeGeneratorAPI  # noqa: F401
    except ImportError:
        raise SystemExit(INSTALL_HINT)
    return UnityPy, TypeTreeGenerator


def locate_data_dir(game_dir):
    """The Unity `<Game>_Data` folder for an install.

    Accepts the `*_Data` folder itself, the folder holding it, or an install root
    with one platform subfolder in between (Steam puts it under `Windows\\`).
    """
    if not game_dir or not os.path.isdir(game_dir):
        raise GameDirError("Game folder not found: %r" % game_dir)
    game_dir = os.path.abspath(game_dir)
    if game_dir.endswith("_Data") and os.path.isdir(os.path.join(game_dir, "Managed")):
        return game_dir

    def data_children(d):
        try:
            names = os.listdir(d)
        except OSError:
            return []
        return [os.path.join(d, n) for n in names
                if n.endswith("_Data") and os.path.isdir(os.path.join(d, n))]

    found = data_children(game_dir)
    if not found:
        for n in os.listdir(game_dir):
            sub = os.path.join(game_dir, n)
            if os.path.isdir(sub):
                found += data_children(sub)
    if not found:
        raise GameDirError("No *_Data folder under %s" % game_dir)
    if len(found) > 1:
        raise GameDirError("Several *_Data folders under %s: %s" % (game_dir, ", ".join(found)))
    return found[0]


def asset_files(data_dir):
    """Serialized asset files in load order: globalgamemanagers, level*, *.assets."""
    names = os.listdir(data_dir)

    def key(n):
        stem = n.split(".")[0]
        digits = "".join(c for c in stem if c.isdigit())
        return (0 if n.startswith("globalgamemanagers") else 1 if n.startswith("level") else 2,
                stem.rstrip("0123456789"), int(digits) if digits else -1, n)

    keep = [n for n in names
            if n == "globalgamemanagers" or n.endswith(".assets")
            or (n.startswith("level") and n[5:].isdigit())]
    return [os.path.join(data_dir, n) for n in sorted(keep, key=key)]


def unity_version(data_dir):
    UnityPy, _ = _unitypy()
    env = UnityPy.load(os.path.join(data_dir, "globalgamemanagers"))
    return next(iter(env.files.values())).unity_version


def typetree_generator(data_dir, version=None):
    """A generator loaded with the game's Managed DLLs (needed: type trees are stripped)."""
    _, TypeTreeGenerator = _unitypy()
    gen = TypeTreeGenerator(version or unity_version(data_dir))
    gen.load_local_dll_folder(os.path.join(data_dir, "Managed"))
    return gen


def _objects_of_class(sf, class_name):
    """MonoBehaviours in one serialized file whose script class is class_name.

    Resolve script names before attaching a type-tree generator: with one
    attached, cross-file script pointers fail to resolve in UnityPy 1.25.
    """
    groups = collections.defaultdict(list)
    for o in sf.objects.values():
        if o.type.name == "MonoBehaviour" and o.serialized_type:
            groups[o.serialized_type.script_type_index].append(o)
    out = []
    for objs in groups.values():
        try:
            if _script_name(objs[0])[0] == class_name:
                out += objs
        except Exception:
            continue
    return out


def game_version(data_dir, gen=None):
    """The game's own version, e.g. '0.7.6.19' (VersionNumberManager in level1).

    PlayerSettings.bundleVersion is just '0.1' in this game, so don't use it.
    """
    UnityPy, _ = _unitypy()
    env = UnityPy.load(os.path.join(data_dir, "level1"))
    sf = next(iter(env.files.values()))
    objs = _objects_of_class(sf, "VersionNumberManager")
    if not objs:
        return None
    env.typetree_generator = gen or typetree_generator(data_dir, sf.unity_version)
    nums = objs[0].read_typetree().get("versionNumber") or []
    while len(nums) > 4 and nums[-1] == 0:   # stored as [0, 7, 6, 19, 0]
        nums = nums[:-1]
    return ".".join(str(n) for n in nums) or None


def _script_name(obj):
    sc = obj.read(check_read=False).m_Script.read()
    ns = sc.m_Namespace
    return ("%s.%s" % (ns, sc.m_ClassName) if ns else sc.m_ClassName), sc.m_AssemblyName


def explore(data_dir, out_dir, files=None, log=print):
    """Inventory of every asset file. Writes two TSVs into out_dir:

    object_types.tsv   file, type, count
    scripts.tsv        file, class, assembly, count   (MonoBehaviour classes)
    """
    UnityPy, _ = _unitypy()
    os.makedirs(out_dir, exist_ok=True)
    type_rows, script_rows = [], []
    for path in files or asset_files(data_dir):
        name = os.path.basename(path)
        env = UnityPy.load(path)
        sf = next(iter(env.files.values()))
        types = collections.Counter()
        by_script = collections.defaultdict(list)
        for o in sf.objects.values():
            types[o.type.name] += 1
            if o.type.name == "MonoBehaviour":
                st = o.serialized_type
                by_script[st.script_type_index if st else -1].append(o)
        for t, n in sorted(types.items()):
            type_rows.append({"file": name, "type": t, "count": n})
        for idx, objs in by_script.items():
            try:
                cls, asm = _script_name(objs[0])
            except Exception as e:  # unresolvable script reference
                cls, asm = "<unresolved %s>" % type(e).__name__, ""
            script_rows.append({"file": name, "class": cls, "assembly": asm, "count": len(objs)})
        log("%-28s %7d objects, %6d MonoBehaviours, type trees: %s"
            % (name, sum(types.values()), types.get("MonoBehaviour", 0),
               "yes" if getattr(sf, "_enable_type_tree", False) else "no"))
    _write(os.path.join(out_dir, "object_types.tsv"), ["file", "type", "count"], type_rows)
    _write(os.path.join(out_dir, "scripts.tsv"), ["file", "class", "assembly", "count"],
           sorted(script_rows, key=lambda r: (r["class"], r["file"])))
    return {"files": len({r["file"] for r in type_rows}), "script_classes": len({r["class"] for r in script_rows})}


def _write(path, fields, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
