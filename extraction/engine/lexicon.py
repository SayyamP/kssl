
"""Custom lexicon — a gazetteer and a retyping layer aimed at the errors we actually make.

WHY THIS EXISTS, AND WHY IT LOOKS LIKE THIS
-------------------------------------------
The external benchmark said recall is not the problem: 96.3% of gold spans are found. Label
accuracy is (80.9% against their 86.0%), and the confusions are concentrated, not diffuse:

    gold country   -> we said organization   19   "Italian", "British", "German"   (demonyms)
    gold agreement -> we said system         16   "VPAM VR9/BRV2009", "LTE-Advanced PRO", "4.5G"
    gold country   -> we said location        7   "Türkiye", "Siria", "法国"
    gold organization -> agreement/system     12   "国家发展改革委", "財務省", "TIME"
    gold event     -> we said program          4   "Operazione Barkhane", "Resolute Support"
    gold count     -> we said measurement      6   "53", "11万名员工"

Every one of those is a *naming* problem, not a *finding* problem, and naming problems are what a
gazetteer is for. The benchmark's own authors say the same: their remaining edge over us is "an
11.6k-term gazetteer" plus "a golden-rule retyping layer". This is that layer.

DESIGN RULES
------------
- **Retype, never re-find.** This runs AFTER merge, over spans that already exist with exact
  offsets. It can change a label; it cannot invent a span. So it can never hurt recall.
- **Whole-token matching only.** "Mali" must not match inside "Malicious", and "Chad" must not
  match inside "Chadwick". Every entry is anchored.
- **Multilingual by construction.** The confusions above are in Chinese, Japanese, Italian, Spanish
  and Russian. An English-only gazetteer would fix a third of them and look like it worked.
- **Regions are not countries.** `Occitanie`, `Ile de France`, `Normandie` were typed country by
  the model; the gazetteer has to be able to say "this is a location and specifically NOT a
  country", so REGIONS is a negative list checked first.
"""
import re
import sys

