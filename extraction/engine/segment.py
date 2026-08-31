"""Segmentation and coverage accounting — the layer that makes "did we understand it?" measurable.

The old extractor answered "which entities are in here?" and stopped. That question cannot be
scored, because nothing says what SHOULD have been found. This layer inverts it: the document is
split into tokens, and every token must end up either **covered** by an annotation or explicitly
**excused** as a function word. Anything else is a hole, and holes are counted.

Three token classes, because lumping them gives a meaningless percentage:

    content    nouns, verbs, names, numbers -- these carry the article's meaning and MUST be covered
    function   the, a, of, is, und, di, на -- grammar, deliberately not extracted
    punct      . , ( ) -- structure

The headline number is **content coverage**: content tokens covered / content tokens. Raw coverage
over all tokens is also reported, but it is the misleading one -- a third of any article is function
words, so raw coverage can never approach 100% and a low figure would look like failure when it is
grammar.

No spaCy or NLTK: neither is installed and a model download per language is a poor trade for a
tokenizer. The regex below is Unicode-aware and offset-exact, which is the only property that
matters downstream -- every annotation is stored as (start, end) into the ORIGINAL text, so
highlighting in the dashboard is a substring operation and can never drift.
"""
import re
import sys
import unicodedata

# A token is a word (letters/digits/marks, allowing internal - . ' /) or a single other character.
# \w is not enough: it drops the hyphen in "Britten-Norman" and the dot in "U.S." and splits
# "9x19mm". Those are single meaningful tokens and splitting them loses the span.
# One alphanumeric rule rather than separate word/number rules. Defence text is full of tokens that
# are both -- "BN-2", "9x19mm", "5.56x45mm", "T-90", "Mk-II". Splitting them at the letter/digit
# boundary destroys exactly the designations the ontology cares about.

def _mark_ranges():
    """Every Unicode combining mark, as character-class ranges.

    MEASURED 2026-08-21, and it was silently costing Hindi ten points of coverage. Python's `\\w`
    matches letters, digits and underscore -- it does NOT match categories Mn/Mc/Me. A Devanagari
    vowel sign is Mc, so `[^\\W_]+` stops dead at one:

        करना   -> ['करन', 'ा']         one word, two tokens
        उपयोग  -> ['उपय', 'ो', 'ग']    one word, three tokens

    The fragments are not words in any language, so no span the extractor produces can ever cover
    them, and they sit in the denominator of content coverage for ever. Hindi could not have
    reached 98% no matter how good the extraction was. The same applies to every script that
    writes vowels as marks -- Bengali, Tamil, Telugu, Thai, Khmer -- and to Arabic and Hebrew
    whenever the text carries harakat or niqqud.

    Built from unicodedata rather than hand-listed: the blocks are scattered across the plane and
    a hand-list silently omits whichever script nobody tested. Costs about 10 ms once at import.
    """
    out, start, prev = [], None, None
    for cp in range(0x300, 0x1E900):        # no combining marks below U+0300
        if unicodedata.category(chr(cp))[0] == "M":
            if start is None:
                start = cp
            prev = cp
        elif start is not None:
            out.append((start, prev))
            start = None
    if start is not None:
        out.append((start, prev))
    # Emit the CHARACTERS, not \uXXXX escapes. `\u` takes exactly four hex digits, so a mark above
    # U+FFFF written as "\\u%04x" becomes a five-character string: "ḓ0" is read as ḓ
    # followed by a literal "0", and inside a character class that turns into the range 0-U+1E13 --
    # which swallows nearly all punctuation. The regex compiles, no error is raised anywhere, and
    # "SOURCE:" quietly becomes one token. Raw characters cannot be mis-parsed this way, and none
    # of these need escaping: every combining mark is above U+0300, so none is -, ], ^ or a
    # backslash.
    return "".join(chr(a) + "-" + chr(b) if a != b else chr(a) for a, b in out)


# A word character, and a word character OR a combining mark. The distinction matters: a token may
# CONTAIN a mark but must not START with one, or a stray dangling mark becomes a word of its own.
_WCH = r"[^\W_]"
_MARKS_CLASS = _mark_ranges()
_WCM = r"(?:[^\W_]|[" + _MARKS_CLASS + r"])"

# A token is a word (letters/digits/marks, allowing internal - . ' /) or a single other character.
# \w is not enough: it drops the hyphen in "Britten-Norman" and the dot in "U.S." and splits
# "9x19mm". Those are single meaningful tokens and splitting them loses the span.
# One alphanumeric rule rather than separate word/number rules. Defence text is full of tokens that
# are both -- "BN-2", "9x19mm", "5.56x45mm", "T-90", "Mk-II". Splitting them at the letter/digit
# boundary destroys exactly the designations the ontology cares about.
_TOKEN = re.compile(
    _WCH + _WCM + r"*(?:[-'’./]" + _WCH + _WCM + r"*)*"  # letters/digits/marks joined by - ' ’ . /
    r"|[^\s]",                       # anything else, one char at a time
    re.UNICODE)

