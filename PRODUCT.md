# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Brian, a triathlete training for his own races, is the primary and today the only user. He opens the app in three situations:

- a morning check on a laptop before training: readiness, today's session and fuel;
- a weekly planning sit-down: the check-in, reviewing and approving plan and nutrition changes, and longer conversations with the coach;
- post-session analysis: how a completed workout went, and trends over weeks.

Other athletes are a stated future audience ("me now, other athletes later"). Serving them is an open decision; see Capabilities and Constraints.

## Product Purpose

A personal AI coaching team over one athlete's own training data. Garmin Connect and TrainingPeaks sync into a local Postgres store. A head coach answers questions by consulting an analyst and a lab interpreter, and briefs the planning and nutrition agents. It proposes changes to the training calendar, daily nutrition targets and fueling plans. The web app is the everyday surface over that coach: today's numbers at a glance, the conversation, and the review gate where proposed changes are approved, edited or rejected.

Success is that the athlete trusts what he sees enough to act on it each morning, and that every change to his plan is one he understood and approved.

## Positioning

Coaching grounded in the athlete's own synced data (TrainingPeaks history, Garmin recovery metrics, lab panels read against functional ranges), not generic advice. Specialist agents sit behind one coach. Nothing reaches TrainingPeaks or Garmin without an explicit human approval at a single review gate.

## Operating Context

- Runs locally: `uv run tri-web serve` on 127.0.0.1:8321, with the React app built from `web/`. The terminal REPLs (`tri-coach chat` and the per-agent CLIs) share the same coach thread and memory.
- Data arrives by sync (`tri sync`, or Sync now in the app). Garmin data can lag a day or more, so the app shows the date a reading is from, and when a sync is stale or failed.
- The weekly check-in syncs, reviews the last 7 days and proposes adjustments through the same review gate.
- Each coach turn spends real Anthropic API credit.

## Capabilities and Constraints

- Local-only: loopback host, no authentication, one athlete, one coach thread. Hosting, accounts and multi-athlete support are undecided future work, and they are in tension with local-only; any change there is a product decision, not a design detail.
- Every write to TrainingPeaks or Garmin is approved first at the review gate. No silent writes.
- The head coach is the front door. The analyst, planning, nutrition and wellness agents are reached through it, not through separate chats in the UI (their CLIs remain).
- Sections today: Today (cards, chat, review gate), Settings (coach memory, reset, readiness checks). Progress, Nutrition and Labs are planned pages: fitness curve and weekly load by sport; targets, fuel plans and fuel log; lab panels, reports and PDF upload.
- Terminology in use: CTL/ATL/TSB (fitness, fatigue, form), TSS, IF, ramp rate, ACWR, readiness, phase and week of plan, fuel plan, check-in, review gate, proposal.

## Brand Commitments

None established. The app has no name beyond `tri-web`, no logo and no voice guide.

## Evidence on Hand

- Real synced data for one athlete: about a year of TrainingPeaks workouts, 60+ days of Garmin daily metrics, and any stored lab panels, in the local database.
- Approved designs and plans in `docs/superpowers/specs/` and `docs/superpowers/plans/`; architecture in `docs/architecture/`.
- No testimonials, other athletes' data, benchmarks or usage metrics exist. Do not fabricate them.

## Product Principles

1. The athlete stays in control: the app proposes, the athlete decides, and every change is visible before it happens.
2. Show the athlete's own numbers against his own baseline, with the date they come from, before any interpretation.
3. One coach, one conversation: complexity lives behind the head coach, not in the navigation.
4. Honest about freshness and gaps: stale syncs, missing data and paused reviews are stated plainly, never hidden.
5. Built for one athlete today without closing the door on coaching others later.

## Accessibility & Inclusion

WCAG 2.2 AA is a standing requirement. That covers text and status contrast, screen-reader announcements for streamed replies and status, keyboard access with a skip link and visible focus, at least 24px targets, and honouring reduced motion. Status is never shown by colour alone.