# --- Countries: name forms + demonyms, in the languages the corpus actually contains -----------
# Keyed by canonical English name. The point is coverage of SURFACE FORMS, not geography.
COUNTRIES = {
    "United States": ["united states", "usa", "u.s.", "u.s.a.", "us", "america", "american",
                      "americans", "états-unis", "etats-unis", "américain", "américaine",
                      "américains", "estados unidos", "estadounidense", "estadounidenses",
                      "vereinigte staaten", "amerikanisch", "amerikanische", "amerikanischen",
                      "stati uniti", "statunitense", "statunitensi", "сша", "американск",
                      "美国", "アメリカ", "米国"],
    "United Kingdom": ["united kingdom", "uk", "u.k.", "britain", "great britain", "british",
                       "briton", "britons", "england", "english", "royaume-uni", "britannique",
                       "grande-bretagne", "reino unido", "británico", "britanico", "británica",
                       "großbritannien", "grossbritannien", "britisch", "britische", "britischen",
                       "regno unito", "britannico", "britannica", "britannici",
                       "великобритания", "британск", "英国", "イギリス", "英"],
    "Germany": ["germany", "german", "germans", "deutschland", "deutsch", "deutsche", "deutschen",
                "deutscher", "allemagne", "allemand", "allemande", "alemania", "alemán", "aleman",
                "alemana", "germania", "tedesco", "tedesca", "tedeschi", "германия", "немецк",
                "德国", "ドイツ", "独"],
    "France": ["france", "french", "français", "francais", "française", "francaise", "frankreich",
               "französisch", "franzosisch", "französische", "francia", "francés", "frances",
               "francese", "francesi", "франция", "французск", "法国", "フランス", "仏"],
    "Italy": ["italy", "italian", "italians", "italia", "italiano", "italiana", "italiani",
              "italie", "italien", "italienne", "italienisch", "italienische", "italienischen",
              "италия", "итальянск", "意大利", "イタリア", "伊"],
    "Spain": ["spain", "spanish", "españa", "espana", "español", "espanol", "española", "espanola",
              "espagne", "espagnol", "espagnole", "spanien", "spanisch", "spanische", "spagna",
              "spagnolo", "spagnola", "испания", "испанск", "西班牙", "スペイン"],
    "Russia": ["russia", "russian", "russians", "russie", "russe", "russland", "russisch",
               "russische", "russischen", "rusia", "ruso", "rusa", "россия", "рф",
               "российск", "русск", "俄罗斯", "ロシア", "露"],
    "China": ["china", "chinese", "chine", "chinois", "chinoise", "cina", "cinese", "cinesi",
              "kina", "chinesisch", "chinesische", "китай", "китайск", "中国", "中華人民共和国",
              "中国人民", "チャイナ", "中"],
    "Japan": ["japan", "japanese", "japon", "japonais", "japonaise", "japón", "japon", "japonés",
              "giappone", "giapponese", "giapponesi", "japanisch", "japanische", "япония",
              "японск", "日本", "日"],
    "Ukraine": ["ukraine", "ukrainian", "ucraina", "ucraino", "ucrania", "ucraniano",
                "ukrainisch", "ukrainische", "украина", "украинск", "乌克兰", "ウクライナ"],
    "India": ["india", "indian", "indians", "inde", "indien", "indienne", "indisch", "indische",
              "индия", "индийск", "印度", "インド", "印"],
    "Turkey": ["turkey", "türkiye", "turkiye", "turkish", "turquie", "turc", "turque", "turquía",
               "turquia", "turco", "turchia", "türkei", "turkei", "türkisch", "турция",
               "турецк", "土耳其", "トルコ"],
    "Israel": ["israel", "israeli", "israelis", "israël", "israélien", "israelien", "israelí",
               "israeliano", "israelisch", "израиль", "израильск", "以色列", "イスラエル"],
    "Poland": ["poland", "polish", "pologne", "polonais", "polonia", "polaco", "polacco",
               "polen", "polnisch", "polnische", "польша", "польск", "波兰", "ポーランド"],
    "Netherlands": ["netherlands", "dutch", "holland", "pays-bas", "néerlandais", "neerlandais",
                    "países bajos", "paesi bassi", "olanda", "olandese", "niederlande",
                    "niederländisch", "нидерланды", "荷兰", "オランダ"],
    "Sweden": ["sweden", "swedish", "suède", "suede", "suédois", "suecia", "sueco", "svezia",
               "svedese", "schweden", "schwedisch", "швеция", "шведск", "瑞典", "スウェーデン"],
    "Norway": ["norway", "norwegian", "norvège", "norvege", "norvégien", "noruega", "noruego",
               "norvegia", "norvegese", "norwegen", "norwegisch", "норвегия", "挪威", "ノルウェー"],
    "Finland": ["finland", "finnish", "finlande", "finlandais", "finlandia", "finlandés",
                "finnisch", "финляндия", "芬兰", "フィンランド"],
    "Denmark": ["denmark", "danish", "danemark", "danois", "dinamarca", "danés", "danimarca",
                "danese", "dänemark", "dänisch", "дания", "丹麦", "デンマーク"],
    "Belgium": ["belgium", "belgian", "belgique", "belge", "bélgica", "belgica", "belgio",
                "belga", "belgien", "belgisch", "бельгия", "比利时", "ベルギー"],
    "Switzerland": ["switzerland", "swiss", "suisse", "suiza", "suizo", "svizzera", "svizzero",
                    "schweiz", "schweizer", "schweizerisch", "швейцария", "瑞士", "スイス"],
    "Austria": ["austria", "austrian", "autriche", "autrichien", "österreich", "oesterreich",
                "österreichisch", "австрия", "奥地利", "オーストリア"],
    "Canada": ["canada", "canadian", "canadien", "canadienne", "canadá", "canadiense",
               "kanada", "kanadisch", "канада", "канадск", "加拿大", "カナダ"],
    "Australia": ["australia", "australian", "australie", "australien", "australienne",
                  "australiano", "australisch", "австралия", "澳大利亚", "オーストラリア"],
    "New Zealand": ["new zealand", "nz", "new zealander", "nouvelle-zélande", "nueva zelanda",
                    "nuova zelanda", "neuseeland", "новая зеландия", "新西兰", "ニュージーランド"],
    "South Korea": ["south korea", "korea", "korean", "corée du sud", "corea del sur",
                    "corea del sud", "südkorea", "suedkorea", "koreanisch", "южная корея",
                    "韩国", "韓国", "大韓民国"],
    "North Korea": ["north korea", "dprk", "corée du nord", "corea del norte", "nordkorea",
                    "северная корея", "朝鲜", "北朝鮮"],
    "Brazil": ["brazil", "brazilian", "brésil", "bresil", "brasil", "brasileño", "brasile",
               "brasiliano", "brasilien", "brasilianisch", "бразилия", "巴西", "ブラジル"],
    "Saudi Arabia": ["saudi arabia", "saudi", "arabie saoudite", "arabia saudita",
                     "saudi-arabien", "саудовская аравия", "沙特阿拉伯", "サウジアラビア"],
    "United Arab Emirates": ["united arab emirates", "uae", "émirats arabes unis",
                             "emiratos árabes unidos", "emirati arabi uniti",
                             "vereinigte arabische emirate", "оаэ", "阿联酋"],
    "Egypt": ["egypt", "egyptian", "égypte", "egypte", "égyptien", "egipto", "egitto",
              "ägypten", "aegypten", "египет", "埃及", "エジプト"],
    "Greece": ["greece", "greek", "grèce", "grece", "grec", "grecia", "griego", "greco",
               "griechenland", "griechisch", "греция", "希腊", "ギリシャ"],
    "Portugal": ["portugal", "portuguese", "portugais", "portugués", "portoghese",
                 "portugiesisch", "португалия", "葡萄牙", "ポルトガル"],
    "Czech Republic": ["czech republic", "czechia", "czech", "tchéquie", "república checa",
                       "repubblica ceca", "tschechien", "tschechisch", "чехия", "捷克"],
    "Romania": ["romania", "romanian", "roumanie", "roumain", "rumanía", "rumania",
                "rumänien", "rumaenien", "румыния", "罗马尼亚"],
    "Iran": ["iran", "iranian", "irán", "iranien", "iranisch", "иран", "иранск", "伊朗", "イラン"],
    "Iraq": ["iraq", "iraqi", "irak", "irakien", "irakisch", "ирак", "伊拉克", "イラク"],
    "Syria": ["syria", "syrian", "syrie", "syrien", "siria", "sirio", "сирия", "叙利亚", "シリア"],
    "Pakistan": ["pakistan", "pakistani", "pakistanais", "pakistán", "pakistanisch",
                 "пакистан", "巴基斯坦", "パキスタン"],
    "Indonesia": ["indonesia", "indonesian", "indonésie", "indonesien", "indonesisch",
                  "индонезия", "印度尼西亚", "インドネシア"],
    "Singapore": ["singapore", "singapour", "singapur", "singapore", "сингапур", "新加坡"],
    "Vietnam": ["vietnam", "vietnamese", "viêt nam", "vietnamita", "вьетнам", "越南", "ベトナム"],
    "Thailand": ["thailand", "thai", "thaïlande", "tailandia", "thailandia", "таиланд", "泰国"],
    "Malaysia": ["malaysia", "malaysian", "malaisie", "malasia", "malesia", "малайзия", "马来西亚"],
    "South Africa": ["south africa", "south african", "afrique du sud", "sudáfrica",
                     "sudafrica", "südafrika", "юар", "南非"],
    "Nigeria": ["nigeria", "nigerian", "nigéria", "nigerianisch", "нигерия", "尼日利亚"],
    "Senegal": ["senegal", "sénégal", "senegalese", "senegalesi", "sénégalais", "senegalés",
                "сенегал", "塞内加尔"],
    "Mali": ["mali", "malian", "malien", "malienne", "maliano", "мали", "马里"],
    "Argentina": ["argentina", "argentine", "argentinian", "argentinien", "argentinisch",
                  "аргентина", "阿根廷", "アルゼンチン"],
    "Mexico": ["mexico", "mexican", "mexique", "méxico", "mexicano", "messico", "messicano",
               "mexiko", "mexikanisch", "мексика", "墨西哥", "メキシコ"],
    "Chile": ["chile", "chilean", "chili", "chilien", "chileno", "cile", "cileno", "чили", "智利"],
    "Colombia": ["colombia", "colombian", "colombie", "colombien", "kolumbien", "колумбия",
                 "哥伦比亚"],
    "Peru": ["peru", "peruvian", "pérou", "perú", "peruano", "perù", "peruanisch", "перу", "秘鲁"],
    "Qatar": ["qatar", "qatari", "катар", "卡塔尔", "カタール"],
    "Kuwait": ["kuwait", "koweït", "koweit", "kuwaití", "кувейт", "科威特"],
    "Jordan": ["jordan", "jordanian", "jordanie", "jordania", "giordania", "jordanien",
               "иордания", "约旦"],
    "Morocco": ["morocco", "moroccan", "maroc", "marocain", "marruecos", "marocco",
                "marokko", "марокко", "摩洛哥"],
    "Algeria": ["algeria", "algerian", "algérie", "algerie", "algérien", "argelia", "algeria",
                "algerien", "алжир", "阿尔及利亚"],
    "Ethiopia": ["ethiopia", "ethiopian", "éthiopie", "etiopía", "etiopia", "äthiopien",
                 "эфиопия", "埃塞俄比亚"],
    "Kenya": ["kenya", "kenyan", "kenia", "кения", "肯尼亚"],
    "Hungary": ["hungary", "hungarian", "hongrie", "hongrois", "hungría", "ungheria",
                "ungarn", "ungarisch", "венгрия", "匈牙利"],
    "Bulgaria": ["bulgaria", "bulgarian", "bulgarie", "bulgarien", "bulgarisch", "болгария",
                 "保加利亚"],
    "Croatia": ["croatia", "croatian", "croatie", "croacia", "croazia", "kroatien",
                "хорватия", "克罗地亚"],
    "Serbia": ["serbia", "serbian", "serbie", "serbien", "serbo", "serba", "serbi",
               "сербия", "塞尔维亚"],
    "Slovakia": ["slovakia", "slovak", "slovaquie", "eslovaquia", "slovacchia", "slowakei",
                 "словакия", "斯洛伐克"],
    "Slovenia": ["slovenia", "slovenian", "slovénie", "eslovenia", "slowenien", "словения"],
    "Ireland": ["ireland", "irish", "irlande", "irlandais", "irlanda", "irlandés", "irland",
                "irisch", "ирландия", "爱尔兰"],
    "Estonia": ["estonia", "estonian", "estonie", "estland", "эстония", "爱沙尼亚"],
    "Latvia": ["latvia", "latvian", "lettonie", "letonia", "lettland", "латвия", "拉脱维亚"],
    "Lithuania": ["lithuania", "lithuanian", "lituanie", "lituania", "litauen", "литва", "立陶宛"],
    "Belarus": ["belarus", "belarusian", "biélorussie", "bielorrusia", "bielorussia",
                "weißrussland", "беларусь", "белоруссия", "白俄罗斯"],
    "Kazakhstan": ["kazakhstan", "kazakh", "kasachstan", "казахстан", "哈萨克斯坦"],
    "Taiwan": ["taiwan", "taiwanese", "taïwan", "taiwán", "台湾", "台灣", "タイワン"],
    "Philippines": ["philippines", "filipino", "philippinen", "filipinas", "filippine",
                    "филиппины", "菲律宾", "フィリピン"],
    "Afghanistan": ["afghanistan", "afghan", "afgano", "afghanisch", "афганистан", "阿富汗"],
    "Libya": ["libya", "libyan", "libye", "libia", "libyen", "ливия", "利比亚"],
    "Sudan": ["sudan", "sudanese", "soudan", "sudán", "судан", "苏丹"],
    "Yemen": ["yemen", "yemeni", "yémen", "jemen", "йемен", "也门"],
    "Lebanon": ["lebanon", "lebanese", "liban", "líbano", "libano", "libanon", "ливан", "黎巴嫩"],
    "Venezuela": ["venezuela", "venezuelan", "vénézuéla", "venezolano", "венесуэла", "委内瑞拉"],
    "Cuba": ["cuba", "cuban", "cubain", "cubano", "kuba", "куба", "古巴"],
}

