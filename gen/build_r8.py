"""r8 sets: public-list fact memorisation + r7's material.

Why: since 14 Nov about two thirds of the node's check pairs are same-template answers that differ in one list
fact (UID, program set, registration number, matched name), with the fact absent from the prompt. r3-r7 are at
chance there; gen/build_probe.py showed an adapter can learn these (88-92% on seen entities in unseen templates).
This builder renders every OFAC SDN / non-SDN, UN, EU and UK entry in many prompt wordings and answer templates,
with one field swapped for another REAL entry's value (half the donors share a program, so cross-field consistency
alone is not enough), adds equal-length listed / not-listed verdict pairs, and keeps r7's training set (twice, to
match its exposure in r7) for the pairs where one answer is plainly more complete.
r8c (third argument > 0) adds "relevance" pairs, because r8b learned to reward any internally true record even when
it is about the wrong entity (36% on Agy's stress set, 6/15 on fexx-style lookalikes): a full true record of another
entity as the wrong answer, clean names against a real record, and two-record prompts where only the question
decides which record is right. It also shifts swap exposure from names (already ~100%) to UIDs and ID numbers.
r8d (fourth argument > 0) adds "decide" pairs, because r8c picked a hit for clean lookalikes and namesakes even when
the prompt showed contradicting evidence, and picked a short clear over a long correct hit: alert-review twins where
a date of birth, an ID number or the name itself in the prompt decides between the same hit and clear answers, with
the two answers in independently chosen formats (terse to memo). It also adds a neutral note to one side of a
quarter of the swap pairs, so an added remark neither helps nor hurts.
r9 (fifth argument > 0) adds "false-positive twins", because on a contributor's published rows r8c won 101 of 101
listed-name-wrongly-cleared pairs but 20 of 99 clean-company-wrongly-flagged pairs: it rewards any true list record,
even one about a different party, over a clear in another layout. Each twin keeps one record, one hit layout and one
clear layout, and changes only the subject: the record's own name or alias (the hit is right) or a clean company (the
clear is right). Layouts are chosen independently, so length and format say nothing.
Run: python3 -I gen/build_r8.py <name> <org_exposures> [relevance_pairs] [decide_pairs] [fp_pairs]  ->  data/pairs_<name>/{train,val}.jsonl"""
import csv
import glob
import json
import random
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import build_pairs as B  # noqa: E402

NAME, ORG_X = sys.argv[1], int(sys.argv[2])
REL = int(sys.argv[3]) if len(sys.argv) > 3 else 0
FIX = int(sys.argv[4]) if len(sys.argv) > 4 else 0
FP = int(sys.argv[5]) if len(sys.argv) > 5 else 0
ROOT = Path(B.ROOT)
r = random.Random(8)

# ---- entities -------------------------------------------------------------------------------------------------
sdn = B.load_ofac("SDN.CSV", "ALT.CSV", B.L_SDN)
ID_RE = re.compile(r"^(Tax ID No\.|Registration Number|National ID No\.|Passport|Business Registration Number|"
                   r"Company Number|Cedula No\.|C\.U\.R\.P\.|R\.F\.C\.|Identification Number|Registration ID|"
                   r"Commercial Registry Number|Legal Entity Number|Government Gazette Number|V\.A\.T\. Number|"
                   r"Chamber of Commerce Number|SWIFT/BIC|MMSI|Aircraft Tail Number|Folio Mercantil No\.) "
                   r"([A-Za-z0-9][A-Za-z0-9\-/\.]{3,30})(?: \(([^)]+)\))?\.?$")
remarks = {row[0].strip(): row[11] for row in csv.reader(open(B.RAW / "SDN.CSV", encoding="latin-1")) if len(row) > 11}
for e in sdn:
    e["ids"] = [m.groups() for seg in remarks.get(e["uid"], "").split("; ") if (m := ID_RE.match(seg.strip()))]
others = B.load_ofac("CONS_PRIM.CSV", "CONS_ALT.CSV", B.L_CONS) + B.load_un() + B.load_eu() + B.load_uk()
for e in others:
    e["ids"] = []
ALL = sdn + others
SHORT = {B.L_SDN: ["OFAC SDN", "the OFAC SDN list", "the US Treasury SDN list", "OFAC's Specially Designated Nationals list"],
         B.L_CONS: ["the OFAC Consolidated (non-SDN) list", "OFAC non-SDN"],
         B.L_UN: ["the UN Security Council Consolidated List", "the UN sanctions list"],
         B.L_EU: ["the EU Consolidated Financial Sanctions List", "the EU sanctions list"],
         B.L_UK: ["the UK Sanctions List", "the UK sanctions list (OFSI)"]}
by_list, by_prog, by_label, with_dob, wallets = {}, {}, {}, [], []
for e in ALL:
    by_list.setdefault(e["list"], []).append(e)
    for p in e["programs"]:
        by_prog.setdefault((e["list"], p), []).append(e)
    for lab, val, ctry in e["ids"]:
        by_label.setdefault((lab, ctry), []).append(e)
        by_label.setdefault((lab, None), []).append(e)
    if e["dob"]:
        with_dob.append(e)
    wallets += [(e, c, a) for c, a in e["wallets"]]
