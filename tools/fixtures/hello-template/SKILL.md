---
name: hello-template
description: Reads one text file and writes a one-line greeting summary of it.
---

# Hello template

## Inputs

- **Text file**: the file to summarise, attached to the run.

## Steps

### 1. Read the file

Read the text file from /workspace/inputs/ and note its first line.

### 2. Write the summary

Write one sentence about the file to /workspace/out/summary.txt.

## Output

- **summary.txt**: one sentence about the file.
