# Engineering handover

Prepared by Vinay Deekonda for the engineers taking over this work.

This is the index. Each item has what it is, the link, and anything an incoming engineer still needs that is not on the linked page.

Send the next item the same way (name + link, plus any repo, job, or table names). It will be added here in order.

## Index

| # | Item | Link |
| --- | --- | --- |
| 1 | Ingestion process for `l2_qualtrics` | [EDP Qualtrics API Ingestion Process](https://asurion.atlassian.net/wiki/spaces/EntArch/pages/103329287/EDP+Qualtrics+API+Ingestion+Process) |

## 1. Ingestion process for `l2_qualtrics`

Qualtrics API ingestion into the Enterprise Data Platform (EDP) `l2_qualtrics` table.

- **Document:** [EDP Qualtrics API Ingestion Process](https://asurion.atlassian.net/wiki/spaces/EntArch/pages/103329287/EDP+Qualtrics+API+Ingestion+Process)
- **Space:** EntArch
- **Page ID:** 103329287
- **Direct URL:** `https://asurion.atlassian.net/wiki/spaces/EntArch/pages/103329287/EDP+Qualtrics+API+Ingestion+Process`

The page title in the URL is **EDP Qualtrics API Ingestion Process**. That is the runbook for how Qualtrics API data is ingested into `l2_qualtrics`.

### Still needed for a complete handover

The Confluence page is behind Atlassian login, so this entry is the link only. Add these before handing the item off:

- Fully qualified table name (catalog, schema, and environment), for example prod vs non-prod `l2_qualtrics`
- Code repository and the job, DAG, or pipeline name that runs the ingestion
- Schedule, owner, and where failures alert
- How to rerun or backfill a failed load
- Which surveys land in this table, and which downstream jobs read it (reprocess, repull, PDI, and others will be linked as their own items)