with_ids = [e for e in sdn if e["ids"]]
listed_keys = {B.key(n) for e in ALL for n in [e["name"]] + e["aliases"]}
clean = []
# GLEIF legal-name files from fexx301's published sanctions material (not included in this repository)
for f in glob.glob(str(ROOT / "data/gleif/*.json")):
    for rec in json.load(open(f)).get("data", []):
        n = rec["attributes"]["entity"]["legalName"]["name"]
        if B.key(n) not in listed_keys:
            clean.append(n)
clean = sorted(set(clean))

# ---- rendering ------------------------------------------------------------------------------------------------
KEYS = {  # one JSON key vocabulary per scheme; the last two are held out for validation
    "name": ["name", "canonical_name", "primary_name", "listed_name", "entity", "entry_name", "matched_name", "subject_name"],
    "uid": ["uid", "ofac_uid", "id", "entry_id", "identifier", "list_id", "record_id", "reference"],
    "programs": ["programs", "program_tags", "sanctions_programs", "programmes", "program", "regimes", "program_codes", "designations"],
    "list": ["list", "source_list", "list_name", "source", "sanctions_list", "dataset", "authority", "list_label"],
    "dob": ["dob", "date_of_birth", "birth_date", "born", "dateOfBirth", "birth", "dob_listed", "birthdate"],
}
N_SCHEME, HELD = 8, (6, 7)


def record(f, s):
    out = {}
    for k in f["order"]:
        if k == "idnum":
            lab, val, ctry = f["idnum"]
            if s % 2:
                out[re.sub(r"[^a-z0-9]+", "_", lab.lower()).strip("_")] = val
            else:
                out["registration"] = {"type": lab, "value": val} | ({"country": ctry} if ctry else {})
        elif k == "wallet":
            out[["address", "wallet", "digital_currency_address", "crypto_address"][s % 4]] = f["wallet"]
        else:
            v = f[k]
            if k == "uid" and s % 3 == 0 and str(v).isdigit():
                v = int(v)
            out[KEYS[k][s]] = v
    return out


def prose_fields(f):
    bits = []
    for k in f["order"]:
        if k == "uid":
            bits.append(f"{r.choice(['UID', 'entry number', 'ID', 'reference'])} {f['uid']}")
        elif k == "programs":
            bits.append(f"{r.choice(['programs', 'designated under', 'program tags'])} {', '.join(f['programs'])}")
        elif k == "list":
            bits.append(f"on {f['list']}")
        elif k == "idnum":
            lab, val, ctry = f["idnum"]
            bits.append(f"{lab} {val}" + (f" ({ctry})" if ctry else ""))
        elif k == "dob":
            bits.append(f"date of birth {f['dob']}")
        elif k == "wallet":
            bits.append(f"address {f['wallet']}")
    return bits


def render(q, f, s, style):
    if style == 0:
        rec = record(f, s)
        shape = s % 4
        if shape == 0:
            return json.dumps({"query": q, "matched": True, "match": rec}, ensure_ascii=False)
        if shape == 1:
            return json.dumps({"name_alert": True, "entries": [rec]}, ensure_ascii=False)
        if shape == 2:
            return json.dumps({"result": "HIT", "record": rec}, ensure_ascii=False)
        return json.dumps({"matched": True} | rec, ensure_ascii=False)
    bits = prose_fields(f)
    if style == 1:
        return f"Match. {f['name']}" + (": " + "; ".join(bits) if bits else "") + "."
    if style == 2:
        return "\n".join([f"Listed-name alert: yes", f"Entry: {f['name']}"] + [b[0].upper() + b[1:] for b in bits])
    return f"{q} matches the listed entry {f['name']}" + (" (" + ", ".join(bits) + ")" if bits else "") + "."


PROMPTS = [  # {q} subject, {L} list phrase; the last three are held out for validation
    "Screen \"{q}\" against {L} and return the matching entry.",
    "Does the name {q} produce a listed-name alert on {L}? Give the matching record.",
    "{q}: name check against {L}. Report the record it matches, with identifiers and programs.",
    "Our onboarding queue has a counterparty called {q}. Which entry on {L}, if any, does that name match?",
    "Using only the current publication of {L} as evidence, does \"{q}\" raise a listed-name alert? Report the canonical name, identifier and complete program tags. The alert means a name match, not confirmation of identity.",
    "Sanctions screening request. Subject: {q}. List: {L}. Return the match record.",
    "Before we release a payment to {q} we need the exact entry on {L} that this name corresponds to.",
    "Is {q} listed? Check {L} and give the entry details.",
    "Please look up {q} on {L} and tell me what it matches.",
    "Vendor due diligence: {q}. Provide the listing on {L} with its reference and program.",
    "KYC refresh, counterparty name \"{q}\". What does {L} hold for this name?",
    "Evidence is restricted to {L}. For the name {q}, report the matched entry's name, its list identifier and the programs it is designated under, plus any registration detail the list records.",
    "Run a sanctions lookup for {q} on {L} and show the record it hits.",
    "Compliance request: identify the entry for \"{q}\" on {L}, with its identifier and programs.",
    "Trade finance check on {q}: which record on {L} is this, exactly?",
]
P_HELD = 3
W_PROMPTS = ["Is the {c} address {a} associated with a sanctioned party on {L}? Name the owner.",
             "Wallet screening: {a} ({c}). Who does {L} attribute this address to?",
             "Check the digital currency address {a} against {L} and report the listed owner."]


