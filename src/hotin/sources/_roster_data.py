"""Insider roster — who counts as an "AI insider", and where each name came from.

AI_1000
    The AI-1000 cohort from digg.com/tech/x/rankings, ranked by "tech ranked
    followers" (how many already-ranked tech accounts follow you). Captured from
    a copy of the page saved locally, then parsed; the live source later went
    behind a bot wall. 759 of the 1000 list a GitHub account, deduped by handle
    (one person held two X accounts pointing at one repo account) and kept in
    rank order, so roster position mirrors the cohort's own ranking.

    NOTE: 64% of these people use a different handle on GitHub than on X
    (DavidDuvenaud -> duvenaud, chrmanning -> manning, goodfellow_ian ->
    goodfeli). The two are stored separately in the source data and must never
    be assumed equal — assuming it would corrupt ~488 of these entries.

    This replaced an earlier attempt to synthesise an equivalent list from
    GitHub contributor data (top committers to 50 major AI repos). Measured
    against this list, that approach found only 4% of it and missed ylecun,
    andrewyng, cbfinn, manning, srush, percyliang and most of the top 50.
    Commit volume measures who BUILDS; this list measures whose judgment the
    field FOLLOWS. For a "what are notable people starring" signal the second is
    what matters. Recorded as a negative result so nobody re-derives it.

OURS_EXTRA
    Accounts from our own observation store and hand-curation that are not in
    the AI-1000 (ggerganov, HuggingFace maintainers, and similar). Real signal,
    just outside that cohort.

Roster size is bounded by the GitHub API budget: ~1 call per member per poll,
two polls per 3h cycle, against a shared 5000/hr limit.

Source data: ~/Downloads/AI-1000/ai-1000.json
"""

