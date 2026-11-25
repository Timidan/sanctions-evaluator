# Sanctions screening evaluator

An entry in the Evaluators track of Telegraph Hackathon Season II. It has two parts:

1. **An adapter** for the intent family `SANCTIONS_SCREENING_MATCH` (child intent `SANCTIONS_SCREENING_MATCH_GENERAL`). The node gives it a screening question and a provider's answer, and ranks answers by the score it returns. It should score a correct screening answer above a wrong one.
2. **Evaluation material**: 496 answer pairs accepted into three evaluation pools.

Network activity used Telegraph's test network on Ethereum Sepolia; the comparisons ran locally with ONNX Runtime. Nothing here is a production result.

## The network record

| Registration | Registered (UTC) | Package | What the node decided |
|---|---|---|---|
| 86 | 17 Nov 2026 | r8a, keccak256 `0x46e8c542…ca37` | Rejected: 68.97% on 29 hidden pairs (20 of 29), below the 70% floor |
| 87 | 18 Nov 2026 | r8c, keccak256 `0x9252f2fe8fc50b6cc7e6716594a1190016a619ab65f22828dd3d257cca6c8c31` | Promoted as the family's first Canonical module: 75.86% on 29 pairs (22 of 29), floor 70% |
| 96 (another author) | 18 Nov 2026 | | Promoted over incumbent 87: 79.31% against 75.86% on 29 pairs, required margin 2.00 points |
| 200 | 23 Nov 2026 | r10, keccak256 `0x71959fd8…9208` | Rejected at the public check: 10 of 15 pairs (66.7%), below the 70% floor |
| 229 | 24 Nov 2026 | r11, keccak256 `0x572e09ed…cc5b` | Rejected at the public check: 9 of 15 pairs (60.0%) |
| 241 | 25 Nov 2026 | r12b, keccak256 `0x17509351…5ebe` | Rejected at the public check: 10 of 15 pairs (66.7%) |

**This entry does not claim Canonical status.** Registration 87 held it for part of 18 Nov 2026: it was registered at 00:33 UTC and replaced at 06:49 UTC. In the registry as read on 25 Nov 2026, 96 is the Canonical module and 87 is recorded as replaced, ranked second. Our three later packages failed the node's public check of 15 pairs and never reached a hidden round; see "Later packages" below.

Check it yourself:

```bash
curl -s "https://devnode.telegraphprotocol.com/api/wasm?intent=SANCTIONS_SCREENING_MATCH&resolve=SANCTIONS_SCREENING_MATCH_GENERAL" \
  | jq '[.. | objects | select(has("registration_id")) | select(.registration_id | IN(87, 96, 200, 229, 241))] | unique_by(.registration_id) | .[] | {registration_id, stage, eval_score, rank, wasm_hash, wasm_url, reason: (.eval.reason // .rejection_reason)}'
```

Saved copies, read on 20 Nov 2026, are in `evidence/`:

- `node-registrations-86-87-96.json` and `node-registration-151.json`: the registry records quoted on this page.
- `sepolia-registration-receipts.jsonl`: the two registration transactions on Ethereum Sepolia (87 is `0x16410d9d50789f56656ee80b53eabb8f5030058f7ea0ea43c66cab6f38ae5aad`, 86 is `0xa9d18acb01ab383d352f70ab886782c6a17cdb494011c076bd4eafce14272b9d`), both sent to Telegraph's contract `0x72a70e949362670Bf8bceAd24eFC5b8f950aa08b`.
- `clean-run-2026-11-20/`: a full run of the comparison below from a clean copy, with package and test-file hashes. The run covered all 1,268 original pairs; the public scores and table were filtered afterwards to the 1,136 pairs kept here.

`baseline/run.sh` downloads the package from the address in the registry and stops if its keccak256 is not the registered hash. It matched on 20 Nov 2026.

## Fair comparison with the current Canonical module

**On the node.** In the round that replaced us, the registry records both modules on 29 pairs: registration 96 at 79.31% (23 of 29) and ours at 75.86% (22 of 29). That establishes the node's decision. It is too small a sample to show that either module is better in general.

Two more readings from the registry: ours scored 22 of 29 in its own first round as well, and in registration 151's round on 19 Nov the incumbent, 96, is recorded at 68.97% (20 of 29).

**Offline, on public test files, same scorer.** `baseline/run.sh` downloads both registered packages from the addresses in the node's registry, checks them against the registered hashes, and scores them with Telegraph's released Foundation graph. A pair counts only when the better answer scores strictly higher, as on the node.