# Sub-national regions that a model happily types as countries. Checked BEFORE the country list.
REGIONS = {
    "occitanie", "ile de france", "île-de-france", "ile-de-france", "normandie", "normandy",
    "bourgogne", "bourgogne-franche-comté", "bretagne", "brittany", "aquitaine", "provence",
    "nouvelle-aquitaine", "auvergne", "grand est", "hauts-de-france", "pays de la loire",
    "bavaria", "bayern", "saxony", "sachsen", "hessen", "hesse", "brandenburg", "thüringen",
    "nordrhein-westfalen", "baden-württemberg", "niedersachsen", "schleswig-holstein",
    "lombardia", "lombardy", "toscana", "tuscany", "sicilia", "sicily", "veneto", "piemonte",
    "lazio", "puglia", "campania", "sardegna", "calabria", "liguria", "emilia-romagna",
    "cataluña", "catalunya", "catalonia", "andalucía", "andalusia", "galicia", "país vasco",
    "basque country", "castilla", "valencia", "aragón", "murcia", "extremadura",
    "california", "texas", "florida", "virginia", "kentucky", "ohio", "michigan", "georgia",
    "alabama", "arizona", "colorado", "maryland", "massachusetts", "missouri", "nevada",
    "new york", "pennsylvania", "washington", "wisconsin", "kansas", "indiana", "illinois",
    "scotland", "wales", "northern ireland", "england",
    "ontario", "quebec", "québec", "alberta", "british columbia", "manitoba",
    "new south wales", "victoria", "queensland", "western australia", "tasmania",
    "siberia", "сибирь", "crimea", "крым", "donbas", "донбасс",
}

