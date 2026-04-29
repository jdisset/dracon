# JOSS Submission Checklist

This repository is now set up for JOSS submission. The main remaining steps are release and archive metadata.

## Before submission

1. Make sure the default branch contains the final `paper/` files.
2. Tag a release for the version you want reviewed.
3. Archive that tagged release in Zenodo or another JOSS-acceptable archive.
4. Update [paper.bib](/Users/jeandisset/Code/Weiss/dracon/paper/paper.bib) so `DraconSoftware` includes the archive DOI instead of the placeholder note.
5. Update [CITATION.cff](/Users/jeandisset/Code/Weiss/dracon/CITATION.cff) with the preferred JOSS paper citation once the paper is published.

## Local paper build

If Docker is available, JOSS's recommended local build command is:

```bash
docker run --rm \
  --volume $PWD/paper:/data \
  --user $(id -u):$(id -g) \
  --env JOURNAL=joss \
  openjournals/inara
```

This should create `paper/paper.pdf`.

## Submission-time notes

- Repository license is already present and OSI-compatible.
- The paper is in the repository at `paper/paper.md`.
- Public documentation and tests are already part of the repo.
- JOSS review will happen in a public GitHub issue, so be ready to reply there.
