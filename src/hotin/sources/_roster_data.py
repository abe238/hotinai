"""Default insider roster for the CLI, derived entirely from the GitHub API.

These are the most prolific human contributors to a set of major open-source AI
repositories (inference, training, agents, tooling, vector stores, eval, ML
infra, speech, vision), filtered to accounts with >=250 commits across that set
and ranked by commit depth.

Nothing here is curated, licensed, or borrowed. Every name was computed from
public GitHub data, and you can regenerate the whole list yourself with your own
token: see `scripts/build_roster.py`. Change the repository set or the commit
threshold and you get a different, equally valid roster -- that is the point.

What this measures, and what it does not
----------------------------------------
Commit depth finds the people who BUILD the tools. It does not find the people
whose taste the field FOLLOWS -- researchers, academics and founders who publish
and lead rather than commit. Those are close to disjoint populations: measured
against a well-known ranking of influential AI figures, this approach overlapped
by only ~4%.

So treat this default as "what are prolific AI maintainers starring", which is a
genuinely useful signal, and not as "what are famous AI people starring", which
it is not. If you want the second, supply your own cohort:

    HOTIN_INSIDER_ROSTER_PATH=/path/to/my_roster.txt
    HOTIN_INSIDER_ROSTER_PATH="karpathy, simonw, ggerganov"

(a file of handles, or a literal comma/whitespace-separated list; `#` comments
are ignored). hotin.ai runs this same code against its own separately-curated
cohort, so the public site's numbers will not match a default local run. The
method is shared and open; the cohort is a parameter you choose.

Size note: ~397 accounts is roughly 397 API calls per poll, a couple of minutes
on a local run. Raise the threshold in the generator for a faster, narrower
roster; lower it for broader coverage.
"""

# >=250 commits across the surveyed AI repositories, deepest first.
TOP_CONTRIBUTORS = (
    "tjbck", "psychedelicious", "charris", "antas-marcin", "pytorchmergebot",
    "oobabooga", "penguine-ip", "etiennedi", "dirkkul", "danielhanchen", "mikeldking",
    "AUTOMATIC1111", "ezyang", "malfet", "comfyanonymous", "mattip", "seberg",
    "harupy", "nfcampos", "ogrisel", "hiyouga", "amueller", "teoliphant", "lstein",
    "patrickvonplaten", "zou3519", "ko3n1g", "ggerganov", "glenn-jocher", "congqixia",
    "sgugger", "winglian", "cournape", "cyyever", "thomwolf", "blessedcoolant",
    "moogacs", "ydshieh", "merrymercy", "rgommers", "baskaryan", "RogerHYang",
    "abidlabs", "asdine", "A-Vamshi", "hwchase17", "pearu", "ericl", "larsmans",
    "mxyng", "logan-markewich", "bobvanluijt", "vanpelt", "eric-wieser", "jerryzh168",
    "raubitsj", "edoakes", "lhoestq", "sven1977", "soumith", "ccurme", "eyurtsev",
    "LysandreJik", "hinthornw", "JinHai-CN", "generall", "agramfort", "gchanan",
    "anijain2305", "jorenham", "axiomofjoy", "RyanJDick", "n1t0", "bigsheeper",
    "jansel", "jaredcasper", "sayakpaul", "timoffex", "aslonnie", "jwongster2",
    "mdrxy", "glouppe", "dmitryduev", "aliszka", "majdyz", "robertnishihara",
    "jerryjliu", "thomasjpfan", "Pwuts", "dhiltgen", "kritinv", "jmorganca",
    "lintangsutawika", "DarkLight1337", "peterbell10", "hnyls2002", "geekan",
    "apaszke", "Narsil", "can-anyscale", "krfricke", "rkooo567", "pprett", "fzyzcjy",
    "huydhn", "zhuwenxing", "agourlay", "WoosukKwon", "zhyncs", "B-Step62",
    "ngoldbaum", "pv", "vbarda", "xiaocai2333", "bveeramani", "suo", "mblondel",
    "vene", "jnothman", "garylin2099", "XuanYang-cn", "janeyx99", "albanD", "mwiebe",
    "Chillee", "juliantaylor", "zdevito", "spike-spiegel-21", "cydrain", "desertfire",
    "freddyaboulton", "serena-ruan", "yhmo", "jeffoverflow", "XuPeng-SH", "pngwn",
    "simon-mo", "stas00", "muellerzr", "timvisee", "albertvillanova", "tsmith023",
    "kptkin", "rolandtannous", "rohan-varma", "swolchok", "longjiquan", "rescrv",
    "glemaitre", "colesbury", "sunby", "aliabd", "parkerduckworth", "lesteve",
    "mlazos", "pcmoritz", "eellison", "jeroiraz", "joaomdmoura", "NanoCode012",
    "richardliaw", "fishpenguin", "amourao", "angelayi", "gante", "ArthurZucker",
    "BenjaminBossan", "dawoodkhan82", "bobrenjc93", "jjyao", "williamwen42", "arjoly",
    "HammadB", "mgoin", "hmellor", "weiliu1031", "shawnlewis", "sre-ci-robot",
    "Classic298", "stevhliu", "r-barnes", "patil-suraj", "smessmer",
    "pytorchupdatebot", "better629", "dqbd", "drisspg", "haileyschoelkopf",
    "robbespo00", "younesbelkada", "stefanv", "abdelr", "eqy", "Swiftyos",
    "greysonlalonde", "ngxson", "bdhirsh", "dbczumar", "kshitij12345", "pacman100",
    "jeremiedbb", "sydney-runkle", "atalman", "guilhermeleobas", "vkuzo", "leogao2",
    "Torantulino", "kavirajk", "wconstab", "stephanie-wang", "mickqian", "seemethere",
    "ekzhu", "Yangqing", "youkaichao", "wanchaol", "Rocketknight1", "codetheweb",
    "chyezh", "xige-16", "Isotr0py", "Skylion007", "TomeHirata", "jackgerrits",
    "zucchini-nlp", "waynehamadi", "BenWilson2", "slin1237", "yanliang567", "julien-c",
    "ssnl", "anticorrelator", "czs007", "amogkam", "yah01", "tugsbayasgalan", "jeffra",
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
)

ROSTER = TOP_CONTRIBUTORS
