"""Insider roster data — who counts as an "AI insider", and where each name came from.

Three provenance tiers, kept separate so the methodology is auditable (L6):

RECOVERED_FROM_DIGG_TRACE
    Mined from our own observation store (~/.local/share/hotin/cache.db, 274 cached
    insiders/smartmoney rows) — the surviving trace of digg.com's AI-1000 cohort
    before that source died behind a bot wall. 63 distinct handles were captured
    across every repo we ever tracked; these are the ones that resolve as real
    GitHub accounts. The other 28 were X/Twitter handles (digg's list was
    social-graph based). We never held the full 1000: their page exposed only the
    top ~12 starrers per repo, never the underlying cohort.

HAND_CURATED
    Well-known AI-community accounts added by hand to broaden coverage.

TOP_CONTRIBUTORS
    Derived from GitHub's own API: the contributors to 50 major AI repositories
    (inference, training, agents, tooling, vector stores, eval, ML infra, speech,
    vision), filtered to humans with >=100 total commits across that set. 4,305
    unique humans were found; the >=100-commit depth filter yields this tier.

    Why depth, not breadth: ranking by "appears in the most repos" surfaces
    prolific drive-by contributors (one account had 20 repos at 8 commits each)
    over people who actually build a project (another had 4 repos at 375 each).
    Breadth was also biased by repo selection — 7 of the 50 repos are
    HuggingFace's, so "in 2+ repos" partly just measured "works at HuggingFace".

    Roster size is bounded by the GitHub API budget, not by taste: each member
    costs ~1 call per poll and the board polls twice per 3h cycle, against a
    shared 5000/hr limit. >=100 commits keeps this comfortably inside it.

Regenerate with scratchpad/build_roster.py. This file is data, not logic.
"""

RECOVERED_FROM_DIGG_TRACE = (
    "ChowdhuryNeil", "DynamicWebPaige", "MilesCranmer", "PMinervini", "VictorTaelin",
    "altryne", "antgoldbloom", "antimatter15", "backpropper", "davemorin", "deepfates",
    "ggerganov", "hmason", "jmtomczak", "jsngr", "kepano", "leloykun", "lintool",
    "marksaroufim", "mayfer", "mckaywrigley", "mrdrozdov", "peterjliu", "quasimondo",
    "samsja19", "simonw", "skirano", "smolix", "steipete", "syhw", "theo",
    "thesephist", "wongmjane", "yisongyue", "yuntiandeng",
)

HAND_CURATED = (
    "karpathy", "jeremyphoward", "rasbt", "clefourrier", "Tostino", "abetlen",
    "tomaarsen", "vikhyat", "huybery", "winglian", "teknium1", "Vaibhavs10",
    "philschmid", "osanseviero", "julien-c", "thomwolf", "lvwerra", "natolambert",
    "soumith", "lhoestq",
)

