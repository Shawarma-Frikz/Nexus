# NEXUS semester project

This repository contains the NEXUS application source, project documents, and presentation deliverables.

## Start here

- **Application source and setup:** [`Project/README.md`](Project/README.md)
- **Architecture and subsystem notes:** [`Project/docs/README.md`](Project/docs/README.md)
- **Presentation decks:** [`deliverables/`](deliverables/)
- **Project specification:** [`cahier_des_charges.pdf`](cahier_des_charges.pdf)
- **Use case diagram:** [`usecasenexus.drawio.pdf`](usecasenexus.drawio.pdf)

The runnable app lives in `Project/`. Run its setup commands from that directory, not from this wrapper root.

## Repository layout

```text
3- Nexus/
├── Project/       NEXUS application source (Git submodule)
├── deliverables/  presentation files
├── cahier_des_charges.pdf
└── usecasenexus.drawio.pdf
```

For a fresh clone, initialize the application submodule with:

```bash
git submodule update --init --recursive
```
