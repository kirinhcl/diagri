# Set up research with the guide

[简体中文](../zh-CN/Guided-Setup.md)

This page is for an operator who wants to build a research protocol step by step instead of filling in the whole protocol form, and then start a round from it. For each step it says what the system offers and what you decide. The guide works without a model: every option comes from the system's own lists and rules.

> **Status.** The guide has run only in the tests and has not been run against a real model or a real device. See [Status and known limitations](Status-and-Known-Limitations.md). Its routes are in [`workbench/guide.py`](../../../src/growbridge/workbench/guide.py); its pages are the `guide*.js` files under [`web/workbench/pages/`](../../../src/growbridge/web/workbench/pages/).

## Start the guide

There are two ways in, both in the console at `/workbench`:

- **New project.** On the projects page, fill in the form "New project with the guide": the project name and the call budget (100 calls and 10 dollars are filled in; change them if you like). The console creates the project, sets the budget, and opens the guide. Setting a budget needs a recent re-authentication, as on the project page. A deployment without a model call budget has no budget route; the console then skips the budget, says so, and opens the guide anyway.
- **Existing project.** On a project page, in the protocols section, press "Set up or change the protocol with the guide". The guide starts from what the project already holds.

Every answer is kept on the server as it is given. You can leave the page and come back, and you can open any finished step again.

## The steps

The steps are numbered 0 to 8 on the page.

### 0. Project

Already done when the guide opens. It names the project the guide works for.

### 1. Research question

You write the research question, and the hypothesis if you have one. The system offers nothing here; it keeps your words.

### 2. Crop

The system offers a list of crops it knows. You choose one, or enter your own species name and its NCBI Taxonomy ID (the page links to the NCBI lookup). The cultivar and the batch are typed in their own fields on the same card.

### 3. Treatments

You choose the factor you change, give each treatment a short ID, a name, a level and, if you like, a description, and say which treatment is the control. The other factors stay as they were.

### 4. Measurements

The system offers the variables of the [variable catalog](Variable-Catalog.md). You choose at least one, and you name the main outcome among the variables measured by hand. A variable the catalog no longer offers stays on a reopened step, marked as gone, until you change it.

### 5. Analysis plan

The system offers two methods, paired blocks and two groups. You choose one and give the target effect (the smallest difference worth finding, in the unit of the main outcome) and the exclusion rules. The largest share of missing data starts at 0.2 and the largest share of deviating runs at 0.1; you can change both.

### 6. Scale

The system offers two layouts, in series or side by side in tents. You decide the number of blocks and rounds and the names of the units and stages. The random seed is set for you so the allocation can be reproduced; the allocation itself is always made by the system's own randomization. If you know the standard deviation of the main outcome from earlier work, the page can estimate the number of blocks; if you do not, the experiment is treated as a pilot and its conclusion is uncertain.

The guide composes experiments up to a size: at most 100 blocks in series, 200 rounds in tents, 50 units, 20 treatments, 20 stages and 2000 allocations. An estimate above 100 blocks is not filled in; the page asks you to check that the target effect and the standard deviation use the same unit. A larger experiment is set up with the protocol form on the project page; a larger version the guide starts from keeps its allocation table, and the review names the limit it passes.

### 7. Review and save

The guide shows what is missing or wrong: steps not answered yet, problems to solve before saving, and hints. Then it shows the composed protocol in the normal protocol form, with every value open to change. The same values give the same protocol digest as the hand-filled form. **Saving is always your own click.** The guide never saves on its own; the form saves through `POST /wb/protocols` like the project page. If the last version of the protocol declared an analysis script hash, it is shown with a "keep" box, ticked at first. The hash goes back on the new version only if you leave the box ticked and save the same protocol id.

### 8. Round and goal

After the save you can create a round of the saved protocol and state the goal. Both are optional: you can skip this step and do it later from the project page. If nothing has been saved in this guide yet, the step says so and points back to the review. The goal box starts with your research question; you can change it before you send it. When the goal is sent, the step links to the round page.

## Where each answer comes from

Every answer in the draft panel carries a mark:

| Mark | Meaning |
| --- | --- |
| From the list | You took one of the options the system offered, and its value is in the answer (the server checks this). Values you typed beside it on the same card, such as the cultivar and batch beside a listed crop or the levels and descriptions of a listed factor, are part of the same answer and carry the same mark. |
| Your own | You typed the value yourself. |
| Kept from the last version | You started from a protocol the project already had and did not change this value. |

When you change an early step, the steps after it that depend on it are marked "An earlier step changed; please check this one" until you look at them again. Keeping the last version keeps its allocation as it was.

## See also

- [Run a research round](Run-a-Research-Round.md)
- [Variable catalog](Variable-Catalog.md)
- [Research methodology](Research-Methodology.md)
- [HTTP, workbench and MCP interfaces](API-Reference.md)