# --- Standards, statutes and specifications. Their `agreement` type includes these -------------
STANDARD_PAT = [
    # Unambiguous standard bodies: case-insensitive, but a digit must appear. A standard without
    # its number is not identifiable anyway, so requiring the digit costs nothing.
    r"^(?:iso|iec|din|astm|ansi|ieee|nato|stanag|mil[\s-]?std|mil[\s-]?prf|mil[\s-]?dtl|"
    r"vpam|brv|nij|rohs|gost|гост|jis)\b[\s\-/]*[a-z]*\d[\w/.-]*",
    # Specification families that carry no number of their own.
    r"^mil[\s-]?spec\b", r"^milspec\b", r"^nato\s+stock\s+number\b", r"^nsn\b",
    r"^(?:lte|lte[\s-]advanced|5g|4g|4\.5g|3g|gsm|umts|wifi|wi-fi|bluetooth|ethernet|"
    r"tcp/ip|http|scpi|usb|hdmi|pcie|can\s?bus|modbus|profibus)\b[\w\s.-]*",
    r"^(?:title|section|article|artikel|articolo|artículo|§)\s*\d+[a-z]?\b",
    r"^\d+\s*u\.?s\.?c\.?\b",
    r"^(?:regulation|directive|richtlinie|règlement|reglamento|regolamento)\s+[\d/()-]+",
]
AGREEMENT_WORDS = [
    "memorandum of understanding", "mou", "framework agreement", "contract", "treaty",
    "protocol", "accord", "convention", "vertrag", "abkommen", "vereinbarung",
    "accordo", "acuerdo", "contrato", "contratto", "договор", "соглашение", "контракт",
    "协议", "合同", "条约", "協定", "契約",
]

# --- Military operations and exercises: gold `event`, we said `program` -----------------------
EVENT_PAT = [
    # `^operation\s+\w+` lived here case-insensitively and also matched "operation of the fleet".
    # An exercise is followed by its NAME, and the name is capitalised: "Exercise Trident Juncture".
    # Matched case-sensitively against the original (see _EVENT_CASED) because the lowercased form
    # made "exercise management capability" and "exercise capabilities" military exercises.
    r"\b(?:resolute support|enduring freedom|freedom sentinel|inherent resolve|barkhane|"
    r"atlantic resolve|sea guardian|active endeavour|ocean shield|operation allied force)\b",
    r"^(?:summit|sommet|cumbre|vertice|gipfel|саммит)\b",
    r"\b(?:air ?show|airshow|salon du bourget|farnborough|eurosatory|dsei|idex|defexpo|"
    r"aero india|le bourget|ila berlin|paris air show)\b",
    r"^(?:deployment|déploiement|dispiegamento|развёртывание)\b",
]

# --- Government bodies and known organisations, including CJK ministries ----------------------
ORG_PAT = [
    r"^(?:ministry|ministère|ministerio|ministero|ministerium|министерство)\b",
    r"^(?:department|département|departamento|dipartimento)\s+of\b",
    r"(?:省|庁|委|部|局|署)$",                       # CJK ministry/agency suffixes
    r"^(?:国家|中央|全国)\w*(?:委|部|局|办)",          # Chinese central bodies
    r"^(?:agency|agence|agencia|agenzia|agentur|агентство)\b",
    r"^(?:bureau|büro|oficina|ufficio)\b",
    # Corporate suffixes, UNAMBIGUOUS ONES ONLY. `kg` (Kommanditgesellschaft) is also kilograms and
    # retyped "1000 kg" as an organisation 10 times on the benchmark; `as`/`ab`/`ag`/`nv`/`bv`/`inc`
    # collide with ordinary words across these languages. A company is nearly always identified by
    # other means, so a narrow list costs little while a wide one corrupts every measurement.
    # `s\.?p\.?a\.?` with every dot optional also matched the word "Spa". At least one dot required.
    r"\b(?:gmbh|s\.p\.?a\.?|s\.?p\.a\.?|ltd|limited|plc|incorporated|corporation|llc|"
    r"oyj|sarl|s\.?a\.?r\.?l\.?|s\.?r\.?l\.?|ооо|оао|пао|株式会社|有限公司|集团)\b",
    r"^(?:university|université|universidad|università|universität|университет)\b",
    r"^(?:nato|otan|osce|opec|asean|african union|european commission|"
    r"european union|european defence agency)\b",
]
# Acronyms that are ordinary words in some language here: `un`/`ue` are Italian and French articles
# ("Un impegno" became the United Nations), `eu` is Portuguese "I", `eda` is a Spanish/Basque name
# fragment. Matched against the ORIGINAL text and only in caps, never against the lowercased form.
# `AG` and `SpA` are only a company suffix when a NAME precedes them: the existing guard case
# `12 AG` is a measurement, and a bare `\bAG\b` claimed it — the same collision that kept `ag`,
# `as`, `nv` and `inc` out of the case-insensitive list in the first place.
ORG_UPPER = re.compile(r"^(?:UN|ONU|EU|UE|EDA|OTAN|NATO)\b"
                       r"|[A-ZÀ-Þ][\wÀ-ÿ.\-]*\s+(?:SpA|AG)\b"
                       r"|[A-ZÀ-Þ][\wÀ-ÿ.\-]*\s+A\.?Ş\.?$")
# Media outlets kept separate: they are organisations but never match a corporate suffix.
MEDIA = {
    "time", "reuters", "bloomberg", "financial times", "ft", "the economist", "wall street journal",
    "wsj", "new york times", "nyt", "washington post", "bbc", "cnn", "guardian", "the guardian",
    "telegraph", "le monde", "le figaro", "les echos", "la tribune", "handelsblatt", "faz",
    "frankfurter allgemeine", "der spiegel", "spiegel", "die welt", "süddeutsche zeitung",
    "corriere della sera", "la repubblica", "il sole 24 ore", "libero quotidiano", "panorama",
    "quotidiano nazionale", "il giornale", "ansa", "el país", "el pais", "el mundo", "abc",
    "la vanguardia", "expansión", "tass", "тасс", "ria novosti", "риа новости", "interfax",
    "интерфакс", "kommersant", "коммерсант", "xinhua", "新华社", "people's daily", "人民日报",
    "global times", "环球时报", "nikkei", "日本経済新聞", "asahi", "朝日新聞", "yomiuri", "読売新聞",
    "al-monitor", "al monitor", "almonitor", "middle east eye", "defense one",
    "janes", "jane's", "defense news", "breaking defense", "defence news", "flight global",
    "aviation week", "shephard media", "army recognition", "naval news",
}