NOTES = ["Checked against the list publication named in the request.", "This is a name alert, not confirmation of identity.",
         "Record verified against the official publication.", "Reviewed by the screening team; no further identifiers were supplied.",
         "Screening completed on the current list version.", "No other entries were returned for this name.",
         "Details are as recorded by the list issuer.", "Escalate to compliance before releasing funds.",
         "Result produced by an exact-name comparison.", "Audit note: lookup logged for the case file.", "Verified.",
         "Source data is current as of the latest publication."]
NOTE_KEYS = ["note", "audit", "comment", "verification", "remarks", "basis"]


def with_note(text, style):
    """The same answer plus a remark that carries no list fact."""
    if style == 0:
        return json.dumps(json.loads(text) | {r.choice(NOTE_KEYS): r.choice(NOTES)}, ensure_ascii=False)
    return text + ("\n" if style == 2 else " ") + r.choice(NOTES)


def donor(e, pool_hard, pool_any, ok):
    for _ in range(40):
        d = r.choice(pool_hard if pool_hard and r.random() < 0.5 else pool_any)
        if d is not e and ok(d):
            return d
    return None


def swap_pair(e, kind, held):
    L = r.choice(SHORT[e["list"]])
    same_prog = by_prog.get((e["list"], r.choice(e["programs"])), []) if e["programs"] else []
    same_list = by_list[e["list"]]
    f = {"name": e["name"], "uid": e["uid"], "programs": e["programs"], "list": e["list"]}
    q = e["name"]
    extra = [k for k in ("uid", "programs", "list") if f.get(k) and r.random() < 0.5]
    g = dict(f)
    if kind == "uid":
        d = donor(e, same_prog, same_list, lambda d: d["uid"] != e["uid"])
        if not d: return None
        g["uid"] = d["uid"]
    elif kind == "prog":
        d = donor(e, None, same_list, lambda d: d["programs"] and sorted(d["programs"]) != sorted(e["programs"]))
        if not d: return None
        g["programs"] = d["programs"]
    elif kind in ("name", "alias"):
        if kind == "alias":
            q = r.choice(e["aliases"])
        d = donor(e, same_prog, same_list, lambda d: B.key(d["name"]) != B.key(e["name"]))
        if not d: return None
        g["name"] = d["name"]
    elif kind == "idnum":
        lab, val, ctry = r.choice(e["ids"])
        d = donor(e, by_label.get((lab, ctry)), by_label[(lab, None)], lambda d: all(v != val for _, v, _ in d["ids"]))
        if not d: return None
        dv = next(x for x in d["ids"] if x[0] == lab)
        f["idnum"], g["idnum"] = (lab, val, ctry), (lab, dv[1], ctry)
    elif kind == "dob":
        d = donor(e, None, with_dob, lambda d: d["dob"] != e["dob"])
        if not d: return None
        f["dob"], g["dob"] = e["dob"], d["dob"]
    elif kind == "list":
        wrong = r.choice([x for x in SHORT if x != e["list"]])
        g["list"] = wrong
    key = {"prog": "programs", "alias": "name"}.get(kind, kind)
    order = [k for k in dict.fromkeys(["name"] + extra + [key]) if k in f]
    if r.random() < 0.5:
        head, tail = order[:1], order[1:]
        r.shuffle(tail)
        order = head + tail
    f["order"] = g["order"] = order
    s = r.choice(HELD) if held else r.randrange(N_SCHEME - len(HELD))
    style = r.choice([0, 0, 1, 2, 3])
    state = r.getstate()
    good = render(q, f, s, style)
    r.setstate(state)  # same random wording choices for both answers
    bad = render(q, g, s, style)
    if good == bad:
        return None
    if FIX and not held and r.random() < 0.25:
        if r.random() < 0.5:
            good = with_note(good, style)
        else:
            bad = with_note(bad, style)
    ps = PROMPTS[-P_HELD:] if held else PROMPTS[:-P_HELD]
    return {"prompt": r.choice(ps).format(q=q, L=L), "chosen": good, "rejected": bad, "label_kind": "preference_pair"}


