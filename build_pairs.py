"""Build preference pairs for the SANCTIONS_SCREENING_MATCH family from public sanctions lists.

Inputs (download with scripts/fetch_lists.sh into data/raw/):
  OFAC SDN.CSV, ALT.CSV, CONS_PRIM.CSV, CONS_ALT.CSV, UN consolidated.xml,
  EU csvFullSanctionsList, UK Sanctions List CSV.
Outputs in data/pairs/: train.jsonl, val.jsonl, test.jsonl (split by entity cluster),
live.jsonl (the recorded live-name cases), stats.json.

Run: python -I build_pairs.py [--seed 7]
"""
import argparse
import csv
import hashlib
import json
import random
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "pairs"
LIVE = ROOT / "data" / "live-names.json"

L_SDN = "OFAC SDN"
L_CONS = "OFAC Consolidated (non-SDN)"
L_UN = "UN Security Council Consolidated List"
L_EU = "EU Consolidated Financial Sanctions List"
L_UK = "UK Sanctions List"
ALL_LISTS = [L_SDN, L_CONS, L_UN, L_EU, L_UK]
SHORT = {L_SDN: "OFAC SDN", L_CONS: "OFAC non-SDN", L_UN: "UN", L_EU: "EU", L_UK: "UK"}
AS_OF = {L_SDN: "2026-11-13", L_CONS: "2026-11-13", L_UN: "2026-11-14", L_EU: "2026-10-23",
         L_UK: "2026-11-12"}
URL = {L_SDN: "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/SDN.CSV",
       L_CONS: "https://sanctionslistservice.ofac.treas.gov/api/PublicationPreview/exports/CONS_PRIM.CSV",
       L_UN: "https://scsanctions.un.org/resources/xml/en/consolidated.xml",
       L_EU: "https://webgate.ec.europa.eu/fsd/fsf/public/files/csvFullSanctionsList_1_1/content",
       L_UK: "https://sanctionslist.fcdo.gov.uk/docs/UK-Sanctions-List.csv"}

# Entities from the recorded live answers. Any cluster whose names contain these is kept
# out of train/val/test so the live set measures names the model never saw.
LIVE_TOKENS = ["ROSNEFT", "SBERBANK", "VTB", "GAZPROMBANK", "MAHAN", "WAGNER", "LAZARUS",
               "HIZBALLAH", "HEZBOLLAH", "REVOLUTIONARY GUARD"]


# ---------------------------------------------------------------- names
def fold(s):
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[^A-Z0-9]+", " ", fold(s).upper())).strip()


def key(s):
    return " ".join(sorted(norm(s).split()))


def display(name, kind):
    """OFAC writes individuals as 'LAST, First'; apps send 'First Last'."""
    if kind == "individual" and "," in name:
        last, first = name.split(",", 1)
        name = f"{first.strip()} {last.strip().title()}"
    if name.isupper() and kind != "vessel":
        name = name.title()
    return name.strip()


# ---------------------------------------------------------------- loading
def none_if(x):
    x = (x or "").strip()
    return None if x in ("", "-0-") else x


def load_ofac(prim, alt, label):
    ents = {}
    for r in csv.reader(open(RAW / prim, encoding="latin-1")):
        if len(r) < 12:
            continue
        uid, name, kind, prog = r[0].strip(), r[1].strip(), (none_if(r[2]) or "entity"), none_if(r[3]) or ""
        remarks = none_if(r[11]) or ""
        e = dict(id=f"{label}:{uid}", uid=uid, list=label, kind=kind, name=name, aliases=[],
                 programs=[p.strip() for p in re.split(r"\]\s*\[", prog) if p.strip()],
                 dob=None, wallets=[], imo=None, flag=none_if(r[9]), vtype=none_if(r[6]))
        m = re.search(r"DOB (\d{1,2} [A-Z][a-z]{2} \d{4}|[A-Z][a-z]{2} \d{4}|\d{4})", remarks)
        if m:
            e["dob"] = m.group(1)
        for cur, addr in re.findall(r"Digital Currency Address - ([A-Z0-9]+) ([A-Za-z0-9]+)", remarks):
            e["wallets"].append((cur, addr))
        m = re.search(r"IMO (\d{7})", remarks)
        if m:
            e["imo"] = m.group(1)
        ents[uid] = e
    for r in csv.reader(open(RAW / alt, encoding="latin-1")):
        if len(r) >= 4 and r[0].strip() in ents and none_if(r[3]):
            ents[r[0].strip()]["aliases"].append(r[3].strip())
    return list(ents.values())


def load_un():
    root = ET.parse(RAW / "consolidated.xml").getroot()
    out = []
    for tag, kind in (("INDIVIDUAL", "individual"), ("ENTITY", "entity")):
        for n in root.iter(tag):
            g = lambda t: (n.findtext(t) or "").strip()
            name = " ".join(x for x in (g("FIRST_NAME"), g("SECOND_NAME"), g("THIRD_NAME"), g("FOURTH_NAME")) if x)
            if not name:
                continue
            aliases = [(a.findtext("ALIAS_NAME") or "").strip() for a in n.iter(f"{tag}_ALIAS")]
            dob = None
            d = n.find("INDIVIDUAL_DATE_OF_BIRTH")
            if d is not None:
                dob = (d.findtext("DATE") or d.findtext("YEAR") or "").strip() or None
            out.append(dict(id=f"UN:{g('REFERENCE_NUMBER')}", uid=g("REFERENCE_NUMBER"), list=L_UN, kind=kind,
                            name=name, aliases=[a for a in aliases if a], programs=[g("UN_LIST_TYPE")],
                            dob=dob, wallets=[], imo=None, flag=None, vtype=None))
    return out