# Sentence end: terminator + space + something that can start a sentence. Abbreviations are the
# usual trap, so a short capitalised token before the dot blocks the split.
_ABBREV = {
    "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "inc", "ltd", "co", "corp",
    "no", "nos", "fig", "vol", "op", "cit", "al", "approx", "dept", "univ", "gen", "col", "lt",
    "capt", "sgt", "adm", "gov", "sen", "rep", "u.s", "u.k", "e.g", "i.e", "cf", "ca", "pp",
    # de / fr / it
    "nr", "bzw", "ca", "usw", "z.b", "d.h", "abb", "hrsg", "str",
    "art", "env", "cf", "ed", "sig", "dott", "ing", "avv", "sec", "ss",
}
# Latin terminators must be followed by whitespace (a bare period is a decimal/abbreviation).
# Full-width CJK terminators are unambiguous and written with NO following space, so they must
# NOT require one -- else a whole zh/ja paragraph fuses into one sentence that overruns GLiNER
# and degrades chunking. Space is consumed outside group 1 so end=m.end(1) is unchanged.
_SENT_END = re.compile(r"([.!?…]+(?=[\s ])|[。！？]+)[\s ]*")

# Function words. Deliberately NOT a full stopword list -- only true grammar words. A word like
# "state" or "force" is a stopword in some lists and is load-bearing in defence text.
STOP = {
"en": set("""a an the and or but nor for yet so of in on at to from by with without within into onto
 upon over under above below between among through during before after since until while as if then
 than that this these those it its it's he she they them his her their we our us you your i me my
 is am are was were be been being do does did doing have has had having will would shall should can
 could may might must not no nor only also very much many more most such own same too s t don
 there here where when who whom which what why how all any both each few other some out off up down
 again further once about against because both during into through under until up""".split()),
"fr": set("""le la les un une des du de d au aux et ou mais donc or ni car que qui quoi dont ou a à
 dans sur sous pour par avec sans vers chez entre depuis pendant avant apres après ce cet cette ces
 son sa ses leur leurs notre nos votre vos mon ma mes ton ta tes il elle ils elles je tu nous vous on
 est sont etait était etaient étaient sera seront ete été etre être avoir a ont avait avaient
 ne pas plus moins tres très bien aussi meme même tout tous toute toutes en y l s c n j m t qu""".split()),
"de": set("""der die das den dem des ein eine einen einem einer eines und oder aber denn sondern
 in an auf aus bei mit nach seit von vor zu zur zum über unter durch für gegen ohne um bis
 ist sind war waren sein wird werden wurde wurden haben hat hatte hatten kann können muss müssen
 nicht kein keine auch noch nur schon sehr mehr als wie so dass daß wenn weil da man es er sie ihr
 wir uns ich du ihn ihm ihnen diese dieser dieses dem den am im vom beim zurStandard""".split()),
"it": set("""il lo la i gli le un uno una del dello della dei degli delle al allo alla ai agli alle
 dal dallo dalla nel nello nella sul sulla e ed o od ma però perche perché che chi cui non di a da
 in con su per tra fra è sono era erano sara sarà essere avere ha hanno aveva avevano si ci vi ne
 questo questa questi queste quel quella suo sua loro come piu più molto anche solo ancora già
 io tu lui lei noi voi essi""".split()),
"es": set("""el la los las un una unos unas del al de a en con por para sin sobre entre desde hasta
 y e o u pero sino que quien cual cuyo es son era eran ser estar ha han habia había no ni se le lo
 su sus este esta estos estas ese esa aquel como mas más muy tambien también solo ya yo tu el ella
 nosotros vosotros ellos""".split()),
"ru": set("""и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только
 ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был
 него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для
 мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот
    вполне
""".split()),
"pt": set("""o a os as um uma de do da dos das em no na nos nas por para com sem sobre entre e ou
 mas que quem qual é são era eram ser estar tem têm tinha não nem se lhe seu sua este esta esse
 aquele como mais muito também só já eu tu ele ela nos vos eles""".split()),
"nl": set("""de het een en of maar van in op aan bij met voor door over onder tot naar uit is zijn
 was waren worden wordt heeft hebben had niet geen ook nog maar zeer meer als dat die dit deze
 ik jij hij zij wij jullie ze er""".split()),
"pl": set("""i w we na z ze do nie że się to jest są był była było były o po za od przez dla jako
 ale lub oraz tym ten ta te tych który która które jego jej ich przy pod nad bez już tylko także
 może będzie ma mają można co jak gdy więc czy sie niż nad
    jednocześnie jeszcze kolei również też
""".split()),
# ---------------------------------------------------------------------------------------------
# Added 2026-08-21. Twenty-three of thirty-six languages in the corpus had NO list, which meant
# their grammar words were counted as content and had to be extracted -- an unreachable
# denominator. zh and ja are deliberately absent: they write no spaces, so a token is a whole run
# and a word list cannot match one. See _demo_stop for what each list must satisfy.
# zh and ja DO get lists. Their tokens are runs between punctuation, so a LONG run is a whole
# clause no word list can match -- but a SHORT run is very often a single grammar word or a nav
# label, and those are what was being counted as content. Measured on the existing corpus:
# また (also), 現在 (currently), 以下 (below), お知らせ
# (announcements) and ニュース (news) were a large share of Japanese holes.
"zh": set("""的 了 和 或 但 而 与 及 是 在 于 对 从 到 把 被 给 让 使 有 没有 不 也 都 就 还
 这 那 这些 那些 其 它 他 她 我们 你们 他们 之 以 为 因为 所以 如果 虽然 并 并且 以及 等
 上 下 中 内 外 前 后 时 时候 通过 关于 根据 按照 由于 新闻 首页 更多 详情""".split()),
"ja": set("""の に は を が と も で へ や から まで より など また および ならびに そして
 しかし ため これ それ あれ この その あの ここ そこ です ます である だ した する
 される された されて いる ない なる なり により による において について 現在
 以下 以上 場合 こと もの お知らせ ニュース プレスリリース 一覧 詳細 トップ""".split()),
"ar": set("""في من على إلى عن مع هذا هذه ذلك تلك التي الذي الذين ما لا لم لن قد كان كانت يكون تكون
 هو هي هم هن أنا نحن أنت أنتم و أو ثم لكن بل حتى إذا كما بعد قبل بين عند لدى ضمن خلال منذ حول
 كل بعض غير سوف إن أن أي به له بها لها فيه فيها منه منها إليه إليها""".split()),
"he": set("""של את על אל מן מ ב ל כ ה ו זה זאת אלה הוא היא הם הן אני אנחנו אתה את שלא לא אין יש
 היה היתה יהיה כי אם אבל או גם רק כמו אחרי לפני בין תחת מעל עם בלי כל כאשר אשר מה מי איך
 אותו אותה להם להן ממנו ממנה
    הזה הזו
""".split()),
"fa": set("""از به در با بر برای که این آن را و یا اما ولی هم نیز تا اگر چون چه کی کجا هر همه
 است بود شد می نمی خواهد باید کرد شده های ها ی یک دو او آنها ما شما من تو خود دیگر بین روی زیر
 بعد قبل مانند طبق درباره""".split()),
"hi": set("""का के की को में से पर और या तो ही भी है हैं था थे थी होगा होगी हो कर करने किया गया
 गई यह वह ये वे इस उस जो कि नहीं ना एक अपने अपनी हम मैं तुम आप उन्हें उनके उनकी लिए साथ बाद पहले
 तक द्वारा तथा एवं जब तब कोई कुछ सब""".split()),
"ko": set("""그리고 또는 그러나 하지만 및 등 등의 이러한 그러한 이와 그와 통해 위해 대한 대해
 있다 있는 있으며 있습니다 없다 없는 한다 하는 하며 합니다 된다 되는 되어 됩니다 이다 인 것
 것이 것은 수 때 때문 경우 따라 따른 대상 관련 지난 오는 이번 해당 각 모든 다른 같은 함께
 에서 으로 에게 부터 까지 보다 처럼
    있게 있도록
""".split()),
"fi": set("""ja tai mutta sekä että kun jos koska vaikka niin myös vain jo vielä ei eivät on ovat
 oli olivat olla ollut se ne tämä nämä hän he minä sinä me te joka jotka mikä mitä kuin yli alle
 kanssa ilman jälkeen ennen aikana välillä sisällä kohti asti saakka
    olemme
""".split()),
"da": set("""og eller men samt at som når hvis fordi selvom så også kun endnu ikke er var være
 blevet blive har havde den det de denne disse han hun jeg vi du I en et til fra på i med uden
 efter før under over mellem ved om for af""".split()),
"no": set("""og eller men samt at som når hvis fordi selv om så også bare ennå ikke er var være
 blitt bli har hadde den det de denne disse han hun jeg vi du en et til fra på i med uten
 etter før under over mellom ved for av""".split()),
"lt": set("""ir ar bet taip pat kad kai jei nes nors todėl taip tik dar ne nėra yra buvo būti
 tas ta tie tos šis ši šie šios jis ji jie jos aš mes tu jūs į iš su be po prieš per nuo iki
 apie ant už tarp prie""".split()),
"lv": set("""un vai bet ka kad ja jo lai gan tā arī tikai vēl ne nav ir bija būt tas tā tie tās
 šis šī šie šīs viņš viņa mēs es tu jūs uz no ar bez pēc pirms par starp pie līdz""".split()),
"et": set("""ja või aga ning et kui sest kuigi nii ka ainult veel ei ole oli olema see need
 need ta tema me ma sa te sisse välja koos ilma pärast enne ajal vahel juures kuni üle alla""".split()),
"hr": set("""i ili ali te da kad ako jer iako pa tako samo još ne nije je su bio bila biti
 taj ta to ti te ovaj ova ovo on ona oni mi ja ti vi u na za od do sa iz po pri kroz
 prije poslije između oko bez""".split()),
"hu": set("""és vagy de hogy ha mert bár így csak még nem van vannak volt voltak lenni
 az a ez ezek azok ő ők én mi te ti ban ben ba be ból ből tól től nak nek val vel
 után előtt alatt között körül nélkül szerint""".split()),
"ro": set("""și sau dar că dacă pentru deoarece deși așa doar încă nu este sunt era erau fi
 fost acest această acești aceste acel acea el ea ei noi eu tu voi în la de pe cu fără
 după înainte sub peste între lângă din prin""".split()),
"id": set("""dan atau tetapi bahwa jika karena meskipun jadi hanya masih tidak bukan adalah
 ada yang ini itu dia mereka kami kita saya anda di ke dari pada untuk dengan tanpa
 setelah sebelum bawah atas antara oleh akan sudah telah""".split()),
"vi": set("""và hoặc nhưng rằng nếu vì mặc dù nên chỉ còn không là có được của cho với
 này đó các những một tôi chúng ta họ anh chị ở tại từ đến trong ngoài trên dưới giữa
 sau trước khi đã sẽ đang bị bởi""".split()),
"el": set("""και ή αλλά ότι αν γιατί αν και έτσι μόνο ακόμη δεν είναι ήταν να θα έχει είχε
 ο η το οι τα του της των τον την ένα μια αυτός αυτή αυτό εγώ εμείς εσύ σε από με χωρίς
 μετά πριν κάτω πάνω μεταξύ για προς κατά""".split()),
"bg": set("""и или но че ако защото макар така само още не е са беше бяха бъде да ще има
 имаше този тази това тези онзи той тя те аз ние ти вие в на за от с без след преди
 под над между при към по""".split()),
"ms": set("""dan atau tetapi bahawa jika kerana walaupun jadi hanya masih tidak bukan adalah
 ada yang ini itu dia mereka kami kita saya anda di ke dari pada untuk dengan tanpa
 selepas sebelum bawah atas antara oleh akan sudah telah ialah""".split()),
"uk": set("""і й в у на з із до не що це є був була було були за від для як але або та той ця ці
 який яка які його її їх при під над без вже лише також може буде має мають про по ми ви вони
 який щоб коли ніж усі""".split()),
"tr": set("""ve ile için bir bu şu da de ki ancak ama veya gibi kadar sonra önce olarak olan oldu
 olmuştur var yok daha çok en her bazı tüm ise mi mı tarafından üzere göre ederek ederek olup
 bunun onun bir çok""".split()),
"sv": set("""och i att det som en på är av för med till den har de inte om ett men var från vi man
 när kan ska eller sig så under över vid blir blev sina sitt denna detta samt även""".split()),
"cs": set("""a v na se je že o s do k i to ale nebo který která které byl byla bylo byly jsou po za
 od pro při pod nad bez už jen také může bude má mají tento tato toto jako když nebo""".split()),
}
STOP["ru"] |= set("""этот эта эти том том числе которая который которые""".split())