| Test file | Pairs | Ours (87) | Canonical (96) |
|---|---:|---:|---:|
| Clean subject wrongly flagged (reviewer A) | 54 | 54 | 48 |
| Listed subject wrongly cleared (reviewer A) | 72 | 36 | 41 |
| Subject twins (reviewer A) | 72 | 52 | 52 |
| Short alias against a clean lookalike (reviewer A) | 72 | 38 | 37 |
| One-field swaps and two-record prompts (reviewer A) | 150 | 132 | 100 |
| Clean subject wrongly flagged (reviewer B) | 120 | 45 | 35 |
| Listed subject wrongly cleared (reviewer B) | 180 | 175 | 141 |
| Subject twins (reviewer B) | 90 | 45 | 44 |
| Short alias against a clean lookalike (reviewer B) | 160 | 103 | 86 |
| One-field swaps and two-record prompts (reviewer B) | 150 | 122 | 87 |
| Answers in the format real providers return | 16 | 14 | 10 |
| **All files** | **1,136** | **816** | **681** |

Read this table with these limits in mind:

- The ten reviewer files (1,120 pairs here) were prepared for a review on 19 and 20 Nov 2026 by two reviewer models working separately (reviewer A is OpenAI Codex, reviewer B is Google Antigravity). Their brief was to attack this adapter's known weak spot, described below. They were fixed before our next package was scored on them. They use public list records only.
- We withheld 132 rows containing person-named clean subjects or their paired listed-subject controls. The rule: a row is withheld when its clean subject is a real individual, or a small body or business named after an identifiable individual, because the wrong answer of such a pair says that subject is a sanctions match. That is 95 rows using 54 real people with their 23 twin partners, then 14 rows using trusts, institutes and sample payees of that kind. On all 1,268 pairs as written the totals were ours 899, Canonical 739. Judges can have the withheld rows.
- The files still use real companies as clean subjects, including large firms that carry a founder's name, and invented bodies that share one word with a listed name, which is what the lookalike test needs. Wherever an answer links one of them to a sanctions record, it is the deliberately wrong answer of the pair. None of them is on the lists used here.
- They are stress tests, not a representative screening workload. Their answer layouts were written to avoid the layouts our own training used. We have not audited registration 96's training data, so we cannot say these layouts or names are new to it.
- In reviewer B's subject-twin file both answers name the listed party, even when the question is about a clean one. The answer labelled better for the clean subject is therefore a clear that names a different party, and a module that prefers the true record is not plainly wrong. We keep the file in the table and rest no claim on it. Reviewer A's twin file does not have this problem: its two answers are a match that cites the listed record and a plain clear.
- `provider_format.jsonl` is a development check, not an unseen-name test. It has ten listed names (a match against a false clear) and six invented payees (a clear against a false match), in the JSON format that sanctions providers on Telegraph return. The listed names also appear in our training pairs. After an early package got 2 of the original 10 invented payees right, we added training pairs with the same kind of false match.

**On another contributor's published rows.** VishAlgoDev publishes 1,000 sanctions pairs in the `praman-desk` repository. We did not train on them and do not copy them here. `baseline/published_rows.sh` downloads the file at a fixed commit and scores both packages: ours 615 of 1,000, Canonical 523. The file has two kinds of pair. Listed name wrongly cleared: ours 497 of 500, Canonical 325. Clean company wrongly flagged: ours 118 of 500, Canonical 198.

## What it gets wrong

This matters more than the totals above.

- **It often does not read the name it was asked about.** In reviewer A's subject-twin file, the same two answers accompany two questions differing only in the queried name, which flips the right answer. Each module gets both rows right in 16 of 36 groups. Reviewer B's file gives 0 of 45 for each module, but also changes the investigation finding and has the answer-label problem noted above; we draw no name-sensitivity conclusion from it.
- **Its preference follows the answer layout.** In reviewer B's layouts it prefers the match for a clean subject more often than not (45 right of 120). In reviewer A's it leans to the clear (36 right of 72 listed subjects, 2 of 36 short aliases).
- **Clean companies wrongly flagged.** On the published rows above it prefers a match that cites some other entity's true list record over a correct clear in a different layout: 118 right of 500, where the Canonical module gets 198.
- **The node evidence is thin.** 22 of 29 on each of two samples.

We tried to fix the first three with a retrained package, r9, which added 34,494 training pairs where only the subject changes. It improved on layouts close to its new training pairs. On the reviewers' two regression files together it fell from 254 of 300 to 239 (reviewer A's file from 132 to 114; reviewer B's rose from 122 to 125). Both reviewers rejected it against pass bars they had fixed before it was scored. It was not registered.

### Later packages: r10, r11 and r12b

Three more packages were registered after 20 Nov. Each failed the node's public check, which needs 11 of 15 pairs, so none was scored on hidden pairs. Registration 87 is still the package this entry stands on.

