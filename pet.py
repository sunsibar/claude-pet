#!/usr/bin/env python3
# ASCII pet for the Claude Code status line.
#   python3 pet.py show [name]  -> status line (no name = the picked pet, default gloop)
#   python3 pet.py pick <name>  -> choose the pet (gloop, bandit, quack, or any file in pets/)
#   python3 pet.py list         -> list the pets, the picked one is marked
#   python3 pet.py hook         -> called by Claude Code hooks, sets the mood
#   python3 pet.py install      -> links this folder to ~/.claude/pet and adds the pet to ~/.claude/settings.json
#   python3 pet.py uninstall    -> removes the pet from ~/.claude/settings.json again
import json, os, random, re, sys, time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(HERE, "state")
CHOICE_FILE = os.path.join(HERE, "chosen-pet.txt")

COLORS = {"gloop": "38;5;75", "bandit": "38;5;141", "quack": "38;5;220"}  # ANSI 256 colors
WIDTH = 13          # columns reserved for the pet before the text starts
DONE_TO_IDLE = 30   # seconds before "done" relaxes back to "idle"
IDLE_TO_SLEEP = 300 # seconds of "idle" before the pet naps
NAPS = ["sleeping", "chilling", "playing"]  # a nap is one of these, at random
# a reply like this, or a background shell / subagent started this turn, = nap instead of "done"
WAIT = re.compile(r"(in the background|still running|will be notified|get notified|i'll wait|waiting (for|on)|once (it|they|that)'?s? (finish|complete|done))", re.I)
# Moods from highest to lowest priority; moods on one line rank the same.
# One rule: a mood with a HOLD time can't be replaced by a lower-priority mood until that time is over.
# After that (or for moods without a HOLD time), any new mood replaces it.
PRIORITY = [["startled"], ["defensive"], ["embarrassed", "confused", "failed"], ["careful"],
            ["asking", "hectic", "working", "thinking", "lecturing", "singing", "done",
             "idle", "sleeping", "chilling", "playing", "surprised"]]
RANK = {m: i for i, row in enumerate(PRIORITY) for m in row}  # lower number = higher priority
HOLD = {"startled": 20, "defensive": 60, "embarrassed": 5, "confused": 5, "failed": 5, "careful": 30}  # seconds
VARIANTS = {"startled": "surprised"}  # shown instead half the time, if the pet has art for it
THINK_TO_WORK = 10  # seconds of "thinking" after your prompt before it counts as "working"
STARTLE_CAPS = 0.6  # share of letters in capitals for "startled" ...
STARTLE_LETTERS = 10  # ... in a prompt with at least this many letters ...
STARTLE_UNDERSCORES = 0.1  # ... and at most this many underscores per word (CONSTANT_NAMES are code, not yelling)
HECTIC_CALLS = 6    # this many tool calls ...
HECTIC_WINDOW = 20  # ... within this many seconds = "hectic"
LECTURE_CHARS = 1500   # an answer this long (characters) = "lecturing" or "singing" (random) after it finishes ...
LECTURE_SPEED = 150    # ... for one second per this many characters ...
LECTURE_MAX = 20       # ... but at most this many seconds, then "done"
CONFUSED_WINDOW = 120  # a second tool failure within this many seconds = "confused"
# a prompt matching this = "defensive" (you are insulting it); checked before OOPS
# a prompt matching this = "embarrassed" (you are correcting it)
# tested on ~7000 past prompts: ~1.4% false alarms, mostly swearing at the situation
_YOU = r"(?:you|u|ya|you're|youre|ur|you are|are you|you being|you're being|youre being|you were|you look|you seem)"
_ADV = r"(?:\s+(?:so|such|really|being|a|an|just|totally|completely|utterly|absolutely|fucking|fuckin|little|lazy|dumb|stupid|the|most|of|one|some|incredibly|very|that))*"
_BAD = r"(?:stupid|dumb\w*|useless|uselless|useles|garbage|trash|crap|lazy|lazyass|incapable|incompetent|pathetic|idiot\w*|moron\w*|liar|lying|r.tard\w*|bastard\w*|joke|disgrace|waste of (?:time|space|tokens))"
INSULT = re.compile(
 r"\b(?:"
 r"fuck\w*|f\*+k\w*|wtf|wth|ffs|stfu"
 r"|bull ?shit\w*|shit(?!\s?tons?\b)\w*"
 r"|idiot\w*|moron\w*|dumbass\w*|ass ?holes?|arse ?holes?|asshol\w*|bastard\w*|lazy ?ass|jackass|dipshit"
 r"|" + _YOU + _ADV + r"\s+" + _BAD +
 r"|(?:this|that|it)(?:'s| is| was)" + _ADV + r"\s+(?:garbage|crap|bullshit|trash)"
 r"|(?<!not )(?:total|complete|utter|pure|absolute)(?:ly)?\s+(?:garbage|crap|nonsense|useless)|how (?:stupid|dumb) (?:are you|you are)"
 r"|you (?:lied|lie)\b|lying to me|lied to me|liar"
 r"|(?:hate|despise) you|i hate the likes of you"
 r"|(?:are you|you must be|you) (?:\w+ )?kidding(?: me)?|kidding me"
 r"|what the (?:hell|heck|f)|the hell (?:are|is|did|do|was)|why the hell|for (?:god'?s|fuck'?s|christ'?s) sake|jesus christ|god ?damn\w*"
 r"|are you serious|are you insane|are you crazy|are you deaf|are you blind"
 r"|(?:can you|do) your (?:fucking )?job|go die|screw you|piss off|shut up"
 r"|stop wasting my time|wasting my time|stealing my time"
 r")\b")