# --- Known defence programmes: gold `program`, we often said `system` -------------------------
PROGRAM_PAT = [
    r"\b(?:joint strike fighter|jsf|air warfare destroyer|future combat air system|fcas|"
    r"global combat air programme|gcap|tempest|scaf|main ground combat system|mgcs|"
    r"nuclear posture review|quadrennial defense review|strategic defence review|"
    r"defence industrial strategy)\b",
    r"^(?:programme|program|programa|programma|programm|программа)\b",
    r"^air\s+\d{3,4}\b",                       # Australian AIR 5428 etc
    r"^(?:project|projet|proyecto|progetto|projekt|проект)\s+\w+",
]

# --- Facilities: gold `facility`, we said `location` ------------------------------------------
FACILITY_PAT = [
    r"\b(?:air ?force base|air base|naval base|military base|army base|marine corps base|"
    r"naval station|naval air station|airfield|aerodrome|shipyard|dockyard|arsenal|depot|"
    r"garrison|barracks|proving ground|test range|firing range|training area|"
    r"plant|factory|foundry|refinery|works|facility|laboratory|complex)\b",
    r"\b(?:base a[ée]rienne|base navale|chantier naval|arsenal|usine|dépôt|caserne)\b",
    r"\b(?:luftwaffenst[üu]tzpunkt|marinest[üu]tzpunkt|werft|werk|fabrik|kaserne)\b",
    r"\b(?:base a[ée]rea|astillero|f[áa]brica|planta|cuartel)\b",
    r"\b(?:base aerea|cantiere navale|stabilimento|fabbrica|caserma)\b",
    r"\b(?:кремл\w*|база|завод\w*|верф\w*|цех\w*|полигон\w*|казарм\w*)\b",
    r"(?:基地|工厂|造船厂|兵工厂|仓库|基地)",
    r"(?:基地|工場|造船所|兵器廠)",
]

# Units. A number followed by one of these is a MEASUREMENT; a number followed by anything else is
# a COUNT. Both directions were wrong on the benchmark: "53" and "11万名员工" were typed measurement,
# while "16 ppm × m" and "30 scd" were typed count.
UNIT_PAT = (r"(?:mm|cm|dm|km|m|in|ft|yd|mi|nmi|mg|kg|g|t|lb|oz|tonnes?|tons?|ml|l|gal|"
            r"m[²³23]|km[²2]|ha|km/h|kmh|mph|kts?|knots?|m/s|rpm|w|kw|mw|gw|kwh|mwh|v|kv|a|ma|"
            r"hz|khz|mhz|ghz|°|°c|°f|k|bar|psi|pa|kpa|mpa|n|kn|nm|hp|ps|cv|ch|db|cal|kcal|"
            r"ppm|ppb|scd|cd|lm|lux|sv|gy|bq|mol|%|percent|prozent)")
# NOT `\b` after the unit: `%`, `°` and `㎜` are not word characters, so a trailing `\b` fails at
# end-of-string and "50 %" stopped being a measurement. This is the identical bug that once
# dropped every CJK-unit measurement in values.py — same guard, same reason. The guard also
# rejects a following DIGIT: without that, "2 DM51 hand grenades" parsed as "2 decimetres".
_NUM_UNIT = re.compile(rf"^\d[\d\s.,]*\s*{UNIT_PAT}(?![A-Za-zÀ-ÿ0-9])", re.I)
_NUM_WORD = re.compile(r"^\d[\d\s.,]*\s*[^\W\d_]", re.U)
_NUM_CJK = re.compile(r"^\d[\d.,]*\s*[万亿千百]?\s*[名个台架艘辆人]")
_BARE_NUM = re.compile(r"^\d[\d\s.,]*$")

_FACILITY = [re.compile(p, re.I) for p in FACILITY_PAT]

# Agreement words must match as WHOLE WORDS. Substring matching put "mou" inside "Portsmouth" and
# retyped a naval base as a contract — the same class of error as `bus` matching `BUSH`. CJK terms
# have no word boundaries, so they stay as plain substrings.
_AGREEMENT = re.compile(
    "|".join([rf"\b{re.escape(w)}\b" for w in AGREEMENT_WORDS if w.isascii()]
             + [re.escape(w) for w in AGREEMENT_WORDS if not w.isascii()]), re.I)

_COUNTRY_LOOKUP = {}
for canon, forms in COUNTRIES.items():
    for f in forms:
        _COUNTRY_LOOKUP[f] = canon

_STANDARD = [re.compile(p, re.I) for p in STANDARD_PAT]

# Short standard prefixes that are also ordinary words in the corpus languages. `EN 1090` is a
# European standard; `en 2020` is Spanish/French for "in 2020". `CE` marking vs French `ce`
# ("this"). Case is the only thing that separates them, so these are matched against the ORIGINAL
# text and require UPPERCASE — lowercasing first destroyed the one available signal and typed two
# dates and two persons as standards.
# No \b after the prefix: "IP68" has none between P and 6. The REQUIRED digit is what stops
# "ENGINE" and "CENTER" from matching, and it does so without needing a boundary.
_STANDARD_UPPER = re.compile(r"^(?:EN|IP|UL|CE|GB|BS|NF|UNE|UNI)[\s\-/]*[A-Z]*\d[\w/.-]*")
_EVENT = [re.compile(p, re.I) for p in EVENT_PAT]
# Case-SENSITIVE: the exercise/operation keyword must be followed by a capitalised name. `allied
# \w+` used to live in the case-insensitive list and made "allied forces", "U.S. and allied forces"
# and "NATO allied armed forces" into events — those are forces, not an operation.
_EVENT_CASED = re.compile(
    r"^(?:Exercise|Exercice|Ejercicio|Esercitazione|Übung|Uebung|Учения|Operation|Opération|"
    r"Operación|Operazione|Unternehmen|Операция)\s+[A-ZÀ-ÞА-Я]")