| Package | Registration | Node's public check | Public test files (1,136) | VishAlgoDev's published rows (1,000) |
|---|---|---:|---:|---:|
| r10 | 200 | 10 of 15 | 858 | 780 |
| r11 | 229 | 9 of 15 | 933 | 618 |
| r12b | 241 | 10 of 15 | 930 | 783 |
| r8c, for comparison | 87 | passed | 816 | 615 |

The offline columns use `score_pairs.py` on the same files as the tables above. Each package can be downloaded from the address in its registry record and checked against its hash. We used these files to compare the later packages, so they are no longer an unseen test for us. All three were trained without the 298 pool rows described below.

**Where r12b's idea came from.** Our scoring server's log records token counts and scores, and no request text. Across the node's public checks of four earlier packages it showed one pattern: we ordered 15 of 16 pairs correctly when the better answer was the shorter text, and 26 of 40 when it was the longer one. We then reproduced the fault on our own test pairs: registration 87 marks an answer down for a true added detail or a caution. r12b is r11's 432,660 training pairs plus 30,000 new pairs built from the public lists, where the better answer either adds a true or cautious detail, or leaves out an overclaim or a false detail. No text the node sent was logged, read or used in training. The builder for these pairs and its review record are not in this repository; judges can have them on request.

**What r12b gets wrong.**

- At the node's check, by our server's log, it ordered all four pairs correctly where the better answer was clearly longer. Four of its five misses were pairs of nearly equal length, each lost by under a point of score. We do not know why.
- It can prefer a false match that carries a caution note. On 20 fresh pairs written by reviewer A, where the customer is a different company from the listed one and the wrong answer adds a note, it ordered 4 correctly; registration 87 ordered 17.
- When two answers differ in one fact and the right one carries a note, it ordered 19 of 50 correctly on reviewer B's unseen set; registration 87 ordered 32.
- Before registration, reviewer B passed its file, training data and reported numbers. Reviewer A did not pass the data check: 25 listed entities that are twin partners in our withheld rows are named in training pairs carried over from r11. The withheld names themselves are not in training, and no withheld row is in any set scored here.

## Things a judge should know