# Language-independent grammar: single letters used as articles/contractions in the tokenizer split.
_UNIVERSAL_STOP = set("l d j n c s t m qu dell nell all sull".split())


def norm_lang(lang):
    """Corpus language codes are dirty: 'de_de', 'en en', literal '{locale}'. Take the first two
    ASCII letters, or fall back to English -- an unknown language must still be tokenized, and
    treating its function words as content only makes the score conservative, never inflated."""
    s = re.sub(r"[^A-Za-z]", "", str(lang or ""))[:2].lower()
    return s if s in STOP else "en"


# Script comes before stopwords, because a stopword list can only recognise the languages it was
# written for. Measured on a 52-document harvest: 42 documents carrying Chinese, Japanese, Korean,
# Devanagari, Arabic or Cyrillic text were ALL reported as `en`, because their navigation chrome
# and boilerplate are English and the scorer counted those Latin function words. A page that is a
# third Chinese characters is not an English page.
#
# This is the fourth time in this project that a closed word list has quietly answered "is this
# English?" instead of the question it was asked. The fix is the same every time: use a signal
# that exists in every language the pipeline runs on. A script is that signal.
_SCRIPT_LANG = [
    ("ko", r"[\uac00-\ud7af\u1100-\u11ff]"),          # hangul -- checked before the CJK block
    ("ja", r"[\u3040-\u309f\u30a0-\u30ff]"),          # kana settles Japanese vs Chinese
    ("zh", r"[\u4e00-\u9fff\u3400-\u4dbf]"),          # han with no kana
    ("hi", r"[\u0900-\u097f]"),
    ("ar", r"[\u0600-\u06ff\u0750-\u077f\ufb50-\ufdff\ufe70-\ufeff]"),
    ("he", r"[\u0590-\u05ff]"),
    ("th", r"[\u0e00-\u0e7f]"),
    ("el", r"[\u0370-\u03ff\u1f00-\u1fff]"),
    ("ru", r"[\u0400-\u04ff]"),                        # Cyrillic; refined to uk below
]
_SCRIPT_LANG = [(k, re.compile(p)) for k, p in _SCRIPT_LANG]
# Letters that exist in Ukrainian and not in Russian. Without this every Ukrainian document is
# reported as Russian, which is both wrong and, in this domain, not a neutral mistake.
_UK_ONLY = re.compile(r"[\u0456\u0457\u0454\u0491\u0406\u0407\u0404\u0490]")
# Letters that exist in Persian and not in Arabic. Same problem as Ukrainian/Russian, same shape
# of fix, and it went unnoticed for the same reason: both languages use one script, so a
# script-keyed detector answers with whichever it was told about first.
#
# MEASURED COST. Over the 500-document run, 62 of 63 documents the corpus labelled `fa` were
# stored as `ar`. Persian never appeared in any per-language number, and Arabic's reported
# coverage of 98.78% over "65 documents" was in fact mostly Persian.
#
# It also drove a FEEDBACK LOOP that spent a quarter of the corpus budget. The harvester's quota
# is water-filled from what the store holds, the store held zero `fa`, so `fa` was allocated the
# largest quota every single cycle -- 10 to 16 documents -- and every one of them landed as `ar`,
# leaving `fa` at zero for the next cycle. 63 Persian documents were fetched to fill a bucket that
# could never fill.
#
# pe/gaf/che/zhe, plus the Persian forms of kaf and yeh, which differ from the Arabic ones.
_FA_ONLY = re.compile(r"[\u067e\u0686\u0698\u06af\u06a9\u06cc]")
# A script has to carry CONTENT, not just appear. 8% of the sample is well above a stray glyph in
# a menu and well below what any genuinely non-Latin page contains.
_SCRIPT_SHARE = 0.08