def wallet_pair(held):
    e, c, a = r.choice(wallets)
    d = donor(e, [w[0] for w in wallets], [w[0] for w in wallets], lambda d: d["name"] != e["name"])
    if not d: return None
    L = r.choice(SHORT[e["list"]])
    s = r.choice(HELD) if held else r.randrange(N_SCHEME - len(HELD))
    style = r.choice([0, 1, 3])
    f = {"name": e["name"], "wallet": a, "uid": e["uid"], "order": ["name", "wallet"] + (["uid"] if r.random() < 0.4 else [])}
    g = dict(f, name=d["name"], uid=d["uid"])
    state = r.getstate()
    good = render(a, f, s, style)
    r.setstate(state)
    bad = render(a, g, s, style)
    return {"prompt": r.choice(W_PROMPTS).format(c=c, a=a, L=L), "chosen": good, "rejected": bad, "label_kind": "preference_pair"}


V_TEMPL = [lambda q, L, m: json.dumps({"query": q, "list": L, "matched": m}),
           lambda q, L, m: f"{q}: {'MATCH' if m else 'NO MATCH'} on {L}.",
           lambda q, L, m: f"{'Yes' if m else 'No'}, {q} {'is' if m else 'is not'} on {L}.",
           lambda q, L, m: json.dumps({"name_alert": m, "subject": q, "source": L}),
           lambda q, L, m: f"Listed-name alert: {'yes' if m else 'no'}. Subject: {q}. List: {L}."]


def verdict_pair(listed):
    if listed:
        e = r.choice(ALL)
        q, L = r.choice([e["name"]] + e["aliases"]), r.choice(SHORT[e["list"]])
    else:
        q, L = r.choice(clean), r.choice(r.choice(list(SHORT.values())))
    t = r.choice(V_TEMPL)
    return {"prompt": r.choice(PROMPTS[:-P_HELD]).format(q=q, L=L), "chosen": t(q, L, listed), "rejected": t(q, L, not listed),
            "label_kind": "preference_pair"}


def kinds_for(e):
    k = ["uid"] * (4 if REL else 3) + ["prog"] * 3 + ["name"] * (1 if REL else 2) + ["list"]
    k += ["alias"] * 2 if e["aliases"] else []
    k += ["idnum"] * (4 if REL else 3) if e["ids"] else []
    k += ["dob"] * 2 if e["dob"] else []
    return [x for x in k if x != "prog" or e["programs"]]


def swaps(ents, n_each, held=False):
    out = []
    for e in ents:
        ks = kinds_for(e)
        for _ in range(n_each):
            p = swap_pair(e, r.choice(ks), held)
            if p:
                out.append(p)
    return out


# ---- relevance pairs (r8c): the record must be about the entity the prompt asks for -----------------------------
NO_JSON = [lambda q: {"query": q, "matched": False, "match": None}, lambda q: {"name_alert": False, "entries": []},
           lambda q: {"result": "NO_HIT", "record": None}, lambda q: {"matched": False}]


def no_match(q, L, s, style):
    if style == 0:
        return json.dumps(NO_JSON[s % 4](q), ensure_ascii=False)
    return [f"No match. {q} is not on {L}.", f"Listed-name alert: no\nSubject: {q}",
            f"{q} does not match any listed entry on {L}."][style - 1]


def full(e, keys):
    return {"name": e["name"], "uid": e["uid"], "programs": e["programs"], "list": e["list"],
            "order": ["name"] + [k for k in keys if e.get(k)]}


def rel_setup(e):
    keys = [k for k in ("uid", "programs", "list") if r.random() < 0.7] or ["uid"]
    r.shuffle(keys)
    return keys, r.randrange(N_SCHEME - len(HELD)), r.choice([0, 0, 1, 2, 3]), r.choice(SHORT[e["list"]])


def both(q, f, g, s, style):
    state = r.getstate()
    good = render(q, f, s, style)
    r.setstate(state)
    return good, render(q, g, s, style)


def wrong_entity_pair():
    e = r.choice(ALL)
    same_prog = by_prog.get((e["list"], r.choice(e["programs"])), []) if e["programs"] else []
    d = donor(e, same_prog, by_list[e["list"]], lambda d: B.key(d["name"]) != B.key(e["name"]))
    if not d: return None
    keys, s, style, L = rel_setup(e)
    q = r.choice([e["name"]] + e["aliases"][:2])
    good, bad = both(q, full(e, keys), full(d, keys), s, style)
    return {"prompt": r.choice(PROMPTS[:-P_HELD]).format(q=q, L=L), "chosen": good, "rejected": bad, "label_kind": "preference_pair"}


def clean_vs_record_pair(listed):
    e = r.choice(ALL)
    keys, s, style, L = rel_setup(e)
    q = e["name"] if listed else r.choice(clean)
    rec, none = render(q, full(e, keys), s, style), no_match(q, L, s, style)
    return {"prompt": r.choice(PROMPTS[:-P_HELD]).format(q=q, L=L), "chosen": rec if listed else none,
            "rejected": none if listed else rec, "label_kind": "preference_pair"}