- **Our pool rows are in our training set.** All 298 sanctions rows we contributed to the pool (below) are included twice in the adapter's 389,448 training pairs. Its hidden-pool scores are therefore not wholly independent of its training data. Telegraph documents that the hidden sample is drawn evenly across contributors, but we have not established how many of our rows were in either 29-pair sample, and we have not measured how much this changed the result. Offline, registration 87 orders 283 of those 298 rows correctly and registration 96 orders 144. On 290 separate rows in our own style that are not in training, ours orders 251. The later packages (registrations 200, 229 and 241) were trained without the 298 rows; r12b orders 263 of them.
- **We also run an app that buys sanctions screening**, [Paysheet](https://github.com/Timidan/paysheet), entered in the Apps & Agents track. We run no provider.
- **Qualification feedback.** Telegraph's documented remote check sends public qualification pairs to the author's runnable address. Validators run the hidden competition separately; the documented protocol does not send those pairs to the author's endpoint. Aggregate observations from our executor (token counts and scores) and our public-check results informed development, as the training builder's header describes. Our own statement, which this repository cannot prove: the server runs Telegraph's `adapterexec` unchanged, its log holds token counts and scores and no request text, and we did not train on text the node sent. Judges can have the log on request. r12b is the clearest case of this feedback; "Later packages" above says exactly what was used.
- **Not derived from another module.** We downloaded and scored the Canonical package for comparison only.
- **Surface checks on the training set.** The kit's probes scored 54.7% at telling the better answer from the worse one without the question, and 50.9% from length alone. These limited checks do not rule out other answer-style shortcuts.

## Evaluation material

Accepted rows, by the node's record (`GET /api/evalpool/submissions/mine?submitter=0xc82E3a196d25841EAB45fff5Ce2A64f5D986370d&intent_id=<INTENT>`; counts saved in `evidence/evalpool-our-rows.json`):

| Intent | Our rows | Status | Pool at 20 Nov 2026 |
|---|---:|---|---|
| `SANCTIONS_SCREENING_MATCH_GENERAL` | 298 | eligible; 184 attested, 114 unverified | 3,187 rows, 16 contributors |
| `CONTENT_MODERATION_GENERAL` | 98 | eligible; unverified | 268 rows, 5 contributors |
| `WEB_SEARCH_GENERAL` | 100 | eligible; attested | 466 rows, 5 contributors |

- The sanctions rows cover listed aliases, listed wallet addresses, one-word lookalike companies and invented payees.
- The content moderation rows are 49 safe and 49 flagged cases with fictional names.
- The web search rows cite 36 distinct public pages in their better answers.
- Each batch was checked by both reviewer models before upload, and passed the kit's data gate.

The rows themselves are not in this repository, because they are now part of the hidden pools. Judges can have them on request.

What we do not claim: the registry lists no scoring module for the content moderation or web search families (`evidence/node-registry-moderation-websearch.json`), so those rows have not affected any ranking. We claim no paid material use. A truth source we wrote for `MINING_HASHPRICE_VERIFY` was rejected by the node as unparseable and is not counted.

## Which missions this serves

Telegraph's intent coverage map ([docs/NETWORK_MAP.md](https://github.com/telegraphprotocol/bounties/blob/main/docs/NETWORK_MAP.md) in the bounties repository) lists `SANCTIONS_SCREENING_MATCH` in six missions: Exchange, Stablecoin, Institutional Markets, Legal, Conflict Intelligence and Commodities. The mission pages on the hackathon site list it in five of those, without Conflict Intelligence.

The one mission-specific check here is for Stablecoin: `provider_format.jsonl` uses the answer format of the providers a payout app buys from. Paysheet's own paid check (`scripts/live-check.mjs` in its repository) records real provider answers for listed and invented names. Paysheet is our own app, so this is not independent adoption, and none of this is evidence of a completed mission integration.

## Run it

Needs git, curl, jq, OpenSSL 3.2 or newer, and Python 3.10 or newer. It downloads about 630 MB and runs on a CPU. No keys, no wallet, no cost. It only reads from Telegraph's test node.

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
./baseline/run.sh
```

It prints the table above with file names in place of the labels. The original 1,268-pair run took 28 minutes on 12 threads (`THREADS=12 ./baseline/run.sh`); the reduced public set has not been timed separately. Then, for the published rows:

```bash
./baseline/published_rows.sh
```

To score your own pairs, write a JSON Lines file with `prompt`, `chosen` (the better answer) and `rejected` (the worse one), and run:

```bash
python score_pairs.py --pkg ours=baseline/pkg/reg87.safetensors --pkg canonical=baseline/pkg/reg96.safetensors your_pairs.jsonl
```

A failure case to try: take a listed-subject row from `baseline/fixtures/astra_subject_twins.jsonl`, such as NEVSKIY NEWS LLC, and score it. The adapter prefers the clear.

## How the adapter was built

- A LoRA delta (rank 16, alpha 32) and a one-logit reward head on the shared Foundation Model (ModernBERT-base, release `modernbert-base-lora16-v1`). 13.5 MB. Class `judgment`.
- 389,448 training pairs, one epoch at learning rate 0.0002, on a free Kaggle T4. (`scripts/kaggle_run.py` defaults to two epochs at 0.0001; this run overrode both.)
- 365,080 pairs are built by `gen/build_r8.py` from public official lists (OFAC SDN and non-SDN, UN, EU, UK). Most take a real list entry, write a correct answer, and make the wrong answer by swapping one field (identifier, program, list, alias, date of birth, registration number, wallet owner) for another real entry's value. A second group teaches that a record must be about the entity asked for.
- The rest is an earlier set of 12,184 pairs, used twice: pairs from fexx301's MIT-licensed public generator, pairs in the format of a public provider's answers, pairs written by two LLM writers, and 1,490 rows in our own pool style, including the 298 we contributed.
- Clean company names are GLEIF legal names from fexx301's published material.

This repository supports scoring the registered packages. The builders show how the training pairs were made, but they do not rebuild the training set from this checkout: the GLEIF name files and the earlier set of 12,184 pairs are not included, and the earlier set contains our pool rows. With those inputs in place, `python3 -I gen/build_r8.py r8c 24 45000` reproduces the training file byte for byte (sha256 `c80f0e4bb70453d1dd2b49b15487de60c4c40c59de93b06ca75c2b3ed866c4bb`, checked on 20 Nov 2026).

## What we learned

- Scores on test sets we wrote ourselves did not predict the node. Early packages did well on our own held-out files and failed the node's public check. Performance varied across those files, so we do not treat any one of them as an estimate of performance on the node.
- One cause was in the data. A probe that never sees the question could tell our writers' better answers from worse ones by habit and length. The kit's dataset gate measures this; we should have run it first.
- Our first packages to pass the node's public check were the ones trained on list facts: every public list entry, with one field swapped for another real entry's value. We did not isolate that as the cause.
- A sample of 29 pairs cannot separate two modules that are one pair apart.
- A lead on our own files still did not carry to the node. r12b was ahead of registration 87 on the public test files and on another contributor's rows, and missed the public check by one pair, as r10 did.

## Files

- `score_pairs.py`: scores answer pairs on the released Foundation graph, the way the node does.
- `baseline/`: the public test files, the two comparison scripts and the table printer.
- `gen/build_r8.py`, `build_pairs.py`: the training-pair builders.
- `scripts/`: fetching the lists, training on Kaggle, packaging.
- `evidence/`: saved node records, receipts, row counts and the clean-copy run.