def script_lang(text):
    """-> a language code when the text is written in a distinctive script, else None."""
    if not text:
        return None
    n = len(text)
    for lang, rx in _SCRIPT_LANG:
        hits = len(rx.findall(text))
        if hits / n >= _SCRIPT_SHARE:
            if lang == "ru" and _UK_ONLY.search(text):
                return "uk"
            # Persian inside the Arabic script, by the same rule. A THRESHOLD rather than a single
            # sighting, because Arabic text quotes Persian names and a lone gaf in a proper noun
            # is not evidence that the document is Persian -- while genuine Persian prose is dense
            # with these letters.
            if lang == "ar" and len(_FA_ONLY.findall(text)) / max(1, len(text)) >= 0.01:
                return "fa"
            return lang
    return None


def detect_lang(text, declared=None, sample=4000):
    """Pick the language from the TEXT, not from the metadata.

    The corpus language column is unreliable — a French Safran job posting is labelled `en`, and the
    corpus carries 59 unnormalised codes including `de_de`, `en en` and a literal `{locale}`.
    Trusting it applied English stopwords to French prose, so `et`, `des`, `la` and `de` were
    counted as CONTENT words and then reported as extraction holes: 55 of that document's 60
    "misses" were French grammar. Coverage was being scored against the wrong denominator.

    Scored by function-word hit rate, which is what actually distinguishes these languages cheaply;
    the declared code only breaks a tie.
    """
    sc = script_lang(text[:sample])
    if sc:
        return sc                       # the script is decisive; stopwords cannot overrule it
    toks = [t["text"].lower() for t in tokenize(text[:sample]) if t["kind"] == "word"]
    if not toks:
        return norm_lang(declared)
    best, best_score = None, 0.0
    for lang, words in STOP.items():
        score = sum(1 for t in toks if t in words) / len(toks)
        if score > best_score:
            best, best_score = lang, score
    dec = norm_lang(declared)
    if best is None or best_score < 0.04:
        return dec                      # too little evidence -- keep what the corpus claimed
    # A declared language that is within a whisker of the winner keeps its claim.
    dec_score = sum(1 for t in toks if t in STOP[dec]) / len(toks)
    return dec if dec_score >= best_score * 0.9 else best