def load_eu():
    ents = {}
    rows = csv.reader(open(RAW / "eu_fsf.csv", encoding="utf-8-sig"), delimiter=";")
    head = next(rows)
    ix = {h: i for i, h in enumerate(head)}
    for r in rows:
        if len(r) < len(head) // 2:
            continue
        lid, whole = r[ix["Entity_LogicalId"]], r[ix["NameAlias_WholeName"]].strip()
        if not whole:
            continue
        kind = "individual" if r[ix["Entity_SubjectType_ClassificationCode"]] == "person" else "entity"
        e = ents.setdefault(lid, dict(id=f"EU:{lid}", uid=r[ix["Entity_EU_ReferenceNumber"]] or lid, list=L_EU,
                                      kind=kind, name=whole, aliases=[], programs=[r[ix["Entity_Regulation_Programme"]]],
                                      dob=None, wallets=[], imo=None, flag=None, vtype=None))
        if whole != e["name"] and whole not in e["aliases"]:
            e["aliases"].append(whole)
    return list(ents.values())


def load_uk():
    ents = {}
    with open(RAW / "uk_sanctions_list.csv", encoding="utf-8-sig") as f:
        f.readline()
        for r in csv.DictReader(f):
            uid = r["Unique ID"]
            parts = [r[f"Name {i}"].strip() for i in (1, 2, 3, 4, 5, 6)]
            name = " ".join(p for p in parts if p)
            if not name:
                continue
            dt = (r.get("Designation Type") or "").lower()
            kind = "individual" if dt == "individual" else ("vessel" if dt == "ship" else "entity")
            e = ents.get(uid)
            if e is None:
                e = ents[uid] = dict(id=f"UK:{uid}", uid=uid, list=L_UK, kind=kind, name=name, aliases=[],
                                     programs=[r["Regime Name"].replace("The ", "").replace(" (Sanctions) (EU Exit) Regulations 2019", "")
                                               .replace(" (Sanctions) (EU Exit) Regulations 2020", "")],
                                     dob=none_if(r.get("D.O.B")), wallets=[], imo=(none_if(r.get("IMO number")) or "").replace("IMO", "").strip() or None,
                                     flag=None, vtype=None)
            if r["Name type"].lower().startswith("primary"):
                if e["name"] != name:
                    e["aliases"].append(e["name"])
                    e["name"] = name
            elif name not in e["aliases"]:
                e["aliases"].append(name)
    return list(ents.values())


# ---------------------------------------------------------------- clustering
class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        self.p[self.find(a)] = self.find(b)


def build_index(ents):
    uf = UF()
    by_key = defaultdict(list)        # name key -> entries
    for e in ents:
        names = [e["name"]] + e["aliases"]
        e["keys"] = sorted({key(n) for n in names if len(key(n)) >= 3})
        for k in e["keys"]:
            by_key[k].append(e)
            uf.union(e["id"], "k:" + k)
        for _, a in e["wallets"]:
            uf.union(e["id"], "w:" + a)
    for e in ents:
        e["cluster"] = uf.find(e["id"])
    return by_key


def split_of(cluster, live):
    if live:
        return "live"
    h = int(hashlib.sha256(cluster.encode()).hexdigest()[:8], 16) % 100
    return "test" if h < 15 else ("val" if h < 25 else "train")


# ---------------------------------------------------------------- vocab for clean names
FIRST = ("Adaeze Amara Chinedu Kofi Ama Kwame Fatima Aisha Omar Yusuf Layla Karim Hassan Mariam Samir Nadia Rania Tariq "
         "Olga Dmitri Sergei Natalia Anya Pavel Irina Mikhail Elena Viktor Wei Mei Jun Hao Xiu Lan Bo Yan Hiroshi Yuki Akira "
         "Sakura Min-jun Ji-woo Seo-yeon Arjun Priya Rohan Ananya Vikram Kavya Diego Lucia Mateo Sofia Javier Camila Pedro "
         "Isabela Liam Emma Noah Olivia Lukas Mia Jonas Lea Tomasz Zofia Jakub Aleksandra Emre Elif Mehmet Zeynep Thabo "
         "Naledi Sipho Lerato Chloe Gabriel Ines Hugo Astrid Erik Freya Nils Ayesha Bilal Hamza Sana Daniel Rachel Noa Eitan").split()