CTX_LINE = [lambda e: f"- {e['name']} | {e['uid']} | {', '.join(e['programs']) or 'n/a'}",
            lambda e: json.dumps({"name": e["name"], "id": e["uid"], "programs": e["programs"]}, ensure_ascii=False),
            lambda e: f"{e['name']} (entry {e['uid']}; {'; '.join(e['programs']) or 'no program tag'})"]
CTX_ASK = ["Two entries from {L} are shown below.\n{a}\n{b}\nGive the record for {q} only.",
           "Extract from {L}:\n{a}\n{b}\nWhich of these is {q}? Return that entry.",
           "{L} returned these candidates for a batch lookup:\n{a}\n{b}\nThe payment under review names {q}. Report the entry that applies to it.",
           "Reference rows ({L}):\n{a}\n{b}\nQuestion: what does the list record for {q}?"]


def context_pairs():
    """Both answers are true records and both appear in the prompt; only the question says which one is wanted."""
    e = r.choice(ALL)
    d = donor(e, None, by_list[e["list"]], lambda d: B.key(d["name"]) != B.key(e["name"]) and d["uid"] != e["uid"])
    if not d: return []
    keys, s, style, L = rel_setup(e)
    line, ask = r.choice(CTX_LINE), r.choice(CTX_ASK)
    a, b = (line(e), line(d)) if r.random() < 0.5 else (line(d), line(e))
    out = []
    for t, o in ((e, d), (d, e)):
        good, bad = both(t["name"], full(t, keys), full(o, keys), s, style)
        out.append({"prompt": ask.format(L=L, a=a, b=b, q=t["name"]), "chosen": good, "rejected": bad, "label_kind": "preference_pair"})
    return out


EVID = [("the customer's {lab} {val} agrees with the list record", True), ("the {lab} on file is {val}, the same as the listed one", True),
        ("no {lab} or other identifier is available for the customer", False), ("only the name is known; there is no {lab} to compare", False)]


def evidence_pairs():
    """Same entity, same two answers; the evidence sentence in the prompt decides between confirmed and name-only."""
    e = r.choice(with_dob + [x for x in sdn if x["ids"]])
    lab, val = ("date of birth", e["dob"]) if e["dob"] and (not e["ids"] or r.random() < 0.5) else e["ids"][0][:2]
    L = r.choice(SHORT[e["list"]])
    yes = r.choice([f"Confirmed match: name and {lab} both agree with {e['name']} ({e['uid']}).",
                    json.dumps({"name": e["name"], "match_strength": "confirmed", "basis": ["name", lab]}, ensure_ascii=False)])
    no = r.choice([f"Name-only match to {e['name']} ({e['uid']}); identity is not confirmed without a second identifier.",
                   json.dumps({"name": e["name"], "match_strength": "name_only", "basis": ["name"]}, ensure_ascii=False)])
    out = []
    for txt, ok in (r.choice(EVID[:2]), r.choice(EVID[2:])):
        p = f"{e['name']} produced a name alert on {L}. In the file, {txt.format(lab=lab, val=val)}. How strong is the match?"
        out.append({"prompt": p, "chosen": yes if ok else no, "rejected": no if ok else yes, "label_kind": "preference_pair"})
    return out

# ---- decide pairs (r8d): evidence in the prompt decides between the same hit and clear answers -----------------
WORDS = [("cleared", "blocked"), ("no match", "match"), ("false positive", "true match"), ("release", "hold"),
         ("not the listed party", "the listed party")]
GENERIC = {"limited", "company", "liability", "joint", "stock", "llc", "ltd", "ooo", "jsc", "inc", "corporation", "group",
           "trading", "general", "international", "public", "private", "society", "open", "closed", "holding", "holdings"}
TRADES = ["Municipal Water Supply Co", "Bakery Ltd", "Dental Clinic", "Youth Football Club", "Logistics GmbH", "Tea Rooms",
          "Primary School", "Veterinary Practice LLP", "Community Credit Union", "Hardware Stores Inc", "Garden Centre",
          "Bookshop", "Tyres and Exhausts Ltd", "Family Farm", "Architects PC", "Driving School", "Florist", "Print Works SARL"]
