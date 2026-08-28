"""Portfolio vocabulary for the nine KSSL categories, in the languages the corpus
actually contains.

WHY THIS FILE EXISTS
--------------------
presignal.py first shipped with English-only category terms. Scored against 60
recent articles per language from the live corpus, the result was unambiguous:

    en  6.7% yield      de 1.7%   fr 0.0%   es 0.0%   ru 0.0%
    ar 16.7%            hi 0.0%   tr 0.0%   zh 0.0%   ja/ko ~0%

Portfolio terms matched 40% of English articles and 0% of Russian and Hindi ones.
That is not a quality signal, it is a LANGUAGE DETECTOR -- the third time this
project has built one by accident. Ranking crawl sources on that score would have
quietly starved every non-English source, including the Indian ones, which are
the client's home market.

`cralwer/scripts/taxonomy.py` already carries some of this (Chinese, Greek,
French) and is reused where it can be. This file fills the rest.

RULES FOR EDITING
-----------------
* Terms are matched folded (lowercase, accents stripped) with word-ish
  boundaries, so give the STEM where a language inflects heavily: Russian
  "артиллер" covers артиллерия/артиллерии/артиллерийский.
* Never add a term shorter than 5 characters unless it is a distinctive proper
  noun. Short substrings collide across languages -- 'mil', 'pel', 'zen' and the
  Greek οπλ/εξοπλισμός collision are all recorded incidents here.
* Any change MUST be re-measured PER LANGUAGE, not on an average. An average is
  what hid this for the whole first version.
"""

# Nine KSSL categories -> terms, stemmed where the language inflects.
PORTFOLIO = {
    "artillery": [
        # en/fr/de/it/pt/es
        "artillery", "howitzer", "artillerie", "haubitze", "obice", "obus",
        "artiglieria", "artilharia", "artilleria", "obusier",
        # ru/uk  (stems: артиллерия/артиллерийский, гаубица/гаубиц)
        "артиллер", "гаубиц", "самохідн", "самоходн",
        # pl/cs/tr/hi/ar/fa/he/zh/ja/ko/el/sv/nl/fi
        "artyleri", "haubic", "delostrelec", "topcu", "topçu", "obüs", "obus",
        "तोपखाना", "मीडियम गन", "مدفعية", "توپخانه", "ארטילריה",
        "火炮", "榴弹炮", "火砲", "포병", "자주포", "πυροβολικ",
        "artilleri", "artillerie", "tykistö",
    ],
    "ammunition": [
        "ammunition", "munition", "munizioni", "municion", "munições", "municoes",
        "боеприпас", "патрон", "amunicj", "strelivo", "mühimmat", "muhimmat",
        "गोला बारूद", "ذخيرة", "مهمات", "תחמושת", "弹药", "彈藥", "弾薬", "탄약",
        "πυρομαχικ", "ammunisjon", "ammunitie", "ampumatarvikk",
    ],
    "small arms": [
        "small arms", "assault rifle", "carbine", "handfeuerwaffen", "sturmgewehr",
        "fusil d'assaut", "fusil de asalto", "стрелков", "автомат калашник",
        "broń strzelecka", "hafif silah", "छोटे हथियार", "أسلحة خفيفة",
        "轻武器", "輕武器", "小火器", "소화기", "φορητ", "handvapen",
    ],
    "protected and armoured vehicles": [
        "armoured vehicle", "armored vehicle", "infantry fighting vehicle",
        "personnel carrier", "mine-resistant", "gepanzerte fahrzeug", "schützenpanzer",
        "vehicule blinde", "véhicule blindé", "vehiculo blindado", "veicolo blindato",
        "veiculo blindado", "бронемаш", "бронетранспорт", "боевая машина",
        "pojazd opancerzon", "obrnene vozidlo", "zirhli arac", "zırhlı araç",
        "बख्तरबंद", "مركبة مدرعة", "רכב משוריין", "装甲车", "裝甲車", "装甲車",
        "장갑차", "τεθωρακισμ", "pansarfordon", "pantservoertuig",
    ],
    "armoured vehicle mro": [
        "sustainment", "overhaul", "refurbishment", "depot maintenance",
        "instandsetzung", "generalüberholung", "revision", "revisione",
        "капитальн ремонт", "ремонт бронет", "remont", "modernizacj",
        "bakim onarim", "bakım onarım", "मरम्मत", "إصلاح", "大修", "정비",
        "underhall", "onderhoud",
    ],
    "naval": [
        "naval", "frigate", "corvette", "submarine", "shipyard", "fregatte",
        "u-boot", "werft", "fregata", "sottomarino", "cantiere navale",
        "fragata", "submarino", "astillero", "фрегат", "подводн лодк", "верф",
        "okręt", "stocznia", "fırkateyn", "denizalt", "नौसेना", "पनडुब्बी",
        "بحرية", "فرقاطة", "חיל הים", "护卫舰", "潜艇", "潛艦", "潜水艦",
        "구축함", "잠수함", "φρεγατ", "υποβρυχ", "fregatt", "fregat",
    ],
    "uav": [
        "unmanned aerial", "drone", "loitering munition", "quadcopter",
        "drohne", "unbemannt", "drone tactique", "dron", "droni",
        "беспилотн", "безпілотн", "бпла", "insansiz hava", "insansız hava",
        "मानव रहित", "ड्रोन", "طائرة مسيرة", "بدون طيار", "כטב\"ם",
        "无人机", "無人機", "無人航空", "무인기", "μη επανδρωμ",
    ],
    "missiles and air defence": [
        "missile", "air defence", "air defense", "surface-to-air", "flugabwehr",
        "lenkflugkörper", "raketen", "missile sol-air", "defense aerienne",
        "misil", "defensa aerea", "missili", "difesa aerea", "míssil",
        "ракет", "протиповітр", "противовоздушн", "пво", "rakiet",
        "obrona powietrzna", "füze", "hava savunma", "मिसाइल", "वायु रक्षा",
        "صاروخ", "دفاع جوي", "טיל", "导弹", "飛彈", "防空", "ミサイル",
        "미사일", "방공", "πυραυλ", "αντιαεροπορ", "robot", "raket",
    ],
    "precision components and forgings": [
        "forging", "forgings", "precision component", "machined component",
        "schmiede", "gesenkschmied", "forge", "forgeage", "forja",
        "forgiatura", "forjamento", "поковк", "штампов", "kucie", "kovani",
        "dövme", "फोर्जिंग", "طرق", "锻件", "锻造", "鍛造", "단조",
        "σφυρηλατ", "smide",
    ],
}