AI_1000 = (
    "karpathy", "ylecun", "goodfeli", "andrewyng", "oriolvinyals", "sarahooker",
    "cbfinn", "kyunghyuncho", "manning", "colah", "srush", "pabbeel", "larocheh",
    "nandodf", "percyliang", "lilianweng", "thomwolf", "svlevine", "sleepinyourhat",
    "zackchase", "demishassabis", "akhaliq", "gdb", "jacobandreas", "joschu",
    "janleike", "duvenaud", "noambrown", "dpkingma", "jackclarksf", "droy",
    "jasonwei20", "rockt", "yejinc", "benjamin-recht", "sebastianruder", "hardmaru",
    "soumith", "hal3", "tdietterich", "dwarkeshsp", "timdettmers", "huggingface",
    "nat", "tengyuma", "ericjang", "DrJimFan", "BeenKim", "shakirm", "alexandr",
    "egrefen", "AranKomat", "lucasb-eyer", "natolambert", "dustinvtran", "ofirpress",
    "zkolter", "suchenzang", "fchollet", "poolio", "neubig", "rgrosse",
    "natashamjaques", "wojzaremba", "benanne", "profsanjeevarora", "yoavg", "ywteh",
    "Newmu", "jph00", "DavidSHolz", "liamb315", "rohan-anil", "aravindsrinivas",
    "barretzoph", "rpadams", "logankilpatrick", "sholtodouglas", "egcap", "delip",
    "tridao", "yisongyue", "jasondlee88", "casutton", "aleksmadry", "jfrankle",
    "bneyshabur", "diyiy", "mattjj", "garrytan", "jakobnicolaus", "danqi", "yaringal",
    "achowdhery", "murphyk", "randomwalker", "saranormous", "ibab", "tkipf",
    "millionintegrals", "fhuszar", "mmitchellai", "jekbradbury", "tscohen",
    "Eric-Wallace", "sriramk", "gwern", "jeffclune", "hendrycks", "bamos",
    "jaseweston", "sohl-dickstein", "andrewgordonwilson", "DaniloRezende",
    "ethanjperez", "tgebru", "hannawallach", "shmsw25", "satyanadella", "aaskell",
    "boazbk", "lexfridman", "lukemetz", "mimosavvy", "lawrennd", "vanzytay",
    "phillipi", "shamulent", "s9xie", "catherio", "yoavartzi", "deviparikh",
    "markriedl", "jachiam", "emostaque", "rasbt", "dpfau", "stanislavfort", "balajis",
    "goodside", "aconneau", "bmcgrew", "yuandong-tian", "rowanz", "emollick",
    "erichorvitz", "dennyzhou", "chillee", "okhat", "hoonose", "tomgoldstein",
    "leopoldaschenbrenner", "capybaralet", "thashim", "simonw", "lmthang",
    "danielgross", "janexwang", "noamshazeer", "collision", "fh295", "cgpotts",
    "anadim", "agarwl", "riedelcastro", "scychan", "gregdurrett", "kevinweil",
    "beirami", "albertfgu", "TalLinzen", "tobi", "chiphuyen", "amasad", "swyxio",
    "rishibommasani", "dfield", "thegregyang", "yang-song", "adamdangelo", "nsaphra",
    "redpony", "neelnanda-io", "PalmerLuckey", "mathemajician", "ezelikman",
    "jxmorris12", "monkbent", "arthurmensch", "glample", "profjure", "jasonbaldridge",
    "douwekiela", "emilymbender", "animesh-garg", "mnielsen", "merettm", "eunsol",
    "doomie", "smerity", "dmrd", "zhuzeyuan", "BlackHC", "deedy", "raiah",
    "karinanguyen", "avdnoord", "Nearcyan", "vbuterin", "jeisner", "joannejang",
    "lampinen", "hhexiy", "eshear", "jacobeisenstein", "fbach2000", "dhruvbatra",
    "stellaathena", "mireshghallah", "smolix", "typedfemale", "racheltho", "pathak22",
    "mrkulk", "rajiinio", "Cogitans", "welinder", "jaderberg", "MelMitchell1",
    "akariasai", "adityaramesh", "dhadfieldmenell", "sameersingh", "aidangomez",
    "finiteloop", "michaeljblack", "ShengjiaZhao", "jonbarron", "soldni",
    "suryaganguli", "shivonz", "kohpangwei", "eugenevinitsky", "cmaddis", "IrwanBello",
    "61cygni", "douglaseck", "prafullasd", "mgbellemare", "miyyer", "jbhuang0604",
    "JustinLin610", "da03", "jiajunwu", "truell20", "KaiWeiChang", "alextamkin",
    "sustcsonglin", "julien-c", "dennybritz", "ysymyth", "teknium1", "cdixon",
    "DoctorTeeth", "sivareddyg", "maithraraghu", "balajiln", "omerlevy", "KhoomeiK",
    "echoyuzhou", "nathanbenaich", "owainevans", "dpfried", "yoshua", "vered1986",
    "aidanmclaughlin", "wenhuchen", "jluan", "yanndubs", "cocoxu", "0hq", "swj0419",
    "ezubaric", "MostafaDehghani", "JohnLangford", "mdenil", "suhail", "danijar",
    "arimorcos", "BorisPower", "robinjia", "bcherny", "matt-gardner", "dsontag",
    "yuchenlin", "girving", "steipete", "iosband", "nelson-liu", "maartensap", "Szepi",
    "rauchg", "jessedodge", "Feryal", "nottombrown", "dynamicwebpaige", "irapha",
    "eric-xw", "ybisk", "swabhs", "ysu1989", "dsadigh", "brendenlake", "preetum",
    "izmailovpavel", "arthurgretton", "yacineMTB", "orph", "korymath",
    "meredith-signal", "mcaleste", "kamalikach", "yukezhu", "kayoyin", "ludwigschmidt",
    "mbavar", "kawine", "sea-snell", "yimaeecs", "johncoogan", "barmstrong", "mateiz",
    "theoweber", "KarolHausman", "FurongHuang", "sebastianGehrmann", "ajayjain",
    "rajammanabrolu", "jcjohnson", "pulkitag", "jayelm", "anjneymidha", "haniesedghi",
    "koraykv", "hwchung27", "wpeebles", "kipply", "LachyGroom", "VioletPeng", "geohot",
    "iamtrask", "patio11", "ncammarata", "yuhuaiwu", "eric-mitchell", "NoviScl",
    "rraileanu", "n-mca", "akanazawa", "tqchen", "boknilev", "Sanger2000",
    "mishalaskin", "sarahwie", "john-hewitt", "aditya-grover", "mlittmancs",
    "drewhouston", "ari-holtzman", "AnanyaKumar", "leogao2", "ngoodman", "andrewnc",
    "rylanschaeffer", "machelreid", "stephenroller", "alexalbertt", "davidbau",
    "shreyashankar", "reedscot", "ruiqi-zhong", "syhw", "allenbai01", "jam3scampbell",
    "tibo-openai", "naveengrao", "Edward-Sun", "lvhimabindu", "yilundu", "edchi",
    "psc-g", "hyren", "annargrs", "gillverd", "vzhong", "andrewchen", "rizar",
    "cohere-ai", "andrewmccallum", "scott-gray", "Will-Manidis-Cascade", "erikto",
    "sashavor", "abhishekunique", "chenhaot", "lucy3", "maxlevchin", "jimmylba", "yk",
    "willccbb", "eringrant", "isabelleaugenstein", "laurent-dinh", "atcbosselut",
    "tongshuangwu", "rmrafailov", "wellecks", "isafulf", "victorsanh",
    "thestephencasper", "sangmichaelxie", "csvoss", "yonatansito", "ryan-lowe",
    "xiaolonw", "catherinewu", "siddk", "mikeyk", "jbigham", "todpole3", "vkrakovna",
    "lennysan", "mononofu", "searchivarius", "cranmer", "minilek", "jiamings",
    "abisee", "ctlllll", "francoisfleuret", "samin100", "jmhessel", "evhub",
    "leecjohnny", "timvieira", "cchan", "kyleclo", "npapernot", "yobibyte",
    "sherjilozair", "franxyao", "YuchenJin", "nikiparmar", "yizhongw", "AlexiaJM",
    "thomason-jesse", "david-abel", "misovalko", "epierson9", "hlml", "tunguz",
    "martinshkreli", "sschoenholz", "alexisjihyeross", "irenetrampoline", "infoxiao",
    "breakend", "pliang279", "zhijing-jin", "gabrielpetersson", "ArmenAg", "sebkrier",
    "amarasovic", "amyzhang", "andyljones", "aw31", "imurray", "tmabraham",
    "angelikilazaridou", "atcold", "annagoldie", "andipeng", "TimSalimans",
    "gabrielilharco", "honglaklee", "daniellevy", "gd-zhang", "mbchang", "mordatch",
    "asaprahul", "gaotianyu1350", "levelsio", "wyshi", "SebastianThrun", "keroro824",
    "JiahuiYu", "aritter", "bryancatanzaro", "shayne-longpre", "vsitzmann", "junyanz",
    "qkaren", "petarv-", "swarooprm", "finbarrtimbers", "yuqirose", "mtegmark", "my89",
    "romainhuet", "shanzhenren", "XiangLi1999", "ravidziv", "gjtucker", "karthikncode",
    "viking-sudo-rm", "gkioxari", "yoshavit", "omarsar", "clementfarabet", "beerys",
    "socketteer", "osanseviero", "abebabirhane", "dmoskov", "JasperSnoek",
    "cvalenzuela", "ofirnachum", "sherwu", "belindal", "zebulgar", "kelvinguu",
    "moxie0", "ztangent", "erikbern", "mshumer", "adinawilliams", "kaixhin",
    "arvind-neural", "kellerjordan", "shurans", "Mascobot", "multipath", "heiner",
    "MaxASchwarzer", "timothybrooks", "theTejMahal", "hwchase17", "kanjun", "gabgoh",
    "yanaiela", "yixuanli", "ruiqigao", "dguo98", "jxnl", "ivzhao", "unixpickle",
    "pminervini", "jlin816", "rtqichen", "neilhoulsby", "dblalock", "aryamanarora",
    "DanielleFong", "vicenteor", "wenting-zhao", "austenallred", "lukaszkaiser",
    "cvondrick", "emtiyaz", "patrick-s-h-lewis", "davidad", "yaroslavvb",
    "christinakim", "joschabach", "limanling", "lerrel", "emorikawa", "flaque",
    "donglixp", "fxia22", "aviralkumar2907", "tonyzhaozh", "boztank", "arnauddoucet",
    "mimno", "nickfrosst", "devonzuegel", "jacobaustin123", "rohinmshah",
    "rememberlenny", "norouzi", "muennighoff", "AbhilashaRavichander", "xiamengzhou",
    "qipeng", "jparkerholder", "TrentBrick", "yasamanb", "ksayash", "mpshanahan",
    "paulbuchheit", "explorerfreda", "dileeplearning", "atroyn", "katja-hofmann",
    "alisawuffles", "elder-plinius", "nouhadziri", "mcleavey", "thariqs", "scottyih",
    "HanGuo97", "sjmielke", "jbohg", "jmoore994", "midjourney", "togelius", "bscholl",
    "tommmitchell", "taoyds", "liuzhuang13", "Jungyhuk", "devendrachaplot", "dellaert",
    "haileyschoelkopf", "bodono", "apaszke", "josh-tobin", "zphang", "blader",
    "RJT1990", "riannevdberg", "dlwh", "mfaruqui", "yosinski", "zhaoranwang",
    "robertnishihara", "bplank", "ggerganov", "mdredze", "nschneid", "peterbhase",
    "Ying1123", "xjdr-alt", "zhoubolei", "wwcohen", "CHandmer", "caglar", "geomblog",
    "lishali", "danfeiX", "coreylynch", "cpaxton", "ajbrock", "julianmichael",
    "lintool", "rromb", "danfu09", "cathykc", "chuangg", "stevesi", "natschluter",
    "ikostrikov", "tedsanders", "jxbz", "merveenoyan", "kuleshov", "altimor",
    "leighmarie", "rao2z", "goldblum", "kzl", "hyhieu", "akosiorek", "quantombone",
    "jmcohen", "robodhruv", "mikeknoop", "techcrunch", "danyaljj", "Moustapha6C",
    "mickypaganini", "aminkarbasi", "timoreilly", "vincentweisser", "canondetortugas",
    "negar-rostamzadeh", "sharonzhou", "mbernst", "krandiash", "andrejristeski",
    "jalammar", "alexander-kirillov", "brendano", "alexpolozov", "ethancaballero",
    "mblondel", "kevinzakka", "heyyjudes", "lauraruis", "paraga", "CSProfKGD",
    "AdrienLE", "sherryy", "jerryjliu", "logangraham", "renmengye", "AdamGleave",
    "shuyanzhou", "tommccoy1", "azizishekoofeh", "snavely", "cloneofsimo",
    "wgrathwohl", "xinw1012", "zlite", "sergebelongie", "kvogt", "urvashik",
    "ranjaykrishna", "micahcarroll", "ksaenko", "idavidrein", "jiayi-pan", "kswersky",
    "danintheory", "amueller", "andreykurenkov", "jazcollins", "mckinziebrandon",
    "lvdmaaten", "sniekum", "vveitch", "langchain-ai", "pratyushasharma",
    "ekinakyurek", "jasoncrawford", "fehrsam", "smilli", "artetxem", "tuhinjubcse",
    "nazneenrajani", "ogrisel", "lattner", "mcmachado", "dribnet", "reinerp", "znado",
    "borgr", "matthen", "aliceoh9", "dshipper", "summer-yue", "milesgrimshaw",
    "mitchellnw", "adityakusupati", "ruchowdh", "Besiroglu", "dyogatama",
)

OURS_EXTRA = (
    "ChowdhuryNeil", "MilesCranmer", "VictorTaelin", "altryne", "antgoldbloom",
    "antimatter15", "backpropper", "davemorin", "deepfates", "hmason", "jmtomczak",
    "jsngr", "kepano", "leloykun", "marksaroufim", "mayfer", "mckaywrigley",
    "mrdrozdov", "peterjliu", "quasimondo", "samsja19", "skirano", "theo",
    "thesephist", "wongmjane", "yuntiandeng", "jeremyphoward", "clefourrier",
    "Tostino", "abetlen", "tomaarsen", "vikhyat", "huybery", "winglian", "Vaibhavs10",
    "philschmid", "lvwerra", "lhoestq",
)

ROSTER = AI_1000 + OURS_EXTRA