INSULT_MAX_CHARS = 1500  # longer prompts are mostly pasted text, not you talking: no insult check
def insulting(prompt):
    if len(prompt) > INSULT_MAX_CHARS:
        return False
    prompt = re.sub(r"^\s*>.*$", "", prompt, flags=re.M)  # quoted lines
    prompt = re.sub(r'"[^"\n]{0,600}"|“[^”\n]{0,600}”', '""', prompt)  # quoted words
    return bool(INSULT.search(prompt))
OOPS = re.compile(r"^\s*(no|nope)\b(?!\s+(idea|worries|problem|rush|need|thanks|clue))|\b(wrong|undo|revert|why did you|that'?s not|didn'?t ask|you broke|stop)\b")  # "no" only at the start

EVENT_MOOD = {
    "SessionStart": "idle",
    "UserPromptSubmit": "thinking",
    "PreToolUse": "working",
    "PostToolUseFailure": "failed",
    "PermissionRequest": "asking",
    "Stop": "done",
}

def read_stdin():
    try:
        return json.load(sys.stdin)
    except Exception:
        return {}

def state_file(session):
    return os.path.join(STATE_DIR, (session or "default") + ".json")

def load_state(session):
    try:
        with open(state_file(session)) as f:
            return json.load(f)
    except Exception:
        return {"mood": "idle", "since": 0, "line": 0}

def save_state(session, st):
    os.makedirs(STATE_DIR, exist_ok=True)
    tmp = state_file(session) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
    os.replace(tmp, state_file(session))

def answer_text(data):
    """Text of Claude's last answer (since your last prompt)."""
    msg = data.get("last_assistant_message")
    if isinstance(msg, str):
        return msg
    parts = []
    try:
        with open(data.get("transcript_path") or "") as f:
            lines = f.readlines()[-400:]
    except Exception:
        return ""
    for raw in reversed(lines):
        try:
            entry = json.loads(raw)
        except Exception:
            continue
        content = (entry.get("message") or {}).get("content")
        if entry.get("type") == "user":
            is_tool_result = isinstance(content, list) and any(
                isinstance(c, dict) and c.get("type") == "tool_result" for c in content)
            if not is_tool_result:
                break  # reached your prompt
        elif entry.get("type") == "assistant" and isinstance(content, list):
            parts[:0] = [c.get("text", "") for c in content
                         if isinstance(c, dict) and c.get("type") == "text"]
    return "\n".join(parts)

def parse_order(text):
    nums = lambda s: [int(x) for x in s.replace(",", " ").split()]
    if "|" in text:
        intro, loop = text.split("|", 1)
        return nums(intro), nums(loop)
    return [], nums(text)

def load_pet(name):
    moods, cur = {}, None
    with open(os.path.join(HERE, "pets", name + ".txt")) as f:
        for raw in f.read().split("\n"):
            line = raw.rstrip()
            if line == "":
                continue
            if line.startswith("@"):
                parts = line[1:].split(None, 1)
                cur = {"frames": [[]], "order": parse_order(parts[1] if len(parts) > 1 else "")}
                moods[parts[0]] = cur
            elif cur is None:
                continue
            elif line.strip() == "--":
                cur["frames"].append([])
            elif len(cur["frames"][-1]) < 4:
                cur["frames"][-1].append("" if line.strip() == "%" else line)
    return moods

def load_lines():
    lines, cur = {}, None
    try:
        with open(os.path.join(HERE, "lines.txt")) as f:
            for raw in f.read().split("\n"):
                line = raw.strip()
                if not line:
                    continue
                if line.startswith("@"):
                    cur = lines.setdefault(line[1:].strip(), [])
                elif cur is not None:
                    main, _, aside = line.partition("|")
                    cur.append((main.strip(), aside.strip()))
    except Exception:
        pass
    return lines