_ORG = [re.compile(p, re.I) for p in ORG_PAT]
_PROGRAM = [re.compile(p, re.I) for p in PROGRAM_PAT]


def _norm(s):
    return re.sub(r"\s+", " ", (s or "").strip().strip(".,;:!?\"'()[]«»„“”‘’")).lower()


# Precompiled ONCE. Building these patterns inside country_of() rebuilt 616 pattern STRINGS per
# call -- a guaranteed miss in re._cache (max 512), so every call recompiled all 616 AND evicted
# every other regex in the process. Measured 8.4ms/call x 138,951 spans = ~20 min per corpus of
# pure compilation, held under the GIL, blocking every worker thread. Verified byte-identical
# across 11,309 real corpus surfaces including all 7,737 that can reach the loop.
_COUNTRY_STEMS = [(re.compile(re.escape(f) + r"[а-яёий]{0,3}"), c)
                  for f, c in _COUNTRY_LOOKUP.items() if len(f) >= 6]


def country_of(text):
    """-> canonical country name, or None. Regions are refused explicitly."""
    n = _norm(text)
    if not n or n in REGIONS:
        return None
    if n in _COUNTRY_LOOKUP:
        return _COUNTRY_LOOKUP[n]
    # Russian/Slavic adjectives inflect heavily; match on a stem for those entries that are stems
    # The `{0,3}` zero-length case is an exact hit, already returned by the dict lookup above, so
    # any surviving match MUST end in one of [а-яёий] -- all of which lie in а-я or are ё. That
    # makes this guard provably equivalent, not a heuristic, and it skips the loop for Latin text.
    c = n[-1]
    if not ("а" <= c <= "я" or c == "ё"):
        return None
    for rx, canon in _COUNTRY_STEMS:
        if rx.fullmatch(n):
            return canon
    return None


def _is_proper(text):
    """Does the ORIGINAL surface look like a proper name?

    Added 2026-08-16 after a 12-language store exposed the same ambiguity three more times: the
    common noun `time` became TIME magazine (twice), and Italian `Un impegno` / `Un maro` became
    the United Nations. Matching is done on the lowercased form, which destroys the only signal
    that separates a name from an ordinary word — exactly the mistake `EN 1090` vs Spanish
    `en 2020` taught the first time. Scripts without case (CJK) cannot answer the question, so
    they are accepted rather than silently dropped.
    """
    cased = [ch for ch in (text or "").strip() if ch.isupper() or ch.islower()]
    if not cased:
        return True                      # no cased characters at all (CJK) -- case says nothing
    return cased[0].isupper()


# A quantity is a digit, or a number written as a word. The word list is deliberately short and
# multilingual: it exists so that "ten-year period" and "zwei Jahre" keep their Measure label,
# not to parse numerals. Anything unrecognised stays as it was -- this rule only ever fires when
# it is confident there is NO quantity at all.
_NUMWORD = re.compile(
    r"(?<![^\W\d_])("
    r"one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|twenty|thirty|forty|fifty|"
    r"hundred|thousand|million|billion|dozen|half|quarter|single|double|triple|"
    r"ein|eine|einem|zwei|drei|vier|f\u00fcnf|sechs|sieben|acht|neun|zehn|hundert|tausend|"
    r"un|une|deux|trois|quatre|cinq|six|sept|huit|neuf|dix|cent|mille|demi|"
    r"uno|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|cien|mil|"
    r"due|tre|quattro|cinque|sei|sette|otto|nove|dieci|mezzo|"
    r"bir|iki|\u00fc\u00e7|d\u00f6rt|be\u015f|alt\u0131|yedi|sekiz|dokuz|on|y\u00fcz|bin|"
    r"jeden|dwa|trzy|cztery|pi\u0119\u0107|dziesi\u0119\u0107|sto|tysi\u0105c"
    r")(?![^\W\d_])", re.I | re.U)
_HAS_QUANTITY = re.compile(r"\d")


