# Codebase Documentation Index

## Purpose
This directory contains structured documentation for the `trading-platform` codebase. AI assistants should use this index to locate the most relevant documentation file for a given question.

## How to Use
1. Read this index file first to understand what documentation is available
2. Consult the specific file(s) relevant to your question
3. For questions spanning multiple concerns, cross-reference across files

## File Manifest

| File | Primary Content | Best For |
|---|---|---|
| `codebase_info.md` | Project overview, stats, structure, tech stack | Quick orientation, build commands, directory layout |
| `architecture.md` | System architecture, design patterns, event flow | Understanding how components interact, overall design |
| `components.md` | All 11+ components, responsibilities, subscriptions | Understanding what each module does in detail |
| `interfaces.md` | Event types, API boundaries, integration points | Understanding event contracts and BC boundaries |
| `data_models.md` | Domain dataclasses, DB models, serialization | Understanding Position, Order, Fill data structures |
| `workflows.md` | Key processes: signal→fill, reconnect, monitoring | Following step-by-step event flows |
| `dependencies.md` | External libraries and their usage patterns | Understanding library usage conventions |
| `design.md` | Original system design specification (pre-implementation blueprint) | Understanding design intent, rationale behind decisions |
| `implementation_plan.md` | Phased implementation plan (P0–P10) | Understanding the build order, task breakdown per phase |
| `status.md` | Implementation status tracker (⚠️ outdated) | Historical per-phase task tracking; see AGENTS.md for current status |

## Quick Reference by Concern

### "How does this system work?"
→ `architecture.md` for overview, `workflows.md` for process flows

### "Where is X implemented?"
→ `components.md` for module locations and responsibilities

### "What events exist and who subscribes to what?"
→ `interfaces.md` for event contracts, `components.md` for subscription tables

### "What data structures/tables exist?"
→ `data_models.md` for domain models and DB schema

### "What external libs and how are they used?"
→ `dependencies.md` for library usage patterns

### "How do I run/lint/test?"
→ `codebase_info.md` for build commands

## Cross-Reference Map
```
                     ┌──────────────────┐
                     │  Architecture.md │──→ High-level design
                     └────────┬─────────┘
                              │ decomposes into
                              ▼
                     ┌──────────────────┐
                     │  Components.md   │──→ Module locations
                     └────────┬─────────┘
                              │ defines contracts
                              ▼
                     ┌──────────────────┐
                     │  Interfaces.md   │──→ Events, types
                     └────────┬─────────┘
                              │ implemented via
                              ▼
                     ┌──────────────────┐
                     │  DataModels.md   │──→ Dataclasses, DB
                     └────────┬─────────┘
                              │ orchestrated by
                              ▼
                     ┌──────────────────┐
                     │  Workflows.md    │──→ Process flows
                     └────────┬─────────┘
                              │ built on
                              ▼
                     ┌──────────────────┐
                     │ Dependencies.md  │──→ External libs
                     └──────────────────┘
```

## Relationship to AGENTS.md
The `AGENTS.md` file at the project root is a consolidated subset of these documentation files, optimized for AI coding assistant context. It focuses on navigation aids, deviations from defaults, and tool configurations. These summary files contain the full depth.
