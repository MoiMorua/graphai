---
name: grafo
description: Delegate a coding ticket to the `grafo` CLI, a cost-efficient agentic graph (local Qwen for code generation, OpenCode Go for planning/review) that plans, writes code, runs the repo's tests, reviews, and commits the result on an isolated `agente/<id>` git branch. Use when the user asks to run, hand off, or delegate a task to grafo / graphai / "the agent graph", wants a ticket implemented cheaply by local models, or asks to review, merge, or clean up an `agente/*` branch or a grafo ticket report.
---

# grafo CLI

`grafo` resolves a development ticket end to end: classify → plan → generate code → verify
(tests/lint) → review, escalating to stronger models only when attempts fail. By default it
works in a separate git worktree on branch `agente/<id>` and commits only the files it wrote,
so the user's working copy is never modified.

## 1. Check prerequisites

```bash
grafo status
```

Expect: a home directory, `clave OpenCode Go: ****xxxx` (or "no guardada"), and the config
layers that apply in the current directory.

- `grafo: command not found` → install the latest release: check the tag at
  https://github.com/MoiMorua/graphai/releases and run
  `uv tool install git+https://github.com/MoiMorua/graphai.git@vX.Y.Z`.
- No key → planning/review fall back to the local model; quality drops but it still runs.
  The key is set with `grafo login`, which prompts without echo. **Ask the user to run it
  themselves**; never ask for the key in chat or pass it with `--key` in a shared log.
- The local model server (Ollama at `http://localhost:11434`) must be running.
- `git` must be on PATH, and the target must be a git repo, unless using `--en-sitio`.

## 2. Write a good ticket

grafo only sees the ticket text plus the repo's file tree, so make the ticket self-contained:

- Name the files, functions, and signatures to create or change.
- State the expected behavior and edge cases (errors raised, return values).
- Say which tests to add and where (e.g. `tests/test_x.py` with pytest).
- Keep one ticket to one coherent change; split large features into several tickets.

The worktree is created from `HEAD`: **uncommitted changes are invisible to grafo**. If the
ticket depends on them, ask the user to commit first.

## 3. Run it

```bash
grafo run "<ticket text>" [--repo PATH] [--id T-name] [--verify "CMD"]... [--en-sitio]
```

| Flag | Meaning |
|---|---|
| `--repo` | Target repo (default: current directory) |
| `--id` | Ticket id, used in the branch name `agente/<id>` (default: random `T-xxxxxxxx`) |
| `--verify CMD` | Verification command, repeatable; overrides config. Must exit 0 on success |
| `--config` | Replace the user-level config file |
| `--en-sitio` | Write directly into the directory: no branch, no commit (use only if there is no git) |

- Runs take **minutes** (each model call can take 5–200 s). Run it as a long-running or
  background command with a generous timeout (≥ 30 min); do not kill it early.
- Pick `--verify` commands that the repo actually supports (`uv run pytest -q`,
  `npm test`, `cargo test`, a linter…). Without them, the default is
  `uv run --with pytest pytest -q`, which is only meaningful for Python repos.
- Per-repo defaults can live in `<repo>/.grafo.yaml`:

  ```yaml
  verify:
    comandos: [uv run pytest -q, uv run ruff check .]
  limites:
    max_iteraciones_ticket: 10
  ```

## 4. Read the result

Exit codes: `0` completed · `1` escalated to a human · `2` usage error.

The final lines look like:

```
== T-cli: completado (todos los pasos aceptados)
   pasos 2/2 · iteraciones 2 · consumo Go $0.0415
   reporte: <repo>/.grafo/tickets/T-cli.json
   rama agente/T-cli · commit 72f3128
   revisar:  git diff HEAD...agente/T-cli
   integrar: git merge agente/T-cli
   limpiar:  git worktree remove "<path>"; git branch -D agente/T-cli
```

`completado` = every step passed verify and review. `escalado_humano` = it stopped; the line
in parentheses gives the reason. Partial work is still committed on the branch.

## 5. Review before merging

Always review the diff yourself; grafo's own review is done by a cheap model.

```bash
git diff HEAD...agente/<id>
git log -1 agente/<id>
```

Check that the change matches the ticket, tests are meaningful (not trivially passing), and
nothing unrelated was rewritten. **grafo rewrites whole files**: look for accidentally
dropped code in large files.

Then, with the user's agreement:

```bash
git merge agente/<id>                        # or open a PR from the branch
git worktree remove "<path printed by grafo>"
git branch -D agente/<id>
```

To fix small issues, edit the branch's worktree directly (the path is printed) or re-run
grafo with a more precise ticket and a new `--id`.

## 6. Diagnose an escalation

Open `<repo>/.grafo/tickets/<id>.json`:

- `motivo` — why it stopped (`tiers agotados`, iteration limit, Go consumption limit, plan/review error).
- `pasos[i].feedback` — the last verify output or reviewer comments per step; usually shows
  the real problem (missing dependency, wrong test command, ambiguous ticket). Lines starting
  with `PISTA:` mean grafo recognized an environment error (import, missing command, timeout),
  not a logic bug; `AVISO:` means the model repeated the same files and the same error.
- `pasos[i].tier_actual`, `historial` — which models were tried and what each node decided.
  A step that escalates before using up its attempts was stuck repeating itself (`repeticiones`).

Common causes and fixes:

| Symptom | Fix |
|---|---|
| verify fails on every attempt with the same error | Wrong/unavailable `--verify` command, or missing dependency in the repo |
| `PISTA: Error de importación` persists across tiers | The repo's own code isn't importable by the test runner (no `pyproject.toml`/`conftest.py`, `go.mod`, `mod` declarations…); name the support file in the ticket or add it first |
| `PISTA: Un comando … no existe` | The `--verify` tool isn't installed or on PATH; no model can fix it, fix the environment |
| "No se encontró ningún bloque '### ARCHIVO: ruta'" | Model ignored the output format; re-run, or simplify the step |
| reviewer keeps asking for changes | Ticket is ambiguous; restate the acceptance criteria explicitly |
| `no es un repo git (o git no está instalado)` | Run inside a git repo, put git on PATH, or use `--en-sitio` |
| `tope alcanzado` / Go models skipped | Go usage window exhausted; grafo falls back to other models (ultimately the local one) until the window resets |

## Other commands

| Command | Purpose |
|---|---|
| `grafo login [--key K]` | Save the OpenCode Go key (user should run it interactively) |
| `grafo logout` | Delete the saved key |
| `grafo status` | Show home, masked key, active config layers |
| `grafo --version` | Installed version and where it came from |
| `grafo upgrade [--check]` | Install the latest release (on Windows it finishes in the background; check `grafo --version` a few seconds later) |
| `grafo mermaid` | Print the graph as a Mermaid diagram |

Files: `~/.config/grafo/` (`.env` key, `logs/uso.jsonl` per-call usage, `worktrees/`);
`GRAFO_HOME` relocates it. Add `.grafo/` to the target repo's `.gitignore`.