LAST = ("Okafor Mensah Boateng Adeyemi Nwosu Haddad Nasser Khoury Rahimi Farouk Saleh Mansour Bakr Volkova Sokolov Morozov "
        "Lebedev Novikova Kozlov Orlov Chen Zhang Liu Huang Zhao Wu Tanaka Sato Watanabe Kim Park Choi Patel Sharma Iyer Reddy "
        "Nair Gupta Hernandez Lopez Moreno Castillo Romero Silva Santos Oliveira Murphy Walsh Schmidt Becker Fischer Kowalski "
        "Nowak Wisniewski Yilmaz Demir Kaya Dlamini Nkosi Mokoena Dubois Laurent Moreau Lindqvist Berg Hansen Qureshi Siddiqui "
        "Malik Cohen Levi Friedman Abara Osei Ndlovu Petrova Ibrahimova Delgado Ferreira Kovac Horvat Popescu Ionescu").split()
CO_A = ("Northwind Bluefield Silverline Kestrel Harborview Granite Meadowlark Cedarpoint Ironbridge Sunfield Lakeshore Brightwater "
        "Copperleaf Redwood Clearpath Stonegate Riverbend Highland Seabright Westmark Eastgate Oakridge Pinecrest Goldcrest "
        "Amberline Fairhaven Larkspur Mapleton Starling Bramble Willowmere Driftwood Summit Coral Saffron Indigo Juniper Tamarind "
        "Baobab Kilimanjaro Volta Zambezi Atlas Aurora Nimbus Orion Vega Lyra Halcyon Solstice Meridian Quillfeather Lumen").split()
CO_B = ("Logistics Analytics Textiles Foods Shipping Holdings Trading Consulting Software Pharma Robotics Ceramics Coffee Solar "
        "Agritech Freight Imports Exports Microfinance Media Studios Architects Dental Clinics Fisheries Timber Packaging "
        "Biotech Insurance Capital Payments Labs Design Translations Bakeries Mining Equipment Telecom Garments Furniture").split()
SUFFIX = ["Ltd", "LLC", "GmbH", "S.A.", "Pte Ltd", "Inc.", "B.V.", "S.r.l.", "Co., Ltd.", "PLC", "SARL", "AG", "Limited",
          "JSC", "LLP", "Pty Ltd", "OOO", "A.S.", "Sp. z o.o.", ""]
SWAP_WORDS = ("Atlantic Pacific Coastal National United Global Modern Central Northern Southern Eastern Western Royal "
              "Premier General Continental Metro Valley Green Blue Crystal Golden Silver Union Star Delta Prime").split()
LIVE_CLEAN = {key(n) for n in ["Adaeze Okonkwo Farms", "Northwind Design Collective", "Kestrel Pixel Labs",
                                "Blue Heron Translations", "Tunde Bakare Studio", "Priya Raman Illustration",
                                "Quillfeather Copywriting", "Ostrava Motion Graphics", "Lumen Harbor Analytics",
                                "Zainab Yusuf Photography"]}

TRANSLIT = [("OU", "U"), ("U", "OU"), ("KH", "H"), ("H", "KH"), ("Y", "I"), ("I", "Y"), ("PH", "F"), ("F", "PH"),
            ("Q", "K"), ("K", "Q"), ("J", "DZH"), ("DZH", "J"), ("AL ", "EL "), ("AL-", "EL-"), ("EE", "I"),
            ("SH", "SCH"), ("TS", "C"), ("V", "W"), ("W", "V"), ("MOHAMMED", "MUHAMMAD"), ("MUHAMMAD", "MOHAMED"),
            ("YU", "IU"), ("YA", "IA"), ("C", "K"), ("X", "KS"), ("Z", "S"), ("E", "A"), ("A", "E")]