# A minimum LENGTH is a Latin-alphabet rule. It exists because short Latin
# substrings collide ('mil' inside 'milk', the Greek οπλ/εξοπλισμός incident).
# Applied blindly it deletes whole scripts: 导弹, 火炮, 弹药, 装甲车, 无人机, 미사일,
# 탄약 are all 2-3 characters, so a flat `len(t) >= 4` dropped 40 terms and left
# Simplified Chinese and Korean with ZERO portfolio vocabulary -- rebuilding the
# language detector this file was written to remove. An ideograph is a word.
_IDEOGRAPHIC = 2      # CJK / Hangul: a 2-character term is a full word
_OTHER_SCRIPT = 3     # Cyrillic, Arabic, Hebrew, Devanagari, Greek: heavily inflected
                      # stems are short and do not collide the way Latin ones do


def _script_class(s: str) -> str:
    for c in s:
        if "぀" <= c <= "ヿ" or "㐀" <= c <= "鿿" or "가" <= c <= "힯":
            return "ideographic"
        if ("\u0400" <= c <= "\u04ff" or "\u0590" <= c <= "\u06ff"
                or "\u0900" <= c <= "\u097f" or "\u0370" <= c <= "\u03ff"):
            return "other"
    return "latin"


def term_ok(t: str, latin_minlen: int = 4) -> bool:
    """Is this term long enough to match without colliding, IN ITS OWN SCRIPT?"""
    cls = _script_class(t)
    if cls == "ideographic":
        return len(t) >= _IDEOGRAPHIC
    if cls == "other":
        return len(t) >= _OTHER_SCRIPT
    return len(t) >= latin_minlen


# Flattened, lowercased. presignal folds accents itself.
ALL_TERMS = sorted({t.lower() for terms in PORTFOLIO.values() for t in terms if term_ok(t)})


def demo():
    """Every category must carry terms in more than one script, or this file has
    quietly regressed to being an English list again."""
    import unicodedata

    def script(s):
        for ch in s:
            if ch.isalpha():
                name = unicodedata.name(ch, "")
                for k in ("CYRILLIC", "ARABIC", "DEVANAGARI", "HEBREW", "CJK",
                          "HIRAGANA", "KATAKANA", "HANGUL", "GREEK"):
                    if k in name:
                        return k
                return "LATIN"
        return "?"

    # Check the EXPORTED list, not PORTFOLIO. The first version of this check
    # counted scripts in the source dict and reported "7 scripts" per category
    # while the length filter had already deleted every Chinese and Korean term
    # from what presignal actually matches on. Validate the object that ships.
    exported = {t for t in ALL_TERMS}
    bad = []
    for cat, terms in PORTFOLIO.items():
        kept = [t for t in terms if t.lower() in exported]
        scripts = {script(t) for t in kept}
        if len(scripts) < 3:
            bad.append((cat, sorted(scripts)))
        print(f"  {cat:34s} {len(kept):3d}/{len(terms):3d} terms kept, {len(scripts)} scripts")
    assert not bad, f"categories with fewer than 3 scripts AFTER filtering: {bad}"

    dropped = [t for terms in PORTFOLIO.values() for t in terms if t.lower() not in exported]
    assert not any(_script_class(t) != "latin" for t in dropped), \
        f"a non-Latin term was dropped by the length rule: {[t for t in dropped if _script_class(t) != 'latin'][:5]}"

    # the scripts that a flat length rule silently deleted
    for probe in ("导弹", "火炮", "弹药", "无人机", "미사일", "탄약", "пво"):
        assert probe in exported, f"{probe!r} missing from ALL_TERMS - the length rule regressed"

    print(f"ok - {len(ALL_TERMS)} unique terms across {len(PORTFOLIO)} categories "
          f"({len(dropped)} Latin terms below the collision floor)")


if __name__ == "__main__":
    demo()