def retype(text, current, context=""):
    """The golden-rule retyping layer -> (new_type, reason) or (None, "").

    Runs over spans that already exist. It may only RELABEL, never add or drop a span, so it
    cannot affect recall — only label accuracy, which is the measured weakness.
    """
    n = _norm(text)
    if not n:
        return None, ""

    c = country_of(text)
    if c and current in ("Location", "Organization", "Attribute", "Concept", "Other", "Person",
                         "Role", "Product", None, ""):
        return "Country", f"gazetteer: country/demonym -> {c}"

    if n in REGIONS and current in ("Country",):
        return "Location", "gazetteer: sub-national region is not a country"

    if n in MEDIA and current not in ("Organization",) and _is_proper(text):
        return "Organization", "gazetteer: media outlet"

    for r in _STANDARD:
        if r.match(n):
            if current not in ("Document",):
                return "Document", "gazetteer: standard / statute / specification"
    if _STANDARD_UPPER.match((text or "").strip()) and current not in ("Document",):
        return "Document", "gazetteer: standard (uppercase-only prefix)"
    if _AGREEMENT.search(n) and current not in ("Contract", "Document"):
        return "Contract", "gazetteer: agreement wording"

    for r in _EVENT:
        if r.search(n) and current not in ("Event",):
            return "Event", "gazetteer: operation / exercise / show"
    if _EVENT_CASED.match((text or "").strip()) and current not in ("Event",):
        return "Event", "gazetteer: named operation / exercise"

    for r in _PROGRAM:
        if r.search(n) and current not in ("Program",):
            return "Program", "gazetteer: named programme"

    # Count vs measurement, checked BEFORE facility and organisation. A span that STARTS with a
    # digit is a quantity whatever noun follows it: "11 производственных цехов" (11 production
    # workshops) is a count of eleven, not the name of a facility, and the facility rule was
    # claiming it. Standards that begin with a digit ("4.5G", "IP68") are already matched above.
    # Only spans whose type is already one of the ambiguous quantity-ish ones are eligible: a
    # span the pipeline confidently called a Date ("2026") or Money ("$4.5m") is not up for
    # reinterpretation as a count just because it begins with a digit.
    # NARROW deliberately. A first version also demoted "number + any word" to Count and promoted
    # "number + unit" to Measure. Measured: it relabelled 136 spans and cost 11 points of
    # measurement typed-recall, because "5.56x45mm" reads as "5 followed by a letter" and calibres
    # and designations are measurements. Typed recall went 81.1 -> 80.2, so the broad rule was
    # reverted and only the two unambiguous shapes kept: a BARE integer, and a CJK counter phrase.
    if n and n[0].isdigit() and current in ("Measure", "Facility", "Technology", "Concept",
                                            "Attribute", "Other", None, ""):
        if not _NUM_UNIT.match(n) and (_BARE_NUM.match(n) or _NUM_CJK.match(n)):
            return "Count", "gazetteer: bare number / counter phrase"

    # A `Measure` with no quantity in it is a word ABOUT measurement, not a measurement:
    # "range", "worth", "order volume", "another decade", "ten-year period". Measured on 100
    # documents: only 11% of spans typed Measure contained a value a parser could read, and the
    # rest were overwhelmingly this. Left alone they promise a number that is not there, and any
    # table keyed on the type inherits an 89% empty rate.
    #
    # Deliberately conservative: it fires only when there is NO digit and NO number word, so
    # "155 mm", "ten-year period" and "zwei Jahre" all keep their label. Concept, not Other,
    # because the span does still carry meaning -- it names the dimension being talked about.
    if current == "Measure" and not (_HAS_QUANTITY.search(n) or _NUMWORD.search(n)):
        return "Concept", "measurement word carrying no quantity"

    for r in _FACILITY:
        if r.search(n) and current not in ("Facility",):
            return "Facility", "gazetteer: named facility"

    for r in _ORG:
        if r.search(n) and current not in ("Organization",):
            return "Organization", "gazetteer: organisation form"
    # search, not match: the acronym alternatives carry their own `^`, but a company SUFFIX
    # ("Fincantieri SpA", "... A.Ş.") sits at the end and match() could never see it.
    if ORG_UPPER.search((text or "").strip()) and current not in ("Organization",):
        return "Organization", "gazetteer: uppercase acronym / company suffix"

    return None, ""


def stats():
    return {"countries": len(COUNTRIES),
            "country_surface_forms": len(_COUNTRY_LOOKUP),
            "regions": len(REGIONS), "media": len(MEDIA),
            "standard_patterns": len(_STANDARD), "event_patterns": len(_EVENT),
            "org_patterns": len(_ORG), "program_patterns": len(_PROGRAM),
            "total_terms": len(_COUNTRY_LOOKUP) + len(REGIONS) + len(MEDIA)
            + len(_STANDARD) + len(_EVENT) + len(_ORG) + len(_PROGRAM)}