# ---------------------------------------------------------------- answers
class Gen:
    def __init__(self, ents, by_key, seed):
        self.r = random.Random(seed)
        self.ents, self.by_key = ents, by_key
        self.rows = []
        self.listed_wallets = {a for e in ents for _, a in e["wallets"]}
        self.counts = Counter()

    # lists on which a name key appears
    def lists_for(self, k):
        return [l for l in ALL_LISTS if any(e["list"] == l for e in self.by_key.get(k, []))]

    def is_listed_name(self, name):
        return key(name) in self.by_key

    def conf(self, lo, hi):
        return round(self.r.uniform(lo, hi), 2)

    # --- prompts
    def prompt(self, subject, role=None, extra=""):
        r = self.r
        role = role or r.choice(["payee", "counterparty", "beneficial owner", "client", "supplier", "director",
                                 "customer", "merchant", "borrower", "entity", "person"])
        t = r.choice([
            f"Screen the {role} '{subject}' against OFAC, EU, UN and other consolidated sanctions lists.{extra}",
            f"Is '{subject}' on any sanctions list (OFAC SDN, EU, UN, UK)? Include near-matches on spelling.{extra}",
            f"Sanctions check before payout. {role.capitalize()}: {subject}.{extra} Does it match a listed party?",
            f"{{\"name\": \"{subject}\", \"role\": \"{role}\"{extra and ', ' + json.dumps('note') + ': ' + json.dumps(extra.strip())}}}",
            f"We are onboarding a {role} named {subject}.{extra} Check the consolidated sanctions lists and tell me if there is a hit.",
            f"Does {subject} appear on the OFAC, EU or UN sanctions lists, including spelling or transliteration variants?{extra}",
            f"Compliance check: run {subject} ({role}) through sanctions screening and report any match with the list it is on.{extra}",
            f"Check whether the {role} {subject} is sanctioned.{extra}",
        ])
        return t

    def wallet_prompt(self, addr, cur):
        role = self.r.choice(["payee wallet", "treasury address", "deposit address", "counterparty wallet",
                              "withdrawal address", "beneficiary wallet"])
        return self.r.choice([
            f"Screen this {role} against sanctions lists: {addr} ({cur}).",
            f"Is the {cur} address {addr} listed by OFAC or any other sanctions authority?",
            f"{{\"wallet\": \"{addr}\", \"chain\": \"{cur}\", \"purpose\": \"{role}\"}}",
            f"Before we send funds: check {role} {addr} for sanctions exposure.",
            f"Return the sanctions status of {role} {addr} and its known owner.",
        ])

    # --- answer renderers: same style for both sides of a pair
    def render(self, style, q, verdict, entries, score, note=None):
        """verdict: match | possible | clear. entries: list of dicts(name,list,uid,programs)."""
        if style == "provider":
            return json.dumps({"name": q, "matched": verdict != "clear",
                               "matches": [e["name"] for e in entries] or None,
                               "lists": sorted({SHORT[e["list"]] + " (published " + AS_OF[e["list"]] + ")" for e in entries}) or None,
                               "match_score": score}, ensure_ascii=False)
        if style == "record":
            d = {"query": q, "result": {"match": "match", "possible": "possible_match", "clear": "no_match"}[verdict],
                 "entries": [{"name": e["name"], "list": e["list"], "id": e["uid"], "programs": e["programs"]} for e in entries],
                 "confidence": score}
            if note:
                d["note"] = note
            return json.dumps(d, ensure_ascii=False)
        # prose
        if verdict == "clear":
            s = f"No match. '{q}' does not appear on {', '.join(SHORT[l] for l in ALL_LISTS)} as of the latest publications."
        elif verdict == "possible":
            s = f"Possible match. '{q}' is close to {self.prose_entries(entries)}. Treat it as a hit pending review."
        else:
            s = f"Match. '{q}' is listed: {self.prose_entries(entries)}."
        s += f" Confidence {score}."
        if note:
            s += " " + note
        return s

    def prose_entries(self, entries):
        return "; ".join(f"{e['name']} on the {e['list']} (id {e['uid']}, programs {', '.join(e['programs']) or 'n/a'})"
                         for e in entries)

    def entry(self, e, name=None):
        return {"name": name or e["name"], "list": e["list"], "uid": e["uid"], "programs": e["programs"]}

    def entries_for_key(self, k, limit=3):
        seen, out = set(), []
        for e in self.by_key.get(k, []):
            if e["id"] not in seen:
                seen.add(e["id"])
                out.append(self.entry(e))
        return out[:limit]

    def other(self, e, pred=lambda x: True):
        while True:
            o = self.r.choice(self.ents)
            if o["cluster"] != e["cluster"] and pred(o):
                return o

    def add(self, kind, cluster, prompt, chosen, rejected):
        if chosen == rejected:
            return
        self.rows.append({"prompt": prompt, "chosen": chosen, "rejected": rejected, "label_kind": "preference_pair",
                          "x_kind": kind, "x_cluster": cluster})
        self.counts[kind] += 1

    def style(self):
        return self.r.choices(["provider", "record", "prose"], [4, 3, 3])[0]

    # Notes share one frame on both sides of a pair, so wording alone never tells them apart.
    def closest(self, st, x, same):
        if st == "provider":
            return None
        verdict = ("Same name allowing for spelling and transliteration; counts as a hit." if same
                   else "Different name; does not count as a hit.")
        return f"Closest listed name: '{x['name']}' ({SHORT[x['list']]}). {verdict}"

    def via(self, st, x):
        return None if st == "provider" else f"Matched on a recorded name or alias of {x['name']}."

    def waddr(self, st, eq, cur, x=None):
        if st == "provider":
            return None
        if eq:
            return f"Address equals a listed {cur} address of {x['name']}."
        return f"Address does not equal any listed {cur} address" + (f"; closest listed owner {x['name']}." if x else ".")

    # --- wrong-answer builders for a listed query
    def wrong_for_hit(self, st, q, e, entries, verdict, score):
        r = self.r
        how = r.choice(["false_clear", "false_clear", "wrong_list", "wrong_detail", "wrong_entity"])
        if how == "false_clear":
            return how, self.render(st, q, "clear", [], self.conf(0, 0.2) if st != "provider" else 0,
                                    self.closest(st, e, False))
        if how == "wrong_list":
            have = {x["list"] for x in entries}
            pool = [l for l in ALL_LISTS if l not in have] or ALL_LISTS
            bad = [dict(x, list=r.choice(pool)) for x in entries]
            if st == "provider" and bad == entries:
                how = "wrong_detail"
            else:
                return how, self.render(st, q, verdict, bad, score, self.via(st, e))
        if how == "wrong_detail" and st != "provider":
            o = self.other(e, lambda x: x["programs"] and x["programs"] != e["programs"])
            bad = [dict(entries[0], programs=o["programs"], uid=o["uid"] if r.random() < .5 else entries[0]["uid"])] + entries[1:]
            return how, self.render(st, q, verdict, bad, score, self.via(st, e))
        o = self.other(e, lambda x: x["kind"] == e["kind"])
        return "wrong_entity", self.render(st, q, verdict, [self.entry(o)], score, self.via(st, o))

    # ------------------------------------------------------------ pair types
    def listed_exact(self, e, use_alias=False):
        names = e["aliases"] if use_alias and e["aliases"] else [e["name"]]
        raw = self.r.choice(names)
        q = display(raw, e["kind"])
        k = key(raw)
        entries = self.entries_for_key(k) or [self.entry(e)]
        st = self.style()
        score = 1 if st == "provider" else self.conf(0.93, 0.99)
        chosen = self.render(st, q, "match", entries, score, self.via(st, e))
        how, rej = self.wrong_for_hit(st, q, e, entries, "match", score)
        self.add(("alias_" if use_alias else "exact_") + how, e["cluster"], self.prompt(q), chosen, rej)

    def misspelled(self, e):
        raw = e["name"]
        q = None
        for _ in range(12):
            cand = self.perturb(norm(raw))
            if cand != norm(raw) and not self.is_listed_name(cand) and len(cand) > 4:
                q = display(cand.title() if e["kind"] != "individual" else cand, "entity")
                break
        if not q:
            return
        st = self.style()
        score = round(self.r.uniform(0.82, 0.95), 3) if st == "provider" else self.conf(0.75, 0.92)
        entries = [self.entry(e)]
        chosen = self.render(st, q, "possible", entries, score, self.closest(st, e, True))
        if self.r.random() < 0.75:
            rej = self.render(st, q, "clear", [], 0 if st == "provider" else self.conf(0.02, 0.2),
                              self.closest(st, e, False))
            how = "false_clear"
        else:
            o = self.other(e, lambda x: x["kind"] == e["kind"])
            rej = self.render(st, q, "possible", [self.entry(o)], score, self.closest(st, o, True))
            how = "wrong_entity"
        self.add("variant_" + how, e["cluster"], self.prompt(q), chosen, rej)

    def perturb(self, s):
        r = self.r
        ops = r.randint(1, 2)
        for _ in range(ops):
            c = r.random()
            subs = [(a, b) for a, b in TRANSLIT if a in s]
            if c < 0.45 and subs:
                a, b = r.choice(subs)
                idx = [m.start() for m in re.finditer(re.escape(a), s)]
                i = r.choice(idx)
                s = s[:i] + b + s[i + len(a):]
            elif c < 0.65 and len(s) > 5:
                i = r.randrange(1, len(s) - 1)
                if s[i].isalpha():
                    s = s[:i] + s[i] + s[i:]
            elif c < 0.85 and len(s) > 5:
                i = r.randrange(1, len(s) - 2)
                if s[i].isalpha() and s[i + 1].isalpha():
                    s = s[:i] + s[i + 1] + s[i] + s[i + 2:]
            else:
                v = [i for i, ch in enumerate(s) if ch in "AEIOU" and 0 < i < len(s) - 1]
                if v:
                    i = r.choice(v)
                    s = s[:i] + s[i + 1:]
        return s

    def lookalike(self, e):
        toks = norm(e["name"]).split()
        cand = [i for i, t in enumerate(toks) if len(t) > 3 and t not in ("COMPANY", "LIMITED", "BANK", "GROUP", "TRADING")]
        if e["kind"] == "individual" or len(toks) < 2 or not cand:
            return
        i = self.r.choice(cand)
        new = toks[:]
        new[i] = self.r.choice(SWAP_WORDS).upper()
        q = " ".join(new).title()
        if self.is_listed_name(q):
            return
        st = self.style()
        chosen = self.render(st, q, "clear", [], 0 if st == "provider" else self.conf(0.03, 0.2), self.closest(st, e, False))
        score = round(self.r.uniform(0.86, 1.0), 3) if st == "provider" else self.conf(0.85, 0.97)
        rej = self.render(st, q, "match", [self.entry(e)], score, self.closest(st, e, True))
        self.add("lookalike_false_hit", e["cluster"], self.prompt(q), chosen, rej)

    def clean_invented(self, idx):
        r = self.r
        if r.random() < 0.5:
            q = f"{r.choice(FIRST)} {r.choice(LAST)}"
            role = r.choice(["payee", "director", "beneficial owner", "customer", "person"])
        else:
            q = f"{r.choice(CO_A)} {r.choice(CO_B)} {r.choice(SUFFIX)}".strip()
            role = r.choice(["supplier", "counterparty", "merchant", "client", "vendor"])
        if self.is_listed_name(q) or key(q) in LIVE_CLEAN:
            return
        st = self.style()
        o = r.choice(self.ents)
        chosen = self.render(st, q, "clear", [], 0 if st == "provider" else self.conf(0.01, 0.12), self.closest(st, o, False))
        how = r.choice(["false_hit", "false_possible", "false_self"])
        score = (round(r.uniform(0.8, 1.0), 3) if st == "provider" else self.conf(0.7, 0.95))
        if how == "false_self":
            # the wrong answer claims the queried name itself is a listed entry
            fake = dict(self.entry(o), name=q.upper() if r.random() < 0.6 else q)
            rej = self.render(st, q, "match", [fake], score, self.closest(st, fake, True))
        else:
            rej = self.render(st, q, "match" if how == "false_hit" else "possible", [self.entry(o)], score,
                              self.closest(st, o, True))
        cl = "clean:" + key(q)
        self.add("clean_" + how, cl, self.prompt(q, role), chosen, rej)

    def wallet_listed(self, e, cur, addr):
        st = self.style()
        q = addr
        entries = [self.entry(e)]
        chosen = self.render(st, q, "match", entries, 1 if st == "provider" else self.conf(0.97, 1.0), self.waddr(st, True, cur, e))
        if self.r.random() < 0.6:
            how = "false_clear"
            rej = self.render(st, q, "clear", [], 0 if st == "provider" else self.conf(0, 0.1),
                              self.waddr(st, False, cur))
        else:
            how = "wrong_owner"
            o = self.other(e, lambda x: bool(x["wallets"]))
            rej = self.render(st, q, "match", [self.entry(o)], 1 if st == "provider" else self.conf(0.97, 1.0),
                              self.waddr(st, True, cur, o))
        self.add("wallet_listed_" + how, e["cluster"], self.wallet_prompt(addr, cur), chosen, rej)

    def wallet_clean(self, e, cur, addr):
        """A one-character change of a listed address, or a fresh address of the same shape."""
        r = self.r
        alphabet = "0123456789abcdef" if addr.startswith("0x") else "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
        if len(addr) < 20:
            return
        if r.random() < 0.5:
            i = r.randrange(len(addr) - 6, len(addr))
            q = addr[:i] + r.choice([c for c in alphabet if c != addr[i]]) + addr[i + 1:]
            near = e
            kind = "wallet_near_false_hit"
        else:
            keep = 2 if addr.startswith("0x") else (4 if addr.startswith("bc1") else 1)
            q = addr[:keep] + "".join(r.choice(alphabet) for _ in range(len(addr) - keep))
            near = None
            kind = "wallet_clean_false_hit"
        if q in self.listed_wallets:
            return
        st = self.style()
        chosen = self.render(st, q, "clear", [], 0 if st == "provider" else self.conf(0, 0.05), self.waddr(st, False, cur, near))
        rej = self.render(st, q, "match", [self.entry(e)], 1 if st == "provider" else self.conf(0.9, 1.0),
                          self.waddr(st, True, cur, e))
        self.add(kind, e["cluster"], self.wallet_prompt(q, cur), chosen, rej)

    def vessel(self, e):
        st = self.style()
        q = e["name"] + (f" (IMO {e['imo']})" if e["imo"] else "")
        chosen = self.render(st, q, "match", [self.entry(e)], 1 if st == "provider" else self.conf(0.93, 0.99), self.via(st, e))
        how, rej = self.wrong_for_hit(st, q, e, [self.entry(e)], "match", 1 if st == "provider" else self.conf(0.93, 0.99))
        p = self.r.choice([f"Screen the vessel {q} and its owner against sanctions lists before we charter it.",
                           f"Is the ship {q} sanctioned?",
                           f"{{\"vessel\": \"{e['name']}\", \"imo\": \"{e['imo'] or ''}\", \"check\": \"sanctions\"}}",
                           f"Port call screening: vessel {q}. Any sanctions hit?"])
        self.add("vessel_" + how, e["cluster"], p, chosen, rej)

    def dob_case(self, e):
        r = self.r
        q = display(e["name"], "individual")
        if r.random() < 0.5:
            dob = e["dob"]
            st = self.style()
            note = self.dobnote(e, dob, True)
            bad = self.dobnote(e, dob, False)
            chosen = self.render(st, q, "match", [self.entry(e)], self.conf(0.95, 0.99), note if st != "provider" else None)
            rej = self.render(st, q, "clear", [], self.conf(0.05, 0.25), bad if st != "provider" else None)
            kind = "dob_agree_false_clear"
        else:
            y = re.search(r"\d{4}", e["dob"]).group(0)
            dob = f"{r.randint(1, 28):02d} {r.choice(['Jan','Mar','Jun','Aug','Oct','Dec'])} {int(y) + r.choice([-9,-6,-4,4,7,11])}"
            st = r.choice(["record", "prose"])
            note = self.dobnote(e, dob, False)
            bad = self.dobnote(e, dob, True)
            chosen = self.render(st, q, "possible", [self.entry(e)], self.conf(0.2, 0.4), note)
            rej = self.render(st, q, "match", [self.entry(e)], self.conf(0.95, 0.99), bad)
            kind = "dob_conflict_false_confirm"
        self.add(kind, e["cluster"], self.prompt(q, r.choice(["payee", "customer", "director", "beneficial owner"]),
                                                    f" Date of birth: {dob}."), chosen, rej)

    def dobnote(self, e, dob, agree):
        return (f"Listed DOB {e['dob']}; supplied DOB {dob}. " +
                ("They agree, so this is a confirmed match." if agree
                 else "They conflict, so this is not a confirmed match; verify with ID."))

    def field_swap(self, e):
        """Same verdict and template; one field (name, id or programs) taken from another real entry."""
        r = self.r
        o = self.other(e, lambda x: x["list"] == e["list"] and x["programs"] != e["programs"] and x["name"] != e["name"])
        q = display(r.choice([e["name"]] + e["aliases"][:3]), e["kind"])
        good = {"query": q, "alert": True, "list": e["list"], "as_of": AS_OF[e["list"]], "listed_name": e["name"],
                "id": e["uid"], "programs": e["programs"], "source": URL[e["list"]]}
        field = r.choice(["listed_name", "id", "programs"])
        bad = dict(good, **{field: {"listed_name": o["name"], "id": o["uid"], "programs": o["programs"]}[field]})
        if r.random() < 0.5:
            gs, bs = json.dumps(good, ensure_ascii=False), json.dumps(bad, ensure_ascii=False)
        else:
            f = lambda d: (f"'{q}' raises a name alert on the {d['list']} published {d['as_of']}: listed as {d['listed_name']}, "
                           f"id {d['id']}, programs {', '.join(d['programs'])}. Source: {d['source']}")
            gs, bs = f(good), f(bad)
        p = r.choice([
            f"Does '{q}' produce a name alert on the {e['list']} published {AS_OF[e['list']]}? Return the listed name, id and programs.",
            f"Screen {q} against the {SHORT[e['list']]} list and give the matching entry's canonical name, identifier and sanction programs.",
            f"{{\"name\": \"{q}\", \"lists\": [\"{SHORT[e['list']]}\"], \"return\": [\"listed_name\", \"id\", \"programs\"]}}",
        ])
        if getattr(self, "long_swaps", False) and r.random() < 0.5:
            p, gs, bs = self.long_swap(e, q, good, bad)
        self.add("swap_" + field, e["cluster"], p, gs, bs)

    def long_swap(self, e, q, good, bad):
        """Evidence-restricted wording: the question pins the publication, the match basis and the fields."""
        r = self.r
        basis = "primary name" if norm(q) == norm(display(e["name"], e["kind"])) else "recorded alias"
        pub = {L_SDN: "the U.S. Treasury OFAC Specially Designated Nationals list", L_CONS: "the U.S. Treasury OFAC Consolidated (non-SDN) list",
               L_UN: "the UN Security Council Consolidated List", L_EU: "the EU Consolidated Financial Sanctions List",
               L_UK: "the UK Sanctions List published by the FCDO"}[e["list"]]
        idname = {L_UN: "UN reference number", L_UK: "UK unique ID", L_EU: "EU reference number"}.get(e["list"], "numeric OFAC UID")
        p = r.choice([
            f"Using only {pub} as retained on {AS_OF[e['list']]} ({URL[e['list']]}), does the name '{q}' raise a primary-name "
            f"or recorded-alias alert? Restrict the evidence to that publication. If it does, report the entry's canonical name, "
            f"its {idname} and its complete program tags. A name alert is not a confirmation of identity.",
            f"Counterparty onboarding for a cross-border payment. Screen '{q}' against {pub} dated {AS_OF[e['list']]} only. "
            f"Return JSON with the match basis (primary name or alias), the listed canonical name, the {idname}, the full "
            f"set of sanctions programs and the source file URL. Do not use any other list or later publication.",
            f"Historical screening question, evidence limited to {pub} published {AS_OF[e['list']]}: is '{q}' on it under any "
            f"recorded name? Give the matching record's name, {idname} and every program code exactly as published.",
        ])
        def j(d):
            return json.dumps({"query": q, "name_alert": True, "match_basis": basis, "publication": e["list"],
                               "publication_date": d["as_of"], "canonical_name": d["listed_name"], "identifier": d["id"],
                               "programs": d["programs"], "source_url": d["source"],
                               "note": "Name alert only; identity not confirmed."}, ensure_ascii=False)
        return p, j(good), j(bad)

    def common_name(self, k, ents):
        """A name shared by several listed people: the right answer is a possible match that needs more data."""
        r = self.r
        e = ents[0]
        q = display(e["name"], "individual")
        st = r.choice(["record", "prose"])
        entries = [self.entry(x) for x in ents[:3]]
        n = f"{len(ents)} listed people share this name; "
        chosen = self.render(st, q, "possible", entries, self.conf(0.4, 0.6), n + "it counts as a hit only once date of birth or nationality agrees.")
        if r.random() < 0.5:
            rej = self.render(st, q, "match", entries[:1], self.conf(0.97, 1.0), n + f"it counts as a hit for {e['name']}.")
            how = "overconfident_hit"
        else:
            rej = self.render(st, q, "clear", [], self.conf(0.0, 0.1), n + "it does not count as a hit.")
            how = "overconfident_clear"
        self.add("common_" + how, e["cluster"], self.prompt(q, r.choice(["payee", "customer", "person"])), chosen, rej)


