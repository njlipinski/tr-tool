"""Thin layer over UnityPy: load asset files, resolve pointers, read game objects.

Pointers (PPtr) are resolved by hand to (file name, path id) keys, so objects
from different files can be joined without UnityPy's environment lookups.
"""
import collections
import os

from . import _unitypy, typetree_generator


class Game:
    def __init__(self, data_dir, files, gen=None):
        UnityPy, _ = _unitypy()
        self.data_dir = data_dir
        self.files = {}         # name -> SerializedFile
        self.externals = {}     # name -> [external file names]
        self.classes = {}       # (file, path_id) -> script class name, MonoBehaviours only
        self.scripts = set()    # (assembly, full class name) seen
        self._cache = {}
        envs = []
        for name in files:
            env = UnityPy.load(os.path.join(data_dir, name))
            sf = next(iter(env.files.values()))
            self.files[name] = sf
            self.externals[name] = [os.path.basename(e.path) for e in sf.externals]
            envs.append(env)
            self._index_classes(name, sf)
        # Script names must be resolved before a generator is attached (UnityPy quirk).
        gen = gen or typetree_generator(data_dir, next(iter(self.files.values())).unity_version)
        for env in envs:
            env.typetree_generator = gen
        self.gen = gen

    def _index_classes(self, name, sf):
        groups = collections.defaultdict(list)
        for o in sf.objects.values():
            if o.type.name == "MonoBehaviour" and o.serialized_type:
                groups[o.serialized_type.script_type_index].append(o)
        for objs in groups.values():
            try:
                sc = objs[0].read(check_read=False).m_Script.read()
            except Exception:
                continue
            full = "%s.%s" % (sc.m_Namespace, sc.m_ClassName) if sc.m_Namespace else sc.m_ClassName
            self.scripts.add((sc.m_AssemblyName, full))
            for o in objs:
                self.classes[(name, o.path_id)] = sc.m_ClassName

    # --- pointers ---------------------------------------------------------
    def key(self, owner_file, pptr):
        """(file, path_id) a pointer refers to, or None for a null pointer."""
        if not pptr or not pptr.get("m_PathID"):
            return None
        fid = pptr["m_FileID"]
        f = owner_file if fid == 0 else self.externals[owner_file][fid - 1]
        return (f, pptr["m_PathID"])

    # --- reading ----------------------------------------------------------
    def read(self, key):
        """Decoded fields of the object at key (cached), with __file and __path_id added."""
        if key not in self._cache:
            f, pid = key
            if f not in self.files or pid not in self.files[f].objects:
                self._cache[key] = None
            else:
                t = self.files[f].objects[pid].read_typetree()
                t["__file"], t["__path_id"], t["__class"] = f, pid, self.classes.get(key)
                self._cache[key] = t
        return self._cache[key]

    def deref(self, owner, pptr):
        k = self.key(owner["__file"], pptr)
        return self.read(k) if k else None

    def by_class(self, *names):
        return [self.read(k) for k, c in self.classes.items() if c in names]

    def raw(self, key):
        f, pid = key
        return self.files[f].objects[pid].get_raw_data()

    def classes_with_field(self, field):
        """Script classes (Assembly-CSharp) whose top-level serialized fields include `field`."""
        out = set()
        for asm, full in self.scripts:
            if asm != "Assembly-CSharp" or "." in full:
                continue        # game data classes live in the global namespace
            try:
                nodes = self.gen.get_nodes("Assembly-CSharp.dll", full)
            except Exception:
                continue
            if any(n.m_Level == 1 and n.m_Name == field for n in nodes):
                out.add(full)
        return out
