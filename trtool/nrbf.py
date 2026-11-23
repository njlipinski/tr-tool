"""Minimal reader for .NET BinaryFormatter (MS-NRBF) streams.

Travellers Rest saves are a single BinaryFormatter-serialized `SaveData`
object. `load(path)` returns it as plain Python dicts/lists, with object
references resolved. Every class instance carries its .NET type name under
the key "__class".
"""
import struct

__all__ = ["load", "loads"]


class _Reader:
    def __init__(self, data):
        self.d = data
        self.p = 0

    def byte(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def fmt(self, f, n):
        v = struct.unpack_from(f, self.d, self.p)[0]
        self.p += n
        return v

    def string(self):
        n = shift = 0
        while True:
            c = self.byte()
            n |= (c & 0x7F) << shift
            shift += 7
            if not c & 0x80:
                break
        v = self.d[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return v

    def char(self):
        c = self.d[self.p]
        n = 1 if c < 0x80 else 2 if c < 0xE0 else 3 if c < 0xF0 else 4
        v = self.d[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        return v


class _Ref:
    __slots__ = ("id",)

    def __init__(self, i):
        self.id = i


class _Nulls:
    __slots__ = ("n",)

    def __init__(self, n):
        self.n = n


_END = object()


class _Parser:
    def __init__(self, data):
        self.r = _Reader(data)
        self.objs = {}
        self.classes = {}

    def prim(self, t):
        r = self.r
        if t == 1: return bool(r.byte())
        if t == 2: return r.byte()
        if t == 3: return r.char()
        if t == 5: return r.string()          # Decimal, stored as text
        if t == 6: return r.fmt("<d", 8)
        if t == 7: return r.fmt("<h", 2)
        if t == 8: return r.i32()
        if t == 9: return r.fmt("<q", 8)
        if t == 10: return r.fmt("<b", 1)
        if t == 11: return round(r.fmt("<f", 4), 4)
        if t in (12, 13): return r.fmt("<q", 8)  # TimeSpan / DateTime ticks
        if t == 14: return r.fmt("<H", 2)
        if t == 15: return r.fmt("<I", 4)
        if t == 16: return r.fmt("<Q", 8)
        if t == 18: return r.string()
        raise ValueError("unknown primitive type %d at %d" % (t, r.p))

    def class_info(self):
        r = self.r
        oid = r.i32()
        name = r.string()
        names = [r.string() for _ in range(r.i32())]
        return oid, name, names

    def type_info(self, n):
        r = self.r
        kinds = [r.byte() for _ in range(n)]
        extra = []
        for k in kinds:
            if k in (0, 7): extra.append(r.byte())
            elif k == 3: extra.append(r.string())
            elif k == 4: extra.append((r.string(), r.i32()))
            else: extra.append(None)
        return kinds, extra

    def members(self, oid, name, names, kinds, extra):
        o = {"__class": name}
        self.objs[oid] = o
        for nm, k, x in zip(names, kinds, extra):
            o[nm] = self.prim(x) if k == 0 else self.record()
        return o

    def array(self, oid, n, get):
        a = []
        self.objs[oid] = a
        while len(a) < n:
            v = get()
            if isinstance(v, _Nulls):
                a.extend([None] * v.n)
            else:
                a.append(v)
        return a

    def record(self):
        r = self.r
        rt = r.byte()
        if rt == 0:                      # stream header
            for _ in range(4): r.i32()
            return self.record()
        if rt == 12:                     # library
            r.i32(); r.string()
            return self.record()
        if rt in (4, 5):                 # class with members and types
            oid, name, names = self.class_info()
            kinds, extra = self.type_info(len(names))
            if rt == 5: r.i32()
            self.classes[oid] = (name, names, kinds, extra)
            return self.members(oid, name, names, kinds, extra)
        if rt == 1:                      # class reusing earlier metadata
            oid = r.i32()
            meta = self.classes[r.i32()]
            self.classes[oid] = meta
            return self.members(oid, *meta)
        if rt == 6:                      # string
            oid = r.i32()
            s = r.string()
            self.objs[oid] = s
            return s
        if rt == 8:                      # boxed primitive
            return self.prim(r.byte())
        if rt == 9: return _Ref(r.i32())
        if rt == 10: return None
        if rt == 13: return _Nulls(r.byte())
        if rt == 14: return _Nulls(r.i32())
        if rt == 15:                     # primitive array
            oid, n, t = r.i32(), r.i32(), r.byte()
            if t == 2:
                a = list(r.d[r.p:r.p + n]); r.p += n
            else:
                a = [self.prim(t) for _ in range(n)]
            self.objs[oid] = a
            return a
        if rt in (16, 17):               # object / string array
            oid, n = r.i32(), r.i32()
            return self.array(oid, n, self.record)
        if rt == 7:                      # general array
            oid, kind, rank = r.i32(), r.byte(), r.i32()
            lens = [r.i32() for _ in range(rank)]
            if kind in (3, 4, 5):
                for _ in range(rank): r.i32()
            t = r.byte()
            x = None
            if t in (0, 7): x = r.byte()
            elif t == 3: x = r.string()
            elif t == 4: x = (r.string(), r.i32())
            n = 1
            for l in lens: n *= l
            if t == 0:
                return self.array(oid, n, lambda: self.prim(x))
            return self.array(oid, n, self.record)
        if rt == 11: return _END
        raise ValueError("unknown record type %d at %d" % (rt, r.p - 1))

    def resolve(self, v, seen=frozenset()):
        if isinstance(v, _Ref):
            if v.id in seen:
                return "<cycle %d>" % v.id
            return self.resolve(self.objs.get(v.id), seen | {v.id})
        if isinstance(v, dict):
            return {k: self.resolve(x, seen) for k, x in v.items()}
        if isinstance(v, list):
            return [self.resolve(x, seen) for x in v]
        return v

    def run(self):
        root = None
        while self.r.p < len(self.r.d):
            v = self.record()
            if v is _END:
                break
            if root is None and isinstance(v, dict):
                root = v
        return self.resolve(root)


def loads(data):
    return _Parser(data).run()


def load(path):
    with open(path, "rb") as f:
        return loads(f.read())