PLACES = ["Canada", "New Zealand", "Portugal", "Chile", "Ireland", "Japan", "Norway", "Uruguay", "Botswana", "Estonia"]
D_PROMPTS = {
    "dob": ["Alert review. Customer: {q}, born {x}. The name matched {L}, entry {uid} ({en}), whose listed date of birth is {v}. Is the customer the listed person?",
            "{q} (date of birth {x}) is opening an account. Screening returned {en}, {L}, entry {uid}, DOB {v}. Decide the alert.",
            "Name hit on {L}: {en} [{uid}], DOB {v}. Our customer {q} gives {x} as date of birth on a verified passport. Match or false positive?",
            "{{\"task\": \"resolve_alert\", \"customer\": {{\"name\": \"{q}\", \"dob\": \"{x}\"}}, \"hit\": {{\"list\": \"{L}\", \"entry\": \"{uid}\", \"name\": \"{en}\", \"dob\": \"{v}\"}}}}"],
    "id": ["Counterparty {q}, {lab} {x}. {L} lists {en} (entry {uid}) with {lab} {v}. Is this the same entity?",
           "Payment screening stopped on {q}. Our records hold {lab} {x} for it. The hit is {en}, entry {uid} on {L}, {lab} {v}. Resolve the alert.",
           "KYC file for {q} shows {lab}: {x}. Candidate list entry: {en} / {uid} / {L} / {lab}: {v}. Same party or not?",
           "{{\"task\": \"resolve_alert\", \"counterparty\": {{\"name\": \"{q}\", \"{lab}\": \"{x}\"}}, \"hit\": {{\"list\": \"{L}\", \"entry\": \"{uid}\", \"name\": \"{en}\", \"{lab}\": \"{v}\"}}}}"],
    "name": ["Screening flagged {q} against {en} ({L}, entry {uid}). {x} Resolve the alert.",
             "Alert queue item: subject {q}; candidate {en}, entry {uid}, {L}. {x} Is the subject the listed party?",
             "{L} entry {uid} is {en}. We are asked whether {q} is that entry. {x}",
             "Fuzzy match report: \"{q}\" scored against \"{en}\" [{uid}] on {L}. {x} Give the disposition."],
}
MEMO_END = ["The payment must not proceed and the case is escalated.", "The alert is closed and the payment may proceed."]


def verdict_text(hit, fmt, w, q, e, L, why):
    word, uid = WORDS[w][hit], e["uid"]
    if fmt == 0:
        return json.dumps({"subject": q, "decision": word, "entry": uid if hit else None} | ({"reason": why} if why else {}), ensure_ascii=False)
    if fmt == 1:
        return json.dumps({"match": bool(hit), "name": q, "listed_as": e["name"] if hit else None} | ({"basis": why} if why else {}), ensure_ascii=False)
    if fmt == 2:
        head = f"Match: {q} is {e['name']}, entry {uid} on {L}." if hit else f"No match: {q} is not {e['name']} (entry {uid} on {L})."
        return head + (f" {why[0].upper()}{why[1:]}." if why else "")
    if fmt == 3:
        return f"Decision: {word}\nSubject: {q}\nEntry considered: {uid}" + (f"\nReason: {why}" if why else "")
    if fmt == 4:
        return f"{word.upper()} - entry {uid}"
    finding = why or ("the subject is the listed party" if hit else "the subject is not the listed party")
    return (f"Alert review memo\nSubject: {q}\nList entry: {e['name']} ({uid}), {L}\nFinding: {finding}.\n"
            f"Comparison: the name, identifiers and dates in the request were compared with the list entry.\n"
            f"Outcome: {word}. {MEMO_END[0 if hit else 1]}")


def year(d):
    m = re.search(r"(1[89]|20)\d\d", d or "")
    return m.group(0) if m else None


def decide_case():
    """One alert in two versions: (prompt slots for 'same party', prompt slots for 'different party', reasons)."""
    kind = r.choice(["dob", "dob", "id", "name", "name", "alias"])
    if kind == "dob":
        e = r.choice(with_dob)
        d = donor(e, None, with_dob, lambda d: d["dob"][0].isdigit() and year(d["dob"]) and year(d["dob"]) != year(e["dob"]))
        if not d or not year(e["dob"]) or not e["dob"][0].isdigit(): return None  # skip partial dates such as dd/mm/1983
        same, diff = dict(q=e["name"], x=e["dob"], v=e["dob"]), dict(q=e["name"], x=d["dob"], v=e["dob"])
        why = {(1, 1): f"name and date of birth {e['dob']} both agree with the list entry",
               (1, 0): r.choice(["the name is common and the hit is treated as a false positive", "no adverse information was found on the customer"]),
               (0, 0): f"date of birth {d['dob']} does not match the listed {e['dob']}",
               (0, 1): r.choice(["the full name matches the list entry, which is enough to block", "blocked as a precaution on the name match alone"])}
        return "dob", e, same, diff, why
    if kind == "id":
        e = r.choice(with_ids)
        lab, val, ctry = r.choice(e["ids"])
        d = donor(e, by_label.get((lab, ctry)), by_label[(lab, None)], lambda d: all(v != val for _, v, _ in d["ids"]))
        if not d: return None
        other = next(x for x in d["ids"] if x[0] == lab)[1]
        same, diff = dict(q=e["name"], x=val, v=val, lab=lab), dict(q=e["name"], x=other, v=val, lab=lab)
        why = {(1, 1): f"the name and the {lab} {val} both agree with the list entry",
               (1, 0): r.choice(["the hit is treated as a coincidence of names", "the counterparty is a long-standing client"]),
               (0, 0): f"the {lab} {other} is not the listed {val}",
               (0, 1): r.choice(["the name is the same as the listed one, which is enough to block", "blocked on the name alone"])}
        return "id", e, same, diff, why
    e = r.choice(ALL)
    if kind == "alias":
        if not e["aliases"]: return None
        q_same, q_diff = r.choice(e["aliases"]), r.choice(clean)
        x_same, x_diff = "The subject name is a recorded alias of that entry.", "The screening tool returned this entry on partial similarity; the names are different and nothing else links the two."
        why = {(1, 1): f"{q_same} is a recorded alias of the list entry", (1, 0): "the names are not the same",
               (0, 0): "the names are different and nothing else links the two", (0, 1): "the screening tool returned this entry for the name"}
    else:
        toks = [t for t in re.findall(r"[A-Za-z]{5,}", e["name"]) if t.lower() not in GENERIC]
        if not toks: return None
        tok = r.choice(toks)
        q_same, q_diff = e["name"], f"{tok.title()} {r.choice(TRADES)}"
        if B.key(q_diff) in listed_keys: return None
        x_same = "The subject's registered name is exactly the listed name."
        x_diff = f"The subject is registered in {r.choice(PLACES)} and its registry record shows no ownership or control link to the listed party."
        why = {(1, 1): "the name is identical to the listed name", (1, 0): "the similarity is treated as coincidental",
               (0, 0): f"{q_diff} is a different entity that only shares the word {tok.title()} with the listed name",
               (0, 1): f"the name contains {tok.title()}, as the listed name does"}
    return "name", e, dict(q=q_same, x=x_same), dict(q=q_diff, x=x_diff), why


