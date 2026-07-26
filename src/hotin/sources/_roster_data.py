"""Default insider roster shipped with the CLI.

These are accounts hotin itself observed and curated: people whose GitHub
starring has been a useful signal for what is worth attention in AI. It is a
small, deliberately partial default -- running `hotin insiders` out of the box
uses it, and you will get real but modest coverage.

BRING YOUR OWN ROSTER. This mechanism is designed to be pointed at whatever
cohort you care about. Set HOTIN_INSIDER_ROSTER_PATH (in the environment or in
~/.config/hotin/.env) to either a path to a file of GitHub handles, or a literal
comma/whitespace-separated list:

    HOTIN_INSIDER_ROSTER_PATH=/path/to/my_roster.txt
    HOTIN_INSIDER_ROSTER_PATH="karpathy, simonw, ggerganov"

hotin.ai runs this same code against its own larger private roster, so the
public site's numbers will differ from a default local run. That is expected:
the method is the shared part, the cohort is a parameter.

Why the cohort is a parameter and not a constant: a roster is an editorial
judgment about who matters, and one curated for someone else's purpose is
rarely the one you want. Ours also includes material derived from a
third-party ranking that is not ours to redistribute.
"""

# Accounts hotin observed and curated directly.
OURS = (
    "ChowdhuryNeil", "MilesCranmer", "VictorTaelin", "altryne", "antgoldbloom",
    "antimatter15", "backpropper", "davemorin", "deepfates", "hmason", "jmtomczak",
    "jsngr", "kepano", "leloykun", "marksaroufim", "mayfer", "mckaywrigley",
    "mrdrozdov", "peterjliu", "quasimondo", "samsja19", "skirano", "theo",
    "thesephist", "wongmjane", "yuntiandeng", "jeremyphoward", "clefourrier",
    "Tostino", "abetlen", "tomaarsen", "vikhyat", "huybery", "winglian", "Vaibhavs10",
    "philschmid", "lvwerra", "lhoestq",
)

ROSTER = OURS