def pick_frame(mood_data, t):
    frames = mood_data["frames"]
    intro, loop = mood_data["order"]
    if not loop and not intro:
        loop = list(range(len(frames)))
    if t < len(intro):
        i = intro[t]
    elif loop:
        i = loop[(t - len(intro)) % len(loop)]
    else:
        i = intro[-1]
    return frames[i] if 0 <= i < len(frames) else frames[0]

def base_mood(st, now):
    """The latest event's mood, after it has had time to relax (thinking -> working, done -> idle -> nap)."""
    mood, since = st.get("mood", "idle"), st.get("since", 0)
    if mood == "thinking" and now - since > THINK_TO_WORK:  # the one special case
        mood, since = "working", since + THINK_TO_WORK
    relax = {  # mood: (after this many seconds, becomes this mood)
        "startled": (HOLD["startled"], "careful"),
        "lecturing": (st.get("lecture_for", 0), "done"),
        "singing": (st.get("lecture_for", 0), "done"),
        "done": (DONE_TO_IDLE, "idle"),
        "idle": (IDLE_TO_SLEEP, NAPS[st.get("line", 0) % len(NAPS)]),
    }
    while mood in relax and now - since > relax[mood][0]:
        after, nxt = relax[mood]
        mood, since = nxt, since + after
    return mood, since, st.get("line", 0)

def yelling(prompt):
    letters = [c for c in prompt if c.isalpha()]
    words = max(1, len(prompt.split()))
    return (len(letters) >= STARTLE_LETTERS
            and sum(c.isupper() for c in letters) >= STARTLE_CAPS * len(letters)
            and prompt.count("_") <= STARTLE_UNDERSCORES * words)

def show(name):
    data = read_stdin()
    st = load_state(data.get("session_id"))
    now = time.time()
    mood, since, line = base_mood(st, now)
    pet = load_pet(name)
    if mood in VARIANTS and VARIANTS[mood] in pet and line % 2:
        mood = VARIANTS[mood]  # half the time, a pet that has the variant shows it instead
    mood_data = pet.get(mood) or pet["idle"]
    frame = pick_frame(mood_data, max(0, int(now - since)))

    says = load_lines().get(mood) or [("", "")]
    main, aside = says[line % len(says)]
    model = (data.get("model") or {}).get("display_name", "")
    folder = os.path.basename((data.get("workspace") or {}).get("current_dir", "") or data.get("cwd", ""))
    talk = "38;5;203" if mood == "failed" else "0"
    right = [f"\033[{talk}m{main}\033[0m", f"\033[2m{aside}\033[0m", "", f"\033[2m{model}  {folder}\033[0m"]

    color = COLORS.get(name, "0")
    out = []
    for r in range(4):
        row = frame[r] if r < len(frame) else ""
        # leading reset keeps the art's leading spaces from being trimmed
        out.append(f"\033[0m\033[{color}m{row.ljust(WIDTH)}\033[0m {right[r]}")
    print("\n".join(out))

def hook():
    data = read_stdin()
    event = data.get("hook_event_name", "")
    session = data.get("session_id")
    st = load_state(session)
    now = time.time()
    mood = EVENT_MOOD.get(event)

    tools = [t for t in st.get("tools", []) if now - t < HECTIC_WINDOW]
    if event == "PreToolUse":
        tools.append(now)
        tool, args = data.get("tool_name", ""), data.get("tool_input") or {}
        if tool in ("Agent", "Task") or args.get("run_in_background"):
            st["bg"] = True  # started something that keeps running after the reply
        if len(tools) >= HECTIC_CALLS:
            mood = "hectic"
    elif event == "PostToolUseFailure":
        if now - st.get("last_fail", 0) < CONFUSED_WINDOW:
            mood = "confused"
        st["last_fail"] = now
    elif event == "UserPromptSubmit":
        raw = data.get("prompt") or ""
        prompt = raw.lower()
        st["bg"] = None
        reactions = []
        if insulting(prompt):
            reactions.append("defensive")
        if OOPS.search(prompt):
            reactions.append("embarrassed")
        reaction = min(reactions, key=RANK.__getitem__, default=None)
        if yelling(raw):
            mood = "startled"
        elif reaction:
            mood = reaction
    elif event == "Stop":
        text = answer_text(data)
        n = len(text)
        if st.pop("bg", None) or WAIT.search(text):
            mood = random.choice(NAPS)  # waiting on background work
        elif n >= LECTURE_CHARS:
            mood = random.choice(["lecturing", "singing"])
            st["lecture_for"] = min(LECTURE_MAX, n / LECTURE_SPEED)
    st["tools"] = tools
    if mood:
        set_mood(st, mood, now)
    save_state(session, st)