def decide_pairs():
    c = decide_case()
    if not c: return []
    kind, e, same, diff, why = c
    L, w, tpl = r.choice(SHORT[e["list"]]), r.randrange(len(WORDS)), r.choice(D_PROMPTS[kind])
    f_hit = r.randrange(6)
    f_clear = f_hit if r.random() < 0.5 else r.randrange(6)  # half the twins differ in length and layout
    reasons = r.random() < 0.6
    out = []
    for is_same, slots in ((1, same), (0, diff)):
        hit = verdict_text(1, f_hit, w, slots["q"], e, L, why[(is_same, 1)] if reasons else None)
        clear = verdict_text(0, f_clear, w, slots["q"], e, L, why[(is_same, 0)] if reasons else None)
        out.append({"prompt": tpl.format(L=L, uid=e["uid"], en=e["name"], **slots), "chosen": hit if is_same else clear,
                    "rejected": clear if is_same else hit, "label_kind": "preference_pair"})
    return out


# ---- false-positive twins (r9): a hit is right only when its record is the subject's own -----------------------
FP_PROMPTS = ["Is {q} on {L}?", "Screen {q} against {L}.", "Does {q} appear on {L}, under its name or an alias?",
              "We are about to pay {q}. Check it for a listing on {L}.", "Sanctions exposure check for {q} ({L}). Listed or not?",
              "Counterparty: {q}. Report whether {L} lists it.", "{q}: any entry on {L}?"]


CO_A = ("Harbourline Northgate Bluefield Quillon Marlowe Tessera Ashcombe Larkspur Windrose Calloway Finchley Orrin Solvane Brightwater "
        "Kestrel Juniper Halden Meridian Oakhurst Pinecrest Redfern Saltmarsh Thornbury Umber Vantage Westmere Yarrow Zephyr Aldergate "
        "Birchwood Copperfield Dunmore Elmstead Foxglove Greyfriars Holloway Ivybridge Jessamine Kingsmead Lowther Maplewood Netherby "
        "Otterburn Pemberton Quayside Rosehill Silverdale Tamarind Upland Verity Wrenfield Amberley Bramble Cedarline Dovetail Everline "
        "Fernhill Glenrock Hawksmoor Inchmere Kirkwall Lindale Moorgate Newlands Oxbow Penrose Ravenscar Stonebridge Tideway").split()
CO_B = ("Analytics Logistics Foods Textiles Robotics Pharma Media Energy Freight Dairy Timber Optics Software Brewing Ceramics Marine "
        "Studios Packaging Motors Travel Insurance Robotics Capital Builders Health Agro Print Mining Foundry Telecom").split()
CO_C = ["Ltd", "Limited", "Inc.", "LLC", "GmbH", "S.A.", "Pty Ltd", "B.V.", "AG", "Co., Ltd.", "plc", "Corp.", "SARL", "AB", "Oy", "K.K."]
FIRSTS = ("Amara Bjorn Chidi Daniela Emeka Freya Gustavo Hana Ingrid Jomo Keiko Lukas Mireille Nnamdi Oksana Pablo Quentin Rosalind "
          "Sven Tariq Uma Valentina Wojciech Xiomara Yusuf Zainab Aoife Baptiste Carys Dmitri Elif Farah Gideon Henrik").split()
LASTS = ("Okonkwo Lindqvist Fairweather Castellano Novak Adeyemi Brennan Takahashi Moreau Kowalczyk Haddad Petrenko Villanueva "
         "Sorensen Mbeki Oyelaran Thackeray Lindgren Abernathy Fontaine Grunewald Halloran Ishikawa Jankowski Kaplan Laurent").split()


def _bits(f):
    return prose_fields(f)


