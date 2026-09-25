# 🎭 SonaVida

**🎭 SonaVida** brings a resident persona to life in the Studio: it reads a definition
once, keeps its own hours, makes its work, decides whether to show it, and remembers
what happened to it.

Studio-only. There is no network listener: every exchange with the Museum side is
started by the Studio, through `miraveja-studiolink`, and every call to **🧠 ModelMora**
is made on loopback. A persona's memory never leaves the Studio.

Full specification, plan, data model and contracts:
`specs/004-sonavida-persona-life/` in the `miraveja-ecosystem` hub.

## Running

```console
$ sonavida run --vault ROOT
$ sonavida run --simulate DAYS --seed N --standins
$ sonavida memory PERSONA
$ sonavida pieces PERSONA
$ sonavida status
```

See `specs/004-sonavida-persona-life/contracts/cli.md` for the full command reference.

## Development

```console
$ uv sync
$ uv run pytest -q
$ uv run ruff check .
$ uv run ruff format --check .
$ uv run mypy
```