def tokenize(text):
    """-> [{i, start, end, text, kind}] with kind in {word, number, punct}. Offsets are into the
    ORIGINAL string; nothing downstream is allowed to re-derive them."""
    out = []
    for m in _TOKEN.finditer(text):
        t = m.group(0)
        if t.isspace():
            continue
        if any(ch.isalpha() for ch in t):
            kind = "word"          # "9x19mm" is a word-shaped designation, not a bare number
        elif any(ch.isdigit() for ch in t):
            kind = "number"
        else:
            kind = "punct"
        out.append({"i": len(out), "start": m.start(), "end": m.end(), "text": t, "kind": kind})
    return out


def classify(tokens, lang):
    """Tag each token content / function / punct. Mutates and returns the list."""
    stop = STOP[norm_lang(lang)]
    for t in tokens:
        low = t["text"].lower().strip(".'’")
        if t["kind"] == "punct":
            t["cls"] = "punct"
        elif t["kind"] == "number":
            t["cls"] = "content"          # a number is always content: quantities carry meaning
        elif low in stop or low in _UNIVERSAL_STOP or len(low) == 0:
            t["cls"] = "function"
        elif len(low) == 1 and not low.isdigit():
            t["cls"] = "function"          # stray single letters from splitting are grammar
        else:
            t["cls"] = "content"
    return tokens


def sentences(text):
    """-> [{i, start, end, text}]. Offset-exact, abbreviation-aware."""
    spans, start = [], 0
    for m in _SENT_END.finditer(text):
        end = m.end(1)
        term = m.group(1)
        # The abbreviation guard is a Latin-script concern ("Ltd." / "z.B." / "U.S."). A full-width
        # CJK terminator is unambiguous -- and a single CJK char before it is `.isalpha()`, so the
        # single-letter guard would WRONGLY suppress every zh/ja split. Skip the guard for CJK.
        if term[0] in ".!?…":
            prev = text[max(0, end - 12):end - len(term)].strip()
            last = re.split(r"[\s(]", prev)[-1].lower().rstrip(".") if prev else ""
            if last in _ABBREV or (len(last) == 1 and last.isalpha()):
                continue
        seg = text[start:end].strip()
        if seg:
            s0 = start + (len(text[start:end]) - len(text[start:end].lstrip()))
            spans.append({"i": len(spans), "start": s0, "end": end, "text": text[s0:end]})
        start = m.end()
    tail = text[start:].strip()
    if tail:
        s0 = start + (len(text[start:]) - len(text[start:].lstrip()))
        spans.append({"i": len(spans), "start": s0, "end": len(text.rstrip()),
                      "text": text[s0:len(text.rstrip())]})
    # Newline-separated fragments (headings, bullets, product tables) never carry a terminator and
    # would otherwise fuse into one enormous "sentence" that no LLM call can handle.
    out = []
    for s in spans:
        if len(s["text"]) < 400 or "\n" not in s["text"]:
            out.append(s); continue
        pos = s["start"]
        for part in re.split(r"(\n+)", s["text"]):
            if part.strip():
                out.append({"i": 0, "start": pos, "end": pos + len(part), "text": part})
            pos += len(part)
    for i, s in enumerate(out):
        s["i"] = i
    return out