TOP_CONTRIBUTORS = (
    "tjbck", "psychedelicious", "charris", "antas-marcin", "pytorchmergebot",
    "oobabooga", "penguine-ip", "etiennedi", "dirkkul", "danielhanchen", "mikeldking",
    "AUTOMATIC1111", "ezyang", "malfet", "comfyanonymous", "mattip", "seberg",
    "harupy", "nfcampos", "ogrisel", "hiyouga", "amueller", "teoliphant", "lstein",
    "patrickvonplaten", "zou3519", "ko3n1g", "glenn-jocher", "congqixia", "sgugger",
    "cournape", "cyyever", "blessedcoolant", "moogacs", "ydshieh", "merrymercy",
    "rgommers", "baskaryan", "RogerHYang", "abidlabs", "asdine", "A-Vamshi",
    "hwchase17", "pearu", "ericl", "larsmans", "mxyng", "logan-markewich",
    "bobvanluijt", "vanpelt", "eric-wieser", "jerryzh168", "raubitsj", "edoakes",
    "sven1977", "ccurme", "eyurtsev", "LysandreJik", "hinthornw", "JinHai-CN",
    "generall", "agramfort", "gchanan", "anijain2305", "jorenham", "axiomofjoy",
    "RyanJDick", "n1t0", "bigsheeper", "jansel", "jaredcasper", "sayakpaul",
    "timoffex", "aslonnie", "jwongster2", "mdrxy", "glouppe", "dmitryduev", "aliszka",
    "majdyz", "robertnishihara", "jerryjliu", "thomasjpfan", "Pwuts", "dhiltgen",
    "kritinv", "jmorganca", "lintangsutawika", "DarkLight1337", "peterbell10",
    "hnyls2002", "geekan", "apaszke", "Narsil", "can-anyscale", "krfricke", "rkooo567",
    "pprett", "fzyzcjy", "huydhn", "zhuwenxing", "agourlay", "WoosukKwon", "zhyncs",
    "B-Step62", "ngoldbaum", "pv", "vbarda", "xiaocai2333", "bveeramani", "suo",
    "mblondel", "vene", "jnothman", "garylin2099", "XuanYang-cn", "janeyx99", "albanD",
    "mwiebe", "Chillee", "juliantaylor", "zdevito", "spike-spiegel-21", "cydrain",
    "desertfire", "freddyaboulton", "serena-ruan", "yhmo", "jeffoverflow", "XuPeng-SH",
    "pngwn", "simon-mo", "stas00", "muellerzr", "timvisee", "albertvillanova",
    "tsmith023", "kptkin", "rolandtannous", "rohan-varma", "swolchok", "longjiquan",
    "rescrv", "glemaitre", "colesbury", "sunby", "aliabd", "parkerduckworth",
    "lesteve", "mlazos", "pcmoritz", "eellison", "jeroiraz", "joaomdmoura",
    "NanoCode012", "richardliaw", "fishpenguin", "amourao", "angelayi", "gante",
    "ArthurZucker", "BenjaminBossan", "dawoodkhan82", "bobrenjc93", "jjyao",
    "williamwen42", "arjoly", "HammadB", "mgoin", "hmellor", "weiliu1031",
    "shawnlewis", "sre-ci-robot", "Classic298", "stevhliu", "r-barnes", "patil-suraj",
    "smessmer", "pytorchupdatebot", "better629", "dqbd", "drisspg", "haileyschoelkopf",
    "robbespo00", "younesbelkada", "stefanv", "abdelr", "eqy", "Swiftyos",
    "greysonlalonde", "ngxson", "bdhirsh", "dbczumar", "kshitij12345", "pacman100",
    "jeremiedbb", "sydney-runkle", "atalman", "guilhermeleobas", "vkuzo", "leogao2",
    "Torantulino", "kavirajk", "wconstab", "stephanie-wang", "mickqian", "seemethere",
    "ekzhu", "Yangqing", "youkaichao", "wanchaol", "Rocketknight1", "codetheweb",
    "chyezh", "xige-16", "Isotr0py", "Skylion007", "TomeHirata", "jackgerrits",
    "zucchini-nlp", "waynehamadi", "BenWilson2", "slin1237", "yanliang567", "ssnl",
    "anticorrelator", "czs007", "amogkam", "yah01", "tugsbayasgalan", "jeffra",
    "njhill", "BowenBao", "BBuf", "zasdfgbnm", "jeffchuber", "RizwanMunawar",
    "XuehaiPan", "ThreadDao", "cbornet", "architkulkarni", "fishbone", "WeichenXu123",
    "houseroad", "cxie", "jeffdaily", "soulitzer", "laithsakka", "mrshenli",
    "lmcafee-nvidia", "xiaofan-luan", "binbinlv", "shanmugamr1992", "ntindle",
    "daniellok-db", "Cyrilvallez", "Y-T-G", "JohannesGaessler", "pietern",
    "BloggerBust", "lvhan028", "ydwu4", "aliabid94", "SunMarc", "sonichi", "aorenste",
    "leo-gan", "Laughing-q", "coszio", "justinvyu", "bwasti", "guangyey", "wasimysaid",
    "yewentao256", "kwen2501", "reyreaud-l", "IvanKobzarev", "lezcano", "baberabb",
    "cephalization", "bddppq", "oulgen", "BruceMacD", "Fridge003", "Yard1", "mhvk",
    "slaren", "OlivierDehaene", "youny626", "davidberard98", "DN6", "khluu",
    "bigcat88", "mdouze", "jakevdp", "zcin", "njsmith", "shoeybi", "jbschlosser",
    "deepakn94", "grimoire", "hannahblair", "mauwii", "zhxchen17", "yanboliang",
    "DimitriPapadopoulos", "LoveEachDay", "r-devulap", "HaoZeke", "mikaylagawarecki",
    "peterjc123", "redouan-rhazouani", "ArturNiederfahrenhorst", "jeejeelee",
    "shimmyshimmer", "Sicheng-Pan", "mariosasko", "w-e-w", "wangting0128", "MechCoder",
    "CISC", "goldsborough", "godchen0212", "xuhdev", "seiko2plus", "ijrsvt", "rickyyx",
    "yushangdi", "adrinjalali", "0ubbe", "anton-l", "hipsterusername", "ispobock",
    "jeffbolznv", "pianpwk", "silentoplayz", "lw", "stellaHSR", "IvanPleshkov",
    "brandonrising", "kouroshHakha", "aoiasd", "onnxbot", "fegin", "seehi",
    "NielsRogge", "dentiny", "justinchuby", "scv119", "donomii", "raulchen",
    "hunteraraujo", "Millu", "WarrenWeckesser", "ericharper", "sshleifer",
    "kurtamohler", "dayshah", "smurching", "NicoYuan1986", "alisonshao", "moretea",
    "matthewdeng", "xzfc", "ffuugoo", "AndreasKaratzas", "ch-wan", "jaime0815",
    "loadams", "yiyixuxu", "Krovatkin", "sanketkedia", "ahaldane", "qinhanmin2014",
    "elliot-barn", "Abhi1992002", "danbev", "mlflow-automation", "jaimefrio",
    "clarkzinzow", "bertmaher", "jessegross", "lorentzenchr", "H-Huang", "lucyleeow",
    "bashtage", "kevin85421", "shunting314", "NicolasHug", "asmeurer", "mehrdadn",
    "eric-jones", "tinkerlin", "StAlKeR7779", "xmfan", "lorenzejay", "richbeales",
    "rkern", "s-yeddula", "maryhipp", "mikolajblaz", "supriyar", "Bentlybro",
    "pritamdamania", "zhagnlu", "NelleV", "SimFG", "adrianbg", "masnesral",
    "IvanYashchuk", "KyleGoyette", "amyeroberts", "etaf", "suquark", "XiaobingSuper",
    "mtsokol", "robertlayton", "pythongosssss", "leslie-fang-intel", "fffrog",
    "frgossen", "shrekris-anyscale", "orange-crow", "itaismith", "omerXfaruq",
    "jeroenstraverskpn", "lukas", "Kangyan-Zhou", "rlancemartin", "anjali411", "ebr",
    "akx", "jspark1105", "LucasWilkinson", "kimishpatel", "cheahjs", "pdevine",
    "sywangyi", "trengrj", "VictorSanh", "tonyyli-wandb", "CatherineSue", "ywang96",
    "Disiok", "Ying1123", "tanujnay112", "NickLucche", "jovany-wang", "fduwjj",
    "wz337", "SherlockNoMad", "xwjiang2010", "killeent", "d4l3k", "a-r-r-o-w",
    "raimbekovm", "ParthSareen", "StellaAthena", "pierregm", "shoyer",
    "DmitriGekhtman", "JustinTong0323", "MrPresent-Han", "AllentDan", "jacoblee93",
    "simonsays1980", "Pfannkuchensack", "abrarsheikh", "shenchucheng", "tylerjereddy",
    "wxywb", "RobertCraigie", "scottjlee", "rossbar", "ruisearch42", "smellthemoon",
    "russellb", "tjruwase", "ShangmingCai", "lysnikolaou", "melissawm", "whitphx",
    "lakshanthad", "ffbin", "jon-tow", "pcuenca", "irexyc", "mfuntowicz",
    "robertgshaw2-redhat", "yfrigui2", "mwtian", "yao-matrix", "GeneDer", "aarushik93",
    "alexeykudinkin", "zhengbuqian", "b8zhong", "cyzus", "moredatarequired", "nerdai",
    "dfaker", "jacobromero", "mrwyattii", "avnishn", "danieldk", "eicherseiji", "kcze",
    "tohtana", "chaunceyjiang", "goutamvenkat-anyscale", "levand", "isahers1",
    "yonigozlan", "sanchit-gandhi", "c21", "lucasgomide", "rynewang", "czgdp1807",
    "faaany", "eltociear", "Imagineer99", "RunningLeon", "jairad26", "masci",
    "del-zhenwu", "comfyui-wiki", "reidliu41", "BillSchumacher", "Qiaolin-Yu",
    "g-despot", "smoorjani", "chainchompa", "eendebakpt", "vasqu", "mrm8488", "noooop",
    "angt", "kvareddy", "Harvester62", "JojiiOfficial", "ShirasawaSama", "haorenfsa",
    "SilenNaihin", "tlrmchlsmth", "ganesh-k13", "jarrodmillman", "mannaandpoem",
    "Pierrci", "vowelparrot", "ByronHsu", "bhancockio", "didiforgithub",
    "peytondmurray", "GreggHelt2", "JPPhoto", "SpadeA-Tang", "kriscon-db",
    "KohakuBlueleaf", "catboxanon", "drbh", "am17an", "jiqing-feng", "raghavrv",
    "MekkCyber", "jiaoew1991", "kaixuanliu", "sihanwang41", "keturn", "ahojnnes",
    "rattus128", "star1327p", "angelinalg", "rth", "salvatore-campagna-weaviate",
    "shanghaikid", "hatianzhang", "andrewnguonly", "kfstorm", "mmangkad",
    "sunishsheth2009", "yellow-shine", "jplu", "MatthewBonanni", "jjerphan",
    "yuan-luo", "maanug-nv", "aarondav", "bigPYJ1151", "dunkeroni", "jannikstdl",
    "missionfloyd", "weblate", "zhuohan123", "jayvius", "tazarov", "technovangelist",
    "tomasonjo", "yctseng0211", "andrew-anyscale", "skzhang1", "tdene", "dev2049",
    "SongGuyang", "WangTaoTheTonic", "williamberman", "StefanieSenger", "rysweet",
    "BUAADreamer", "afourney", "bcsherma", "jielinxu", "jon-barker", "kashif",
    "qingyun-wu", "ServeurpersoCom", "hlky", "0cc4m", "Qiyu8", "vinibrsl", "yhyang201",
    "betatim", "wayblink", "Justin-ZL", "Sai-Suraj-27", "jingkl", "jikunshang",
    "rueian", "huchenlei", "TomDLT", "maxpumperla", "FluorineDog", "MortalHappiness",
    "seldo", "woshiyyya", "Charlie-XIAO", "Wauplin", "LittleLittleCloud", "algoriddle",
    "jianoaix", "jllllll", "lzhangzz", "michaelpoluektov", "victordibia", "weilinear",
    "Phlip79", "shaoting-huang", "tssweeney", "chtruong814", "prithvikannan",
    "remi-or", "santhnm2", "cebtenzzre", "chenmoneygithub", "drifkin", "iamjustinhsu",
    "matthew-brett", "adrnswanberg", "alibeklfc", "beauby", "beggers", "cmarmo",
    "tolgacangoz", "AstraBert", "allozaur", "jlopatec", "ravi03071991", "clayw",
    "hzh0425", "jeffreywang88", "jiaodong", "varun-sundar-rabindranath", "heheda12345",
    "onuralpszr", "space-nuko", "ikaharudin", "lnhsingh", "wuisawesome", "ikawrakow",
    "keenborder786", "kemaleren", "yeahdongcn",
)

ROSTER = RECOVERED_FROM_DIGG_TRACE + HAND_CURATED + TOP_CONTRIBUTORS
