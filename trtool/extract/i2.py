"""Reader for the game's I2 Localization `LanguageSourceAsset` (raw bytes).

UnityPy can't decode it with the generated type tree: the serialized data has
8 extra bytes (two ints) before the term list that the generated layout lacks.
Layout handled here (Unity serialization, 4-byte aligned):

  MonoBehaviour header (m_GameObject, m_Enabled, m_Script, m_Name)
  3 bools, 2 ints (unknown), mTerms: [Term, TermType, Languages[], Flags[], Languages_Touch[]]
  CaseInsensitiveTerms, OnMissingTranslation, mTerm_AppName,
  mLanguages: [Name, Code, Flags]
"""
import struct


class _R:
    def __init__(self, data):
        self.d, self.p = data, 0

    def align(self):
        self.p = (self.p + 3) & ~3

    def i32(self):
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def i64(self):
        v = struct.unpack_from("<q", self.d, self.p)[0]
        self.p += 8
        return v

    def u8(self):
        v = self.d[self.p]
        self.p += 1
        return v

    def string(self):
        n = self.i32()
        if n < 0 or n > len(self.d) - self.p:
            raise ValueError("bad string length %d at offset %d" % (n, self.p - 4))
        v = self.d[self.p:self.p + n].decode("utf-8", "replace")
        self.p += n
        self.align()
        return v

    def strings(self):
        return [self.string() for _ in range(self.i32())]

    def blob(self):
        n = self.i32()
        self.p += n
        self.align()


def read_language_source(raw):
    """(languages [(name, code)], {term: [text per language]}) from the raw object bytes."""
    r = _R(raw)
    r.i32(); r.i64()            # m_GameObject
    r.u8(); r.align()           # m_Enabled
    r.i32(); r.i64()            # m_Script
    r.string()                  # m_Name
    r.u8(); r.u8(); r.u8(); r.align()   # UserAgrees... / GoogleLiveSyncIsUptoDate
    r.i32(); r.i32()            # two ints not in the generated layout
    terms = {}
    for _ in range(r.i32()):
        term = r.string()
        r.i32()                 # TermType
        langs = r.strings()
        r.blob()                # Flags
        r.strings()             # Languages_Touch
        terms[term] = langs
    r.u8(); r.align()           # CaseInsensitiveTerms
    r.i32()                     # OnMissingTranslation
    r.string()                  # mTerm_AppName
    languages = []
    for _ in range(r.i32()):
        name, code = r.string(), r.string()
        r.u8(); r.align()
        languages.append((name, code))
    return languages, terms


class Localization:
    """Term lookup in one language (English by default), '' treated as missing."""

    def __init__(self, languages, terms, code="en"):
        codes = [c for _, c in languages]
        self.index = codes.index(code)
        self.terms = terms

    def get(self, term):
        langs = self.terms.get(term)
        if not langs or self.index >= len(langs):
            return None
        return langs[self.index] or None