def _demo():
    # --- 2026-08-16: ambiguity found by a 12-language store, not by the gold pack --------------
    # Every one of these is the SAME defect as `kg` = Kommanditgesellschaft: a gazetteer entry that
    # is also an ordinary word in some language. The gold pack scored identically before and after
    # the fixes (96.3/81.2/84.4), which is the point -- it never contained these cases.
    for text, cur, want in [
        # The point of this case is that the MEDIA gazetteer must not fire on the common noun.
        # It now also loses its Measure label to the no-quantity rule below, which is correct and
        # unrelated -- so assert the intent (never an Organization) rather than a literal.
        ("time", "Measure", "Concept"),            # the common noun, not TIME magazine
        ("Time", "Platform", "Organization"),
    ]:
        assert retype(text, cur)[0] == want, (text, cur, retype(text, cur))
    assert retype("time", "Measure")[0] != "Organization", "the common noun is not TIME magazine"

    # --- a Measure with no quantity is a word ABOUT measurement, not a measurement -------------
    for text, cur, want in [
        ("range", "Measure", "Concept"),
        ("worth", "Measure", "Concept"),
        ("order volume", "Measure", "Concept"),
        ("another decade", "Measure", "Concept"),
        # ...but anything carrying a quantity keeps its label, digits or words, any language
        ("155 mm", "Measure", None),
        ("1000 Kg", "Measure", None),
        ("35 years", "Measure", None),
        ("ten-year period", "Measure", None),
        ("zwei Jahre", "Measure", None),
        ("üç yıl", "Measure", None),
        # and the rule is confined to Measure: it must not demote other types
        ("range", "Equipment", None),
        ("artillery", "WeaponSystem", None),
        ("Un impegno", "Action", None),            # Italian "a commitment", not the UN
        ("Un maro", "Role", None),
        ("eu sou", "Other", None),                 # Portuguese "I am", not the EU
        ("UN", "Location", "Organization"),
        ("EU", "Location", "Organization"),
        ("exercise capabilities", "Concept", None),          # a product feature, not an exercise
        ("exercise management capability", "Concept", None),
        ("Exercise Trident Juncture", "Program", "Event"),   # a real one: the name is capitalised
        ("Operation Barkhane", "Program", "Event"),
        ("operation of the fleet", "Concept", None),
        ("allied forces", "Concept", None),                  # forces, not Operation Allied Force
        ("NATO allied armed forces", "Organization", None),
        ("Spa", "Facility", None),                           # a spa, not S.p.A.
        ("Leonardo S.p.A.", "Other", "Organization"),
        ("Fincantieri SpA", "Other", "Organization"),
        ("Rheinmetall AG", "Other", "Organization"),         # a NAME must precede the suffix...
        ("12 AG", "Measure", None),                          # ...so this measurement is untouched
        ("ag", "Other", None),
        ("1000 kg", "Measure", None),                        # the original bug, still fixed
        ("50 %", "Other", None),
        ("新华社", "Platform", "Organization"),                # CJK has no case: must not be blocked
    ]:
        assert retype(text, cur)[0] == want, (text, cur, retype(text, cur))

    # --- the exact confusions the benchmark reported, in the languages it reported them ------
    for s in ["Italian", "British", "German", "United States", "estadounidense", "senegalesi"]:
        assert retype(s, "Organization")[0] == "Country", (s, retype(s, "Organization"))
    for s in ["Türkiye", "Siria", "Iraq", "法国", "РФ", "NZ"]:
        assert retype(s, "Location")[0] == "Country", (s, retype(s, "Location"))
    # regions must NOT become countries -- gold said location, the model said country
    for s in ["Occitanie", "Ile de France", "Normandie", "Bourgogne-Franche-Comté", "California"]:
        assert country_of(s) is None, s
        assert retype(s, "Country")[0] == "Location", s
    # standards: gold `agreement`, we said `system`
    for s in ["VPAM VR9/BRV2009", "SCPI", "LTE-Advanced PRO", "4.5G", "Title 10", "section 130i",
              "MIL-STD-810", "STANAG 4569", "ISO 9001"]:
        assert retype(s, "Technology")[0] == "Document", (s, retype(s, "Technology"))
    # operations: gold `event`, we said `program`
    for s in ["Operazione Barkhane", "Resolute Support", "Operation Enduring Freedom",
              "Exercise Sea Guardian", "Eurosatory"]:
        assert retype(s, "Program")[0] == "Event", (s, retype(s, "Program"))
    # CJK ministries and media: gold `organization`
    for s in ["国家发展改革委", "财政部", "経済産業省", "民政部"]:
        assert retype(s, "Concept")[0] == "Organization", (s, retype(s, "Concept"))
    for s in ["TIME", "Libero Quotidiano", "Panorama", "Quotidiano Nazionale", "Reuters"]:
        assert retype(s, "Technology")[0] == "Organization", (s, retype(s, "Technology"))
    # named programmes
    for s in ["Joint Strike Fighter", "Air Warfare Destroyer", "AIR 5428", "Nuclear Posture Review"]:
        assert retype(s, "Platform")[0] == "Program", (s, retype(s, "Platform"))

    # --- it must NOT fire on ordinary things ------------------------------------------------
    for s, t in [("aircraft", "Product"), ("the engine", "Equipment"), ("Airbus", "Organization"),
                 ("delivers", "Action"), ("padded", "Attribute"), ("2026", "Date")]:
        assert retype(s, t)[0] is None, (s, retype(s, t))
    # --- regressions the first lexicon version CAUSED, each measured on the benchmark --------
    # `kg` is Kommanditgesellschaft AND kilograms: this retyped 10 measurements as organisations.
    # The assertion is that it is never an ORGANISATION -- "12 AG" legitimately becomes a Count.
    for s in ["1000 kg", "250 kg Nutzlast", "53 kg", "12 AG", "5 AS"]:
        assert retype(s, "Measure")[0] != "Organization", (s, retype(s, "Measure"))
    for s in ["1000 kg", "250 kg Nutzlast", "53 kg"]:
        assert retype(s, "Measure")[0] is None, (s, retype(s, "Measure"))
    # `en` and `ce` are French/Spanish words, not just standard prefixes
    for s in ["en 2020", "ce contrat", "en el marco", "ce programme"]:
        assert retype(s, "Date")[0] is None, (s, retype(s, "Date"))
    # ...but a real standard WITH its number must still be caught, uppercase or not
    for s in ["EN 1090", "ISO 9001", "IP68", "STANAG 4569", "MIL-STD-810", "VPAM VR9/BRV2009",
              "iso 14001", "CE 765/2008"]:
        assert retype(s, "Technology")[0] == "Document", (s, retype(s, "Technology"))
    # case is the ONLY separator for the short prefixes, so it must be respected both ways
    assert retype("EN 1090", "Technology")[0] == "Document"
    assert retype("en 1090 personas", "Count")[0] is None
    # whole-token only: "Mali" must not match inside another word
    assert country_of("Malicious") is None and country_of("Chadwick") is None
    assert country_of("Indianapolis") is None
    # --- count vs measurement: both directions were wrong on the benchmark ------------------
    # Only the two unambiguous shapes -- a bare integer and a CJK counter phrase.
    for s in ["53", "11万名员工", "2000"]:
        assert retype(s, "Measure")[0] == "Count", (s, retype(s, "Measure"))
    # ...and a calibre or designation must NOT be demoted: this is what cost 11 points of
    # measurement typed-recall when the rule was "number + any word".
    for s in ["5.56x45mm", "1000 Abtastwerten", "32 frecuencias", "2 DM51 hand grenades",
              "140 km/h", "250 kg", "50 %"]:
        assert retype(s, "Measure")[0] is None, (s, retype(s, "Measure"))
    # --- facilities: gold `facility`, we said `location` ------------------------------------
    for s in ["Langley Air Force Base", "Кремля", "Portsmouth Naval Base", "chantier naval",
              "Werft Hamburg", "造船厂"]:
        assert retype(s, "Location")[0] == "Facility", (s, retype(s, "Location"))
    # --- gazetteer gaps the benchmark exposed ------------------------------------------------
    assert retype("serbo", "Organization")[0] == "Country"
    assert retype("Al-Monitor", "Technology")[0] == "Organization"
    assert retype("Mil-Spec", "Technology")[0] == "Document"
    # substring matching put "mou" inside "Portsmouth" and made a naval base a contract
    assert retype("Portsmouth Naval Base", "Location")[0] == "Facility"
    assert retype("Portsmouth", "Location")[0] is None
    assert retype("signed a MoU", "Concept")[0] == "Contract"

    # already-correct labels are left alone rather than churned
    assert retype("United States", "Country")[0] is None
    assert retype("Reuters", "Organization")[0] is None
    st = stats()
    assert st["country_surface_forms"] > 500, st
    print(f"ok  ({st['total_terms']} lexicon terms: {st['countries']} countries / "
          f"{st['country_surface_forms']} surface forms, {st['regions']} regions, "
          f"{st['media']} media, {st['total_terms'] - st['country_surface_forms'] - st['regions'] - st['media']} patterns)")


if __name__ == "__main__":
    _demo() if "--demo" in sys.argv else _demo()