HIT_F = [lambda q, f, s, style, L: render(q, f, s, style)] * 4 + [
    lambda q, f, s, style, L: json.dumps({"subject": q, "status": "MATCH", "hits": [record(f, s)], "list": L}, ensure_ascii=False),
    lambda q, f, s, style, L: "\n".join([f"### Sanctions screening: {q}", "- Result: **match**", f"- Entry: {f['name']}"] + ["- " + b for b in _bits(f)]),
    lambda q, f, s, style, L: " | ".join([f"SCREENING RESULT | subject={q}", "outcome=HIT", f"entry={f['name']}"] + _bits(f)),
    lambda q, f, s, style, L: f"Determination: listed. {q} matches {f['name']}" + "".join(", " + b for b in _bits(f)) + ".",
]
CLEAR_F = [lambda q, s, style, L: no_match(q, L, s, style)] * 4 + [
    lambda q, s, style, L: json.dumps({"subject": q, "status": "NO_MATCH", "hits": [], "list": L}, ensure_ascii=False),
    lambda q, s, style, L: f"### Sanctions screening: {q}\n- Result: **no match**\n- List checked: {L}\n- Entries under this name or an alias: 0",
    lambda q, s, style, L: f"SCREENING RESULT | subject={q} | outcome=CLEAR | entries=0 | list={L}",
    lambda q, s, style, L: f"Determination: not listed. {q} does not appear on {L} under its name or any recorded alias.",
    lambda q, s, style, L: f"CLEAR - {q}",
    lambda q, s, style, L: json.dumps({"matched": False, "match_count": 0, "matches": [], "lists": [L]}, ensure_ascii=False),
]


def fp_twins():
    e = r.choice(ALL)
    keys, s, style, L = rel_setup(e)
    if r.random() < 0.25:  # a clean lookalike that shares one distinctive word with the listed name
        toks = [t for t in re.findall(r"[A-Za-z]{5,}", e["name"]) if t.lower() not in GENERIC]
        if not toks: return []
        c = f"{r.choice(toks).title()} {r.choice(TRADES)}"
        if B.key(c) in listed_keys: return []
    elif r.random() < 0.5:
        c = r.choice(clean)
    else:  # invented names, so the clean side is not a list of 2,666 names to memorise
        c = (f"{r.choice(FIRSTS)} {r.choice(LASTS)}" if r.random() < 0.3 else
             f"{r.choice(CO_A)}{r.choice(['', ' ' + r.choice(CO_B)])} {r.choice(CO_C)}")
        if B.key(c) in listed_keys: return []
    own = r.choice([e["name"]] + e["aliases"][:2])
    hit_f, clear_f, tpl = r.choice(HIT_F), r.choice(CLEAR_F), r.choice(PROMPTS[:-P_HELD] + FP_PROMPTS)
    f, state, out = full(e, keys), r.getstate(), []
    for q, listed in ((own, True), (c, False)):
        r.setstate(state)  # same wording choices for both subjects
        hit, clear = hit_f(q, f, s, style, L), clear_f(q, s, style, L)
        out.append({"prompt": tpl.format(q=q, L=L), "chosen": hit if listed else clear, "rejected": clear if listed else hit,
                    "label_kind": "preference_pair"})
    return out


def relevance(n):
    out = [p for _ in range(n * 3 // 10) if (p := wrong_entity_pair())]
    out += [clean_vs_record_pair(i % 2 == 0) for i in range(n * 3 // 10)]
    out += [p for _ in range(n * 3 // 20) for p in context_pairs()]
    out += [p for _ in range(n // 20) for p in evidence_pairs()]
    return out


train = []
for e_kind, n in (("entity", ORG_X), ("individual", 4), ("vessel", 2), ("aircraft", 2)):
    train += swaps([e for e in sdn if e["kind"] == e_kind], n)
train += swaps(others, 2)
train += [p for _ in range(3000) if (p := wallet_pair(False))]
train += [verdict_pair(True) for _ in range(8000)] + [verdict_pair(False) for _ in range(4000)]
train += relevance(REL)
train += [p for _ in range(FIX // 2) for p in decide_pairs()]
train += [p for _ in range(FP // 2) for p in fp_twins()]
n_new = len(train)
r7 = [json.loads(l) for l in open(ROOT / "data/pairs_r7/train.jsonl")]
train += r7 + r7
r.shuffle(train)
val = swaps(r.sample(sdn, 500), 1, held=True) + swaps(r.sample(others, 200), 1, held=True)
val += [json.loads(l) for l in open(ROOT / "data/pairs_r7/val.jsonl")]
d = ROOT / f"data/pairs_{NAME}"
d.mkdir(exist_ok=True)
for name, rows in (("train", train), ("val", val)):
    with open(d / f"{name}.jsonl", "w") as f:
        f.writelines(json.dumps(x, ensure_ascii=False) + "\n" for x in rows)
print(NAME, "train", len(train), "(new", n_new, "+ r7 x2", 2 * len(r7), ") val", len(val), "clean names", len(clean), "wallets", len(wallets))
