---
name: Bug report
about: Something produced wrong output or crashed
title: ''
labels: bug
assignees: ''
---

**What happened**

A clear description of the wrong behaviour.

**The command or code you ran**

```bash
shopify-scraper ...
```

**The input that triggered it**

This is the most useful part of the report. If a description came out wrong,
paste the raw `body_html` snippet (a few lines is plenty). If pagination or the
network layer misbehaved, give the store domain if you are able to share it.

**Expected output**

**Actual output**

```
paste the output or traceback here
```

**Environment**

- Package version (`shopify-scraper --version`):
- Python version (`python --version`):
- OS:

**Note:** please don't paste an entire scraped catalog into the issue — a few
representative lines are enough to reproduce almost anything.