def coverage(tokens, spans):
    """What fraction of the article did we actually account for?

    A token counts as covered when some annotation's [start,end) overlaps it. Reported per class,
    because one blended percentage hides the only number that matters: function words are ~35-45%
    of any article and are never extracted, so a raw figure is capped far below 100 by grammar
    alone and reads as failure when nothing is wrong.
    """
    marks = sorted((s["start"], s["end"]) for s in spans)
    counts = {"content": 0, "function": 0, "punct": 0}
    covered = {"content": 0, "function": 0, "punct": 0}
    j = 0
    uncovered = []
    for t in tokens:
        counts[t["cls"]] += 1
        while j < len(marks) and marks[j][1] <= t["start"]:
            j += 1
        hit = any(s < t["end"] and e > t["start"] for s, e in marks[j:j + 40])
        t["covered"] = hit
        if hit:
            covered[t["cls"]] += 1
        elif t["cls"] == "content":
            uncovered.append(t)
    tot = sum(counts.values()); cov = sum(covered.values())
    return {
        "tokens": tot, "covered": cov,
        "pct_all": round(100.0 * cov / tot, 2) if tot else 0.0,
        "content_tokens": counts["content"], "content_covered": covered["content"],
        "pct_content": round(100.0 * covered["content"] / counts["content"], 2)
        if counts["content"] else 0.0,
        "function_tokens": counts["function"], "punct_tokens": counts["punct"],
        "uncovered_content": [t["text"] for t in uncovered][:400],
        "n_uncovered_content": len(uncovered),
    }


def _demo_script():
    # Every one of these was reported `en` before the script check existed, because the surrounding
    # page furniture is English.
    zh = "\u4e2d\u56fd\u8239\u8236\u96c6\u56e2\u53d1\u5e03\u4e86\u65b0\u578b\u62a4\u536b\u8230\u7684\u8be6\u7ec6\u89c4\u683c" * 4
    assert detect_lang("Home About Contact " + zh) == "zh", detect_lang("Home " + zh)
    ja = "\u4e09\u83f1\u91cd\u5de5\u696d\u306f\u65b0\u578b\u8266\u8247\u306e\u958b\u767a\u3092\u767a\u8868\u3057\u307e\u3057\u305f" * 4
    assert detect_lang(ja) == "ja", "kana settles Japanese against Chinese"
    ko = "\ud55c\ud654\uc2dc\uc2a4\ud15c\uc740 \uc0c8\ub85c\uc6b4 \ub808\uc774\ub354\ub97c \uacf5\uac1c\ud588\uc2b5\ub2c8\ub2e4" * 4
    assert detect_lang(ko) == "ko"
    hi = "\u092d\u093e\u0930\u0924 \u0921\u093e\u092f\u0928\u093e\u092e\u093f\u0915\u094d\u0938 \u0928\u0947 \u0928\u092f\u0940 \u092e\u093f\u0938\u093e\u0907\u0932 \u0915\u093e \u092a\u0930\u0940\u0915\u094d\u0937\u0923 \u0915\u093f\u092f\u093e" * 4
    assert detect_lang(hi) == "hi"
    ar = "\u0623\u0639\u0644\u0646\u062a \u0627\u0644\u0625\u0645\u0627\u0631\u0627\u062a \u0639\u0646 \u0635\u0641\u0642\u0629 \u062f\u0641\u0627\u0639\u064a\u0629 \u062c\u062f\u064a\u062f\u0629" * 4
    assert detect_lang(ar) == "ar"
    # Cyrillic, and the letters that separate Ukrainian from Russian
    ru = "\u0420\u043e\u0441\u0441\u0438\u044f \u043e\u0431\u044a\u044f\u0432\u0438\u043b\u0430 \u043e \u043d\u043e\u0432\u043e\u043c \u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442\u0435" * 4
    assert detect_lang(ru) == "ru"
    uk = "\u0423\u043a\u0440\u0430\u0457\u043d\u0430 \u043e\u0433\u043e\u043b\u043e\u0441\u0438\u043b\u0430 \u043f\u0440\u043e \u043d\u043e\u0432\u0438\u0439 \u043a\u043e\u043d\u0442\u0440\u0430\u043a\u0442 \u0457\u0457" * 4
    assert detect_lang(uk) == "uk", "\u0456/\u0457/\u0454 exist in Ukrainian and not in Russian"
    # a genuinely Latin document is untouched by any of this
    assert detect_lang("The company announced a new contract for the defence ministry today.") == "en"
    assert script_lang("Mostly English with one \u4e2d character") is None, \
        "a stray glyph is not a script"


