# Unmoderated Target-User Test

**Status:** LIVE / participant-session runbook

**Version:** 1.0

## Purpose

Run the three release-required sessions for people who want to express a story
but do not already know screenplay, shot planning, or model parameters. This
runbook measures whether a person can independently make a short work through
the Director workflow. It is not a usability demo, sales call, or support
session.

Use one redacted record per participant. Store source-bound runtime evidence in
`tmp/p0-evidence/<source-commit>/`; store only pseudonymous notes in the Gate
review record. Do not record names, contact details, raw screen capture,
credentials, or unpublished media in Git.

## Roles And Guardrails

| Role | Allowed | Not Allowed |
|---|---|---|
| Participant | Use the product, narrate thoughts if they choose, stop at any time | Access developer tooling, Provider consoles, database, queues, or logs |
| Observer | Read neutral task text, observe, record timestamps and quotes | Explain controls, suggest clicks, repair the environment, operate the product, or interpret quality for the participant |
| Safety owner | Confirm the session budget and stop unsafe or unauthorized activity | Treat a paid retry as implied consent |

Before each session, confirm a usable clean candidate, a unique participant
project, a pre-approved maximum budget, and a tested download path. If the
environment fails, record the failure and end or reschedule; do not silently
repair it during the session.

## Participant Task Card

Give only the following task card, then remain silent except for the neutral
prompts below.

> 你想把一个对你有意义的小故事做成一段短剧。请从这里开始，按照你自己的理解完成作品。你可以使用自己的想法，也可以让系统帮你找灵感。完成后，请查看试拍结果，决定是否继续，并在最后下载你认为合适的交付物。请在任何让你犹豫、困惑或不确定的地方直接说出来。你可以随时停止。

The participant may choose their own story. Do not require them to disclose
personal experiences; a fictional premise is equally valid.

## Neutral Prompts

Use only when the participant is quiet for an extended period or asks the
observer what to do:

- “请按你认为合适的方式继续。”
- “你现在在想什么？”
- “你可以选择停止，也可以继续。”

Do not say where to click, which option is correct, whether a budget should be
approved, whether a trial is good enough, or how to repair a result.

## Observation Checklist

Record the timestamp and outcome for each item:

1. Finds a start entry and chooses an idea path without instruction.
2. Understands and confirms the story core.
3. Understands and confirms the shooting plan, including risk and model/cost
   summary at the level shown in the compact workspace view.
4. Notices that trial and formal production require different budget decisions.
5. Reviews the representative trial and makes an independent continue, repair,
   or stop decision.
6. If continuing, authorizes formal production, reviews quality evidence, and
   accepts or requests local repair without help.
7. Finds and downloads the complete delivery.
8. States whether the result feels like their intended story and whether they
   would save, show, publish, or make another work.

For each confusion, record the participant's words, the visible workflow
state, and what happened next. Do not infer motive or paraphrase a quote as a
fact.

## Redacted Participant Record Template

Copy this section into an external, access-controlled test record. Use a
pseudonym such as `P01`; do not put the completed record in this repository.

```markdown
# Participant P__

Session date/time (local):
Candidate commit:
Observer:
Pre-approved trial / production / repair limit:
Entry chosen: no idea / one sentence / import script

## Timeline
| Time | Observed action or workflow state | Participant words (verbatim when possible) | Outcome |
|---|---|---|---|

## Required Outcomes
| Criterion | Completed without help? | Evidence / note |
|---|---|---|
| Found an entry | yes / no | |
| Understood four confirmation points | yes / no / unclear | |
| Made an independent trial decision | yes / no | |
| Downloaded complete delivery | yes / no | |
| Developer operated DB, queue, or Provider console | no / yes | |

## Result And Follow-Up
Final workflow status:
Delivery downloaded:
Would save / show / publish / make another work:
Main blocker or misunderstanding:
Reported quality limitation:
Created issue IDs and severity:
Session ended normally / stopped by participant / environment failure:
```

## After The Session

1. Preserve runtime evidence using the candidate commit and the normal
   evidence process.
2. Create a Director Issue or engineering issue for each blocker, with the
   participant pseudonym only when necessary for aggregation.
3. Update `release-gate-board.md` only with a redacted summary and the
   evidence location; never with the participant's identity or raw media.
4. Do not count a session as passing if a developer repaired the environment,
   database, queue, model console, or workflow during the participant task.
5. Count the release requirement only when all three sessions satisfy the
   product contract conditions and at least two participants state a genuine
   intent to save, show, publish, or continue creating.