# ---------------------------------------------------------------- live set
def live_pairs():
    rows = []
    for item in json.load(open(LIVE)):
        if item["expect"] is None:
            continue
        good = next(c["result"] for c in item["checks"] if c.get("result", {}).get("matched") is not None)
        q = item["name"]
        p = f"Screen the payee '{q}' against OFAC, EU, UN and other consolidated sanctions lists."
        if item["expect"]:
            bad = dict(good, matched=False, matches=None, lists=None, match_score=0)
            kind = "live_listed_false_clear"
        else:
            bad = dict(good, matched=True, matches=[q.upper()], lists=["OFAC SDN"], match_score=0.91)
            kind = "live_clean_false_hit"
        rows.append({"prompt": p, "chosen": json.dumps(good), "rejected": json.dumps(bad),
                     "label_kind": "preference_pair", "x_kind": kind, "x_cluster": "live:" + key(q)})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--n-listed", type=int, default=2600, help="listed entities sampled for name pairs")
    ap.add_argument("--n-clean", type=int, default=1100)
    ap.add_argument("--swap-all", action="store_true",
                    help="add a one-field swap pair for every train-split OFAC/UN entry, plus a seen-entity swap eval file")
    ap.add_argument("--r3", action="store_true", help="add UK swaps and evidence-restricted long swap prompts")
    ap.add_argument("--out", default=str(OUT))
    a = ap.parse_args()
    out_dir = Path(a.out)

    ents = (load_ofac("SDN.CSV", "ALT.CSV", L_SDN) + load_ofac("CONS_PRIM.CSV", "CONS_ALT.CSV", L_CONS)
            + load_un() + load_eu() + load_uk())
    by_key = build_index(ents)
    live_clusters = {e["cluster"] for e in ents
                     if any(t in norm(n) for n in [e["name"]] + e["aliases"] for t in LIVE_TOKENS)}
    for e in ents:
        e["split"] = split_of(e["cluster"], e["cluster"] in live_clusters)
    g = Gen([e for e in ents if e["split"] != "live"], by_key, a.seed)
    r = g.r
    pool = [e for e in g.ents if e["kind"] in ("individual", "entity") and len(norm(e["name"])) >= 4]
    r.shuffle(pool)
    for e in pool[:a.n_listed]:
        c = r.random()
        if c < 0.22:
            g.listed_exact(e)
        elif c < 0.34:
            g.listed_exact(e, use_alias=True)
        elif c < 0.56:
            g.misspelled(e)
        elif c < 0.70:
            g.lookalike(e) if e["kind"] == "entity" else g.misspelled(e)
        else:
            g.field_swap(e)
    for e in pool[a.n_listed:a.n_listed + 900]:
        g.field_swap(e)
    ents_only = [e for e in pool if e["kind"] == "entity"]
    for e in ents_only[-500:]:
        g.lookalike(e)
    for i in range(a.n_clean):
        g.clean_invented(i)
    for e in [e for e in g.ents if e["wallets"]]:
        for cur, addr in e["wallets"]:
            (g.wallet_listed if r.random() < 0.55 else g.wallet_clean)(e, cur, addr)
    vessels = [e for e in g.ents if e["kind"] == "vessel"]
    r.shuffle(vessels)
    for e in vessels[:250]:
        g.vessel(e)
    dobs = [e for e in g.ents if e["kind"] == "individual" and e["dob"] and re.search(r"\d{4}", e["dob"])]
    r.shuffle(dobs)
    for e in dobs[:350]:
        g.dob_case(e)
    if a.swap_all:
        swap_lists = (L_SDN, L_CONS, L_UN, L_UK) if a.r3 else (L_SDN, L_CONS, L_UN)
        g.long_swaps = a.r3
        seen = [e for e in pool if e["split"] == "train" and e["list"] in swap_lists and e["programs"]]
        for e in seen:
            g.field_swap(e)
        n = len(g.rows)
        for e in r.sample(seen, 400):
            g.field_swap(e)
        seen_rows, g.rows = g.rows[n:], g.rows[:n]
        train_keys = {(x["prompt"], x["chosen"], x["rejected"]) for x in g.rows}
        seen_rows = [x for x in seen_rows if (x["prompt"], x["chosen"], x["rejected"]) not in train_keys]
    commons = [(k, [e for e in v if e["kind"] == "individual" and e["split"] != "live"]) for k, v in by_key.items()]
    commons = [(k, v) for k, v in commons if len({e["cluster"] for e in v}) == 1 and len({e["uid"] for e in v}) >= 3
               and len(k.split()) == 2]
    r.shuffle(commons)
    for k, v in commons[:200]:
        g.common_name(k, v)

    split = {e["cluster"]: e["split"] for e in ents}
    out_dir.mkdir(parents=True, exist_ok=True)
    buckets = defaultdict(list)
    for row in g.rows:
        c = row["x_cluster"]
        buckets[split.get(c) or split_of(c, False)].append(row)
    if LIVE.exists():
        buckets["live"] = live_pairs()
    if a.swap_all:
        buckets["seen_swap"] = seen_rows
    for name, rows in buckets.items():
        r.shuffle(rows)
        with open(out_dir / f"{name}.jsonl", "w") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    stats = {"entities": len(ents), "per_list": Counter(e["list"] for e in ents),
             "splits": {k: len(v) for k, v in buckets.items()},
             "kinds": {k: Counter(r["x_kind"] for r in v) for k, v in buckets.items()}}
    (out_dir / "stats.json").write_text(json.dumps(stats, indent=1))
    print(json.dumps({"splits": stats["splits"], "kinds_train": stats["kinds"].get("train")}, indent=1))
    # entity-split sanity: no cluster in two splits
    cl = defaultdict(set)
    for name, rows in buckets.items():
        for row in rows:
            if name != "seen_swap":
                cl[row["x_cluster"]].add(name)
    assert all(len(v) == 1 for v in cl.values()), "a cluster leaked across splits"


if __name__ == "__main__":
    sys.exit(main())