def _demo_stop():
    """Every language the pipeline actually meets needs a function-word list, or its grammar is
    counted as content and its coverage ceiling is set below what extraction can reach.

    This asserts the property, not the contents: a list may be improved, but a language may not
    silently go back to having none.
    """
    # The languages with a real presence in the corpus, excluding the two that write no spaces.
    need = ("en fr de es it pt nl pl ru uk tr cs sv ar he fa hi ko zh ja fi da no lt lv et hr "
            "hu ro id vi el bg ms").split()
    missing = [l for l in need if l not in STOP]
    assert not missing, "no function-word list for: %s" % missing
    for lang in need:
        assert len(STOP[lang]) >= 30, "%s list is too thin to be a grammar list (%d)" % (
            lang, len(STOP[lang]))
        assert all(w == w.strip() and w for w in STOP[lang]), "%s has a blank or padded entry" % lang

    # zh and ja DO need lists. The first reading of this problem said they could not use one --
    # no spaces, so a token is a whole run and a word list cannot match it. That is true only of
    # the LONG runs. A run breaks at punctuation, and a short run is very often a single grammar
    # word or a nav label, which is precisely what was inflating their denominators. And because
    # coverage() counts a token as covered when a span OVERLAPS it, the long runs are the EASY
    # case -- one span touching a 40-character clause covers it.
    for _lang in ("zh", "ja"):
        assert _lang in STOP and len(STOP[_lang]) >= 30, "%s needs a function-word list" % _lang
    assert "また" in STOP["ja"] and "現在" in STOP["ja"]
    assert "的" in STOP["zh"] and "这些" in STOP["zh"]

    # The grammar words that were being counted as content must now be excused.
    for lang, words in (("ar", ["في", "من", "على", "إلى"]),
                        ("hi", ["और", "यह", "एक", "है"]),
                        ("ko", ["또는", "이러한", "통해", "있습니다"])):
        for w in words:
            assert w in STOP[lang], "%s: %r must be a function word" % (lang, w)

    # ...and load-bearing defence vocabulary must NOT be excused in any language.
    for lang in need:
        for w in ("system", "systems", "force", "state", "radar", "missile"):
            assert w not in STOP[lang], "%s excuses %r, which carries meaning here" % (lang, w)


def _demo_marks():
    """A combining mark belongs to the word it sits on, and punctuation never does.

    Both halves are needed. The first fix rejoined Devanagari words that `\\w` had been splitting at
    every vowel sign. The obvious way to write it -- building the character class from "\\u%04x"
    escapes -- then silently broke ASCII, because `\\u` takes exactly FOUR hex digits and a mark
    above U+FFFF became a truncated escape plus a stray digit, which inside a character class read
    as the range 0-U+1E13 and swallowed most punctuation. Nothing raised; "SOURCE:" simply became
    one token. So the punctuation half is asserted here for ever.
    """
    # Marks join their base character: one word, one token, in every script that writes vowels
    # as marks.
    for word in ("करना",                      # करना, Devanagari
                 "उपयोग",                # उपयोग
                 "การจัดซื้อ",   # Thai
                 "বাংলাদেশ",               # Bengali
                 "தமிழ்"):                                # Tamil
        got = [t["text"] for t in tokenize(word)]
        assert got == [word], "%r split into %r" % (word, got)

    # ...and punctuation is still its own token. This is the assertion that would have caught the
    # escape-width bug immediately.
    for txt, first in (("SOURCE: x", "SOURCE"), ("and] x", "and"), ("providing? x", "providing")):
        got = [t["text"] for t in tokenize(txt)]
        assert got[0] == first and len(got) == 3, "%r -> %r" % (txt, got)

    # The designations the original regex exists to protect must be unchanged.
    assert [t["text"] for t in tokenize("Britten-Norman BN-2 9x19mm T-90")] == \
        ["Britten-Norman", "BN-2", "9x19mm", "T-90"]

    # No mark range may reach down into ASCII -- that is exactly what the truncated escape did.
    assert not _MARKS_CLASS or min(ord(c) for c in _MARKS_CLASS if c != "-") >= 0x300, \
        "a mark range reaches below U+0300 and will swallow punctuation"