def set_mood(st, mood, now):
    """Switch to a new mood, unless the current one is held and outranks it."""
    cur = base_mood(st, now)[0]
    if now < st.get("until", 0) and RANK.get(mood, 99) > RANK.get(cur, 99):
        return  # current mood is still held and has higher priority
    if mood in ("working", "hectic") and cur == mood:
        return  # already busy: keep the animation running instead of restarting it
    st.update(mood=mood, since=now, line=random.randrange(1000), until=now + HOLD.get(mood, 0))

def all_pets():
    return sorted(f[:-4] for f in os.listdir(os.path.join(HERE, "pets")) if f.endswith(".txt"))

def chosen():
    try:
        with open(CHOICE_FILE) as f:
            name = f.read().strip()
        if name in all_pets():
            return name
    except Exception:
        pass
    return "gloop"

def pick(name):
    if name not in all_pets():
        sys.exit(f"unknown pet '{name}'. choose one of: {', '.join(all_pets())}")
    with open(CHOICE_FILE, "w") as f:
        f.write(name + "\n")
    print(f"pet is now {name}")

def list_pets():
    cur = chosen()
    for name in all_pets():
        print(("* " if name == cur else "  ") + name)

CLAUDE_DIR = os.path.join(os.path.expanduser("~"), ".claude")
SETTINGS = os.path.join(CLAUDE_DIR, "settings.json")
PET_LINK = os.path.join(CLAUDE_DIR, "pet")

def read_settings():
    try:
        with open(SETTINGS) as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except Exception as e:
        sys.exit(f"could not read {SETTINGS} ({e}); nothing changed")

def write_settings(st):
    import shutil
    target = os.path.realpath(SETTINGS)  # keep a symlinked settings.json a symlink
    if os.path.exists(target):
        backup = SETTINGS + time.strftime(".backup-%Y-%m-%d-%H%M%S")
        shutil.copy2(target, backup)  # copy2 keeps the file's permissions
        print(f"backup of your settings: {backup}")
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target + ".tmp", "w") as f:
        json.dump(st, f, indent=2)
        f.write("\n")
    if os.path.exists(target):
        shutil.copymode(target, target + ".tmp")
    os.replace(target + ".tmp", target)

def install():
    os.makedirs(CLAUDE_DIR, exist_ok=True)
    if not os.path.lexists(PET_LINK):
        os.symlink(HERE, PET_LINK)
        print(f"linked {PET_LINK} -> {HERE}")
    elif os.path.realpath(PET_LINK) != os.path.realpath(HERE):
        sys.exit(f"{PET_LINK} already exists and is not this folder; move it away first. nothing changed")
    with open(os.path.join(HERE, "settings-example.json")) as f:
        example = json.load(f)
    st = read_settings()
    old = st.get("statusLine")
    if old and old != example["statusLine"]:
        print(f"replacing your status line (it is in the backup): {old.get('command', old)}")
    st["statusLine"] = example["statusLine"]
    hooks = st.setdefault("hooks", {})
    for event, entries in example["hooks"].items():
        cmd = entries[0]["hooks"][0]["command"]
        mine = hooks.setdefault(event, [])
        if not any(h.get("command") == cmd for e in mine for h in e.get("hooks", [])):
            mine.append(entries[0])
    write_settings(st)
    print("done. restart Claude Code to see the pet.")

def uninstall():
    with open(os.path.join(HERE, "settings-example.json")) as f:
        example = json.load(f)
    st = read_settings()
    if st.get("statusLine") == example["statusLine"]:
        del st["statusLine"]
    cmd = "python3 ~/.claude/pet/pet.py hook"
    for event in list(st.get("hooks", {})):
        kept = []
        for e in st["hooks"][event]:
            e["hooks"] = [h for h in e.get("hooks", []) if h.get("command") != cmd]
            if e["hooks"]:
                kept.append(e)
        if kept:
            st["hooks"][event] = kept
        else:
            del st["hooks"][event]
    write_settings(st)
    print("pet removed from your settings. restart Claude Code.")
    print("your old status line, if you had one, is in the backup from when you installed.")

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "show"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "pick" and arg:
        pick(arg)
    elif cmd == "list":
        list_pets()
    elif cmd == "install":
        install()
    elif cmd == "uninstall":
        uninstall()
    else:
        try:
            if cmd == "hook":
                hook()
            else:
                show(arg or chosen())
        except Exception:
            pass  # never break Claude Code over a pet