def _demo():
    _demo_marks()
    _demo_stop()
    txt = ("Cubic Corp. and 4C Strategies signed a deal on 12 March 2026. "
           "The contract is worth $4.5 million.\nIt covers Britten-Norman BN-2 aircraft.")
    toks = classify(tokenize(txt), "en")
    # a trailing dot is its own token (nothing follows it to bind to); the sentence splitter is
    # what has to know "Corp." is an abbreviation, and that is tested below
    assert [t["text"] for t in toks][:4] == ["Cubic", "Corp", ".", "and"], \
        [t["text"] for t in toks][:6]
    # offsets must be exact -- every downstream highlight depends on it
    for t in toks:
        assert txt[t["start"]:t["end"]] == t["text"], t
    # hyphenated names and alphanumeric designations stay ONE token
    assert "Britten-Norman" in [t["text"] for t in toks]
    assert "BN-2" in [t["text"] for t in toks]
    # "Corp." must not end the sentence; the 2026 full stop must
    ss = sentences(txt)
    assert len(ss) == 3, [s["text"] for s in ss]
    for s in ss:
        assert txt[s["start"]:s["end"]] == s["text"]
    # classification
    by = {t["text"]: t["cls"] for t in toks}
    assert by["and"] == "function" and by["the"] if "the" in by else True
    assert by["Cubic"] == "content" and by["2026"] == "content"
    assert by["."] == "punct"
    # a number is content, never a stopword
    assert all(t["cls"] == "content" for t in toks if t["kind"] == "number")
    # alphanumeric designations survive as ONE content token
    assert by.get("Britten-Norman") == "content" and by.get("BN-2") == "content"
    # coverage: mark just "Cubic" and check the arithmetic is per class
    cv = coverage(toks, [{"start": 0, "end": 5}])
    assert cv["content_covered"] == 1 and cv["pct_content"] < 10
    assert cv["content_tokens"] + cv["function_tokens"] + cv["punct_tokens"] == cv["tokens"]
    # full cover -> 100% content
    cv2 = coverage(toks, [{"start": 0, "end": len(txt)}])
    assert cv2["pct_content"] == 100.0 and cv2["n_uncovered_content"] == 0
    # multilingual: function words must be recognised, or the score is inflated by grammar
    de = classify(tokenize("Die Tasche ist aus Cordura und hat eine Molle Aufnahme."), "de")
    assert {t["text"]: t["cls"] for t in de}["Die"] == "function"
    assert {t["text"]: t["cls"] for t in de}["Tasche"] == "content"
    ru = classify(tokenize("Инновационное развитие ОДК и его программы."), "ru")
    assert {t["text"]: t["cls"] for t in ru}["и"] == "function"
    assert {t["text"]: t["cls"] for t in ru}["ОДК"] == "content"
    # --- language detection: the corpus label is wrong often enough to break the denominator ---
    fr = ("Vous rejoignez le service Assurance Qualite Production au coeur de la production des "
          "aubes de turbine pour les moteurs d'avions civils et militaires dans la ligne")
    assert detect_lang(fr, declared="en") == "fr", detect_lang(fr, declared="en")
    de_t = ("Die Tasche ist aus Cordura und hat eine Molle Aufnahme fuer den Guertel mit "
            "der Moeglichkeit an dem System zu befestigen und ist sehr robust")
    assert detect_lang(de_t, declared="en") == "de"
    en_t = ("The company signed a contract with the ministry and will deliver the vehicles "
            "to the army in the next year as part of the programme")
    assert detect_lang(en_t, declared="en") == "en"
    # a correct declaration is not overturned by a marginal winner
    assert detect_lang(en_t, declared="en") == "en"
    # too little evidence -> keep the declared code rather than guess
    assert detect_lang("BN-2 155mm", declared="de") == "de"
    assert detect_lang("", declared="fr") == "fr"
    # Five languages added 2026-08-16 so a top-up set could test something new. A new STOP entry can
    # STEAL detections from an existing one (pl/cs and uk/ru share a lot of short function words),
    # so every language is checked together — adding one must not cost another.
    for want, txt in [
        ("pl", "Ministerstwo Obrony Narodowej podpisalo umowe na dostawe czolgow, ktora obejmuje "
               "takze szkolenie i serwis w kraju"),
        ("uk", "Міністерство оборони уклало контракт на постачання броньованих машин, які буде "
               "передано у наступному році"),
        ("tr", "Savunma Bakanligi ile imzalanan sozlesme kapsaminda zirhli araclarin teslimati "
               "gelecek yil baslayacak ve bu bir ilk olacak"),
        ("sv", "Forsvarsmakten har tecknat ett avtal om leverans av pansarfordon som ska levereras "
               "under nasta ar till armen"),
        ("cs", "Ministerstvo obrany podepsalo smlouvu na dodavku obrnenych vozidel, ktera budou "
               "dodana v pristim roce"),
        ("ru", "Министерство обороны подписало контракт на поставку бронированных машин в "
               "следующем году"),
        ("pt", "O ministerio da Defesa assinou um contrato para o fornecimento de veiculos "
               "blindados no proximo ano"),
        ("nl", "Het ministerie van Defensie heeft een contract getekend voor de levering van "
               "pantservoertuigen in het komende jaar"),
    ]:
        assert detect_lang(txt) == want, (want, detect_lang(txt))
    # CJK used to fall back to "en", so a Chinese document's coverage was scored against ENGLISH
    # grammar. The note here said fixing it needed a segmenter, not a word list. That was half
    # right: a LONG run is a whole clause no word list can match -- but coverage() counts a token
    # as covered when a span OVERLAPS it, so long runs are the easy case, and the SHORT runs that
    # were inflating the denominator are single grammar words a list matches exactly. Measured
    # 2026-08-21. A segmenter would still improve span-level precision; it is not what coverage
    # was waiting for.
    assert norm_lang("ja") == "ja" and norm_lang("zh") == "zh"
    assert norm_lang("ko") == "ko", "Korean grammar must not be scored against English"
    # An unknown code still falls back to English, and the docstring's reasoning still holds for
    # it: excusing too few words makes the score conservative, never inflated.
    assert norm_lang("{locale}") == "en" and norm_lang("zxx") == "en"

    # dirty language codes from the corpus must not crash or silently become "content-only"
    assert norm_lang("de_de") == "de" and norm_lang("en en") == "en"
    assert norm_lang("{locale}") == "en" and norm_lang(None) == "en"
    assert norm_lang("zz") == "en"
    _demo_script()
    print("ok")


if __name__ == "__main__":
    _demo() if "--demo" in sys.argv else _demo()
